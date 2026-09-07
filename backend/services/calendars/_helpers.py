"""Phase I1.7.c.3 · Feb-2026 — Calendar-BYO shared helpers."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import InvalidCalendarProviderConfig


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def calendars_testmode_mock() -> bool:
    return os.environ.get("CALENDARS_TESTMODE_MOCK", "").strip().lower() in ("1", "true", "yes")


def current_period_yyyymm() -> str:
    d = datetime.now(timezone.utc)
    return f"{d.year:04d}{d.month:02d}"


def validate_config(
    *, provider_key: str,
    config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> None:
    """Schema-shape validator — every ``required=True`` field must be
    present + non-empty. Used by the ``PUT /calendars_{provider}``
    cap endpoint (non-secret fields only for Calendars — the actual
    OAuth token is stored per-technician via services.secrets)."""
    missing: List[str] = []
    for name, meta in schema.items():
        if not meta.get("required"):
            continue
        val = config.get(name)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    if missing:
        raise InvalidCalendarProviderConfig(
            f"provider={provider_key} missing required fields: {', '.join(missing)}"
        )


# ── OAuth env resolution — REDIRECT_URI comes from env only ──────
# Never derive the redirect URI from request headers — that is a
# well-known open-redirect / origin-spoof vector on OAuth flows.
def _env_or_none(name: str) -> Optional[str]:
    v = (os.environ.get(name) or "").strip()
    return v or None


def google_oauth_env() -> Dict[str, Optional[str]]:
    return {
        "client_id":     _env_or_none("GOOGLE_CALENDAR_CLIENT_ID"),
        "client_secret": _env_or_none("GOOGLE_CALENDAR_CLIENT_SECRET"),
        "redirect_uri":  _env_or_none("GOOGLE_CALENDAR_REDIRECT_URI"),
    }


def outlook_oauth_env() -> Dict[str, Optional[str]]:
    return {
        "client_id":     _env_or_none("OUTLOOK_CLIENT_ID"),
        "client_secret": _env_or_none("OUTLOOK_CLIENT_SECRET"),
        "redirect_uri":  _env_or_none("OUTLOOK_REDIRECT_URI"),
    }
