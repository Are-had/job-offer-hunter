"""app.py - Job Finder (dark navy look, Telegraf type only).   Run:  streamlit run app.py
Flow: 1. career websites  ->  2. your CV  ->  3. analysis  ->  results."""
import atexit
import hashlib
import html
import json
import os
import re
import threading
from collections import Counter
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import altair as alt
import pandas as pd
import streamlit as st

from jobfinder import apply as apply_form
from jobfinder import cv as cvm
from jobfinder import llm
from jobfinder import market
from jobfinder.analysis import analyze_pipeline
from jobfinder.classify import KIND_GROUPS, KIND_LABEL, OFFER_TYPES, contract_type, wanted_types
from jobfinder.config import (APPLICANT_DEFAULT, CONFIG_DEFAULT, PRESET_DAYS, PROFILE_DEFAULT, run_config, run_profile,
                             upgrade_config, upgrade_profile)
from jobfinder.scan import PROBLEM_ORDER, Progress, run_scan, site_problem
from jobfinder.store import (ENV_KEYS, CoverLetter, CVDocument, Job, OfferMark, SessionLocal, Source, mark_offer, ensure_gitignore, file_coverage,
                             get_setting, init_db, keep_recent_offers, keyword_sources, load_keys, load_new_sources, people, save_key,
                             save_person_key, delete_key,
                             scan_ended, scan_running_elsewhere, set_setting, wipe_session_data, recent_count,
                             forget_recent_offers, restart_session, unfinished_scan)
from jobfinder.web import extract_urls, offer_link, pasted_urls

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="Job Finder", page_icon=str(ASSETS / "icon.svg"), layout="wide")
init_db()
ensure_gitignore()
st.html(f"<style>{(ASSETS / 'navy.css').read_text(encoding='utf-8')}</style>")


@st.cache_resource
def _launch():
    """Runs once per launch: websites and offers from a previous run are deleted (fresh start), unless the last scan did
    not finish: its websites and results stay, and the Search page offers to resume it or to start again."""
    p = Progress()
    with SessionLocal() as s:
        left = unfinished_scan(s)
    if not left:
        wipe_session_data()  # the analysed offers are first copied into the market history
    with SessionLocal() as s:
        market.run_if_due(s)  # the statistics, every 15 days

    def on_exit():  # the app is turned off
        if p.snap()[0]["running"]:  # during a scan: it stays to be resumed, with every offer read so far
            with SessionLocal() as s:
                keep_recent_offers(s)
                scan_ended(s, "the app was closed during the scan")
            return
        with SessionLocal() as s:
            if unfinished_scan(s):
                return
        wipe_session_data()

    atexit.register(on_exit)
    return p


prog = _launch()
with SessionLocal() as _s:
    CFG, PROFILE, APPLICANT = (get_setting(_s, "config", CONFIG_DEFAULT), get_setting(_s, "profile", PROFILE_DEFAULT),
                               get_setting(_s, "applicant", APPLICANT_DEFAULT))
    # providers added to the app since these settings were saved (NVIDIA): known without re-saving the settings
    CFG = {**CFG, "providers": {**CONFIG_DEFAULT["providers"], **(CFG.get("providers") or {})}}
    PROFILE, _upgraded = upgrade_profile(PROFILE)  # keywords added to the defaults since this profile was saved
    if _upgraded:
        set_setting(_s, "profile", PROFILE)
    CFG, _upgraded = upgrade_config(CFG)  # robots.txt: a setting now (saved once, then the user's choice is kept)
    if _upgraded:
        set_setting(_s, "config", CFG)
c, p, ap = (json.loads(json.dumps(x)) for x in (CFG, PROFILE, APPLICANT))  # working copies, auto-saved at the end
ALL_KEYS = load_keys()
# your own keys: every search for you, letters, CV matching. Your friends' Gemini keys ('gemini@ziyad') are used only in
# the searches made for them (scan_keys)
KEYS = {k: v for k, v in ALL_KEYS.items() if "@" not in k}
FRIENDS = people(ALL_KEYS)
PRESETS = list(PRESET_DAYS) + ["All dates"]
FONT = "PP Telegraf"  # the only typeface of the app (static/fonts), also in the charts
STATUS = {"relevant": ("Relevant", "green"), "review": ("To check", "yellow"), "candidate": ("Not analysed", ""),
          "excluded": ("Excluded", "red")}


# =================================================================== shell: navy top bar and page header
def shell(title, subtitle="", eyebrow="Job Finder", wide=False):
    """The page's navy header: its title, one line about it, and the live counters. wide: the page uses the screen's width."""
    n, d = counts(), prog.snap()[0]
    stats = [(n["sites"], "websites"), (n["cvs"], "CVs"), (n["relevant"], "relevant offers"), (n["review"], "to check")]
    state = ("live", "Analysis running") if d["running"] else ("", "Idle")
    st.html(f'<div class="jf-hero{" jf-wide" if wide else ""}"><div class="jf-top"><span class="jf-eyebrow">{html.escape(eyebrow)}</span>'
            f'<span class="jf-state {state[0]}">{state[1]}</span></div><h1>{html.escape(title)}</h1>'
            f'<p class="jf-lead">{html.escape(subtitle)}</p><div class="jf-stats">'
            + "".join(f'<div class="jf-stat"><b>{v:,}</b><span>{k}</span></div>' for v, k in stats) + "</div></div>")


def counts():
    with SessionLocal() as s:
        return dict(sites=s.query(Source).count(), cvs=s.query(CVDocument).filter_by(enabled=True).count(),
                    relevant=s.query(Job).filter(Job.status == "relevant").count(),
                    review=s.query(Job).filter(Job.status == "review").count())


def brand():
    st.logo(str(ASSETS / "logo.svg"), size="large")  # the whole logo in the navy top bar


def chips(items):  # texts come from websites and CV file names: always escaped
    return '<div class="jf-chips">' + "".join(f'<span class="jf-chip {cls}">{html.escape(str(txt))}</span>'
                                              for txt, cls in items if txt) + "</div>"


def web_link(u):
    """Only http(s) links are offered as buttons (a scraped 'javascript:' URL is never clickable)."""
    return u if str(u or "").lower().startswith(("http://", "https://")) else None


def step(n, title, done):
    st.html(f'<div class="jf-step"><span class="jf-stepnum {"done" if done else ""}">{n}</span>{title}</div>')


def autosave(name, new, old):
    snap = json.dumps(new, sort_keys=True, default=str)
    if snap != json.dumps(old, sort_keys=True, default=str) and snap != st.session_state.get("_saved_" + name):
        with SessionLocal() as s:
            set_setting(s, name, new)
        st.session_state["_saved_" + name] = snap
        st.rerun()


def _sig(files):
    return hashlib.sha1("|".join(f"{f.name}:{f.size}" for f in files).encode()).hexdigest()


# =================================================================== page 1: the three steps
def step_websites(running, n):
    with st.container(border=True, key="card_websites"):
        step(1, "Career websites", n["sites"] > 0)
        files = st.file_uploader("HTML file(s) with the career pages — read, never executed", type=["html", "htm"],
                                 accept_multiple_files=True, disabled=running)
        if files and _sig(files) != st.session_state.get("sites_sig"):  # loaded as soon as the files are chosen
            for f in files:
                if f.size > 2_000_000:
                    st.toast(f"{f.name} is over 2 MB: skipped", icon=":material/warning:")
            origins = {}  # url -> the files that list it: the scan shows how much of each file it searched
            for f in files:
                if f.size <= 2_000_000:
                    for u in extract_urls(f.getvalue().decode("utf-8", errors="replace")):
                        origins.setdefault(u, []).append(f.name)
            try:
                with SessionLocal() as s:
                    load_new_sources(s, list(origins), origins)
            except RuntimeError as e:
                st.error(str(e))
                return
            prog.reset()
            st.session_state["sites_sig"] = _sig(files)
            st.rerun()
        with st.expander("…or paste URLs"):
            pasted = st.text_area("One URL per line", height=90, label_visibility="collapsed")
            if st.button("Use these URLs", disabled=running or not pasted_urls(pasted)):
                try:
                    with SessionLocal() as s:
                        load_new_sources(s, pasted_urls(pasted), {u: ["pasted URLs"] for u in pasted_urls(pasted)})
                except RuntimeError as e:
                    st.error(str(e))
                    return
                prog.reset()
                st.rerun()
        if n["sites"]:
            with SessionLocal() as s:
                srcs = s.query(Source).all()
            st.caption(f"**{len(srcs)} websites** ready. Loading another file replaces them. Search words, page numbers and "
                       "tracking codes from a past search are removed from company URLs, so every website is read whole "
                       "and filtered the same way; country filters and job-board searches are kept.")
            worse = [x for x in srcs if x.health and not x.health.endswith("read again now")]
            if worse:  # the health report: websites that worked at the previous scan and do not any more
                st.warning(f"**{len(worse)} website(s) changed since the previous scan**: "
                           + "; ".join(f"{x.label}: {x.health}" for x in worse[:5]) + (" …" if len(worse) > 5 else ""),
                           icon=":material/monitor_heart:")
            with st.expander("Websites and how each one was read"):
                st.dataframe(pd.DataFrame([dict(website=x.label, file=(x.origin or "").replace("\n", ", "), host=urlparse(x.url).hostname, read_by=x.platform or "—",
                                                status=READ_OUTCOME.get(x.outcome, x.status), offers=x.jobs_found,
                                                on_lists=x.listed, since_last_scan=x.health, note=x.last_error, url=x.url)
                                           for x in srcs]),
                             width="stretch", hide_index=True, height=min(38 + 35 * len(srcs), 420),
                             column_config={"url": st.column_config.LinkColumn("url", display_text="open")})


READ_OUTCOME = {"offers_found": "offers found", "nothing_in_range": "read: nothing in the date range",
                "no_offers_detected": "no offers detected", "partial": "possibly incomplete",
                "no_openings": "read: the website says it has no offers now"}


SEARCH_MODES = {"cv": "Search by my CV", "keywords": "Search by keywords"}


def my_keywords(text) -> list[str]:
    """The keywords typed on the Search page: one per line, or separated by commas or semicolons; each one once."""
    return list(dict.fromkeys(k.strip() for k in re.split(r"[\n,;]", text or "") if k.strip()))


