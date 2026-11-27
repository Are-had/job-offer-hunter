"""routes_search.py - the Search page: career websites, the scan (start, stop, resume) and its live progress (SSE)."""
from __future__ import annotations

import asyncio
import io
import csv
import json
from collections import Counter

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .core import READ_OUTCOME, SCANNER, load_settings, models_caption, offer_row, scan_profile
from jobfinder import market
from jobfinder.scan import PROBLEM_ORDER, site_problem
from jobfinder.store import (CVDocument, Job, OfferMark, SessionLocal, Source, file_coverage, forget_recent_offers,
                             load_new_sources, recent_count, restart_session, unfinished_scan)
from jobfinder.web import extract_urls, pasted_urls

router = APIRouter(prefix="/api")
MAX_FILE = 2_000_000


def summary() -> dict:
    """The header's counters and state."""
    with SessionLocal() as s:
        return dict(sites=s.query(Source).count(), cvs=s.query(CVDocument).filter_by(enabled=True).count(),
                    relevant=s.query(Job).filter(Job.status == "relevant").count(),
                    review=s.query(Job).filter(Job.status == "review").count(),
                    applied=s.query(OfferMark).filter(OfferMark.state == "applied").count(),
                    running=SCANNER.running)


@router.get("/summary")
def get_summary():
    return summary()


# --------------------------------------------------------------------------- career websites
@router.get("/sources")
def sources():
    with SessionLocal() as s:
        rows = [dict(id=x.id, website=x.label or x.url, file=(x.origin or "").replace("\n", ", "), url=x.url,
                     read_by=x.platform or "", status=READ_OUTCOME.get(x.outcome, x.status or ""), offers=x.jobs_found or 0,
                     on_lists=x.listed or 0, since_last_scan=x.health or "", note=x.last_error or "")
                for x in s.query(Source).all()]
    changed = [r for r in rows if r["since_last_scan"] and not r["since_last_scan"].endswith("read again now")]
    return {"sources": rows, "changed": changed}


def _load(urls: list[str], origins: dict) -> int:
    if SCANNER.running:
        raise HTTPException(409, "A search is running: wait for it to end or stop it first.")
    if not urls:
        raise HTTPException(400, "No career website address was found.")
    try:
        with SessionLocal() as s:
            load_new_sources(s, urls, origins)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    SCANNER.prog.reset()
    return len(urls)


@router.post("/sources/files")
async def sources_from_files(files: list[UploadFile] = File(...)):
    """HTML files listing career pages: read (never executed); they replace the websites loaded before."""
    origins, skipped = {}, []
    for f in files:
        data = await f.read()
        if len(data) > MAX_FILE:
            skipped.append(f.filename)
            continue
        for u in extract_urls(data.decode("utf-8", errors="replace")):
            origins.setdefault(u, []).append(f.filename or "file")
    n = _load(list(origins), origins)
    return {"loaded": n, "skipped": skipped}


class Pasted(BaseModel):
    text: str


@router.post("/sources/urls")
def sources_from_text(body: Pasted):
    urls = pasted_urls(body.text)
    return {"loaded": _load(urls, {u: ["pasted URLs"] for u in urls})}


@router.get("/coverage")
def coverage():
    """One bar per input file: how many of its websites were searched, and how each one ended."""
    with SessionLocal() as s:
        return {"files": file_coverage(s), "running": SCANNER.running}


def _problems(running: bool) -> list[dict]:
    cfg, _, _ = load_settings()
    with SessionLocal() as s:
        rows = []
        for x in s.query(Source).all():
            pb = site_problem(x, scan_finished=not running, respect_robots=bool(cfg.get("respect_robots", False)))
            if pb:
                rows.append(dict(problem=pb[0], website=x.label or x.url, why=pb[1], what_to_do=pb[2],
                                 file=(x.origin or "").replace("\n", ", "), address=x.url))
    rows.sort(key=lambda r: (PROBLEM_ORDER.index(r["problem"]), r["website"].lower()))
    return rows


