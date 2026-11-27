"""The API: websites, searches, offers and your marks, settings, keys, live progress, the pages."""
from datetime import datetime


def _job(uid, title="Data Scientist", status="relevant", **kw):
    from jobfinder import store
    with store.SessionLocal() as s:
        src = s.query(store.Source).first()
        if src is None:
            src = store.Source(url="https://x.fr/jobs", label="X")
            s.add(src)
            s.flush()
        s.add(store.Job(uid=uid, source_id=src.id, title=title, employer="X", url=f"https://x.fr/{uid}", status=status,
                        pub_date=datetime.utcnow(), relevance_score=kw.pop("relevance_score", 80), **kw))
        s.commit()


def test_every_page_of_the_api_answers(client):
    for path in ("/api/summary", "/api/meta", "/api/settings", "/api/scan", "/api/offers", "/api/sources", "/api/coverage",
                 "/api/problems", "/api/cvs", "/api/marks", "/api/keys", "/api/stats", "/api/quota", "/api/live-offers",
                 "/api/accounts"):
        assert client.get(path).status_code == 200, path
    meta = client.get("/api/meta").json()
    assert list(meta["offer_types"]) == ["cdi", "cdd", "phd", "postdoc", "internship", "apprenticeship", "other"]


def test_websites_are_loaded_from_pasted_addresses_and_files(client):
    r = client.post("/api/sources/urls", json={"text": "https://careers.example.com/jobs\nhttps://jobs.example.org/"})
    assert r.status_code == 200 and r.json()["loaded"] == 2
    assert {x["url"] for x in client.get("/api/sources").json()["sources"]} >= {"https://careers.example.com/jobs"}
    html = b'<html><a href="https://careers.other.com/offres">x</a></html>'
    r = client.post("/api/sources/files", files=[("files", ("list.html", html, "text/html"))])
    assert r.status_code == 200 and r.json()["loaded"] == 1  # a new file replaces the websites
    assert client.get("/api/summary").json()["sites"] == 1
    assert client.post("/api/sources/urls", json={"text": "no address here"}).status_code == 400


def test_a_search_needs_websites_and_a_keyword_in_a_search_by_keywords(client):
    assert client.post("/api/scan/start").status_code == 400  # no website yet
    client.post("/api/sources/urls", json={"text": "https://careers.example.com/jobs"})
    client.put("/api/settings/profile", json={"search_mode": "keywords", "my_keywords": []})
    r = client.post("/api/scan/start")
    assert r.status_code == 400 and "keyword" in r.json()["detail"]
    s = client.put("/api/settings/profile", json={"my_keywords": ["comptable"]}).json()
    assert s["models"]["by_keywords"] and s["models"]["keywords"] == ["comptable"]
    assert client.post("/api/scan/resume").status_code == 404  # nothing unfinished


def test_settings_are_saved_by_group_and_unknown_or_locked_ones_refused(client):
    s = client.put("/api/settings/config", json={"date_preset": "Last 7 days", "ai_analysis_keywords": True}).json()
    assert s["config"]["date_preset"] == "Last 7 days" and s["config"]["ai_analysis_keywords"] is True
    assert client.put("/api/settings/config", json={"no_such_setting": 1}).status_code == 400
    s = client.put("/api/settings/config", json={"providers": {"gemini": {"base_url": "https://evil.example"}}}).json()
    assert s["config"]["providers"]["gemini"]["base_url"].startswith("https://generativelanguage.googleapis.com")
    s = client.put("/api/settings/profile", json={"offer_types": ["cdi", "phd"]}).json()
    assert s["profile"]["offer_types"] == ["cdi", "phd"]
    s = client.put("/api/settings/applicant", json={"first_name": "Ada", "last_name": "Lovelace", "name": "Ada Lovelace"}).json()
    assert s["applicant"]["name"] == "Ada Lovelace"
    assert client.put("/api/settings/nothing", json={}).status_code == 404