def cv_uploader(running, label):
    up = st.file_uploader(label, type=["pdf"], accept_multiple_files=True, key="cvup", disabled=running)
    if up and _sig(up) != st.session_state.get("cv_sig"):
        with SessionLocal() as s:
            for f in up:
                try:
                    cvm.add_cv(s, f.name, f.getvalue())
                except ValueError as e:
                    st.error(f"{f.name}: {e}")
        st.session_state["cv_sig"] = _sig(up)
        st.rerun()
    with SessionLocal() as s:
        for cv in s.query(CVDocument).all():
            a, b = st.columns([6, 1], vertical_alignment="center")
            a.html(chips([(cv.name, "navy"), (cv.language, ""),
                          ("needs OCR (scanned PDF)" if cv.status == "needs_ocr" else "", "red")]))
            if b.button("Remove", key=f"rm{cv.id}", disabled=running):
                cvm.delete_cv(s, cv.id)
                st.rerun()


def keywords_box(words, running, who="Your"):
    """The keywords of a search: typed one per line or with commas -> the list, shown as chips."""
    words = my_keywords(st.text_area(
        f"{who} keywords — one per line, or separated by commas (English or French)", "\n".join(words or []),
        height=120, placeholder="data scientist\ncomputer vision\ningénieur traitement du signal", disabled=running,
        key=f"kw_{who}"))
    if words:
        st.html(chips([(k, "blue") for k in words]))
        st.caption("A keyword also finds its translation (*computer vision* matches *vision par ordinateur*). "
                   "Offers are not compared with a CV in this mode.")
    else:
        st.caption("Add at least one keyword to start a search.")
    return words


def step_cv(running, n):
    with st.container(border=True, key="card_cv"):
        friend = p.get("search_for") if p.get("search_for") in FRIENDS else ""
        cur = "keywords" if friend else p.get("search_mode") if p.get("search_mode") in SEARCH_MODES else "cv"
        mine = (p.get("people") or {}).get(friend, {}).get("keywords") if friend else p.get("my_keywords")
        step(2, "What you look for", bool(mine) if cur == "keywords" else n["cvs"] > 0)
        if FRIENDS:  # friends who gave their own Gemini key (Settings): a search for one of them uses their key
            p["search_for"] = st.selectbox(
                "Searching for", [""] + FRIENDS, index=([""] + FRIENDS).index(friend), disabled=running,
                format_func=lambda x: "Me" if not x else f"{x.replace('_', ' ').title()} (their own Gemini key)",
                help="A search for a friend: by their keywords, with their own Gemini key (Settings → AI model). "
                     "Your own Gemini keys are not used for it. Each new search replaces the results.")
            friend = p["search_for"]
        if friend:
            st.caption(f"Search by keywords for **{friend.replace('_', ' ').title()}** (your CVs are not used for a friend).")
            people_ = p.setdefault("people", {})
            people_.setdefault(friend, {})["keywords"] = keywords_box(people_[friend].get("keywords"), running,
                                                                      f"{friend.replace('_', ' ').title()}'s")
            return
        p["search_mode"] = st.segmented_control(
            "Search", list(SEARCH_MODES), default=cur, format_func=SEARCH_MODES.get, key="search_mode", disabled=running,
            help="By my CV: offers are chosen with the research profile of Settings, then compared with your CV (CV match). "
                 "By keywords: only offers whose title (then whose work, when the AI analysis is on) matches one of your "
                 "keywords; no CV comparison.") or cur
        if p["search_mode"] == "keywords":
            p["my_keywords"] = keywords_box(p.get("my_keywords"), running)
            with st.expander("Your CV (optional here: only for cover letters and applications)"):
                cv_uploader(running, "PDF CV(s) — not used to rank the offers in a search by keywords")
        else:
            cv_uploader(running, "PDF CV(s) — compared with every relevant offer")
        hosted = sorted({x[0] for x in llm.model_chain(c, KEYS) if x[0] in llm.PAID}) if c["auto_models"] else []
        if hosted:  # the models switch automatically: the consent names every provider that could receive the CV
            ok = st.checkbox(f"Allow sending my CV text to these hosted providers: {', '.join(hosted)}",
                             set(hosted) <= set(c["cv_consent_providers"]),
                             help="Free plans may keep or use what they receive: check each provider's terms.")
            c["cv_consent_providers"] = hosted if ok else []
        elif c["model"]["provider"] in llm.PAID:
            c["send_cv_remote_ok"] = st.checkbox(f"Allow sending my CV text to {c['model']['provider']} (hosted model)",
                                                 c["send_cv_remote_ok"])
        with st.expander("Your details (cover letters and application forms)"):
            st.caption("Used to write your cover letters and to fill application forms ('Open and fill the application' on an "
                       "offer). Kept only on this computer. No password is ever asked or stored: you sign in on each website "
                       "yourself, once, in the application window.")
            if not (ap["first_name"] or ap["last_name"]) and ap["name"]:
                ap["first_name"], ap["last_name"] = apply_form.split_name(ap["name"])
            civ = ["", "M.", "Mme"]
            x, y, z = st.columns([1, 2, 2])
            ap["civility"] = x.selectbox("Civility", civ, civ.index(ap["civility"]) if ap["civility"] in civ else 0)
            ap["first_name"], ap["last_name"] = y.text_input("First name", ap["first_name"]), z.text_input("Last name", ap["last_name"])
            ap["name"] = f"{ap['first_name']} {ap['last_name']}".strip()
            x, y = st.columns(2)
            ap["email"], ap["phone"] = x.text_input("Email", ap["email"]), y.text_input("Phone", ap["phone"])
            ap["address"] = st.text_area("Address (as on your letters)", ap["address"], height=68)
            x, y, z = st.columns(3)
            ap["postal_code"] = x.text_input("Postal code", ap["postal_code"], help="Empty: taken from the address")
            ap["city"] = y.text_input("City", ap["city"], help="Empty: taken from the address")
            ap["country"] = z.text_input("Country", ap["country"])
            x, y = st.columns(2)
            ap["linkedin"], ap["website"] = x.text_input("LinkedIn URL", ap["linkedin"]), y.text_input("Website / GitHub", ap["website"])
            st.markdown("**Education**")
            x, y = st.columns(2)
            ap["degree"], ap["school"] = x.text_input("Highest degree", ap["degree"], placeholder="Master / Bac+5"), \
                y.text_input("School / university", ap["school"])
            ap["field_of_study"], ap["grad_year"] = x.text_input("Field of study", ap["field_of_study"]), \
                y.text_input("Graduation year", ap["grad_year"])
            st.markdown("**Right to work and other questions**")
            auth = {"": "Not said (left to me)", "yes": "Yes, I can work in France", "visa": "No, I need a visa sponsorship"}
            x, y = st.columns(2)
            ap["work_authorization"] = x.selectbox("Right to work in France", list(auth), list(auth).index(ap["work_authorization"])
                                                   if ap["work_authorization"] in auth else 0, format_func=auth.get)
            ap["nationality"] = y.text_input("Nationality", ap["nationality"])
            ap["how_heard"] = st.text_input("How did you hear about the offer?", ap["how_heard"])
            x, y, z = st.columns(3)
            ap["salary_expectation"] = x.text_input("Salary expectation (gross / year, €)", ap.get("salary_expectation", ""),
                                                    placeholder="38000", help="Empty: left to you on each form")
            avail = {"": "Not said (left to me)", "immediately": "Immediately", "1 month": "Within 1 month",
                     "3 months": "Within 3 months"}
            ap["availability"] = y.selectbox("Available to start", list(avail), list(avail).index(ap.get("availability", ""))
                                             if ap.get("availability", "") in avail else 0, format_func=avail.get)
            lvl = {"": "Not said (left to me)", "B2": "Professional (B2)", "C1": "Fluent (C1)", "C2": "Bilingual (C2)"}
            ap["english_level"] = z.selectbox("English level", list(lvl), list(lvl).index(ap.get("english_level", ""))
                                              if ap.get("english_level", "") in lvl else 0, format_func=lvl.get)
            ap["current_position"] = st.text_input("Current or last position (job title)", ap.get("current_position", ""),
                                                   placeholder="Machine Learning Engineer", help="Empty: left to you")
            st.markdown("**Accounts on the websites**")
            st.caption("When a website asks you to sign in, the app signs in with the account it created there, or creates "
                       "one: this email, and a strong password made for that website alone, kept only on this computer "
                       "(data/accounts.json). Captchas and the codes sent by email stay yours.")
            ap["account_email"] = st.text_input("Email for website accounts", ap["account_email"], placeholder=ap["email"],
                                                help="Empty: the email above")
            ap["accept_terms"] = st.checkbox(
                "Let the app accept each website's terms of use (account forms) and tick the required consent box of "
                "application forms", bool(ap["accept_terms"]),
                help="Off: the app leaves every terms or consent box to you. A newsletter, job-alert or partner-offers box "
                     "is never ticked, and no form is ever sent.")
            accounts = apply_form.load_accounts()
            if accounts:
                show = st.toggle("Show the passwords", False, key="show_passwords")
                st.dataframe(pd.DataFrame([{"website": k, "email": v.get("email", ""),
                                            "password": v.get("password", "") if show else "••••••••",
                                            "state": ACCOUNT_STATES.get(v.get("state"), v.get("state")),
                                            "since": (v.get("created") or "")[:16].replace("T", " ")}
                                           for k, v in sorted(accounts.items())]), hide_index=True, width="stretch")


COVERAGE = (("read", "read", "green"), ("partial", "partly read", "amber"), ("failed", "blocked or failed", "red"),
            ("waiting", "not searched yet", "grey"))


