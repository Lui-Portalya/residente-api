import os
from pathlib import Path


def database_path() -> str:
    return str(Path(os.environ.get("DATABASE_PATH", "./data/residente.db")).resolve())


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]
