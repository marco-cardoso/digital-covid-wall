import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Point the app at a throwaway database file for the duration of a test."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    return path


@pytest.fixture
def client(test_db):
    # Entering the context manager runs the lifespan, which creates and seeds the db.
    with TestClient(app) as test_client:
        yield test_client