def coverage_bars(running):
    """One bar per input file: how many of its websites were searched, and how each one ended."""
    with SessionLocal() as s:
        rows = file_coverage(s)
    if not rows:
        return
    out = []
    for r in rows:
        done, tot = r["total"] - r["waiting"], r["total"] or 1
        segs = "".join(f'<span class="jf-cov-seg {cls}" style="width:{100 * r[k] / tot:.2f}%" title="{r[k]} {lab}"></span>'
                       for k, lab, cls in COVERAGE if r[k])
        if not r["waiting"]:
            head = f"All {r['total']} websites searched"
        else:
            head = f"{done} / {r['total']} websites searched" + ("" if running else f" — {r['waiting']} not reached")
        legend = " · ".join(f'<span class="jf-cov-key {cls}"></span>{r[k]} {lab if k != "waiting" or running else "not reached"}'
                            for k, lab, cls in COVERAGE if r[k])
        out.append(f'<div class="jf-cov"><div class="jf-cov-head"><b>{html.escape(r["file"])}</b><span>{head}</span></div>'
                   f'<div class="jf-cov-bar" role="img" aria-label="{html.escape(r["file"])}: {head}">{segs}</div>'
                   f'<div class="jf-cov-legend">{legend}</div></div>')
    st.html('<div class="jf-covs">' + "".join(out) + "</div>")


def problems_panel(running):
    """Every website that did not work at this scan (blocked, not reachable, page gone, partly read, no offer found...),
    with the reason and what to do. Updated while the scan runs."""
    with SessionLocal() as s:
        rows = []
        for x in s.query(Source).all():
            pb = site_problem(x, scan_finished=not running, respect_robots=bool(c.get("respect_robots", False)))
            if pb:
                rows.append(dict(problem=pb[0], website=x.label or x.url, why=pb[1], what_to_do=pb[2],
                                 file=(x.origin or "").replace("\n", ", "), address=x.url))
    if not rows:
        return
    rows.sort(key=lambda r: (PROBLEM_ORDER.index(r["problem"]), r["website"].lower()))
    by = Counter(r["problem"] for r in rows)
    title = (f"{len(rows)} website{'s' if len(rows) > 1 else ''} did not work{' so far' if running else ''}: "
             + ", ".join(f"{by[k]} {k.lower()}" for k in PROBLEM_ORDER if by[k]))
    esc = html.escape
    groups = []
    for k in PROBLEM_ORDER:
        items = [r for r in rows if r["problem"] == k]
        if not items:
            continue
        dot = "red" if k in PROBLEM_ORDER[:4] else "grey" if k == "Not reached" else "amber"
        lis = "".join(f'<li><a href="{esc(r["address"], quote=True)}" target="_blank" rel="noopener noreferrer">{esc(r["website"])}</a>'
                      + (f' <span class="jf-prob-file">· {esc(r["file"])}</span>' if r["file"] else "")
                      + f'<div class="jf-prob-why">{esc(r["why"])}</div><div class="jf-prob-do">→ {esc(r["what_to_do"])}</div></li>'
                      for r in items)
        groups.append(f'<div><div class="jf-prob-head"><span class="jf-cov-key {dot}"></span>{esc(k)} <span>{len(items)}</span></div>'
                      f'<ul class="jf-prob-list">{lis}</ul></div>')
    df = pd.DataFrame(rows)
    with st.expander(title, expanded=not running):
        st.html('<div class="jf-probs">' + "".join(groups) + "</div>")
        if not running:
            st.download_button("Download this list (CSV)", df.to_csv(index=False).encode("utf-8"), "websites_not_working.csv",
                               "text/csv", icon=":material/download:")


def _monitor():
    d, log = prog.snap()
    if d["running"]:
        st.session_state["was_running"] = True
    elif st.session_state.pop("was_running", False):
        st.rerun()  # the analysis just finished: refresh counts
    if not (d["running"] or d["finished"]):
        return
    if d["running"]:  # a spinning indicator: the search is alive
        st.status(f"Searching… {d['task']} — websites {d['sources_done']} / {d['sources_total']}, "
                  f"{d['jobs']} offers in the date range so far", state="running", expanded=False)
    st.progress(min(d["sources_done"] / (d["sources_total"] or 1), 1.0),
                text=f"{d['task'].capitalize()} — websites {d['sources_done']} / {d['sources_total']}")
    coverage_bars(d["running"])
    problems_panel(d["running"])
    if d["ai_total"]:
        more = " — more arrive as the websites are read" if d["running"] and d["task"] == "crawling" else ""
        st.progress(min(d["ai_done"] / d["ai_total"], 1.0), text=f"AI reading offers {d['ai_done']} / {d['ai_total']}{more}")
        if llm.USAGE["model"]:
            st.caption(f"Model in use: {llm.USAGE['model']}")
    m = st.columns(4)
    m[0].metric("Offers in the date range", d["jobs"])
    m[1].metric("Too old (hidden)", d["date_x"])
    m[2].metric("Not France / not wanted", d["loc_x"] + d["title_x"])
    m[3].metric("Relevant", d["relevant"])
    if d["ai_msg"]:
        st.warning(d["ai_msg"])
    if d["type_x"] and not d["running"]:
        st.warning(f"{d['type_x']} {'offer was' if d['type_x'] == 1 else 'offers were'} set aside only because of their type (internship, PhD, apprenticeship...). "
                   "If you want them too, select these types in 'I am looking for' and analyse again.")
    if not d["running"] and d["finished"]:
        st.page_link(RESULTS, label="See the results", icon=":material/arrow_forward:")
    live_offers()
    with st.expander("Activity log"):
        st.code("\n".join(log[-60:]) or "—", language=None)


def live_offers(limit=100):
    """The newest offers found in the date range, with their links: filled in while the scan runs."""
    with SessionLocal() as s:
        q = s.query(Job).filter(Job.status.notin_(["out_of_range", "excluded"]))
        total = q.count()
        jobs = q.order_by(Job.discovered.desc()).limit(limit).all()
        rows = [dict(title=j.title, company=j.employer, location=j.location_original or j.city or "",
                     published=f"{j.pub_date:%Y-%m-%d}" if j.pub_date else "not stated",
                     link=web_link(offer_link(j.url, j.title, j.apply_url))) for j in jobs]
    if not rows:
        return
    st.markdown(f"**Offers found so far** — {total:,}" + (f" (the {limit} newest shown)" if total > limit else ""))
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=38 + 35 * min(len(rows), 10),
                 column_config={"title": st.column_config.TextColumn(width="large"),
                                "link": st.column_config.LinkColumn("link", help="Opens the offer on its website")})


def step_analysis(running, n):
    with st.container(border=True, key="card_analysis"):
        step(3, "Analysis", bool(prog.snap()[0]["finished"]))
        # each type on its own; a profile saved with 'job' or 'phd_postdoc' shows the types they cover
        cur = [k for k in OFFER_TYPES if k in wanted_types(p)] or list(KIND_GROUPS["job"])
        p["offer_types"] = st.pills("I am looking for", list(OFFER_TYPES), selection_mode="multi", default=cur,
                                    format_func=OFFER_TYPES.get, key="types",
                                    help="Pick each type you want. An offer that does not state its contract is kept: "
                                         "its type shows as 'not stated'.") or cur
        pre = c["date_preset"] if c["date_preset"] in PRESETS else "Last 30 days"
        c["date_preset"] = st.segmented_control("Published within", PRESETS, default=pre, key="preset") or pre
        c["respect_robots"] = st.toggle(
            "Respect robots.txt", value=bool(c.get("respect_robots", False)), disabled=running,
            help="Off (default): no robots.txt rule is applied, only its list of sitemaps is used to find every offer "
                 "(Hellowork's search and its next pages are read, SmartRecruiters' data feed, every offer page). On: the "
                 "app reads only the pages each website's robots.txt allows. Either way the app keeps its own name, reads "
                 "one page per second per website and never gets around an anti-bot page, a login or a captcha.")
        if not c["respect_robots"]:
            st.caption("robots.txt rules are not applied in this scan (the websites' anti-bot protections still are).")
        c["hellowork_keywords"] = st.checkbox(
            "Also search Hellowork with my keywords", value=bool(c.get("hellowork_keywords", True)), disabled=running,
            help="Reads Hellowork's open page of each keyword of the search profile (its 20 newest offers in France: Hellowork "
                 "does not let robots read its search or its next pages). The offers go through the same filters, the "
                 "date range first. Company pages on Hellowork are read when their address is in a website file.")
        prof = scan_profile(p)  # what Start would search: yours by CV or keywords, or a friend's keywords
        by_words = bool(prof.get("keywords_only"))
        if by_words:
            c["ai_analysis_keywords"] = st.toggle(
                "Analyse each offer with AI", bool(c.get("ai_analysis_keywords")), disabled=running,
                help="Off (default for a search by keywords): no AI call for the offers. Every offer whose title has one of "
                     "your keywords, published in the date range and in France, is listed as it is ('not checked by AI'): "
                     "an offer whose place or date the website does not give goes to 'To check', its contract may show "
                     "'not stated', and there is no relevance score and nothing for the Statistics page. On: the AI reads "
                     "each of these offers (date, place, contract, relevance): one AI call per offer.")
        c["ai_readers"] = st.toggle(
            "Use AI to read the websites the app cannot read alone", bool(c.get("ai_readers", True)), disabled=running,
            help="On (default): a website whose offers the app cannot read by itself (no known job platform, offers "
                 "written in the page) is read by the AI page reader or the AI browser — a few AI calls per such website. "
                 "Off: those websites are read without AI and may give fewer offers.")
        ai_used = not by_words or c["ai_analysis_keywords"] or c["ai_readers"]
        m, keys = c["model"], scan_keys(prof.get("search_for") or "")
        first = llm.model_chain(c, keys)[0]
        whose = f" with {first[2].split('@', 1)[1]}'s key" if "@" in first[2] else ""
        if not ai_used:
            models = "No AI call in this search. "
        elif c["auto_models"]:
            models = f"AI models: starts with **{first[0]} / {first[1]}**{whose} and switches when a limit is reached — see Settings. "
        else:
            models = f"AI model **{m['provider']} / {m['model']}**{whose} — change it in Settings. "
        st.caption(models + ("Search by keywords: offers are ranked by your keywords, not compared with a CV." if by_words else
                      "" if n["cvs"] else "No CV yet: offers are ranked, but not compared with a CV."))
        with SessionLocal() as s:
            due = market.due(s)
        c["stats_with_scan"] = st.checkbox(
            "Update the statistics at the end of this scan", value=bool(c.get("stats_with_scan")), disabled=running,
            help="Computes the Statistics page from the offers analysed in the last 15 days as soon as this scan's AI analysis "
                 "ends. Unticked, the statistics are updated every 15 days" + (" (due now)." if due else "."))
        with SessionLocal() as s:
            kept = recent_count(s)
        k1, k2 = st.columns([4, 1], vertical_alignment="center")
        k1.caption(f"**{kept:,}** offers read in the last 24 h are kept: the next scan does not open their pages again, and the "
                   "AI does not analyse them again (same search profile and CVs)." if kept else
                   "No offer kept from the last 24 h: the next scan reads and analyses every offer.")
        if k2.button("Delete them", disabled=running or not kept, icon=":material/delete:", width="stretch",
                     help="Deletes the kept offers and the current results: the next scan reads every page and the AI "
                          "analyses every offer again. The websites, settings, CVs and statistics stay."):
            try:
                st.session_state["kept_msg"] = f"{forget_recent_offers():,} kept offers deleted, and the current results"
            except RuntimeError as e:
                st.session_state["kept_msg"] = str(e)
            st.rerun()
        if st.session_state.get("kept_msg"):
            st.toast(st.session_state.pop("kept_msg"))
        with SessionLocal() as s:
            left = None if running else unfinished_scan(s)
        if left:
            unfinished_box(left)
        x, y, _ = st.columns([1, 1, 3])
        no_words = by_words and not prof.get("keywords")  # a search by keywords needs one
        if not left and x.button("Start", type="primary", disabled=running or not n["sites"] or no_words, icon=":material/play_arrow:",
                                 width="stretch"):
            start_scan()
        if y.button("Stop", disabled=not running, icon=":material/stop:", width="stretch"):
            prog.cancel.set()
        st.fragment(run_every=2 if running else None)(_monitor)()


