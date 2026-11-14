"""Community-local naive datetimes, stored as 'YYYY-MM-DDTHH:mm' (port of lib/dates.ts)."""
import re
from datetime import date, datetime, timedelta

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def is_date(s: str) -> bool:
    if not _DATE.match(s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def is_time(s: str) -> bool:
    return bool(_TIME.match(s))


def to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def from_minutes(n: int) -> str:
    return f"{n // 60:02d}:{n % 60:02d}"


def local_now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def local_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def today() -> str:
    return local_now()[:10]


def add_days(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def shift_hours(local: str, hours: int) -> str:
    dt = datetime.fromisoformat(local if len(local) > 16 else f"{local}:00")
    return (dt + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
