"""
In-memory rate limiter for admin login.

Tracks failed login attempts per IP. After 5 consecutive failures within
10 minutes, the IP is blocked for 15 minutes.
"""

import threading
from datetime import datetime, timezone, timedelta

# Configuration
MAX_ATTEMPTS = 5
WINDOW_MINUTES = 10
BLOCK_MINUTES = 15

_store: dict = {}  # {ip: {"count": int, "window_start": datetime, "blocked_until": datetime|None}}
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_blocked(ip: str) -> bool:
    """Return True if the IP is currently rate-limited."""
    with _lock:
        entry = _store.get(ip)
        if entry is None:
            return False
        blocked_until = entry.get("blocked_until")
        if blocked_until and _now() < blocked_until:
            return True
        return False


def record_failure(ip: str) -> bool:
    """
    Record a failed login attempt for the given IP.
    Returns True if the IP has now been blocked as a result.
    """
    with _lock:
        now = _now()
        entry = _store.get(ip)

        if entry is None:
            _store[ip] = {"count": 1, "window_start": now, "blocked_until": None}
            return False

        # If currently blocked, stay blocked (caller should have checked is_blocked first)
        if entry.get("blocked_until") and now < entry["blocked_until"]:
            return True

        # Reset window if it has expired
        window_start = entry["window_start"]
        if (now - window_start) > timedelta(minutes=WINDOW_MINUTES):
            entry["count"] = 1
            entry["window_start"] = now
            entry["blocked_until"] = None
            return False

        # Increment within the current window
        entry["count"] += 1
        if entry["count"] >= MAX_ATTEMPTS:
            entry["blocked_until"] = now + timedelta(minutes=BLOCK_MINUTES)
            return True

        return False


def record_success(ip: str) -> None:
    """Clear the failure record for an IP on successful login."""
    with _lock:
        _store.pop(ip, None)
