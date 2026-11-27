"""routes_settings.py - Settings (AI model, keys, search profile, your details), Statistics and AI quota."""
from __future__ import annotations

import os
import time
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .core import (APPLICANT_DEFAULT, CONFIG_DEFAULT, PROFILE_DEFAULT, PROVIDER_LABEL, load_settings, meta,
                   models_caption, own_keys, save_setting, wanted)
from jobfinder import llm, market
from jobfinder.store import ENV_KEYS, SessionLocal, get_setting, save_key

router = APIRouter(prefix="/api")
DEFAULTS = {"config": CONFIG_DEFAULT, "profile": PROFILE_DEFAULT, "applicant": APPLICANT_DEFAULT}
# settings the browser never changes: the providers' addresses (a page could point the AI calls elsewhere)
LOCKED = {"config": {"providers"}}


@router.get("/meta")
def get_meta():
    return meta()


@router.get("/settings")
def settings():
    cfg, prof, ap = load_settings()
    return {"config": cfg, "profile": {**prof, "offer_types": wanted(prof)}, "applicant": ap,
            "models": models_caption(cfg, prof)}


@router.put("/settings/{name}")
def save(name: str, body: dict):
    """Saves the changed fields of one group of settings (config, profile, applicant)."""
    if name not in DEFAULTS:
        raise HTTPException(404, "config, profile or applicant")
    cfg, prof, ap = load_settings()
    cur = {"config": cfg, "profile": prof, "applicant": ap}[name]
    unknown = set(body) - set(DEFAULTS[name]) - set(cur)
    if unknown:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
    # a running search copied its settings when it started: a change applies to the next one
    new = {**cur, **{k: v for k, v in body.items() if k not in LOCKED.get(name, set())}}
    save_setting(name, new)
    return settings()


# --------------------------------------------------------------------------- API keys and models
@router.get("/keys")
def keys():
    """Which providers have a key (shown masked): api_keys.txt."""
    k = own_keys()
    cfg, _, _ = load_settings()
    out = {}
    for p in cfg["providers"]:
        if p == "ollama":
            continue
        v = k.get(p) or os.environ.get(ENV_KEYS.get(p, ""), "")
        out[p] = {"saved": bool(v), "masked": llm.mask(v), "label": PROVIDER_LABEL.get(p, p)}
    return out


class KeyIn(BaseModel):
    key: str


@router.put("/keys/{provider}")
def put_key(provider: str, body: KeyIn):
    cfg, _, _ = load_settings()
    if provider not in cfg["providers"] or provider == "ollama":
        raise HTTPException(404, "Unknown provider")
    try:
        save_key(provider, body.key)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return keys()


@router.get("/models/{provider}")
def models(provider: str):
    """The models this provider offers on your key ('tested': checked on this app's tasks)."""
    cfg, _, _ = load_settings()
    if provider not in cfg["providers"]:
        raise HTTPException(404, "Unknown provider")
    ok, ms, msg = llm.list_models(provider, cfg, own_keys())
    return {"ok": ok, "models": ms if ok else [], "message": msg, "tested": llm.VERIFIED.get(provider, [])}


# --------------------------------------------------------------------------- statistics
LABELS = {"job": "Job (CDI / CDD)", "internship": "Internship", "apprenticeship": "Apprenticeship", "phd_postdoc": "PhD / post-doc",
          "phd": "PhD", "master": "Master", "engineer": "Engineering degree", "bachelor": "Bachelor", "none": "None stated",
          "intern": "Intern", "junior": "Junior", "mid": "Mid-level", "senior": "Senior", "lead": "Lead / principal",
          "onsite": "On site", "hybrid": "Hybrid", "remote": "Remote", "unknown": "Not stated", "cdi": "CDI", "cdd": "CDD",
          "postdoc": "Post-doc", "other": "Other job"}


@router.get("/stats")
def stats():
    """The job market of your field, computed every 15 days from the offers the AI analysed (and the previous period)."""
    with SessionLocal() as s:
        snaps = market.snapshots(s, 2)
        kept = s.query(market.MarketOffer).count()
        due = market.due(s)
    if not snaps:
        return {"current": None, "previous": None, "kept": kept, "due": due, "labels": LABELS}
    cur = snaps[0]
    nxt = cur.created + market.timedelta(days=market.PERIOD_DAYS)
    return {"current": cur.data, "previous": snaps[1].data if len(snaps) > 1 else None, "kept": kept, "due": due,
            "period": f"{cur.period_start:%d %b} – {cur.period_end:%d %b %Y}", "next": f"{nxt:%d %b}", "labels": LABELS}


@router.post("/stats/compute")
def compute_stats():
    with SessionLocal() as s:
        market.archive_offers(s)
        market.compute_snapshot(s)
    return stats()


# --------------------------------------------------------------------------- AI quota
QUOTA_SLOTS = ("gemini", "gemini#2", "gemini#3", "gemini#4", "groq", "groq#2", "groq#3", "groq#4", "nvidia", "openrouter",
               "openrouter#2", "openrouter#3", "cohere", "cohere#2", "cohere#3", "xai")
