"""Feb-2026 · Payment Processor Primary/Backup settings + audit + test.

Mounts under ``/api/tenants/mine/*`` — admin-gated. Companion to the
BusinessSettings page's new *Payment Processors* section.

Endpoints
---------
* ``GET    /tenants/mine/settings/payment-providers``
    Current settings + available providers with per-provider
    ``is_configured``.
* ``PATCH  /tenants/mine/settings/payment-providers``
    Update ``primary_provider`` / ``backup_provider``. Rejects
    same-provider-in-both-slots as 400.
* ``GET    /tenants/mine/payment-audit``
    Paginated failover history (current tenant only).
* ``POST   /tenants/mine/payment-providers/test``
    Rate-limited (5/hour/tenant) provider connection probe.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from services.payments_byo.failover_router import (
    FAILOVER_AUDIT_COLLECTION,
    list_available_providers,
    read_tenant_provider_settings,
)
from services.payments_byo.models import UnknownPaymentsProvider
from services.payments_byo.registry import (
    get_payments_byo_provider_by_short_name,
    list_short_names,
)
from utils import require_admin


router = APIRouter(prefix="/tenants/mine", tags=["payment-providers"])
log = logging.getLogger("payment_providers_settings")


# ── Rate-limit primitives (5/hour/tenant per Ticket Test-Connection) ──
_TEST_RATE_LIMIT_PER_HOUR = 5
_TEST_RATE_WINDOW_SECONDS = 60 * 60
_TEST_RATE_COLLECTION = "payment_provider_test_calls"


async def _enforce_test_rate_limit(tenant_id: str) -> None:
    """5 test-connection calls / hour / tenant. Mongo-backed rolling
    window — same pattern ``mass_messaging._enforce_rate_limit`` uses.
    """
    window_start = datetime.now(timezone.utc) - timedelta(
        seconds=_TEST_RATE_WINDOW_SECONDS,
    )
    count = await db[_TEST_RATE_COLLECTION].count_documents({
        "tenant_id": tenant_id,
        "at": {"$gte": window_start.isoformat()},
    })
    if count >= _TEST_RATE_LIMIT_PER_HOUR:
        raise HTTPException(status_code=429, detail={
            "code": "RATE_LIMITED",
            "window_seconds": _TEST_RATE_WINDOW_SECONDS,
            "limit_per_hour": _TEST_RATE_LIMIT_PER_HOUR,
        })


async def _record_test_call(tenant_id: str, provider: str) -> None:
    """Insert a rate-limit ledger row + trim old rows lazily."""
    now_iso = datetime.now(timezone.utc).isoformat()
    await db[_TEST_RATE_COLLECTION].insert_one({
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "provider": provider,
        "at": now_iso,
    })


# ── Request / response schemas ────────────────────────────────────
class PaymentProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_provider: Optional[str] = Field(
        None, description="Short name: stripe|square|paypal|authnet|lumino",
    )
    backup_provider: Optional[str] = Field(
        None, description="Short name, or null for no backup",
    )


class TestConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(..., description="Short name to test")


# ── Endpoints ─────────────────────────────────────────────────────
@router.get("/settings/payment-providers")
async def get_payment_provider_settings(
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return current primary/backup + available provider list."""
    tenant_id = tenant["id"]
    settings = await read_tenant_provider_settings(tenant_id, db=db)
    available = await list_available_providers(tenant_id=tenant_id, db=db)
    return {
        "primary_provider": settings["primary_provider"],
        "backup_provider": settings["backup_provider"],
        "available": available,
    }