@router.get("/problems")
def problems():
    """Every website that did not work at this scan, with the reason and what to do."""
    running = SCANNER.running
    rows = _problems(running)
    by = Counter(r["problem"] for r in rows)
    return {"rows": rows, "order": [k for k in PROBLEM_ORDER if by[k]], "counts": by, "running": running}


@router.get("/problems.csv")
def problems_csv():
    rows = _problems(SCANNER.running)
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["problem", "website", "why", "what_to_do", "file", "address"])
    w.writeheader()
    w.writerows(rows)
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="websites_not_working.csv"'})


# --------------------------------------------------------------------------- the scan
def scan_state() -> dict:
    d, log = SCANNER.prog.snap()
    cfg, prof, _ = load_settings()
    with SessionLocal() as s:
        left = None if SCANNER.running else unfinished_scan(s)
        kept = recent_count(s)
        due = market.due(s)
    if left:
        left = {k: left.get(k) for k in ("started", "why", "done", "pending")} | {
            "total": len(left.get("source_ids") or []), "preset": (left.get("cfg") or {}).get("date_preset", "")}
    return {"progress": json.loads(json.dumps(d, default=str)), "log": list(log)[-60:], "unfinished": left,
            "kept_offers": kept, "stats_due": due, "models": models_caption(cfg, prof), "summary": summary()}


@router.get("/scan")
def get_scan():
    return scan_state()


def _can_start():
    if SCANNER.running:
        raise HTTPException(409, "A search is already running.")
    with SessionLocal() as s:
        if not s.query(Source).count():
            raise HTTPException(400, "Load the career websites first (step 1).")
    _, prof, _ = load_settings()
    p2 = scan_profile(prof)
    if p2.get("keywords_only") and not p2.get("keywords"):
        raise HTTPException(400, "Add at least one keyword (step 2).")


@router.post("/scan/start")
def start():
    _can_start()
    with SessionLocal() as s:
        if unfinished_scan(s):
            raise HTTPException(409, "The last search did not finish: resume it or start again.")
    SCANNER.start()
    return {"started": True}


@router.post("/scan/resume")
def resume():
    if SCANNER.running:
        raise HTTPException(409, "A search is already running.")
    with SessionLocal() as s:
        left = unfinished_scan(s)
    if not left:
        raise HTTPException(404, "There is no unfinished search to resume.")
    SCANNER.start(resume=left)
    return {"started": True}


@router.post("/scan/restart")
def restart():
    """'Start again' after an unfinished search: its offers are kept 24 hours like any search's, then a new one starts."""
    _can_start()
    with SessionLocal() as s:
        restart_session(s)
    SCANNER.start()
    return {"started": True}


@router.post("/scan/stop")
def stop():
    SCANNER.stop()
    return {"stopping": True}


@router.delete("/recent-offers")
def forget_kept():
    """Deletes the offers kept from the last 24 hours and the current results: the next search reads and analyses all."""
    if SCANNER.running:
        raise HTTPException(409, "A search is running.")
    try:
        return {"deleted": forget_recent_offers()}
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


def live_offers(limit=100) -> dict:
    """The newest offers found in the date range, with their links: filled in while the scan runs."""
    with SessionLocal() as s:
        q = s.query(Job).filter(Job.status.notin_(["out_of_range", "excluded", "dismissed"]))
        total = q.count()
        rows = [offer_row(j) for j in q.order_by(Job.discovered.desc()).limit(limit)]
    return {"total": total, "rows": rows}


@router.get("/live-offers")
def get_live_offers():
    return live_offers()


@router.get("/scan/events")
async def events(request: Request):
    """Server-sent events: the scan's progress every second (and the newest offers every 3 seconds) while the page
    listens. One last event after the scan ends, then every 5 seconds."""
    async def stream():
        tick = 0
        while not await request.is_disconnected():
            state = await asyncio.to_thread(scan_state)
            if tick % 3 == 0:
                state["live"] = await asyncio.to_thread(live_offers)
            yield f"data: {json.dumps(state, default=str)}\n\n"
            tick += 1
            await asyncio.sleep(1 if state["progress"]["running"] else 5)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
