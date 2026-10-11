"""Preview isolation · env detection + salt + tenant whitelist loader.

Three invariants:

1. ``is_preview_env()`` is the sole gate consumed by the decorator /
   middleware / scrubber / healthcheck. Reads ``APP_ENV`` on every
   call (not import-time) so pytest can patch ``os.environ`` between
   cases.

2. ``PREVIEW_SYNTHETIC_SALT`` is read ONCE at import — rotation would
   re-shuffle every synthetic identity and break admin test flows.
   Defaults to ``preview-salt-feb2026`` when unset so a dev pod boots
   without extra config; production never consults this value.

3. ``PREVIEW_TENANT_WHITELIST`` is parsed from
   ``/app/memory/preview_tenants.md`` once at import. The file holds
   the authoritative list of ``tenant_id`` values that are legit
   preview tenants. Missing file → empty whitelist (safe default:
   nothing is auto-sanitized without an explicit whitelist entry).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Set


def is_production_env() -> bool:
    """``True`` iff ``APP_ENV=production`` (case-insensitive)."""
    return (os.environ.get("APP_ENV", "preview") or "preview").lower() == "production"


def is_preview_env() -> bool:
    """``True`` iff NOT production. Preview + development both count
    as "preview env" for PII-sanitization purposes."""
    return not is_production_env()


# Immutable at import — see docstring (3).
PREVIEW_SYNTHETIC_SALT: str = os.environ.get(
    "PREVIEW_SYNTHETIC_SALT", "preview-salt-feb2026",
)


def _parse_tenant_whitelist() -> Set[str]:
    """Load the whitelist from ``/app/memory/preview_tenants.md``.

    Format: any UUID-shaped token appearing in a code fence or
    inside backticks is accepted. Missing / unreadable file → empty
    set. Pytest patches this via ``PREVIEW_TENANT_WHITELIST_OVERRIDE``.
    """
    override = os.environ.get("PREVIEW_TENANT_WHITELIST_OVERRIDE", "")
    if override:
        return {t.strip() for t in override.split(",") if t.strip()}
    md = Path("/app/memory/preview_tenants.md")
    if not md.exists():
        return set()
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return set()
    # UUID v4-ish — tolerant of surrounding backticks / list markers.
    uuid_re = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    )
    return {m.group(0).lower() for m in uuid_re.finditer(text)}


PREVIEW_TENANT_WHITELIST: Set[str] = _parse_tenant_whitelist()