def scan_profile(prof):
    """The profile of a new scan: yours (by CV or by your keywords), or a friend's search by their own keywords."""
    friend = prof.get("search_for") or ""
    if friend not in FRIENDS:
        return run_profile({**prof, "search_for": ""})
    words = ((prof.get("people") or {}).get(friend) or {}).get("keywords") or []
    return run_profile({**prof, "search_for": friend, "search_mode": "keywords", "my_keywords": words})


def scan_keys(friend) -> dict:
    """The keys of a scan. For you: your own keys. For a friend: their own Gemini key in place of yours (your Gemini keys
    are not used, not even from the environment); your other providers' keys stay as backup when the models switch
    automatically."""
    if not friend or f"gemini@{friend}" not in ALL_KEYS:
        return dict(KEYS)
    return {**KEYS, **{x: "" for x in ("gemini", "gemini#2", "gemini#3", "gemini#4")}, f"gemini@{friend}": ALL_KEYS[f"gemini@{friend}"]}


def start_scan(resume=None):
    """A new scan of every website with today's settings, or the resumed one: its websites still to read, with its own
    search settings and profile, and today's AI settings and keys (credits added in between are used)."""
    if resume:
        ids, cfg, prof = resume["todo"], {**c, **resume.get("cfg", {})}, run_profile(resume.get("profile") or p)
    else:
        with SessionLocal() as s:
            keyword_sources(s, c)  # Hellowork searched with the profile's keywords (when ticked)
            ids = [r.id for r in s.query(Source).all()]
        cfg, prof = c, scan_profile(p)  # search by CV, or by the keywords of step 2 (yours or a friend's)
    keys = scan_keys(prof.get("search_for") or "")
    cfg, prof = json.loads(json.dumps(cfg)), json.loads(json.dumps(prof))
    # a search by keywords reads the offers without the AI unless it is turned on (Search page, step 3)
    cfg["ai_analysis"] = not prof.get("keywords_only") or bool(c.get("ai_analysis_keywords"))
    # in memory only (never saved): lets the AI read the websites the app cannot read alone, when that is allowed
    cfg["_keys"] = keys if c.get("ai_readers", True) else None
    threading.Thread(target=run_scan, args=(ids, cfg, prof, prog, lambda pr, feed: analyze_pipeline(cfg, prof, keys, pr, feed)),
                     kwargs={"resume": resume}, daemon=True).start()
    st.rerun()


def unfinished_box(left):
    """The last scan did not finish (Stop, time limit, AI credits, app closed): resume it, or start again."""
    started = datetime.fromisoformat(left["started"]).replace(tzinfo=timezone.utc).astimezone()  # saved in UTC: local time
    total = len(left.get("source_ids") or [])
    with st.container(border=True, key="card_resume"):
        st.markdown(f"**The last scan did not finish** — {html.escape(left.get('why') or 'stopped')}.")
        st.caption(f"Started {started:%d %b %Y at %H:%M}, range “{left.get('cfg', {}).get('date_preset', '')}”: "
                   f"{left['done']:,} of {total:,} websites read" + (f", {left['pending']:,} offers waiting for the AI analysis"
                                                                     if left["pending"] else "") + ". "
                   "**Resume** reads only the websites not read yet and analyses only the offers not analysed yet, with that "
                   "scan's date range and search profile, and today's AI keys and models (add credits or a key in Settings "
                   "first if they ran out). **Start again** reads every website from the first one; the offers read in the "
                   "last 24 hours are not opened or analysed again.")
        a, b, _ = st.columns([1, 1, 3])
        if a.button("Resume", type="primary", icon=":material/play_arrow:", width="stretch", key="resume_scan"):
            start_scan(resume=left)
        if b.button("Start again", icon=":material/restart_alt:", width="stretch", key="restart_scan"):
            with SessionLocal() as s:
                restart_session(s)
            start_scan()


def page_search():
    shell("Find research & engineering offers in France",
          "Load the career websites, add your CV, then let the app read every offer, date it, place it and rank it.",
          "Search · 3 steps")
    elsewhere = scan_running_elsewhere()
    if elsewhere:  # a scan started outside this app (script, other window): its data is kept and nothing can change
        st.warning("A scan is running in another process: its websites and offers are kept. Loading websites and "
                   "starting a scan are locked until it ends — reload this page then.", icon=":material/lock:")
    running, n = prog.snap()[0]["running"] or elsewhere, counts()
    step_websites(running, n)
    step_cv(running, n)
    step_analysis(running, n)


# =================================================================== page 2: results