PROVIDER_NAME = {"gemini": "Gemini", "groq": "Groq", "nvidia": "NVIDIA NIM", "openrouter": "OpenRouter", "cohere": "Cohere",
                 "xai": "xAI (billed)"}
COHERE_MONTH = 1000  # Cohere trial keys: 1,000 calls a month


@lru_cache(maxsize=8)
def _openrouter_info(key, _five_minutes):
    return llm.openrouter_key_info(key)


def _share(left, total):
    return max(0.0, min(1.0, left / total)) if total else 0.0


def _model_bar(prov, model, slot, rec, now, gone) -> dict:
    """One model on one key: what the provider reported, or what the app counted. -> {model, share, text, state}"""
    e, today = rec.get(f"{slot}|{model}", {}), time.strftime("%Y-%m-%d")
    calls = e.get("calls", 0) if e.get("day") == today else 0
    until = max(e.get("until", 0), llm._EXHAUSTED.get((prov, model, slot), 0))
    plural = "s" if calls != 1 else ""
    if f"{slot}|{model}" in gone:
        return dict(model=model, share=0.0, state="gone", text="no longer offered on this key: skipped for a week")
    if e.get("error") and e.get("error_at", 0) > e.get("last_ok", 0) and now - e.get("error_at", 0) < 86400:
        return dict(model=model, share=0.0, state="error", text=f"refused by the provider: {e['error'][:90]}")
    if until > now:
        return dict(model=model, share=0.0, state="limit",
                    text=f"limit reached, back at {datetime.fromtimestamp(until):%H:%M} ({calls} call{plural} today)")
    if e.get("limit") and e.get("day") == today:
        return dict(model=model, share=_share(e["remaining"], e["limit"]), state="ok",
                    text=f"{e['remaining']:,} of {e['limit']:,} requests left today (reported by {PROVIDER_NAME[prov]})")
    if e.get("learned"):
        left = max(0, e["learned"] - calls)
        return dict(model=model, share=_share(left, e["learned"]), state="ok",
                    text=f"about {left} of ~{e['learned']} calls left today (limit reached on an earlier day)")
    return dict(model=model, share=1.0, state="ok", text=f"available · {calls} call{plural} today (no remaining count published)")


@router.get("/quota")
def quota():
    """What each of your API keys has left: as the provider reports it, or as the app counts its calls."""
    rec, now, gone, keys_ = llm.quota_record(), time.time(), llm._gone(), own_keys()
    today = time.strftime("%Y-%m-%d")
    cards = []
    for slot in QUOTA_SLOTS:
        prov = slot.split("#")[0]
        key = keys_.get(slot) or (os.environ.get(ENV_KEYS.get(slot, ""), "") if slot in ENV_KEYS else "")
        if not key:
            continue
        nth = {"#2": "second key", "#3": "third key", "#4": "fourth key"}.get(slot[len(prov):], "")
        entries = {k.split("|", 1)[1]: v for k, v in rec.items() if k.startswith(slot + "|")}
        key_bar = None
        if prov == "cohere":
            used = sum(v.get("month_calls", 0) for v in entries.values() if v.get("month") == today[:7])
            key_bar = dict(share=_share(COHERE_MONTH - used, COHERE_MONTH),
                           text=f"about {max(0, COHERE_MONTH - used):,} of {COHERE_MONTH:,} trial calls left this month")
        if prov == "openrouter":
            info = _openrouter_info(key, int(now // 300))
            cap = 50 if info.get("is_free_tier", True) else 1000  # free models: 50 a day, 1,000 after $10 of credits
            used = sum(v.get("calls", 0) for v in entries.values() if v.get("day") == today)
            key_bar = dict(share=_share(cap - used, cap), text=f"about {max(0, cap - used)} of {cap} free-model requests left today"
                           + ("" if info else " (OpenRouter's account figures could not be read)"))
        cards.append(dict(slot=slot, provider=PROVIDER_NAME[prov], nth=nth, masked=llm.mask(key), key_bar=key_bar,
                          models=[_model_bar(prov, m, slot, rec, now, gone) for p, m in llm.LADDER if p == prov]))
    jobspipe = None
    jp_key = keys_.get("jobspipe") or os.environ.get("JOBSPIPE_API_KEY", "")
    if jp_key:
        with SessionLocal() as s:
            jp = get_setting(s, "jobspipe_credits", {})
        jobspipe = dict(masked=llm.mask(jp_key), share=_share(jp["remaining"], jp["allowance"]) if jp.get("allowance") else 1.0,
                        text=(f"{jp['remaining']:,} of {jp['allowance']:,} credits left "
                              f"(at the last scan, {datetime.fromtimestamp(jp['at']):%d %b %H:%M})") if jp.get("allowance")
                        else "Credits are shown after the first scan that reads JobsPipe")
    return {"cards": cards, "jobspipe": jobspipe}
