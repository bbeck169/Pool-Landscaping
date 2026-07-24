"""Feb-2026 · Phase 21 — Tenant-aware URL builder helpers.

Absolute-URL builders (invoice pay link, review request link, magic
login, unsubscribe) should honor a per-tenant ``primary_app_domain``
setting when the admin has one configured. When unset, fall back to
the request's own base URL, and lastly to ``APP_PUBLIC_URL`` env.

The setting is introduced in the Phase 21 rebrand migration with a
default of ``None`` — no existing behavior changes until an admin
opts in.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def resolve_primary_app_domain(
    tenant: Optional[Dict[str, Any]] = None,
    *,
    request_base_url: Optional[str] = None,
) -> str:
    """Return the best public base URL for building customer-facing
    absolute URLs, in order:

      1. ``tenant.settings.primary_app_domain`` — admin soft-override.
      2. ``request_base_url`` — caller's own scheme+host (from FastAPI's
         ``Request.base_url``).
      3. ``APP_PUBLIC_URL`` env — deployment-wide fallback.
      4. Empty string — caller should treat as "no URL available".

    Never raises. Trailing slash is always stripped so callers can
    ``f"{base}/portal/..."`` without doubling.
    """
    settings = ((tenant or {}).get("settings") or {})
    tenant_domain = settings.get("primary_app_domain")
    if tenant_domain:
        return str(tenant_domain).rstrip("/")
    if request_base_url:
        return str(request_base_url).rstrip("/")
    env_url = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    return env_url
