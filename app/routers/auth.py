from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import security
from ..audit import log_audit
from ..db import Db, get_db, one
from ..deps import client_ip, current_user, get_token, residence_of
from ..schemas import LoginIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, request: Request, db: Annotated[Db, Depends(get_db)]):
    email = body.email.strip()
    ip = client_ip(request)
    key = f"{email.lower()}|{ip}"
    if security.is_locked(db, key):
        log_audit(db, actor_id=None, action="auth.locked_out", severity="critical", entity_type="login", entity_label=email,
                  summary=f"Locked-out sign-in attempt for {email}", details={"email": email}, ip=ip)
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    user = one(db, "SELECT id, email, name, role, active, password_hash FROM users WHERE email = ? AND active = 1", (email,))
    ok = security.verify_password(body.password, user["password_hash"] if user else security.DUMMY_HASH) and user is not None
    if not ok:
        security.record_failure(db, key)
        log_audit(db, actor_id=None, action="auth.login_failed", severity="warning", entity_type="login", entity_label=email,
                  summary=f"Failed sign-in for {email}", details={"email": email, "knownAccount": user is not None}, ip=ip)
        raise HTTPException(401, "Invalid email or password.")
    security.clear_failures(db, key)
    token, expires = security.create_session(db, user["id"])
    # Staff sign-ins are audited; residents signing in is routine.
    if user["role"] != "resident":
        who = "Administrator" if user["role"] == "admin" else "Gate user"
        log_audit(db, actor_id=user["id"], action="auth.login", entity_type="user", entity_id=user["id"], entity_label=email,
                  summary=f"{who} signed in ({email})", ip=ip)
    return {
        "token": token, "token_type": "bearer", "expires_at": expires,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]},
    }


@router.post("/logout", status_code=204)
def logout(token: Annotated[str, Depends(get_token)], _user: Annotated[dict, Depends(current_user)], db: Annotated[Db, Depends(get_db)]):
    security.delete_session(db, token)


@router.get("/me")
def me(user: Annotated[dict, Depends(current_user)], db: Annotated[Db, Depends(get_db)]):
    return {**user, "residence": residence_of(db, user["id"]) if user["role"] == "resident" else None}
