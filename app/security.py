"""Passwords, sessions and sign-in lockout, compatible with the web app's tables and hash format."""
import hashlib
import hmac
import secrets
import time
from base64 import urlsafe_b64encode

from .db import Db, one

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
LOCK_WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
_SCRYPT = dict(n=16384, r=8, p=1, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=64, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "scrypt" or not parts[1] or not parts[2]:
        return False
    try:
        salt, expected = bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, dklen=len(expected), **_SCRYPT)
    return hmac.compare_digest(actual, expected)


# Checked against when the email is unknown, so timing does not reveal which emails exist.
DUMMY_HASH = hash_password("dummy-password")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Db, user_id: int) -> tuple[str, int]:
    token = urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    expires = int(time.time()) + SESSION_TTL_SECONDS
    db.execute("INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (?,?,?)", (user_id, hash_token(token), expires))
    return token, expires


def user_for_token(db: Db, token: str) -> dict | None:
    return one(
        db,
        """SELECT u.id, u.email, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
        (hash_token(token), int(time.time())),
    )


def delete_session(db: Db, token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))


def is_locked(db: Db, key: str) -> bool:
    db.execute("DELETE FROM login_attempts WHERE at < ?", (int(time.time()) - LOCK_WINDOW_SECONDS,))
    n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key = ?", (key,)).fetchone()[0]
    return n >= MAX_FAILURES


def record_failure(db: Db, key: str) -> None:
    db.execute("INSERT INTO login_attempts (key, at) VALUES (?, ?)", (key, int(time.time())))


def clear_failures(db: Db, key: str) -> None:
    db.execute("DELETE FROM login_attempts WHERE key = ?", (key,))