@router.patch("/settings/payment-providers")
async def patch_payment_provider_settings(
    body: PaymentProviderSettings,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Update the tenant's primary/backup provider slots.

    Validation:
      * ``primary_provider == backup_provider`` (both non-null) → 400.
      * Unknown short-name in either slot → 400.
      * Same provider as primary AND backup is disallowed per Ticket.
    """
    tenant_id = tenant["id"]
    known = set(list_short_names())

    primary = body.primary_provider
    backup = body.backup_provider

    # Normalize "none" / "" → None so the client can pass either.
    if backup in ("", "none", "None"):
        backup = None

    # Validate against registry.
    for slot_name, val in (("primary_provider", primary),
                              ("backup_provider", backup)):
        if val is None:
            if slot_name == "primary_provider":
                # Primary is mandatory — falling back to registry default.
                continue
            continue
        if val not in known:
            raise HTTPException(status_code=400, detail={
                "code": "unknown_provider",
                "slot": slot_name,
                "provided": val,
                "available_short_names": sorted(known),
            })

    if primary and backup and primary == backup:
        raise HTTPException(status_code=400, detail={
            "code": "same_provider_forbidden",
            "message": "Primary and backup payment providers must differ.",
        })

    set_doc: Dict[str, Any] = {}
    if primary is not None:
        set_doc["settings.payment.primary_provider"] = primary
    if backup is None:
        # Explicit null via PATCH clears backup — use $unset in a
        # secondary write so a caller PATCH-ing only ``primary``
        # doesn't accidentally clear their backup.
        pass
    else:
        set_doc["settings.payment.backup_provider"] = backup

    update_ops: Dict[str, Any] = {}
    if set_doc:
        update_ops["$set"] = set_doc
    if backup is None and body.backup_provider is None and (
        "backup_provider" in body.model_fields_set
    ):
        update_ops["$unset"] = {"settings.payment.backup_provider": ""}

    if update_ops:
        await db.tenants.update_one({"id": tenant_id}, update_ops)

    settings = await read_tenant_provider_settings(tenant_id, db=db)
    available = await list_available_providers(tenant_id=tenant_id, db=db)
    return {
        "primary_provider": settings["primary_provider"],
        "backup_provider": settings["backup_provider"],
        "available": available,
    }


@router.get("/payment-audit")
async def get_payment_audit(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Paginated failover history for the current tenant.

    Cross-tenant isolation: every read scopes on ``tenant_id`` so
    admin at tenant A never sees tenant B's rows.
    """
    tenant_id = tenant["id"]
    q = {"tenant_id": tenant_id}
    total = await db[FAILOVER_AUDIT_COLLECTION].count_documents(q)
    cursor = (
        db[FAILOVER_AUDIT_COLLECTION]
        .find(q, {"_id": 0})
        .sort("timestamp", -1)
        .skip(int(skip)).limit(int(limit))
    )
    rows = [r async for r in cursor]
    return {"total": total, "rows": rows}


@router.post("/payment-providers/test")
async def post_payment_provider_test(
    body: TestConnectionBody,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Rate-limited canary probe (5/hour/tenant).

    Runs the provider's :meth:`test_connection` method + times it.
    Response never carries raw credentials.
    """
    tenant_id = tenant["id"]
    provider_short = (body.provider or "").strip().lower()
    if not provider_short:
        raise HTTPException(status_code=400, detail={
            "code": "provider_required",
        })
    if provider_short not in set(list_short_names()):
        raise HTTPException(status_code=400, detail={
            "code": "unknown_provider",
            "provided": provider_short,
            "available_short_names": sorted(list_short_names()),
        })

    await _enforce_test_rate_limit(tenant_id)
    try:
        provider = get_payments_byo_provider_by_short_name(provider_short)
    except UnknownPaymentsProvider:
        raise HTTPException(status_code=400, detail={
            "code": "unknown_provider", "provided": provider_short,
        })

    started = time.perf_counter()
    try:
        health = await provider.test_connection(tenant_id=tenant_id)
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _record_test_call(tenant_id, provider_short)
        return {
            "ok": bool(health.ok),
            "provider": provider_short,
            "latency_ms": latency_ms,
            # ``message`` is safe — providers never echo raw creds
            # from their test_connection paths (see docstring notes
            # on each provider).
            "message": health.message or "",
            "error": None if health.ok else (health.message or "probe failed"),
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _record_test_call(tenant_id, provider_short)
        log.warning(
            "[payment-providers/test] tenant=%s provider=%s failed: %s",
            tenant_id, provider_short, type(exc).__name__,
        )
        return {
            "ok": False,
            "provider": provider_short,
            "latency_ms": latency_ms,
            "message": "",
            "error": f"{type(exc).__name__}",
        }
