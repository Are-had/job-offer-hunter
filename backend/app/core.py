"""core.py - what the routes share: the settings, your API keys, the scan's progress and the helpers that turn the
engine's rows (jobfinder/) into JSON. The data (database, CVs, letters) is in data/, or in JOBFINDER_DATA_DIR when set."""
from __future__ import annotations

import atexit
import json
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the repository: jobfinder/, frontend/, api_keys.txt, assets/, static/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jobfinder import llm, market  # noqa: E402
from jobfinder.analysis import analyze_pipeline  # noqa: E402
from jobfinder.classify import KIND_GROUPS, KIND_LABEL, OFFER_TYPES, contract_type, wanted_types  # noqa: E402
from jobfinder.config import (APPLICANT_DEFAULT, CONFIG_DEFAULT, PRESET_DAYS, PROFILE_DEFAULT,  # noqa: E402
                              run_profile, upgrade_config, upgrade_profile)
from jobfinder.scan import Progress, run_scan  # noqa: E402
from jobfinder.store import (Job, SessionLocal, Source, get_setting, init_db, keep_recent_offers,  # noqa: E402
                             keyword_sources, load_keys, scan_ended, scan_running_elsewhere, set_setting,
                             unfinished_scan, wipe_session_data)
from jobfinder.web import offer_link  # noqa: E402

init_db()

PRESETS = list(PRESET_DAYS) + ["All dates"]
SEARCH_MODES = {"cv": "Search by my CV", "keywords": "Search by keywords"}
STATUS_LABEL = {"relevant": "Relevant", "review": "To check", "candidate": "Not analysed", "new": "Not analysed",
                "excluded": "Excluded", "dismissed": "Removed", "out_of_range": "Out of the date range"}
TYPE_LABEL = {"cdi": "CDI", "cdd": "CDD", "phd": "PhD", "postdoc": "Post-doc", "internship": "Internship",
              "apprenticeship": "Apprenticeship", "other": "Other job", "job": "Job (CDI / CDD not stated)",
              "phd_postdoc": "PhD / post-doc"}
READ_OUTCOME = {"offers_found": "offers found", "nothing_in_range": "read: nothing in the date range",
                "no_offers_detected": "no offers detected", "partial": "possibly incomplete",
                "no_openings": "read: the website says it has no offers now"}
PROVIDER_LABEL = {"ollama": "Ollama (local, free)", "openrouter": "OpenRouter", "xai": "xAI (Grok)", "cohere": "Cohere",
                  "nvidia": "NVIDIA NIM", "gemini": "Gemini", "groq": "Groq", "openai": "OpenAI", "anthropic": "Anthropic"}


# --------------------------------------------------------------------------- settings and keys
def load_settings() -> tuple[dict, dict, dict]:
    """(config, profile, applicant) as saved, upgraded when an older version saved them."""
    with SessionLocal() as s:
        cfg = get_setting(s, "config", CONFIG_DEFAULT)
        prof = get_setting(s, "profile", PROFILE_DEFAULT)
        ap = get_setting(s, "applicant", APPLICANT_DEFAULT)
        cfg = {**cfg, "providers": {**CONFIG_DEFAULT["providers"], **(cfg.get("providers") or {})}}
        prof, changed = upgrade_profile(prof)
        if changed:
            set_setting(s, "profile", prof)
        cfg, changed = upgrade_config(cfg)
        if changed:
            set_setting(s, "config", cfg)
    return cfg, prof, ap


def save_setting(name: str, value: dict):
    with SessionLocal() as s:
        set_setting(s, name, value)


def own_keys() -> dict:
    """Your keys (api_keys.txt)."""
    return load_keys()


def scan_profile(prof: dict) -> dict:
    """The profile a scan works with: by your CV, or by your keywords."""
    return run_profile(prof)


# --------------------------------------------------------------------------- the scan (one at a time, in this process)
class Scanner:
    """The one scan of this process: started in a thread, followed through `prog` (the engine's Progress)."""

    def __init__(self):
        self.prog = Progress()
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self.prog.snap()[0]["running"]) or scan_running_elsewhere()

    def start(self, resume: dict | None = None) -> None:
        cfg, prof, _ = load_settings()
        if resume:
            ids = resume["todo"]
            cfg = {**cfg, **resume.get("cfg", {})}
            prof = scan_profile(resume.get("profile") or prof)
        else:
            with SessionLocal() as s:
                keyword_sources(s, cfg)  # Hellowork searched with the profile's keywords (when ticked)
                ids = [r.id for r in s.query(Source).all()]
            prof = scan_profile(prof)
        keys = own_keys()
        cfg, prof = json.loads(json.dumps(cfg)), json.loads(json.dumps(prof))
        # a search by keywords reads the offers without the AI unless it is turned on
        cfg["ai_analysis"] = not prof.get("keywords_only") or bool(cfg.get("ai_analysis_keywords"))
        cfg["_keys"] = keys if cfg.get("ai_readers", True) else None  # in memory only: lets the AI read hard websites
        self.thread = threading.Thread(
            target=run_scan, args=(ids, cfg, prof, self.prog, lambda pr, feed: analyze_pipeline(cfg, prof, keys, pr, feed)),
            kwargs={"resume": resume}, daemon=True, name="scan")
        self.thread.start()

    def stop(self) -> None:
        self.prog.cancel.set()


