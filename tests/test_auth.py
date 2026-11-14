import pytest

from .conftest import login

API = "/api/v1"


@pytest.mark.parametrize("email,password,role", [
    ("admin", "admin123", "admin"), ("resident", "resident123", "resident"),
    ("neighbour", "neighbour123", "resident"), ("gate", "gate123", "gate"),
])
def test_seeded_users_can_log_in(client, email, password, role):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == role and body["token"] and body["expires_at"] > 0


def test_wrong_password_and_unknown_user_look_the_same(client):
    a = client.post(f"{API}/auth/login", json={"email": "admin", "password": "nope"})
    b = client.post(f"{API}/auth/login", json={"email": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_lockout_after_five_failures(client):
    for _ in range(5):
        assert client.post(f"{API}/auth/login", json={"email": "admin", "password": "x"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "admin", "password": "admin123"}).status_code == 429


def test_me_logout_and_expiry(client, raw):
    h = login(client, "resident", "resident123")
    me = client.get(f"{API}/auth/me", headers=h).json()
    assert me["email"] == "resident" and me["residence"]["code"] == "A-101"
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 204
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401
    h = login(client, "resident", "resident123")
    raw.execute("UPDATE sessions SET expires_at = 1"); raw.commit()
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401


def test_deactivated_user_cannot_log_in_or_use_session(client, raw):
    h = login(client, "resident", "resident123")
    raw.execute("UPDATE users SET active = 0 WHERE email = 'resident'"); raw.commit()
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "resident", "password": "resident123"}).status_code == 401


def test_requires_token_and_roles(client, resident, admin):
    assert client.get(f"{API}/resident/dashboard").status_code == 401
    assert client.get(f"{API}/admin/dashboard", headers=resident).status_code == 403
    assert client.get(f"{API}/resident/dashboard", headers=admin).status_code == 403
    gate = login(client, "gate", "gate123")
    assert client.get(f"{API}/admin/dashboard", headers=gate).status_code == 403
    assert client.get(f"{API}/resident/dashboard", headers=gate).status_code == 403


def test_staff_login_is_audited(client, raw):
    login(client, "admin", "admin123")
    assert raw.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'auth.login'").fetchone()[0] == 1
