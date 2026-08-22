"""Feb-2026 · P16B — shared HTTP request helpers.

Extraction driven by the rule of three: ``auth.py`` and
``customer_account.py`` each had a local ``_client_ip`` helper with
subtly different fallback strings (``"unknown"`` vs ``""``).  Both
call sites now import this module so the semantics live in one
place; the per-caller fallback is preserved via the ``default`` arg.
"""
from __future__ import annotations

from fastapi import Request


def client_ip(request: Request, *, default: str = "unknown") -> str:
    """Return the client IP address for an audit trail.

    Resolution order:
      1. First hop of the ``X-Forwarded-For`` header (Cloudflare +
         other reverse proxies terminate TLS and populate this).
      2. ``request.client.host`` (direct socket peer).
      3. ``default`` (caller-provided fallback string).

    The ``default`` argument exists so pre-P16 audit rows continue to
    render the same sentinel that each caller used before extraction:

      * ``auth.py`` used ``"unknown"``.
      * ``customer_account.py`` used ``""``.

    Callers pass ``default=""`` explicitly to preserve the empty
    fallback; everything else gets the ``"unknown"`` default so
    grep-for-``unknown`` in audit logs continues to work.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return default
