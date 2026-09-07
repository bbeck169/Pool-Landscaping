"""Phase I1.7.d · Feb-2026 — Unified provider-health cron.

Runs every ``HEALTH_CRON_INTERVAL_SECONDS`` (default 900 = 15 min)
and probes every connected BYO provider across the AI / Maps /
Calendars / Payments families. Writes a normalised row to
``tenant_provider_health`` per probe.

Reuses ``asyncio.create_task`` — no new scheduler infra required.
Started once on FastAPI startup via ``start_health_cron()``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


log = logging.getLogger("provider_health.cron")

HEALTH_CRON_INTERVAL_SECONDS = int(
    os.environ.get("PROVIDER_HEALTH_CRON_INTERVAL_SECONDS", "900") or "900"
)


# ── Family registration ──────────────────────────────────────────
def _load_ai_family() -> Optional[Tuple[str, Callable, Callable]]:
    try:
        from services.ai.registry import (
            get_ai_provider, list_registered_ai_provider_keys,
        )
        return ("ai", list_registered_ai_provider_keys, get_ai_provider)
    except Exception:
        return None


def _load_maps_family() -> Optional[Tuple[str, Callable, Callable]]:
    try:
        from services.maps.registry import (
            get_maps_provider, list_registered_maps_provider_keys,
        )
        return ("maps", list_registered_maps_provider_keys, get_maps_provider)
    except Exception:
        return None


def _load_calendars_family() -> Optional[Tuple[str, Callable, Callable]]:
    try:
        from services.calendars.registry import (
            get_calendar_provider, list_registered_calendar_provider_keys,
        )
        return ("calendars", list_registered_calendar_provider_keys, get_calendar_provider)
    except Exception:
        return None


def _load_payments_byo_family() -> Optional[Tuple[str, Callable, Callable]]:
    try:
        from services.payments_byo.registry import (
            get_payments_byo_provider, list_registered_payments_byo_provider_keys,
        )
        return ("payments_byo", list_registered_payments_byo_provider_keys, get_payments_byo_provider)
    except Exception:
        return None


def provider_families() -> List[Tuple[str, Callable, Callable]]:
    """Return the ordered ``(family_name, list_keys_fn, get_fn)``
    tuples for every family the cron probes. Import errors are
    swallowed so a partially-installed module doesn't wedge the cron.
    """
    fams: List[Tuple[str, Callable, Callable]] = []
    for loader in (_load_ai_family, _load_maps_family,
                    _load_calendars_family, _load_payments_byo_family):
        f = loader()
        if f is not None:
            fams.append(f)
    return fams


# ── Cycle body ───────────────────────────────────────────────────
async def _probe_provider(
    *, tenant_id: str, provider_key: str,
    get_provider_fn: Callable, db,
) -> Dict[str, Any]:
    from .store import record_probe
    try:
        provider = get_provider_fn(provider_key)
        result = await provider.test_connection(tenant_id=tenant_id)
        ok = bool(getattr(result, "ok", False))
        msg = str(getattr(result, "message", "")) or ""
        # Redact anything that looks like a token — public messages
        # should already avoid this, but guard defensively.
        for needle in ("Authorization: Bearer", "api_key=", "access_token="):
            if needle in msg:
                msg = msg.split(needle)[0] + "[redacted]"
        return await record_probe(
            tenant_id=tenant_id, provider_key=provider_key,
            ok=ok, message=msg if not ok else "", db=db,
        )
    except Exception as e:
        return await record_probe(
            tenant_id=tenant_id, provider_key=provider_key,
            ok=False, message=f"probe raised {type(e).__name__}",
            db=db,
        )


async def run_health_cycle_once(*, db=None) -> Dict[str, Any]:
    """Execute a single unified probe cycle. Returns a summary
    ``{"probed": int, "ok": int, "failed": int, "tenants": int}``
    for observability / testing.

    Tenants are the SET of tenant_ids present in ``tenant_secrets``
    plus ``tenant_calendars_technician_links``. Providers are the
    intersection of a family's registered keys and what the tenant
    has connected.
    """
    from .store import (
        list_connected_provider_keys_for_tenant, ensure_indexes,
    )
    if db is None:
        from config import db as _db
        db = _db
    await ensure_indexes(db=db)

    # ── Build the tenant list ──
    tenant_ids: set[str] = set()
    async for row in db["tenant_secrets"].find({}, {"_id": 0, "tenant_id": 1}):
        tid = row.get("tenant_id")
        if tid:
            tenant_ids.add(tid)
    try:
        async for row in db["tenant_calendars_technician_links"].find(
            {}, {"_id": 0, "tenant_id": 1},
        ):
            tid = row.get("tenant_id")
            if tid:
                tenant_ids.add(tid)
    except Exception:
        pass

    fams = provider_families()
    total_probed = ok_count = failed_count = 0

    for tid in tenant_ids:
        connected_keys = set(await list_connected_provider_keys_for_tenant(
            tenant_id=tid, db=db,
        ))
        for family_name, list_keys_fn, get_fn in fams:
            try:
                fam_keys = set(list_keys_fn())
            except Exception:
                continue
            for pk in sorted(connected_keys & fam_keys):
                res = await _probe_provider(
                    tenant_id=tid, provider_key=pk,
                    get_provider_fn=get_fn, db=db,
                )
                total_probed += 1
                if res.get("status") == "ok":
                    ok_count += 1
                else:
                    failed_count += 1

    log.info("provider-health cycle done: probed=%d ok=%d failed=%d tenants=%d",
                total_probed, ok_count, failed_count, len(tenant_ids))
    return {
        "probed": total_probed, "ok": ok_count,
        "failed": failed_count, "tenants": len(tenant_ids),
    }


# ── Background loop ──────────────────────────────────────────────
_TASK: Optional[asyncio.Task] = None


async def _cron_loop() -> None:
    # Small startup jitter so restarts don't hammer providers in
    # lockstep with sibling pods.
    await asyncio.sleep(30)
    while True:
        try:
            await run_health_cycle_once()
        except Exception as e:
            log.warning("provider-health cycle raised %s", type(e).__name__)
        await asyncio.sleep(HEALTH_CRON_INTERVAL_SECONDS)


def start_health_cron(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """Idempotent — safe to call multiple times."""
    global _TASK
    if _TASK is not None and not _TASK.done():
        return
    if os.environ.get("PROVIDER_HEALTH_CRON_DISABLED", "").lower() in ("1", "true", "yes"):
        log.info("provider-health cron disabled via env")
        return
    lp = loop or asyncio.get_event_loop()
    _TASK = lp.create_task(_cron_loop())


def stop_health_cron() -> None:
    global _TASK
    if _TASK is not None and not _TASK.done():
        _TASK.cancel()
    _TASK = None
