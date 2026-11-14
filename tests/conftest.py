import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC_DB = Path(__file__).resolve().parent.parent / "data" / "residente.db"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A throwaway copy of the real database; the original is never touched."""
    dst = tmp_path / "test.db"
    shutil.copy(SRC_DB, dst)
    monkeypatch.setenv("DATABASE_PATH", str(dst))
    return dst


@pytest.fixture()
def client(db_path):
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def raw(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def resident(client):
    return login(client, "resident", "resident123")


@pytest.fixture()
def neighbour(client):
    return login(client, "neighbour", "neighbour123")


@pytest.fixture()
def admin(client):
    return login(client, "admin", "admin123")


def area_id(raw, name):
    return raw.execute("SELECT id FROM common_areas WHERE name = ?", (name,)).fetchone()[0]


def days_ahead(n):
    return (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d")
