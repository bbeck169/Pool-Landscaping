"""Phase I1.7.e · Chunk 3 · Feb-2026 — HTTP-layer helpers for
propagating Maps cap-exceeded events to FastAPI callers.

Sibling of :mod:`services.ai.cap_http` — the dispatcher raises
:class:`services.maps.models.TenantMapsRequestCapExceeded` when a
tenant's BYO provider hits its monthly request cap. Transactional
HTTP endpoints (dispatch-board optimize, on-my-way ETA, rank-tracker
reverse-geocode) call :func:`raise_if_maps_cap_exceeded` after their
Maps dispatch to translate that signal into ``HTTPException(429)``.
Scheduled / bulk callsites (reverse-geocode-backfill cron, GPS ping
enrichment, geocode-and-persist migrations) DO NOT call this helper —
they persist ``skipped_cap_exceeded`` in their job log and continue
with the next batch item.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from .models import TenantMapsRequestCapExceeded


CAP_EXCEEDED_HTTP_STATUS = 429
CAP_EXCEEDED_ERROR_CODE = "maps_spend_cap_exceeded"


def is_maps_cap_exceeded(result: Optional[Dict[str, Any]]) -> bool:
    """Return True when a legacy shim result dict indicates a tenant
    BYO Maps cap hit. Sibling of :func:`services.ai.cap_http.is_ai_cap_exceeded`."""
    if not result:
        return False
    if result.get("cap_exceeded"):
        return True
    if result.get("error") == CAP_EXCEEDED_ERROR_CODE:
        return True
    if result.get("http_status") == CAP_EXCEEDED_HTTP_STATUS:
        return True
    return False


def raise_if_maps_cap_exceeded(
    result: Optional[Dict[str, Any]],
    *,
    detail: str = "Monthly Maps request cap exceeded for this tenant",
) -> None:
    """Raise ``HTTPException(429)`` when the given legacy-shim result
    dict carries a cap-exceeded flag. No-op for any other shape
    (plain success, plain error, or ``None``)."""
    if is_maps_cap_exceeded(result):
        raise HTTPException(
            status_code=CAP_EXCEEDED_HTTP_STATUS, detail=detail,
        )


def translate_tenant_maps_cap_exception(
    exc: TenantMapsRequestCapExceeded,
    *,
    detail: Optional[str] = None,
) -> HTTPException:
    """Convert a raw :class:`TenantMapsRequestCapExceeded` into
    ``HTTPException(429)``. Direct-dispatcher callers can::

        try:
            await dispatch_maps_geocode(tenant_id=..., ...)
        except TenantMapsRequestCapExceeded as cap:
            raise translate_tenant_maps_cap_exception(cap)
    """
    msg = detail or (
        f"Monthly Maps request cap exceeded for provider {exc.provider} "
        f"(cap={exc.cap}, used={exc.used})"
    )
    return HTTPException(status_code=CAP_EXCEEDED_HTTP_STATUS, detail=msg)


__all__ = [
    "CAP_EXCEEDED_HTTP_STATUS",
    "CAP_EXCEEDED_ERROR_CODE",
    "is_maps_cap_exceeded",
    "raise_if_maps_cap_exceeded",
    "translate_tenant_maps_cap_exception",
]