def online_for(since):
    """'2026-10-12' -> '2026-10-12 (30 days)': how long the app has seen the offer online."""
    try:
        n = (datetime.now().date() - datetime.strptime(since, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return ""
    return f"{since} ({'today' if n <= 0 else '1 day' if n == 1 else f'{n} days'})"


TYPE_LABEL = {"cdi": "CDI", "cdd": "CDD", "phd": "PhD", "postdoc": "Post-doc", "internship": "Internship",
              "apprenticeship": "Apprenticeship", "other": "Other job", "job": "Job (CDI / CDD not stated)",
              "phd_postdoc": "PhD / post-doc"}


def offer_type(j) -> str:
    """The offer's exact type (cdi, cdd, phd, postdoc, internship, apprenticeship, other), else its broad kind (job,
    phd_postdoc), else '' (not stated): the AI's reading first, then the title's. Offers analysed by an older version have
    no exact type saved: it is read again from their title and employment type."""
    ti, r = (j.extra or {}).get("title_info") or {}, j.relevance_json or {}
    if r.get("contract_type"):
        return r["contract_type"]
    kind = r.get("contract_kind") if r.get("contract_kind") not in (None, "unknown") else (
        ti.get("training") or ("job" if ti.get("contract") in ("cdi", "cdd", "freelance", "interim", "vie") else ""))
    return contract_type(kind, j.title, j.employment_type) or kind or ""


def _rows():
    with SessionLocal() as s:
        out, mine = [], {m.uid: m for m in s.query(OfferMark)}  # your marks: applied, comment (kept between searches)
        for j in s.query(Job).filter(Job.status.notin_(["out_of_range", "dismissed"])).all():
            ti = (j.extra or {}).get("title_info") or {}
            r = j.relevance_json or {}
            m = mine.get(j.uid)
            out.append(dict(uid=j.uid, applied=bool(m and m.state == "applied"), title=j.title, company=j.employer,
                            location=j.location_original or "",
                            # ISO text: sorts by date ('not stated' is written in after sorting)
                            published=f"{j.pub_date:%Y-%m-%d}" if j.pub_date else "",
                            online_since=online_for((j.extra or {}).get("first_seen")),
                            type=TYPE_LABEL.get(offer_type(j), "not stated"),
                            topics=", ".join(r.get("research_topics") or ti.get("topics", [])),
                            relevance=j.relevance_score, match=j.match_score, link=web_link(offer_link(j.url, j.title, j.apply_url)),
                            # the app's own page for the offer, which opens and fills its application at once
                            fill=f"/results?fill={j.uid}",
                            url=web_link(offer_link(j.url, j.title, j.apply_url)),  # the offer's full address, shown in the list
                            comment=m.note if m else "", status=j.status))
    return pd.DataFrame(out)


def page_results():
    shell("Results", "Every offer found, with its exact link, its publication date and why it was kept.", "Offers", wide=True)
    df = _rows()
    fill = st.query_params.get("fill")
    top = st.container()  # the row's 'fill' link: that offer's card, its application opened and filled at once
    if df.empty:
        st.html('<div class="jf-empty"><div class="jf-big">No offers yet</div>Follow the three steps on the Search page.</div>')
        return
    if prog.snap()[0]["running"]:
        r1, r2 = st.columns([5, 1], vertical_alignment="center")
        r1.status("Search in progress — new offers keep arriving", state="running", expanded=False)
        r2.button("Refresh", icon=":material/refresh:", width="stretch", key="refresh_results")
    views = {"Relevant": lambda d: d.status == "relevant", "To check": lambda d: d.status == "review",
             "Not analysed": lambda d: d.status.isin(["candidate", "new"]), "Excluded": lambda d: d.status == "excluded",
             "Applied": lambda d: d.applied, "All": None}
    size = lambda k: len(df) if views[k] is None else int(views[k](df).sum())
    label = lambda k: f"{k} ({size(k)})"
    first = next((k for k in ("Relevant", "To check", "Not analysed") if size(k)), "All")  # opens on a view that has offers
    a, b = st.columns([3, 2])
    view = a.segmented_control("Show", list(views), default=first, format_func=label, key="view") or first
    q = b.text_input("Filter", placeholder="title, company, topic…")
    v = df if views[view] is None else df[views[view](df)]
    order = list(TYPE_LABEL.values()) + ["not stated"]
    present = sorted(set(df.type), key=lambda x: order.index(x) if x in order else len(order))
    kinds = st.pills("Contract", present, selection_mode="multi", key="contract_filter",
                     format_func=lambda x: f"{x} ({int((v.type == x).sum())})",
                     help="Show only these types (CDI, CDD, PhD, post-doc…). None selected: every type.")
    if kinds:
        v = v[v.type.isin(kinds)]
    if q:
        v = v[(v.title + " " + v.company.fillna("") + " " + v.topics + " " + v.type + " " + v.comment).str.lower()
              .str.contains(q.lower(), regex=False)]
    v = v.sort_values(["match", "relevance", "published"], ascending=False, na_position="last")
    v = v.assign(published=v.published.where(v.published != "", "not stated"))
    # up to 20 rows on screen at once; the table scrolls beyond
    sel = st.dataframe(v.drop(columns=["uid", "status"]), width="stretch", hide_index=True, height=38 + 35 * min(max(len(v), 1), 20),
                       # a new key after an offer is removed: the selection does not jump to the next offer
                       on_select="rerun", selection_mode="single-row", key=f"grid{st.session_state.get('grid_n', 0)}",
                       column_config={"title": st.column_config.TextColumn(width="large"),  # the others fit their text
                                      "applied": st.column_config.CheckboxColumn(
                                          "applied", help="You applied (select the row, then 'I applied'): kept between "
                                                          "searches, and the offer is not added again by the next ones"),
                                      "comment": st.column_config.TextColumn("my comment", width="medium"),
                                      "published": st.column_config.TextColumn(
                                          help="'not stated': the website gives no publication date (see 'online since')"),
                                      "online_since": st.column_config.TextColumn(
                                          "online since", help="The first day the app saw the offer, in this or an earlier scan: "
                                                               "an offer without a date was published that day or before"),
                                      "type": st.column_config.TextColumn("contract", help="'not stated': the offer does not say it"),
                                      "relevance": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                                      "match": st.column_config.ProgressColumn("CV match", min_value=0, max_value=100, format="%d"),
                                      "link": st.column_config.LinkColumn(
                                          "description", display_text="read", help="The offer on its website: read it"),
                                      "url": st.column_config.LinkColumn(
                                          "offer link", width="large", help="The offer's address on its website: click to open it"),
                                      "fill": st.column_config.LinkColumn(
                                          "apply", display_text="fill", help="Opens the application in the app's window, "
                                          "signed in (or your account made), everything filled and your CV attached: you check "
                                          "and submit")})
    st.download_button("Export CSV", v.drop(columns=["uid", "fill", "url"]).to_csv(index=False), "offers.csv", icon=":material/download:")
    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        if fill:
            del st.query_params["fill"]  # a row chosen in the table replaces the offer of the link
        offer_actions(v.iloc[rows[0]].uid)
        job_detail(v.iloc[rows[0]].uid)
    elif fill and fill in set(df.uid):
        with top:
            job_detail(fill, autostart=True)
            st.divider()
    else:
        st.caption("Select a row to open the offer, mark it as applied, remove it or comment it — or use its 'fill' link.")
    my_marks()


def offer_actions(uid):
    """For the offer chosen in the list: I applied / Remove it (not for me) / my comment. Remembered between searches: an
    offer you applied to or removed is not added again by the next searches."""
    with SessionLocal() as s:
        j = s.query(Job).filter_by(uid=uid).first()
        if j is None:
            return
        m = s.get(OfferMark, uid)
        state, note = (m.state, m.note or "") if m else ("", "")
        with st.container(border=True, key="card_mine"):
            a, b, x = st.columns([1.3, 1.7, 4], vertical_alignment="bottom")
            if state == "applied":
                if a.button("Applied", icon=":material/check_circle:", key=f"ap_{uid}", width="stretch",
                            help="Click to undo: the offer is no longer marked as applied"):
                    mark_offer(s, j, "")
                    st.rerun()
            elif a.button("I applied", type="primary", icon=":material/send:", key=f"ap_{uid}", width="stretch"):
                mark_offer(s, j, "applied", st.session_state.get(f"note_{uid}"))
                st.rerun()
            if b.button("Remove: not for me", icon=":material/delete:", key=f"rm_{uid}", width="stretch",
                        help="Takes the offer out of the results; the next searches do not add it again. "
                             "Put it back from 'Your applications and removed offers' below."):
                mark_offer(s, j, "dismissed", st.session_state.get(f"note_{uid}"))
                st.session_state["grid_n"] = st.session_state.get("grid_n", 0) + 1
                st.toast(f"Removed: {j.title[:60]}")
                st.rerun()
            new = x.text_input("My comment", note, key=f"note_{uid}",
                               placeholder="sent on 27/11 · call back in 2 weeks · asks for 3 years of experience…")
            if new.strip() != note:  # saved when you press Enter or leave the field
                mark_offer(s, j, None, new)
                st.toast("Comment saved")


MARK_LABEL = {"applied": "applied", "dismissed": "removed (not for me)", "": "comment only"}


def my_marks():
    """Every offer you applied to, removed or commented, kept between searches (the session's offers are deleted at each
    launch, these marks are not): change one, or forget it so that the searches can show the offer again."""
    with SessionLocal() as s:
        marks = s.query(OfferMark).order_by(OfferMark.updated.desc()).all()
        if not marks:
            return
        n = Counter(m.state for m in marks)
        with st.expander(f"Your applications and removed offers — {n['applied']} applied, {n['dismissed']} removed"):
            st.caption("Kept between searches. Applied or removed, an offer is not added again by the next searches. "
                       "Change the status or the comment here; delete a row to forget it (the searches can show the "
                       "offer again).")
            df = pd.DataFrame([dict(uid=m.uid, status=m.state or "", title=m.title, company=m.employer, comment=m.note or "",
                                    date=f"{m.updated:%Y-%m-%d}", link=web_link(m.url)) for m in marks])
            ed = st.data_editor(df, hide_index=True, width="stretch", num_rows="dynamic",
                                key=f"marks_editor{st.session_state.get('marks_n', 0)}",  # new after each change
                                disabled=["title", "company", "date", "link"], column_order=[k for k in df.columns if k != "uid"],
                                column_config={"status": st.column_config.SelectboxColumn(
                                                   "status", options=list(MARK_LABEL), format_func=MARK_LABEL.get, required=True),
                                               "comment": st.column_config.TextColumn("my comment", width="large"),
                                               "link": st.column_config.LinkColumn("link", display_text="open")})
            st.download_button("Export my applications (CSV)", df.drop(columns=["uid"]).to_csv(index=False),
                               "my_applications.csv", icon=":material/download:")
            changed = False
            kept = set(ed.uid.dropna())
            for m in marks:
                if m.uid not in kept:  # row deleted: forgotten, the searches can show the offer again
                    job = s.query(Job).filter_by(uid=m.uid).first()
                    if job is not None and job.status == "dismissed":
                        job.status, job.reason = "new", ""
                    s.delete(m)
                    changed = True
            for r in ed.itertuples():
                m = s.get(OfferMark, r.uid) if isinstance(r.uid, str) else None
                if m is None or (m.state, m.note or "") == (r.status or "", r.comment or ""):
                    continue
                job = s.query(Job).filter_by(uid=m.uid).first()
                if job is not None:
                    mark_offer(s, job, r.status or "", r.comment or "")
                else:  # the offer is not in this session's results any more: only the record changes
                    m.state, m.note, m.updated = r.status or "", (r.comment or "").strip(), datetime.utcnow()
                changed = True
            if changed:  # a fresh editor: its edits are not applied again to the rows as they are now
                s.commit()
                st.session_state["marks_n"] = st.session_state.get("marks_n", 0) + 1
                st.rerun()


def job_detail(uid, autostart=False):
    with SessionLocal() as s:
        j = s.query(Job).filter_by(uid=uid).first()
        ti, r = (j.extra or {}).get("title_info") or {}, j.relevance_json or {}
        label, cls = STATUS.get(j.status, (j.status, ""))
        with st.container(border=True, key="card_offer"):
            st.subheader(j.title, anchor=False)
            kind = offer_type(j)
            st.html(chips([(j.employer, "navy"), (label, cls), (KIND_LABEL.get(kind, ""), "blue"),
                           ("" if kind else "contract not stated", ""), ("" if j.pub_date else "no publication date", "yellow"),
                           ("research subject" if ti.get("kind") == "research_topic" else "", "blue"),
                           ({"fr": "français", "en": "English"}.get(ti.get("lang"), ""), "")]
                          + [(t, "") for t in (r.get("research_topics") or ti.get("topics") or [])[:6]]))
            l1, l2, _ = st.columns([1, 1, 3])
            link = web_link(offer_link(j.url, j.title, j.apply_url))
            if link:
                l1.link_button("Open the offer", link, icon=":material/open_in_new:", width="stretch", type="primary")
            if web_link(j.apply_url) and j.apply_url not in (j.url, link) and "jboffer=" not in j.apply_url:
                l2.link_button("Apply page", j.apply_url, icon=":material/send:", width="stretch")
            _apply_controls(s, j, link, autostart)
            a, b = st.columns(2)
            seen = (j.extra or {}).get("first_seen")
            when = (f"{j.pub_date:%d %b %Y}" if j.pub_date else "not stated by the website" +
                    (f" — online since at least {online_for(seen)}: published that day or before" if seen else ""))
            a.html(f'<div class="jf-kv"><b>Published</b> {when}</div>')
            if j.date_source or j.pub_date_text:
                a.caption(f"{j.date_source or '—'}" + (f" · “{j.pub_date_text[:80]}”" if j.pub_date_text else ""))
            b.html(f'<div class="jf-kv"><b>Location</b> {html.escape(j.location_original or "unknown")}</div>')
            b.caption(j.location_evidence or "")
            if r:
                st.markdown(f"**Relevance {r.get('relevance_score', 0):.0f}/100** · {r.get('reasoning_summary', '')}")
                ex = j.extra or {}
                if ex.get("ai_model"):
                    st.caption(f"Read by {ex['ai_model']}" + (f" · first read by {ex['first_reading']}, then by a better model"
                                                             if ex.get("first_reading") else ""))
            if j.status == "review":
                flags = [f.replace("_", " ") for f in (j.review_flags or "").split(",") if f and f != "publication_date_unknown"]
                st.info("To check: " + " · ".join(flags) if flags else "To check.")
                if st.button("Keep this offer"):
                    j.status, j.review_flags = ("relevant" if j.relevance_score is not None else "candidate"), ""
                    s.commit()
                    st.rerun()
            elif j.status == "excluded":
                st.caption(f"Excluded: {j.reason}")
        with st.expander("Description"):
            st.write(j.description or "(none)")
        _cv_and_letter(s, j)


ACCOUNT_STATES = {"created": "created", "sent": "sent to the website", "waiting_code": "waiting for the email code",
                  "waiting_link": "waiting for you to click the link in the confirmation email",
                  "creating": "form filled, not sent yet", "wrong_password": "the website refuses this password"}
FIELD_NAMES = {"first_name": "first name", "last_name": "last name", "full_name": "full name", "email": "email",
               "phone": "phone", "address": "address", "postal_code": "postal code", "city": "city", "country": "country",
               "linkedin": "LinkedIn", "website": "website", "civility": "civility", "nationality": "nationality",
               "degree": "degree", "school": "school", "grad_year": "graduation year", "field_of_study": "field of study",
               "work_authorization": "right to work", "sponsorship": "visa sponsorship", "how_heard": "how you heard",
               "cover_letter": "cover letter", "cv": "CV (attached)"}


def _apply_letter(s, j):
    """The text pasted into the form's cover-letter box: a short message of 5 lines at most (greeting, 3 sentences at most,
    signature), written once for the offer with the AI and kept. The full letter (LaTeX / PDF, below) is the file the user
    attaches. -> (text, where it comes from)"""
    saved = apply_form.message_path(j.uid)
    if saved.exists():
        return apply_form.clamp_lines(saved.read_text(encoding="utf-8")), "the short message written for this offer"
    cvs = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok"]
    if not cvs:
        return "", "no CV uploaded, so no message was written"
    cv = next((x for x in cvs if x.name == j.best_cv), cvs[0])
    try:
        msg = cvm.generate_form_message(s, j, cv, run_config(c), KEYS)
    except llm.AIError as e:
        return "", f"no message written: {str(e)[:150]}"
    text = apply_form.form_message(ap, msg.lines)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(text, encoding="utf-8")
    return text, f"short message written for this offer ({apply_form.MAX_LINES} lines at most)"


def _free_page_reader():
    """A page the rules do not understand, without an Anthropic key: read once by the free models of the user's other
    keys (structure only), from the application window's thread with its own database session (the AI cache)."""
    cfg, keys = {**run_config(c), "_timeout": 25, "_no_wait": True}, dict(KEYS)  # the user waits at the window

    def ask(prompt, schema, system):
        with SessionLocal() as s2:
            return llm.call_json(prompt, schema, cfg, s2, keys, system=system)
    return ask


def _apply_cv(uid) -> str:
    """The CV the form's CV field takes: the one that matches the offer best, else the first CV uploaded."""
    with SessionLocal() as s:
        j = s.query(Job).filter_by(uid=uid).first()
        cvs = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok" and x.path]
        cv = next((x for x in cvs if j is not None and x.name == j.best_cv), cvs[0] if cvs else None)
        return str(cv.path) if cv and Path(cv.path).exists() else ""


def _apply_letter_pdf(uid) -> str:
    """The offer's latest cover letter as a PDF (written and compiled on its card), for a form's letter file field."""
    with SessionLocal() as s:
        for cl in s.query(CoverLetter).filter_by(job_uid=uid).order_by(CoverLetter.version.desc()).all():
            if cl.pdf_path and Path(cl.pdf_path).exists():
                return str(cl.pdf_path)
    return ""


def _apply_job(uid, code=""):
    """What the application window needs: the details, the message, the CV, the account email, the user's choices, the
    keys."""
    text = st.session_state.get(f"apply_letter_{uid}", ("", ""))[0]
    with SessionLocal() as s:
        title = (s.query(Job.title).filter(Job.uid == uid).scalar() or "")
    values = {**apply_form.form_values(ap), "position": re.sub(r"\s+", " ", title).strip()[:120]}  # 'Poste recherché'
    return {"values": values, "letter": text, "email": ap["account_email"] or ap["email"],
            "allow_terms": bool(ap["accept_terms"]), "ai_key": KEYS.get("anthropic", ""), "ai_free": _free_page_reader(),
            "cv_path": _apply_cv(uid), "letter_path": _apply_letter_pdf(uid), "code": code}


def _apply_status(uid):
    stt = apply_form.WINDOW.status.get(uid)
    if not stt:
        return
    msg = stt.get("message", "")
    show = {"filled": st.success, "nothing": st.info, "no_form": st.warning, "needs_user": st.warning,
            "needs_code": st.warning, "needs_link": st.warning, "wrong_password": st.warning, "blocked": st.warning, "gone": st.warning, "by_email": st.info,
            "error": st.error}.get(stt.get("state"), st.info)
    show(msg + (" Filled: " + ", ".join(FIELD_NAMES.get(k, k) for k in stt.get("filled", [])) + "." if stt.get("filled") else ""),
         icon=":material/assignment_turned_in:")
    if stt.get("state") == "needs_code":  # here, in the part that follows the window: the box shows as soon as it is asked
        c1, c2 = st.columns([2, 1])
        code = c1.text_input("Code from the email", key=f"code{uid}", label_visibility="collapsed",
                             placeholder="Code received by email")
        if c2.button("Send the code", key=f"sc{uid}", icon=":material/send:", width="stretch") and code.strip():
            apply_form.WINDOW.resume(uid, _apply_job(uid, code.strip()))
    if stt.get("state") in ("needs_link", "wrong_password") and stt.get("site"):
        # some websites email a password they made (Talentsoft, MAIF): kept with the account, then the app signs in
        c1, c2 = st.columns([2, 1])
        given = c1.text_input("Password from the email", key=f"pw{uid}", type="password", label_visibility="collapsed",
                              placeholder="Password from the website's email (if it sent one)")
        if c2.button("Use this password", key=f"up{uid}", icon=":material/key:", width="stretch") and given.strip():
            apply_form.set_account(stt["site"], None, password=given.strip(), state="created",
                                   password_from="the website's email")
            apply_form.WINDOW.resume(uid, _apply_job(uid))
        l1, l2 = st.columns([2, 1])  # or the email's link (activate the account, set its password): opened in the window
        link = l1.text_input("Link from the email", key=f"ln{uid}", label_visibility="collapsed",
                             placeholder="…or paste the link from the website's email")
        if l2.button("Open it in the window", key=f"ol{uid}", icon=":material/link:", width="stretch") and link.strip():
            if link.strip().lower().startswith("https://"):
                apply_form.WINDOW.open_link(uid, link.strip(), _apply_job(uid))
            else:
                st.warning("Paste the whole link, starting with https://")
    acct = apply_form.load_accounts().get(stt.get("site", ""))
    if acct:
        st.caption(f"Account on {stt['site']}: {acct.get('email', '')} · "
                   + ACCOUNT_STATES.get(acct.get("state"), acct.get("state", "")) + " (password: Search, step 2)")
    if stt.get("steps"):
        st.caption("Steps: " + " → ".join(stt["steps"]))
    text, note = st.session_state.get(f"apply_letter_{uid}", ("", ""))
    if note:
        with st.expander(f"Cover letter pasted in the form: {note}" if text else f"Cover letter: {note}"):
            if text:
                st.code(text, language=None, wrap_lines=True)


def _start_fill(s, j, target):
    """The offer's application opened in the app's window and filled (the button, or the 'fill' link of its row)."""
    if not (ap["first_name"] and ap["last_name"] and ap["email"]):
        st.warning("Add your first name, last name and email first: Search page, step 2, 'Your details'.")
        return
    with st.spinner("Preparing the message for this offer…"):
        st.session_state[f"apply_letter_{j.uid}"] = _apply_letter(s, j)
    apply_form.WINDOW.open(j.uid, target, _apply_job(j.uid))


def _apply_controls(s, j, link, autostart=False):
    """'Open and fill the application': the offer opened in the app's own browser window on this computer, signed in (or
    an account created) when the website asks, its form filled with the user's details and a short message for the
    offer. The user attaches the CV and the letter and submits."""
    target = j.apply_url if web_link(j.apply_url) and "jboffer=" not in j.apply_url else link
    if not target:
        return
    ok, why = apply_form.can_open_window()
    x1, x2, x3 = st.columns([2, 1.2, 1.8])
    if x1.button("Open and fill the application", key=f"ap{j.uid}", icon=":material/assignment_turned_in:", width="stretch",
                 disabled=not ok, help=why or ("Opens the application in a browser window of the app on this computer, signs "
                                               "in (or creates your account) when the website asks, and fills in your "
                                               "details and a short message for this offer. You attach your CV and letter "
                                               "and submit yourself.")):
        _start_fill(s, j, target)
    elif autostart and ok and not st.session_state.get(f"autofilled_{j.uid}"):
        st.session_state[f"autofilled_{j.uid}"] = True  # once: a rerun of the page never opens it again
        if not apply_form.WINDOW.status.get(j.uid):
            _start_fill(s, j, target)
    stt = apply_form.WINDOW.status.get(j.uid)
    if stt:
        if x2.button("Continue", key=f"af{j.uid}", icon=":material/play_arrow:", width="stretch",
                     help="After you acted in the window: signed in, solved a captcha, ticked a box, opened the next step"):
            apply_form.WINDOW.resume(j.uid, _apply_job(j.uid))
        st.fragment(run_every=2)(_apply_status)(j.uid)


def _cv_and_letter(s, j):
    cvs = [x for x in s.query(CVDocument).filter_by(enabled=True).all() if x.status == "ok"]
    if not cvs:
        return
    with st.container(border=True, key="card_letter"):
        st.html('<div class="jf-section">CV match & cover letter</div>')
        if j.match_json:
            st.dataframe(pd.DataFrame([{"cv": k, "score": x["match_score"], "advice": x["recommendation"],
                                        "missing": ", ".join(x["missing_requirements"]), "not shown in CV": ", ".join(x["not_evidenced"])}
                                       for k, x in j.match_json.items()]), width="stretch", hide_index=True)
        names = [x.name for x in cvs]
        x1, x2, x3 = st.columns([1, 1, 2])
        if not j.match_json and x1.button("Compare with my CV", icon=":material/compare_arrows:", width="stretch"):
            try:
                cvm.match_job(s, j, run_config(CFG), KEYS)
                st.rerun()
            except llm.AIError as e:
                st.error(str(e))
        cvn = x3.selectbox("CV for the letter", names, names.index(j.best_cv) if j.best_cv in names else 0, label_visibility="collapsed")
        if x2.button("Write cover letter", icon=":material/edit_note:", width="stretch"):
            if not APPLICANT["name"]:
                st.error("Add your name in step 2 (Your details) first.")
            else:
                try:
                    cv = next(x for x in cvs if x.name == cvn)
                    cvm.save_letter(s, j, cvn, cvm.build_tex(APPLICANT, j, cvm.generate_letter_content(s, j, cv, run_config(CFG), KEYS)))
                    st.rerun()
                except llm.AIError as e:
                    st.error(str(e))
        for cl in s.query(CoverLetter).filter_by(job_uid=j.uid).order_by(CoverLetter.version.desc()).all()[:1]:
            if not Path(cl.tex_path).exists():
                continue  # the letter file was deleted from the disk
            txt = st.text_area(f"Letter v{cl.version} (LaTeX, editable)", Path(cl.tex_path).read_text(encoding="utf-8"), height=260,
                               key=f"tx{cl.id}")
            c1, c2, c3 = st.columns(3)
            if c1.button("Save as new version", key=f"sv{cl.id}", icon=":material/save:"):
                cvm.save_letter(s, j, cl.cv_name, txt, "edited")
                st.rerun()
            c2.download_button("Download .tex", txt, f"{j.uid}.tex")
            if cl.pdf_path and Path(cl.pdf_path).exists():
                c3.download_button("Download PDF", Path(cl.pdf_path).read_bytes(), f"{j.uid}.pdf")


# =================================================================== page 3: settings (AI model + search profile)
def settings_ai():
    c["auto_models"] = st.toggle("Switch models automatically", c["auto_models"],
                                 help="Starts with the most capable model. When a limit is reached, the next one takes over.")
    if c["auto_models"]:
        nth = {"#2": " (second key)", "#3": " (third key)", "#4": " (fourth key)"}
        order = [f"{i}. {p} / {m}" + nth.get(k[len(p):], "") for i, (p, m, k) in enumerate(llm.model_chain(c, KEYS), 1)]
        st.caption("Order of use: " + " → ".join(order))
    provs = list(c["providers"])
    models = st.session_state.setdefault("models", {})
    a, b = st.columns([1, 2], vertical_alignment="bottom")
    prov = a.selectbox("Provider", provs, index=provs.index(CFG["model"]["provider"]) if CFG["model"]["provider"] in provs else 0,
                       format_func=lambda x: {"ollama": "ollama (local, free)", "openrouter": "Open Router", "xai": "xAI (Grok)", "cohere": "Cohere", "nvidia": "NVIDIA NIM"}.get(x, x))
    if prov != "ollama":
        have = prov in KEYS or os.environ.get(ENV_KEYS[prov])
        key = b.text_input(f"API key for {prov}", type="password", placeholder="key saved" if have else "paste your key")
        if key and st.button("Save key"):
            try:
                save_key(prov, key)
                st.toast(f"Key saved for {prov}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if st.button("Load the models", icon=":material/sync:"):
        with st.spinner("Contacting the provider…"):
            ok, ms_, msg = llm.list_models(prov, c, KEYS)
        (st.success if ok else st.error)(msg)
        if ok:
            models[prov] = ms_
    if models.get(prov):
        ms = models[prov]
        cur = CFG["model"]["model"] if CFG["model"]["provider"] == prov and CFG["model"]["model"] in ms else ms[0]
        ok = llm.VERIFIED.get(prov, [])
        c["model"] = {"provider": prov, "model": st.selectbox("Model", ms, ms.index(cur),
                                                              format_func=lambda m: f"{m}  (tested)" if m in ok else m)}
        st.caption("Tested: checked on this app's tasks (offer analysis, publication date, lab pages, browser).")
    st.caption(f"In use: **{c['model']['provider']} / {c['model']['model']}**")
    friends_keys()


def friends_keys():
    """Friends who also look for a job give their own Gemini key: a search made for one of them (Search page, 'Searching
    for') uses their key and their keywords, never for anyone else's search."""
    st.divider()
    st.markdown("**Friends' Gemini keys**")
    st.caption("A friend who also looks for a job can give you their own Gemini key. A search made for them (Search page → "
               "'Searching for') uses their key and their keywords; it is never used for your searches or another friend's. "
               "Kept only on this computer, in api_keys.txt.")
    for f in FRIENDS:
        a, b = st.columns([5, 1], vertical_alignment="center")
        a.html(chips([(f.replace("_", " ").title(), "navy"), (llm.mask(ALL_KEYS[f"gemini@{f}"]), "")]))
        if b.button("Remove", key=f"rmkey_{f}"):
            delete_key(f"gemini@{f}")  # a search still set for this friend becomes yours again (scan_profile)
            st.toast(f"{f}'s key removed")
            st.rerun()
    a, b, x = st.columns([2, 3, 1], vertical_alignment="bottom")
    name = a.text_input("Friend's name", key="friend_name", placeholder="Ziyad")
    key = b.text_input("Their Gemini API key", type="password", key="friend_key", placeholder="AIza…")
    if x.button("Add", disabled=not (name and key), width="stretch", key="friend_add"):
        try:
            n = save_person_key(name, key)
            st.toast(f"Key saved for {n}")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def settings_profile():
    p["description"] = st.text_area("My research interests (every offer is compared with this)", p["description"])
    a, b = st.columns(2)
    p["keywords"] = [x.strip() for x in a.text_area("Wanted topics / titles — English or French, one per line",
                                                    "\n".join(p["keywords"]), height=280).splitlines() if x.strip()]
    a.caption("A topic also finds its translation: *computer vision* matches *vision par ordinateur*.")
    p["exclude_titles"] = [x.strip() for x in b.text_area("Words that exclude an offer", "\n".join(p["exclude_titles"]),
                                                          height=200).splitlines() if x.strip()]
    c["min_relevance"] = b.slider("Minimum relevance", 0, 100, int(c["min_relevance"]))


def page_settings():
    shell("Settings", "The AI model and your search profile. Every change is saved automatically.", "Preferences")
    t1, t2 = st.tabs(["AI model", "Search profile"])
    with t1, st.container(border=True, key="card_ai"):
        settings_ai()
    with t2, st.container(border=True, key="card_profile"):
        settings_profile()


# =================================================================== page: market statistics (every 15 days)
NAVY, INK, INK_DIM, GRID = "#4A78C8", "#C9D3E3", "#8C9BB4", "#1F2E4A"  # chart colours on the dark cards
LABELS = {"job": "Job (CDI / CDD)", "internship": "Internship", "apprenticeship": "Apprenticeship", "phd_postdoc": "PhD / post-doc",
          "phd": "PhD", "master": "Master", "engineer": "Engineering degree", "bachelor": "Bachelor", "none": "None stated",
          "intern": "Intern", "junior": "Junior", "mid": "Mid-level", "senior": "Senior", "lead": "Lead / principal",
          "onsite": "On site", "hybrid": "Hybrid", "remote": "Remote", "unknown": "Not stated"}


def hbar(rows, label, value="offers", prev=None):
    """Ranked counts: one series, one colour, sorted, value written at the bar's end, tooltip on hover."""
    df = pd.DataFrame([[LABELS.get(str(k), k), v] for k, v in rows], columns=[label, value])
    if df.empty:
        st.caption("No data in this period yet.")
        return
    tip = [alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{value}:Q")]
    if prev is not None:
        df["previous period"] = [dict(prev).get(k, 0) for k, _ in rows]
        tip.append(alt.Tooltip("previous period:Q"))
    base = alt.Chart(df).encode(
        y=alt.Y(f"{label}:N", sort="-x", title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=260, labelColor=INK,
                                                                    labelOverlap=False, labelPadding=6)),
        x=alt.X(f"{value}:Q", title=None, axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)))
    bars = base.mark_bar(color=NAVY, cornerRadiusEnd=4, height=14).encode(tooltip=tip)
    text = base.mark_text(align="left", dx=5, color=INK_DIM, fontSize=12).encode(text=f"{value}:Q")
    st.altair_chart((bars + text).properties(height=28 * len(df) + 8, background="transparent").configure_view(stroke=None)
                    .configure(font=FONT),
                    width="stretch")


def page_stats():
    shell("Statistics", "The job market of your field: computed every 15 days from the offers the AI analysed.", "Market")
    with SessionLocal() as s:
        snaps = market.snapshots(s, 2)
        kept = s.query(market.MarketOffer).count()
        due_now = market.due(s)
    cur = snaps[0] if snaps else None
    prev = snaps[1].data if len(snaps) > 1 else None
    with st.container(border=True, key="card_stats_head"):
        a, b = st.columns([3, 1], vertical_alignment="center")
        if cur:
            nxt = cur.created + market.timedelta(days=market.PERIOD_DAYS)
            a.markdown(f"**Period:** {cur.period_start:%d %b} – {cur.period_end:%d %b %Y} · next computation on "
                       f"**{nxt:%d %b}** · {kept:,} analysed offers kept in the history (6 months)")
        else:
            a.markdown(f"No statistics yet: they are computed from the offers the AI analyses (history: {kept:,} offers). "
                       "Run a scan with AI analysis first.")
        if b.button("Compute now", disabled=not kept, help="Statistics of the last 15 days, from the offers kept in the history"):
            with SessionLocal() as s:
                market.archive_offers(s)
                market.compute_snapshot(s)
            st.rerun()
        if due_now and cur:
            st.caption("15 days have passed: the next scan with AI analysis computes a new snapshot.")
    if not cur:
        return
    d = cur.data
    pv = (lambda k: prev.get(k)) if prev else (lambda k: None)
    share = lambda rows, key: round(100 * dict(rows).get(key, 0) / max(1, sum(v for _, v in rows)))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Relevant offers" if d["base"] == "relevant" else "Analysed offers", d["relevant"] or d["analysed"],
              delta=(d["relevant"] - pv("relevant")) if prev else None)
    m2.metric("Companies hiring", d["companies"], delta=(d["companies"] - pv("companies")) if prev else None)
    m3.metric("Remote or hybrid", f"{share(d['remote'], 'remote') + share(d['remote'], 'hybrid')} %")
    m4.metric("Average CV match", f"{d['avg_match']:.0f} / 100" if d.get("avg_match") is not None else "—",
              help="Shown once CVs are compared with relevant offers")
    if d["base"] != "relevant":
        st.info("No offer was judged relevant in this period: the figures cover every offer the AI analysed.")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True, key="card_stats_skills"):
        st.markdown("**Most requested skills**")
        st.caption("Number of offers asking for each skill, tool or method: what to put first on the CV.")
        hbar(d["top_skills"], "skill", prev=pv("top_skills"))
    with c2, st.container(border=True, key="card_stats_gaps"):
        st.markdown("**Skills missing from the CV**")
        st.caption("Requirements of the offers that the CV does not show: what to learn or to make visible.")
        hbar(d["skill_gaps"], "requirement", prev=pv("skill_gaps"))
    c3, c4 = st.columns(2)
    with c3, st.container(border=True, key="card_stats_companies"):
        st.markdown("**Companies hiring the most**")
        hbar(d["top_companies"], "company", prev=pv("top_companies"))
    with c4, st.container(border=True, key="card_stats_cities"):
        st.markdown("**Cities**")
        hbar(d["cities"], "city", prev=pv("cities"))
    with st.container(border=True, key="card_stats_weeks"):
        st.markdown("**Offers per week**")
        wk = pd.DataFrame(d["weeks"], columns=["week", "offers"])
        if len(wk):
            st.altair_chart(alt.Chart(wk).mark_bar(color=NAVY, cornerRadiusEnd=4, size=26)
                            .encode(x=alt.X("week:N", title=None, axis=alt.Axis(labelAngle=0, ticks=False, domain=False)),
                                    y=alt.Y("offers:Q", title=None, axis=alt.Axis(grid=True, gridColor=GRID, domain=False, ticks=False, format="d", tickMinStep=1)),
                                    tooltip=["week", "offers"]).properties(height=180, background="transparent")
                            .configure_view(stroke=None).configure(font=FONT), width="stretch")
    st.markdown('<div class="jf-section">Profile of the offers</div>', unsafe_allow_html=True)
    p1, p2, p3 = st.columns(3)
    for col, key, title in ((p1, "contracts", "Contract"), (p2, "degree", "Degree required"), (p3, "seniority", "Seniority")):
        with col, st.container(border=True, key=f"card_stats_{key}"):
            st.markdown(f"**{title}**")
            hbar(d[key], title.lower())
    p4, p5 = st.columns(2)
    with p4, st.container(border=True, key="card_stats_languages"):
        st.markdown("**Languages required**")
        hbar(d["languages"], "language")
    with p5, st.container(border=True, key="card_stats_remote"):
        st.markdown("**Remote work**")
        hbar(d["remote"], "remote work")
    t1, t2 = st.tabs(["Best CV matches", "Salaries stated"])
    with t1:
        if d["best_titles"]:
            st.dataframe(pd.DataFrame(d["best_titles"], columns=["offer", "company", "CV match"]), hide_index=True, width="stretch")
        else:
            st.caption("Upload a CV: the offers it matches best are listed here.")
    with t2:
        if d["salaries"]:
            st.dataframe(pd.DataFrame(d["salaries"], columns=["offer", "company", "salary as written"]), hide_index=True, width="stretch")
        else:
            st.caption("No offer of this period states a salary.")
    with st.expander("Websites giving the most offers of your field"):
        hbar(d["websites"], "website")


