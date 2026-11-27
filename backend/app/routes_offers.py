"""routes_offers.py - the Results page: offers, your marks (applied / removed / comment), CVs, CV match, cover letters
and the application window."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .core import (KIND_LABEL, STATUS_LABEL, load_settings, offer_row, offer_type, online_for, own_keys, web_link)
from jobfinder import apply as apply_form
from jobfinder import cv as cvm
from jobfinder import llm
from jobfinder.config import run_config
from jobfinder.store import CoverLetter, CVDocument, Job, OfferMark, SessionLocal, mark_offer
from jobfinder.web import offer_link

router = APIRouter(prefix="/api")


def _job(s, uid) -> Job:
    j = s.query(Job).filter_by(uid=uid).first()
    if j is None:
        raise HTTPException(404, "This offer is not in the results any more.")
    return j


@router.get("/offers")
def offers():
    """Every offer of this session (out of the date range and removed ones left out), with your marks."""
    with SessionLocal() as s:
        mine = {m.uid: m for m in s.query(OfferMark)}
        return [offer_row(j, mine.get(j.uid))
                for j in s.query(Job).filter(Job.status.notin_(["out_of_range", "dismissed"])).all()]


def _letter(s, uid) -> dict | None:
    for cl in s.query(CoverLetter).filter_by(job_uid=uid).order_by(CoverLetter.version.desc()).all()[:1]:
        if Path(cl.tex_path).exists():
            return {"id": cl.id, "version": cl.version, "cv": cl.cv_name, "tex": Path(cl.tex_path).read_text(encoding="utf-8"),
                    "pdf": bool(cl.pdf_path and Path(cl.pdf_path).exists())}
    return None


@router.get("/offers/{uid}")
def offer(uid: str):
    """The offer's card: what the website says, what the app read, why it was kept, your mark, its letter."""
    with SessionLocal() as s:
        j = _job(s, uid)
        ti, r, ex = (j.extra or {}).get("title_info") or {}, j.relevance_json or {}, j.extra or {}
        link = web_link(offer_link(j.url, j.title, j.apply_url))
        apply_page = j.apply_url if web_link(j.apply_url) and j.apply_url not in (j.url, link) and "jboffer=" not in j.apply_url else None
        m = s.get(OfferMark, uid)
        kind = offer_type(j)
        seen = ex.get("first_seen")
        flags = [f.replace("_", " ") for f in (j.review_flags or "").split(",") if f and f != "publication_date_unknown"]
        cvs = [x.name for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok"]
        ok, why = apply_form.can_open_window()
        return dict(
            uid=j.uid, title=j.title, company=j.employer or "", status=j.status, status_label=STATUS_LABEL.get(j.status, j.status),
            type=KIND_LABEL.get(kind, ""), research_subject=ti.get("kind") == "research_topic",
            language={"fr": "français", "en": "English"}.get(ti.get("lang"), ""),
            topics=(r.get("research_topics") or ti.get("topics") or [])[:6], link=link, apply_page=apply_page,
            published=f"{j.pub_date:%d %b %Y}" if j.pub_date else "", online_since=online_for(seen) if seen else "",
            date_source=j.date_source or "", date_text=(j.pub_date_text or "")[:80],
            location=j.location_original or "", location_evidence=j.location_evidence or "",
            relevance=r.get("relevance_score"), reasoning=r.get("reasoning_summary", ""),
            ai_model=ex.get("ai_model", ""), first_reading=ex.get("first_reading", ""),
            review_flags=flags, reason=j.reason or "", description=j.description or "",
            match=[{"cv": k, "score": x["match_score"], "advice": x["recommendation"],
                    "missing": ", ".join(x["missing_requirements"]), "not_shown": ", ".join(x["not_evidenced"])}
                   for k, x in (j.match_json or {}).items()],
            best_cv=j.best_cv or "", cvs=cvs, letter=_letter(s, uid),
            mark={"state": m.state, "note": m.note or ""} if m else {"state": "", "note": ""},
            can_fill=ok and bool(apply_page or link), fill_why=why or "", fill=_fill_status(uid))


# --------------------------------------------------------------------------- your marks
class MarkIn(BaseModel):
    state: str | None = None  # applied | dismissed | '' (undo); None: unchanged
    note: str | None = None


@router.post("/offers/{uid}/mark")
def mark(uid: str, body: MarkIn):
    """I applied / Remove it (not for me) / my comment: remembered between searches. An offer you applied to or removed
    is not added again by the next searches."""
    if body.state not in (None, "", "applied", "dismissed"):
        raise HTTPException(400, "state: applied, dismissed or ''")
    with SessionLocal() as s:
        m = mark_offer(s, _job(s, uid), body.state, body.note)
        return {"state": m.state, "note": m.note}


@router.post("/offers/{uid}/keep")
def keep(uid: str):
    """'To check' -> kept: the doubts are cleared."""
    with SessionLocal() as s:
        j = _job(s, uid)
        j.status, j.review_flags = ("relevant" if j.relevance_score is not None else "candidate"), ""
        s.commit()
        return {"status": j.status}


@router.get("/marks")
def marks():
    """Every offer you applied to, removed or commented: kept between searches."""
    with SessionLocal() as s:
        return [dict(uid=m.uid, state=m.state or "", title=m.title, company=m.employer, note=m.note or "",
                     date=f"{m.updated:%Y-%m-%d}" if m.updated else "", link=web_link(m.url))
                for m in s.query(OfferMark).order_by(OfferMark.updated.desc())]


@router.put("/marks/{uid}")
def edit_mark(uid: str, body: MarkIn):
    with SessionLocal() as s:
        m = s.get(OfferMark, uid)
        if m is None:
            raise HTTPException(404, "No mark for this offer.")
        j = s.query(Job).filter_by(uid=uid).first()
        if j is not None:
            mark_offer(s, j, body.state, body.note)
        else:  # the offer is not in this session's results any more: only the record changes
            if body.state is not None:
                m.state = body.state
            if body.note is not None:
                m.note = body.note.strip()
            m.updated = datetime.utcnow()
            s.commit()
        return {"state": m.state, "note": m.note}


@router.delete("/marks/{uid}")
def forget_mark(uid: str):
    """Forgotten: the searches can show the offer again."""
    with SessionLocal() as s:
        m = s.get(OfferMark, uid)
        if m is None:
            raise HTTPException(404, "No mark for this offer.")
        j = s.query(Job).filter_by(uid=uid).first()
        if j is not None and j.status == "dismissed":
            j.status, j.reason = "new", ""
        s.delete(m)
        s.commit()
    return {"deleted": True}


# --------------------------------------------------------------------------- CVs
@router.get("/cvs")
def cvs():
    with SessionLocal() as s:
        return [dict(id=c.id, name=c.name, language=c.language or "", status=c.status or "")
                for c in s.query(CVDocument).all()]


@router.post("/cvs")
async def add_cvs(files: list[UploadFile] = File(...)):
    errors = []
    with SessionLocal() as s:
        for f in files:
            try:
                cvm.add_cv(s, f.filename or "cv.pdf", await f.read())
            except ValueError as e:
                errors.append(f"{f.filename}: {e}")
    return {"errors": errors, "cvs": cvs()}


@router.delete("/cvs/{cv_id}")
def remove_cv(cv_id: int):
    with SessionLocal() as s:
        cvm.delete_cv(s, cv_id)
    return {"deleted": True}


@router.post("/offers/{uid}/match")
def compare_with_cv(uid: str):
    cfg, _, _ = load_settings()
    with SessionLocal() as s:
        try:
            cvm.match_job(s, _job(s, uid), run_config(cfg), own_keys())
        except llm.AIError as e:
            raise HTTPException(502, str(e)) from e
    return offer(uid)


# --------------------------------------------------------------------------- cover letters
class LetterIn(BaseModel):
    cv: str = ""
    tex: str = ""


@router.post("/offers/{uid}/letter")
def write_letter(uid: str, body: LetterIn):
    """A French cover letter in LaTeX, written by the AI from the offer and the chosen CV."""
    cfg, _, ap = load_settings()
    if not ap.get("name"):
        raise HTTPException(400, "Add your name in 'Your details' first (Search page, step 2).")
    with SessionLocal() as s:
        j = _job(s, uid)
        cvs_ = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok"]
        cv = next((x for x in cvs_ if x.name == body.cv), cvs_[0] if cvs_ else None)
        if cv is None:
            raise HTTPException(400, "Upload a CV first.")
        try:
            cvm.save_letter(s, j, cv.name, cvm.build_tex(ap, j, cvm.generate_letter_content(s, j, cv, run_config(cfg), own_keys())))
        except llm.AIError as e:
            raise HTTPException(502, str(e)) from e
        return _letter(s, uid)


@router.put("/offers/{uid}/letter")
def save_edited_letter(uid: str, body: LetterIn):
    with SessionLocal() as s:
        j = _job(s, uid)
        cur = _letter(s, uid)
        cvm.save_letter(s, j, (cur or {}).get("cv") or body.cv, body.tex, "edited")
        return _letter(s, uid)


@router.get("/offers/{uid}/letter.tex")
def letter_tex(uid: str):
    with SessionLocal() as s:
        cur = _letter(s, uid)
    if not cur:
        raise HTTPException(404, "No letter yet.")
    return Response(cur["tex"], media_type="application/x-tex",
                    headers={"Content-Disposition": f'attachment; filename="{re.sub(r"[^A-Za-z0-9_-]", "_", uid)}.tex"'})


@router.get("/offers/{uid}/letter.pdf")
def letter_pdf(uid: str):
    with SessionLocal() as s:
        for cl in s.query(CoverLetter).filter_by(job_uid=uid).order_by(CoverLetter.version.desc()).all():
            if cl.pdf_path and Path(cl.pdf_path).exists():
                return FileResponse(cl.pdf_path, media_type="application/pdf", filename=f"{uid}.pdf")
    raise HTTPException(404, "No PDF yet (LaTeX is needed on this computer to make one).")


# --------------------------------------------------------------------------- the application window
_MESSAGES: dict[str, tuple[str, str]] = {}  # uid -> (short message pasted in the form, where it comes from)
ACCOUNT_STATES = {"created": "created", "sent": "sent to the website", "waiting_code": "waiting for the email code",
                  "waiting_link": "waiting for you to click the link in the confirmation email",
                  "creating": "form filled, not sent yet", "wrong_password": "the website refuses this password"}
FIELD_NAMES = {"first_name": "first name", "last_name": "last name", "full_name": "full name", "email": "email",
               "phone": "phone", "address": "address", "postal_code": "postal code", "city": "city", "country": "country",
               "linkedin": "LinkedIn", "website": "website", "civility": "civility", "nationality": "nationality",
               "degree": "degree", "school": "school", "grad_year": "graduation year", "field_of_study": "field of study",
               "work_authorization": "right to work", "sponsorship": "visa sponsorship", "how_heard": "how you heard",
               "cover_letter": "cover letter", "cv": "CV (attached)"}


def _short_message(s, j, cfg, ap) -> tuple[str, str]:
    """The text pasted into the form's cover-letter box: 5 lines at most, written once for the offer and kept."""
    saved = apply_form.message_path(j.uid)
    if saved.exists():
        return apply_form.clamp_lines(saved.read_text(encoding="utf-8")), "the short message written for this offer"
    cvs_ = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok"]
    if not cvs_:
        return "", "no CV uploaded, so no message was written"
    cv = next((x for x in cvs_ if x.name == j.best_cv), cvs_[0])
    try:
        msg = cvm.generate_form_message(s, j, cv, run_config(cfg), own_keys())
    except llm.AIError as e:
        return "", f"no message written: {str(e)[:150]}"
    text = apply_form.form_message(ap, msg.lines)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(text, encoding="utf-8")
    return text, f"short message written for this offer ({apply_form.MAX_LINES} lines at most)"


def _free_page_reader(cfg):
    """A page the rules do not understand, without an Anthropic key: read once by the free models of your other keys."""
    c2, keys = {**run_config(cfg), "_timeout": 25, "_no_wait": True}, own_keys()

    def ask(prompt, schema, system):
        with SessionLocal() as s2:
            return llm.call_json(prompt, schema, c2, s2, keys, system=system)
    return ask


def _apply_job(uid, code="") -> dict:
    """What the application window needs: your details, the message, the CV, the letter PDF, the account email, the keys."""
    cfg, _, ap = load_settings()
    with SessionLocal() as s:
        j = s.query(Job).filter_by(uid=uid).first()
        title = (j.title if j else "") or ""
        cvs_ = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok" and x.path]
        cv = next((x for x in cvs_ if j is not None and x.name == j.best_cv), cvs_[0] if cvs_ else None)
        cv_path = str(cv.path) if cv and Path(cv.path).exists() else ""
        letter = next((str(cl.pdf_path) for cl in s.query(CoverLetter).filter_by(job_uid=uid).order_by(CoverLetter.version.desc())
                       if cl.pdf_path and Path(cl.pdf_path).exists()), "")
    values = {**apply_form.form_values(ap), "position": re.sub(r"\s+", " ", title).strip()[:120]}
    return {"values": values, "letter": _MESSAGES.get(uid, ("", ""))[0], "email": ap.get("account_email") or ap.get("email", ""),
            "allow_terms": bool(ap.get("accept_terms")), "ai_key": own_keys().get("anthropic", ""),
            "ai_free": _free_page_reader(cfg), "cv_path": cv_path, "letter_path": letter, "code": code}


def _fill_status(uid) -> dict | None:
    stt = apply_form.WINDOW.status.get(uid)
    if not stt:
        return None
    acct = apply_form.load_accounts().get(stt.get("site", ""))
    text, note = _MESSAGES.get(uid, ("", ""))
    return {"state": stt.get("state", ""), "message": stt.get("message", ""),
            "filled": [FIELD_NAMES.get(k, k) for k in stt.get("filled", [])], "steps": stt.get("steps") or [],
            "site": stt.get("site", ""), "account": ({"email": acct.get("email", ""),
                                                      "state": ACCOUNT_STATES.get(acct.get("state"), acct.get("state", ""))}
                                                     if acct else None),
            "letter": text, "letter_note": note}


@router.post("/offers/{uid}/fill")
def open_and_fill(uid: str):
    """Opens the offer's application in the app's browser window on this computer, signs in (or creates your account)
    when the website asks, and fills in your details and a short message. You attach and submit yourself."""
    cfg, _, ap = load_settings()
    if not (ap.get("first_name") and ap.get("last_name") and ap.get("email")):
        raise HTTPException(400, "Add your first name, last name and email first: Search page, step 2, 'Your details'.")
    ok, why = apply_form.can_open_window()
    if not ok:
        raise HTTPException(400, why)
    with SessionLocal() as s:
        j = _job(s, uid)
        link = web_link(offer_link(j.url, j.title, j.apply_url))
        target = j.apply_url if web_link(j.apply_url) and "jboffer=" not in j.apply_url else link
        if not target:
            raise HTTPException(400, "This offer has no web address to open.")
        _MESSAGES[uid] = _short_message(s, j, cfg, ap)
    apply_form.WINDOW.open(uid, target, _apply_job(uid))
    return _fill_status(uid)


@router.get("/offers/{uid}/fill")
def fill_status(uid: str):
    return _fill_status(uid)


class FillIn(BaseModel):
    code: str = ""
    password: str = ""
    link: str = ""


@router.post("/offers/{uid}/fill/continue")
def fill_continue(uid: str, body: FillIn):
    """After you acted in the window (signed in, a captcha, a box, the next step) - or with the email's code, password
    or link."""
    stt = apply_form.WINDOW.status.get(uid) or {}
    if body.password.strip() and stt.get("site"):
        apply_form.set_account(stt["site"], None, password=body.password.strip(), state="created",
                               password_from="the website's email")
    if body.link.strip():
        if not body.link.strip().lower().startswith("https://"):
            raise HTTPException(400, "Paste the whole link, starting with https://")
        apply_form.WINDOW.open_link(uid, body.link.strip(), _apply_job(uid))
    else:
        apply_form.WINDOW.resume(uid, _apply_job(uid, body.code.strip()))
    return _fill_status(uid)


@router.get("/accounts")
def accounts(show: bool = False):
    """The accounts the app made on the websites (kept only on this computer)."""
    return [{"website": k, "email": v.get("email", ""), "password": v.get("password", "") if show else "••••••••",
             "state": ACCOUNT_STATES.get(v.get("state"), v.get("state")), "since": (v.get("created") or "")[:16].replace("T", " ")}
            for k, v in sorted(apply_form.load_accounts().items())]
