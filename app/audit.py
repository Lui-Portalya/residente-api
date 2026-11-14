"""Append-only audit trail; same columns and conventions as the web app (repos/audit.ts)."""
import json
from typing import Any

from .db import Db, one
from .timeutil import local_timestamp


def log_audit(
    db: Db,
    *,
    actor_id: int | None,
    action: str,
    summary: str,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str = "",
    details: dict[str, Any] | None = None,
    ip: str = "",
    at: str | None = None,
) -> int:
    name, role = "", None
    if actor_id is not None:
        u = one(db, "SELECT name, role FROM users WHERE id = ?", (actor_id,))
        if u:
            name, role = u["name"], u["role"]
    cur = db.execute(
        """INSERT INTO audit_log (at, actor_id, actor_name, actor_role, category, action, severity,
             entity_type, entity_id, entity_label, summary, details, ip)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (at or local_timestamp(), actor_id, name, role, action.split(".")[0], action, severity,
         entity_type, entity_id, entity_label, summary, json.dumps(details or {}), ip),
    )
    return int(cur.lastrowid)