# =================================================================== page 4: what each AI key has left
QUOTA_SLOTS = ("gemini", "gemini#2", "gemini#3", "gemini#4", "groq", "groq#2", "groq#3", "groq#4", "nvidia", "openrouter", "openrouter#2", "openrouter#3", "cohere", "cohere#2", "cohere#3", "xai")
PROVIDER_NAME = {"gemini": "Gemini", "groq": "Groq", "nvidia": "NVIDIA NIM", "openrouter": "OpenRouter", "cohere": "Cohere",
                 "xai": "xAI (billed)"}
COHERE_MONTH = 1000  # Cohere trial keys: 1,000 calls a month


@st.cache_data(ttl=300, show_spinner=False)
def _openrouter_info(key):
    return llm.openrouter_key_info(key)


def _share(left, total):
    return max(0.0, min(1.0, left / total)) if total else 0.0


def _model_bar(prov, model, slot, rec, now, gone):
    """One model on one key: what the provider reported, or what the app counted."""
    e, today = rec.get(f"{slot}|{model}", {}), time.strftime("%Y-%m-%d")
    calls = e.get("calls", 0) if e.get("day") == today else 0
    until = max(e.get("until", 0), llm._EXHAUSTED.get((prov, model, slot), 0))
    if f"{slot}|{model}" in gone:
        st.progress(0.0, text=f"{model} — no longer offered on this key: skipped for a week")
    elif e.get("error") and e.get("error_at", 0) > e.get("last_ok", 0) and now - e.get("error_at", 0) < 86400:
        st.progress(0.0, text=f"{model} — refused by the provider: {e['error'][:90]}")
    elif until > now:
        st.progress(0.0, text=f"{model} — limit reached, back at {datetime.fromtimestamp(until):%H:%M} ({calls} call{'s' if calls != 1 else ''} today)")
    elif e.get("limit") and e.get("day") == today:
        st.progress(_share(e["remaining"], e["limit"]),
                    text=f"{model} — {e['remaining']:,} of {e['limit']:,} requests left today (reported by {PROVIDER_NAME[prov]})")
    elif e.get("learned"):
        left = max(0, e["learned"] - calls)
        st.progress(_share(left, e["learned"]), text=f"{model} — about {left} of ~{e['learned']} calls left today "
                                                     "(limit reached on an earlier day)")
    else:
        st.progress(1.0, text=f"{model} — available · {calls} call{'s' if calls != 1 else ''} today (no remaining count published)")


