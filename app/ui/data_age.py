"""How old a panel's data is, in words, and whether it is past its cache
lifetime. Shared by the combat, hauling and ore finder panels."""
from __future__ import annotations

import time
from datetime import datetime


def age_text(stamp: float | None, now: float | None = None) -> str:
    """Relative age of a unix time: "just now", "5 min ago", "2 h ago",
    "yesterday 14:05", "3 Oct 14:05". Empty when there is no time."""
    if not stamp:
        return ""
    now = time.time() if now is None else now
    try:
        then = datetime.fromtimestamp(float(stamp))
        today = datetime.fromtimestamp(now).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    age = now - float(stamp)
    if age < 60:
        return "just now"
    if age < 3600:
        return f"{int(age // 60)} min ago"
    days = (today - then.date()).days
    if days <= 0:
        return f"{int(age // 3600)} h ago"
    if days == 1:
        return f"yesterday {then:%H:%M}"
    return f"{then.day} {then:%b} {then:%H:%M}"


def is_stale(stamp: float | None, ttl: float, now: float | None = None) -> bool:
    """True when data stamped ``stamp`` is older than its cache lifetime."""
    if not stamp:
        return False
    now = time.time() if now is None else now
    return now - float(stamp) > ttl
