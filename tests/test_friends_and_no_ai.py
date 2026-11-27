"""The user's requests (27 Nov 2026): a search by keywords without any AI call, and friends' own Gemini keys, each one
used only in the searches made for that friend."""
from datetime import datetime


def test_a_friends_gemini_key_is_saved_under_their_name(monkeypatch, tmp_path):
    from jobfinder import store
    monkeypatch.setattr(store, "SECRETS_FILE", tmp_path / "api_keys.txt")
    store.save_key("gemini", "mine")
    assert store.save_person_key("Ziyad B.", "theirs") == "ziyad_b"
    assert "GEMINI_API_KEY__ZIYAD_B=theirs" in (tmp_path / "api_keys.txt").read_text()
    keys = store.load_keys()
    assert keys == {"gemini": "mine", "gemini@ziyad_b": "theirs"} and store.people(keys) == ["ziyad_b"]
    store.save_key("groq", "q")  # saving another key keeps the friend's
    assert store.load_keys()["gemini@ziyad_b"] == "theirs"
    store.delete_key("gemini@ziyad_b")
    assert store.people(store.load_keys()) == []


def test_a_search_for_a_friend_uses_their_key_and_never_yours():
    from jobfinder import llm
    friend = {"gemini": "", "gemini#2": "", "gemini@ziyad": "theirs", "groq": "q"}  # app.scan_keys for Ziyad
    chain = llm.model_chain({"auto_models": True, "model": {"provider": "ollama", "model": "x"}}, friend)
    assert {k for p, _, k in chain if p == "gemini"} == {"gemini@ziyad"}
    one = llm.model_chain({"auto_models": False, "model": {"provider": "gemini", "model": "gemini-2.5-flash"}}, friend)
    assert one == [("gemini", "gemini-2.5-flash", "gemini@ziyad")]
    assert llm.get_key("gemini", friend) == ""  # no fallback to your key in the environment
    mine = {"gemini": "mine", "groq": "q"}  # your own searches: the friends' keys are not in them (app.KEYS)
    assert {k for p, _, k in llm.model_chain({"auto_models": True, "model": {"provider": "ollama", "model": "x"}}, mine)
            if p == "gemini"} == {"gemini"}


def test_a_search_by_keywords_without_ai_lists_the_offers_as_they_are(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jobfinder import analysis, llm, store
    from jobfinder.config import CONFIG_DEFAULT
    from jobfinder.scan import Progress
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False})
    store.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(analysis, "SessionLocal", Session)
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI call")))
    with Session() as s:
        s.add_all([store.Job(uid="a", title="Comptable", url="https://a.fr/1", status="candidate", pub_date=datetime.utcnow(),
                             reason="title: title matches your keywords ['comptable']; date: in range"),
                   store.Job(uid="b", title="Comptable Lyon", url="https://a.fr/2", status="review",
                             reason="title: title matches your keywords ['comptable']; date: in range")])
        s.commit()
    analysis.analyze_pipeline({**CONFIG_DEFAULT, "ai_analysis": False}, {"keywords_only": True}, {}, Progress())
    with Session() as s:
        a, b = s.query(store.Job).filter_by(uid="a").one(), s.query(store.Job).filter_by(uid="b").one()
        assert (a.status, b.status) == ("relevant", "review") and a.relevance_score is None
        assert a.reason == "title matches your keywords ['comptable'] - not checked by AI"


def test_when_every_ai_quota_is_out_the_search_ends_without_ai(monkeypatch, tmp_path):
    """The user's request (27 Nov 2026): a search goes to the end; when every key is at its limit, the other offers are
    listed without AI instead of staying 'Not analysed', and the scan does not wait to be resumed for them."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from jobfinder import analysis, store
    from jobfinder.config import CONFIG_DEFAULT, PROFILE_DEFAULT
    from jobfinder.llm import QuotaExhausted
    from jobfinder.scan import Progress
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    store.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(analysis, "SessionLocal", Session)
    monkeypatch.setattr(store, "SessionLocal", Session)

    def out_of_quota(*a, **k):
        raise QuotaExhausted("every model is at its daily limit")
    monkeypatch.setattr(analysis, "call_json", out_of_quota)
    text = "Vous concevrez des modèles de vision par ordinateur pour la robotique, en Python et PyTorch. " * 12
    with Session() as s:
        src = store.Source(url="https://a.fr/jobs")
        s.add(src)
        s.flush()
        for i in range(5):
            s.add(store.Job(uid=f"j{i}", source_id=src.id, title=f"Ingénieur Vision {i}", url=f"https://a.fr/{i}",
                            status="candidate", description=text, pub_date=datetime.utcnow(), date_conf=0.95,
                            date_source="json-ld", location_original="Paris", location_verified=True, france_eligible=True,
                            reason="title: title matches ['vision']; date: in range"))
        s.commit()
        ids = [src.id]
    prog = Progress()
    analysis.analyze_pipeline({**CONFIG_DEFAULT, "ai_wait_max": 0}, PROFILE_DEFAULT, {}, prog)
    with Session() as s:
        jobs = s.query(store.Job).all()
        assert {j.status for j in jobs} == {"relevant"} and all(j.reason.endswith("not checked by AI") for j in jobs)
        assert store.scan_todo(s, {"started": "2000-01-01T00:00:00", "source_ids": ids})[2] == 0  # nothing waits for the AI
    assert "without AI" in prog.snap()[0]["ai_msg"]