def test_applied_removed_and_comments_are_kept_and_removed_offers_leave_the_list(client):
    _job("a1"), _job("a2", title="ML Engineer")
    uids = {o["uid"] for o in client.get("/api/offers").json()}
    assert uids == {"a1", "a2"}
    assert client.post("/api/offers/a1/mark", json={"state": "applied", "note": "sent 27/11"}).json() == {"state": "applied", "note": "sent 27/11"}
    a1 = next(o for o in client.get("/api/offers").json() if o["uid"] == "a1")
    assert a1["applied"] and a1["comment"] == "sent 27/11"
    client.post("/api/offers/a2/mark", json={"state": "dismissed"})
    assert [o["uid"] for o in client.get("/api/offers").json()] == ["a1"]
    marks = {m["uid"]: m["state"] for m in client.get("/api/marks").json()}
    assert marks == {"a1": "applied", "a2": "dismissed"}
    assert client.get("/api/summary").json()["applied"] == 1
    client.put("/api/marks/a1", json={"note": "interview on Monday"})
    assert client.get("/api/offers/a1").json()["mark"] == {"state": "applied", "note": "interview on Monday"}
    client.delete("/api/marks/a2")  # forgotten: back in the list, through the filters again
    assert {o["uid"]: o["status"] for o in client.get("/api/offers").json()}["a2"] == "new"
    assert client.post("/api/offers/a1/mark", json={"state": "maybe"}).status_code == 400
    assert client.get("/api/offers/nope").status_code == 404


def test_an_offer_card_says_what_the_app_read(client):
    _job("c1", title="Ingénieur IA - CDD 12 mois", status="review", review_flags="location_unverified",
         relevance_json={"relevance_score": 72, "reasoning_summary": "deep learning", "contract_kind": "job", "contract_type": "cdd"})
    o = client.get("/api/offers/c1").json()
    assert o["type"] == "CDD" and o["relevance"] == 72 and o["review_flags"] == ["location unverified"]
    assert client.post("/api/offers/c1/keep").json()["status"] == "relevant"
    assert next(x for x in client.get("/api/offers").json() if x["uid"] == "c1")["type"] == "CDD"


def test_keys_are_saved_masked_and_a_line_added_by_hand_is_kept(client):
    from jobfinder import store
    store.SECRETS_FILE.write_text("MY_OWN_TOKEN=abc\n", encoding="utf-8")
    k = client.put("/api/keys/groq", json={"key": "gsk_1234567890abcdef"}).json()
    assert k["groq"]["saved"] and k["groq"]["masked"] == "gsk…def"
    assert "MY_OWN_TOKEN=abc" in store.SECRETS_FILE.read_text(encoding="utf-8")
    assert client.put("/api/keys/groq", json={"key": "with space"}).status_code == 400
    assert client.put("/api/keys/nope", json={"key": "x"}).status_code == 404
    from backend.app.core import own_keys
    assert own_keys()["groq"] == "gsk_1234567890abcdef"


def test_the_live_progress_is_pushed_as_server_sent_events(client):
    from backend.app.routes_search import scan_state
    s = scan_state()
    assert s["progress"]["running"] is False and "models" in s and "summary" in s
    r = client.get("/api/scan")
    assert r.json()["kept_offers"] == 0
    # the stream's first event: the same state, with the newest offers
    import json
    with client.stream("GET", "/api/scan/events") as ev:
        assert ev.headers["content-type"].startswith("text/event-stream")
        line = next(x for x in ev.iter_lines() if x.startswith("data: "))
    first = json.loads(line[len("data: "):])
    assert first["progress"]["running"] is False and first["live"] == {"total": 0, "rows": []}


def test_the_built_pages_are_served_with_the_fonts_and_logo(client):
    from backend.app.main import DIST
    assert client.get("/fonts/PPTelegraf-Regular.otf").status_code == 200
    assert client.get("/brand/logo.svg").status_code == 200
    assert client.get("/brand/logo.svg").headers["content-type"].startswith("image/svg+xml")
    if DIST.is_dir():
        for path in ("/", "/results", "/settings"):  # every page of the single-page app is its index.html
            r = client.get(path)
            assert r.status_code == 200 and '<div id="root">' in r.text
        # the script must be served as JavaScript: a 'text/plain' script (the Windows registry's type on some computers,
        # 28 Nov 2026) is refused by the browser and the page stays empty
        import re
        page = client.get("/").text
        js, css = re.search(r'/assets/[^"]+\.js', page).group(0), re.search(r'/assets/[^"]+\.css', page).group(0)
        assert client.get(js).headers["content-type"].startswith("text/javascript")
        assert client.get(css).headers["content-type"].startswith("text/css")
        assert client.get("/../api_keys.txt").status_code in (200, 404) and "API_KEY" not in client.get("/../api_keys.txt").text