SCANNER = Scanner()


def launch():
    """At start: a fresh session (the previous one's websites and offers are deleted, your marks and settings stay),
    unless the last scan did not finish: it waits to be resumed."""
    with SessionLocal() as s:
        left = unfinished_scan(s)
    if not left:
        wipe_session_data()
    with SessionLocal() as s:
        market.run_if_due(s)  # the statistics, every 15 days

    def on_exit():
        if SCANNER.prog.snap()[0]["running"]:  # during a scan: it stays to be resumed, with every offer read so far
            with SessionLocal() as s:
                keep_recent_offers(s)
                scan_ended(s, "the app was closed during the scan")
    atexit.register(on_exit)


# --------------------------------------------------------------------------- offers as JSON
def web_link(u) -> str | None:
    """Only http(s) links are offered (a scraped 'javascript:' URL is never a link)."""
    return u if str(u or "").lower().startswith(("http://", "https://")) else None


def online_for(since) -> str:
    """'2026-10-12' -> '2026-10-12 (30 days)': how long the app has seen the offer online."""
    try:
        n = (datetime.now().date() - datetime.strptime(since, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return ""
    return f"{since} ({'today' if n <= 0 else '1 day' if n == 1 else f'{n} days'})"


def offer_type(j: Job) -> str:
    """The offer's exact type (cdi, cdd, phd, postdoc, internship, apprenticeship, other), else its broad kind (job,
    phd_postdoc), else '' (not stated): the AI's reading first, then the title's."""
    ti, r = (j.extra or {}).get("title_info") or {}, j.relevance_json or {}
    if r.get("contract_type"):
        return r["contract_type"]
    kind = r.get("contract_kind") if r.get("contract_kind") not in (None, "unknown") else (
        ti.get("training") or ("job" if ti.get("contract") in ("cdi", "cdd", "freelance", "interim", "vie") else ""))
    return contract_type(kind, j.title, j.employment_type) or kind or ""


def offer_row(j: Job, mark=None) -> dict:
    """One line of the results list."""
    ti, r = (j.extra or {}).get("title_info") or {}, j.relevance_json or {}
    link = web_link(offer_link(j.url, j.title, j.apply_url))
    return dict(uid=j.uid, title=j.title, company=j.employer or "", location=j.location_original or "",
                published=f"{j.pub_date:%Y-%m-%d}" if j.pub_date else "",
                online_since=online_for((j.extra or {}).get("first_seen")),
                type=TYPE_LABEL.get(offer_type(j), "not stated"),
                topics=", ".join(r.get("research_topics") or ti.get("topics", [])),
                relevance=j.relevance_score, match=j.match_score, link=link, status=j.status,
                applied=bool(mark and mark.state == "applied"), comment=(mark.note or "") if mark else "",
                not_checked=(j.reason or "").endswith("not checked by AI"))


def meta() -> dict:
    """The fixed lists the pages show: offer types, date ranges, providers, labels."""
    cfg, _, _ = load_settings()
    return {"offer_types": OFFER_TYPES, "job_types": list(KIND_GROUPS["job"]), "presets": PRESETS,
            "search_modes": SEARCH_MODES, "providers": list(cfg["providers"]), "provider_labels": PROVIDER_LABEL,
            "paid_providers": sorted(llm.PAID), "type_labels": TYPE_LABEL, "kind_labels": KIND_LABEL,
            "status_labels": STATUS_LABEL}


def wanted(prof: dict) -> list[str]:
    """The offer types a profile looks for, one by one (older profiles: 'job', 'phd_postdoc' expanded)."""
    return [k for k in OFFER_TYPES if k in wanted_types(prof)]


def models_caption(cfg: dict, prof: dict) -> dict:
    """What the next search will use: the first model, whether the AI is used at all, the hosted providers."""
    keys, p2 = own_keys(), scan_profile(prof)
    by_words = bool(p2.get("keywords_only"))
    ai_used = not by_words or bool(cfg.get("ai_analysis_keywords")) or bool(cfg.get("ai_readers", True))
    chain = llm.model_chain(cfg, keys)
    hosted = sorted({x[0] for x in chain if x[0] in llm.PAID}) if cfg.get("auto_models") else []
    return {"ai_used": ai_used, "by_keywords": by_words, "first": {"provider": chain[0][0], "model": chain[0][1]},
            "order": [f"{p} / {m}" + {"#2": " (second key)", "#3": " (third key)", "#4": " (fourth key)"}.get(k[len(p):], "")
                      for p, m, k in chain],
            "hosted": hosted, "keywords": p2.get("keywords") if by_words else []}


def clean_name(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", x)[:120]
