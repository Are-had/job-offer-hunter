"""The user's request (27 Nov 2026): mark an offer as applied, remove one that does not fit, comment it; the next
searches do not add again an offer already applied to or removed."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _raw(n):
    return {"title": f"Data Analyst {n}", "url": f"https://x.fr/{n}", "location": "Paris", "date": None, "date_conf": 0.0,
            "date_text": "", "date_source": "", "conf": 0.9, "provenance": "test", "description": "Analyse de données à Paris."}


def test_an_offer_applied_to_or_removed_is_not_added_again(monkeypatch):
    from jobfinder import store
    from jobfinder.scan import upsert_job
    engine = create_engine("sqlite://")
    store.Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        src = store.Source(url="https://x.fr/", label="x")
        s.add(src)
        s.flush()
        for n in (1, 2, 3):
            upsert_job(s, src, _raw(n))
        s.commit()
        j1, j2, j3 = (s.query(store.Job).filter_by(url=f"https://x.fr/{n}").one() for n in (1, 2, 3))
        store.mark_offer(s, j1, "applied", "sent on 27/11")
        store.mark_offer(s, j2, "dismissed", "asks for 5 years")
        store.mark_offer(s, j3, None, "to read again")  # a comment only
        assert j2.status == "dismissed" and j2.reason == "removed by you: asks for 5 years"
        u1, u2, u3 = j1.uid, j2.uid, j3.uid
        # the next session: the offers are deleted (wipe), your marks stay
        s.query(store.Job).delete()
        s.commit()
        assert {m.uid: (m.state, m.note) for m in s.query(store.OfferMark)} == {
            u1: ("applied", "sent on 27/11"), u2: ("dismissed", "asks for 5 years"), u3: ("", "to read again")}
        # the next search finds the three offers again: only the one with a comment alone comes back
        assert [upsert_job(s, src, _raw(n)) for n in (1, 2, 3)] == [False, False, True]
        s.commit()
        assert [j.url for j in s.query(store.Job)] == ["https://x.fr/3"]
        assert store.marked_uids(s) == {u1, u2}
        # forgotten (its row deleted in 'Your applications and removed offers'): the searches show it again
        s.delete(s.get(store.OfferMark, u2))
        s.commit()
        assert upsert_job(s, src, _raw(2)) is True


def test_an_offer_put_back_goes_through_the_filters_again():
    from jobfinder import store
    engine = create_engine("sqlite://")
    store.Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        j = store.Job(uid="u1", title="Data Analyst", url="https://x.fr/1", status="relevant")
        s.add(j)
        s.commit()
        store.mark_offer(s, j, "dismissed")
        assert j.status == "dismissed"
        store.mark_offer(s, j, "")  # put back
        assert j.status == "new" and s.get(store.OfferMark, "u1").state == ""
