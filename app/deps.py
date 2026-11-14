from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import security
from .db import Db, get_db, one

_bearer = HTTPBearer(auto_error=False)


def get_token(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(401, "Not authenticated.", headers={"WWW-Authenticate": "Bearer"})
    return creds.credentials


def current_user(token: Annotated[str, Depends(get_token)], db: Annotated[Db, Depends(get_db)]) -> dict:
    user = security.user_for_token(db, token)
    if user is None:
        raise HTTPException(401, "Invalid or expired session.", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Administrators only.")
    return user


def residence_of(db: Db, user_id: int) -> dict | None:
    """The residence a user belongs to (primary membership first); None when the user has none."""
    return one(
        db,
        """SELECT r.id, r.code, r.address FROM residence_residents rr JOIN residences r ON r.id = rr.residence_id
           WHERE rr.user_id = ? AND r.active = 1 ORDER BY rr.is_primary DESC, r.id LIMIT 1""",
        (user_id,),
    )


def require_resident(user: Annotated[dict, Depends(current_user)], db: Annotated[Db, Depends(get_db)]) -> dict:
    """A resident user, enriched with their `residence`."""
    if user["role"] != "resident":
        raise HTTPException(403, "Residents only.")
    residence = residence_of(db, user["id"])
    if residence is None:
        raise HTTPException(403, "Your account is not linked to an active residence.")
    return {**user, "residence": residence}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "local"
