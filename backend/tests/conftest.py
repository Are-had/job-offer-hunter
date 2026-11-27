"""The API tests run on their own data folder (never data/) and never read
or write the real api_keys.txt."""
import os
import tempfile

os.environ["JOBFINDER_DATA_DIR"] = tempfile.mkdtemp(prefix="jobfinder-web-tests-")

import pytest  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import core  # noqa: F401 - puts the repository (jobfinder) on the path
    from jobfinder import store
    monkeypatch.setattr(store, "SECRETS_FILE", tmp_path / "api_keys.txt")  # no real key read or written
    from backend.app.main import app
    with TestClient(app) as c:  # the app's start: a fresh session
        yield c
    store.wipe_session_data()
    with store.SessionLocal() as s:
        s.query(store.OfferMark).delete()
        s.query(store.Setting).delete()
        s.commit()