def page_quota():
    shell("AI quota", "What each API key has left: as the provider reports it, or as the app counts its calls.", "Settings")
    st.caption("Gemini quotas reset around 09:00 (midnight Pacific time); Groq frees requests gradually over the day; "
               "Cohere's trial limit is monthly; NVIDIA limits requests per minute. Models are used in this order, best first.")
    rec, now, gone, keys = llm.quota_record(), time.time(), llm._gone(), load_keys()
    today = time.strftime("%Y-%m-%d")
    for slot in QUOTA_SLOTS + tuple(f"gemini@{f}" for f in people(keys)):  # each friend's key: its own quota
        prov = re.split(r"[#@]", slot)[0]
        key = keys.get(slot) or (os.environ.get(ENV_KEYS.get(slot, ""), "") if slot in ENV_KEYS else "")
        if not key:
            continue
        with st.container(border=True, key=f"card_quota_{re.sub(r'[#@]', '_', slot)}"):
            nth = {"#2": " — second key", "#3": " — third key", "#4": " — fourth key"}.get(slot[len(prov):], "") or (
                f" — {slot.split('@', 1)[1].replace('_', ' ').title()}'s key" if "@" in slot else "")
            st.markdown(f"**{PROVIDER_NAME[prov]}**{nth} · `{llm.mask(key)}`")
            entries = {k.split("|", 1)[1]: v for k, v in rec.items() if k.startswith(slot + "|")}
            if prov == "cohere":
                used = sum(v.get("month_calls", 0) for v in entries.values() if v.get("month") == today[:7])
                st.progress(_share(COHERE_MONTH - used, COHERE_MONTH),
                            text=f"Key — about {max(0, COHERE_MONTH - used):,} of {COHERE_MONTH:,} trial calls left this month")
            if prov == "openrouter":
                info = _openrouter_info(key)
                cap = 50 if info.get("is_free_tier", True) else 1000  # free models: 50 a day, 1,000 after $10 of credits
                used = sum(v.get("calls", 0) for v in entries.values() if v.get("day") == today)
                st.progress(_share(cap - used, cap), text=f"Key — about {max(0, cap - used)} of {cap} free-model requests left today"
                            + ("" if info else " (OpenRouter's account figures could not be read)"))
            for p_, model in llm.LADDER:
                if p_ == prov:
                    _model_bar(prov, model, slot, rec, now, gone)
    jp_key = keys.get("jobspipe") or os.environ.get("JOBSPIPE_API_KEY", "")
    if jp_key:
        with SessionLocal() as s:
            jp = get_setting(s, "jobspipe_credits", {})
        with st.container(border=True, key="card_quota_jobspipe"):
            st.markdown(f"**JobsPipe** (job data, not AI) · `{llm.mask(jp_key)}`")
            if jp.get("allowance"):
                st.progress(_share(jp["remaining"], jp["allowance"]),
                            text=f"{jp['remaining']:,} of {jp['allowance']:,} credits left "
                                 f"(at the last scan, {datetime.fromtimestamp(jp['at']):%d %b %H:%M})")
            else:
                st.progress(1.0, text="Credits are shown after the first scan that reads JobsPipe")


# =================================================================== navigation
RESULTS = st.Page(page_results, title="Results", icon=":material/work:", url_path="results")
brand()
st.navigation([st.Page(page_search, title="Search", icon=":material/travel_explore:", default=True), RESULTS,
               st.Page(page_stats, title="Statistics", icon=":material/insights:", url_path="statistics"),
               st.Page(page_quota, title="AI quota", icon=":material/speed:", url_path="quota"),
               st.Page(page_settings, title="Settings", icon=":material/settings:", url_path="settings")], position="top").run()
for _n, _new, _old in (("config", c, CFG), ("profile", p, PROFILE), ("applicant", ap, APPLICANT)):
    autosave(_n, _new, _old)
