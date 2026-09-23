"""Phase P39 · Feb-2026 — MyGeotab polling adapter.

Multi-tenant asyncio poller that hits MyGeotab's JSON-RPC endpoint
every 60 seconds (configurable) with ``Get typeName=DeviceStatusInfo``
and persists each device's current location into ``gps_pings``.

Enable
------
Set ``TELEMATICS_GEOTAB_POLL_ENABLED=true`` in the environment.  The
poller is deliberately OFF by default so a code-drop doesn't wake
up the network for every tenant on the first boot after the P39 PR
lands.  Once at least one tenant has configured the Geotab provider,
the ops runbook flips the env var and restarts.

Auth
----
Uses the JSON-RPC ``credentials`` object:
    {"database": <tenant.config.account_id>,
     "userName": "sessionId",         # sentinel — Geotab accepts sessionId
     "sessionId": <tenant.config.api_key>}

We treat ``api_key`` as either a MyGeotab sessionId (preferred) or a
password.  MyGeotab's JSON-RPC handles either as long as ``database``
matches.  The settings UI helper text spells this out.

Multi-tenant loop
-----------------
Every ``TELEMATICS_GEOTAB_POLL_INTERVAL_SEC`` seconds (default 60,
min 30), the poller:

  1. Iterates ``tenant_secrets`` for rows with
     ``provider_key == "telematics_geotab"`` AND
     ``connection_type == "api_key"``.
  2. For each tenant it isn't in cooldown for, decrypts the config,
     hits MyGeotab, and for each device in the response persists a
     ``gps_pings`` row with ``source="telematics_geotab_poll"``.
  3. Failure → mark the tenant's connection with a ``last_error``
     stamp AND enter a 5-cycle cooldown to avoid hammering a bad
     credential.

Idempotency
-----------
MyGeotab returns the same ``dateTime`` for a device that hasn't
moved between polls.  The ``gps_pings_dedup_bg`` unique compound
index on ``(tenant_id, external_vehicle_id, captured_at)`` catches
the duplicate at the storage layer — ``persist_telematics_ping``
returns ``status="duplicate"`` and we increment a metric.

Not-Celery / Not-APScheduler
----------------------------
Per the P39 brief: use the existing FastAPI lifespan pattern (P21).
The scheduler is a single ``asyncio.create_task`` on startup, joined
+ cancelled on shutdown.  No new dependency introduced.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import db, logger
from services.telematics import GEOTAB_PROVIDER_KEY
from services.telematics._helpers import load_provider_config


# ═════════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════════
_ENABLED_ENV = "TELEMATICS_GEOTAB_POLL_ENABLED"
_INTERVAL_ENV = "TELEMATICS_GEOTAB_POLL_INTERVAL_SEC"
_DEFAULT_INTERVAL_SEC = 60
_MIN_INTERVAL_SEC = 30
_COOLDOWN_CYCLES = 5


def poll_enabled() -> bool:
    return (os.environ.get(_ENABLED_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def poll_interval_sec() -> int:
    raw = (os.environ.get(_INTERVAL_ENV) or "").strip()
    if not raw:
        return _DEFAULT_INTERVAL_SEC
    try:
        v = int(raw)
    except ValueError:
        logger.warning(
            "[p39-geotab-poll] invalid %s=%r — falling back to default %ss",
            _INTERVAL_ENV, raw, _DEFAULT_INTERVAL_SEC,
        )
        return _DEFAULT_INTERVAL_SEC
    if v < _MIN_INTERVAL_SEC:
        logger.warning(
            "[p39-geotab-poll] %s=%s below floor %s — clamping",
            _INTERVAL_ENV, v, _MIN_INTERVAL_SEC,
        )
        return _MIN_INTERVAL_SEC
    return v


# ═════════════════════════════════════════════════════════════════
# In-memory cooldown map (per-process — fine for a single web worker
# or dedicated scheduler pod).  Not persisted; a pod restart resets it.
# ═════════════════════════════════════════════════════════════════
_cooldown: Dict[str, int] = {}


# ═════════════════════════════════════════════════════════════════
# Multi-tenant discovery
# ═════════════════════════════════════════════════════════════════
async def _list_geotab_tenants() -> List[str]:
    """Return distinct ``tenant_id`` values that carry a Geotab config."""
    out: List[str] = []
    seen: set[str] = set()
    async for row in db.tenant_secrets.find(
        {"provider_key": GEOTAB_PROVIDER_KEY},
        {"_id": 0, "tenant_id": 1},
    ):
        tid = row.get("tenant_id")
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


# ═════════════════════════════════════════════════════════════════
# MyGeotab JSON-RPC call
# ═════════════════════════════════════════════════════════════════
async def _call_geotab_api(
    *, server_url: str,
    database: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Fetch ``DeviceStatusInfo`` list from a tenant's MyGeotab server.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx and ``ValueError`` on
    JSON-RPC ``error`` responses.  Returns the raw ``result`` list.
    """
    url = f"https://{server_url.strip().strip('/')}/apiv1"
    payload = {
        "method": "Get",
        "params": {
            "typeName": "DeviceStatusInfo",
            "credentials": {
                "database": database,
                "userName": "sessionId",
                "sessionId": session_id,
            },
        },
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
    r.raise_for_status()
    body = r.json()
    if isinstance(body, dict) and "error" in body:
        raise ValueError(f"MyGeotab RPC error: {body['error']}")
    if not isinstance(body, dict) or "result" not in body:
        raise ValueError(f"MyGeotab RPC unexpected shape: {list(body)!r}")
    result = body["result"]
    if not isinstance(result, list):
        return []
    return result


def _normalise_device_status_info(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """MyGeotab ``DeviceStatusInfo`` row → canonical ping dict.

    Fields we consume:
      * ``device.id`` → external_vehicle_id
      * ``latitude`` / ``longitude`` → lat / lon
      * ``dateTime`` → captured_at
      * ``speed`` (kmh) → speed_mps
      * ``bearing`` → heading
    """
    if not isinstance(row, dict):
        return None
    device = row.get("device") or {}
    vid = None
    if isinstance(device, dict):
        vid = device.get("id")
    if not vid:
        return None
    lat = row.get("latitude")
    lon = row.get("longitude")
    if lat is None or lon is None:
        return None
    ts = row.get("dateTime")
    if not ts:
        return None
    speed_kmh = row.get("speed")
    speed_mps: Optional[float] = None
    if speed_kmh is not None:
        try:
            speed_mps = float(speed_kmh) / 3.6
        except (TypeError, ValueError):
            speed_mps = None
    bearing = row.get("bearing")
    try:
        heading = float(bearing) if bearing is not None else None
    except (TypeError, ValueError):
        heading = None
    return {
        "external_vehicle_id": str(vid),
        "lat": float(lat),
        "lon": float(lon),
        "captured_at": str(ts),
        "speed_mps": speed_mps,
        "heading": heading,
        "event_id": None,
    }


# ═════════════════════════════════════════════════════════════════
# Per-tenant tick
# ═════════════════════════════════════════════════════════════════
async def _record_last_error(tenant_id: str, message: str) -> None:
    """Stamp ``last_error`` + ``last_error_at`` on the tenant's Geotab
    connection row for observability."""
    try:
        await db.tenant_secrets.update_one(
            {"tenant_id": tenant_id, "provider_key": GEOTAB_PROVIDER_KEY},
            {"$set": {
                "last_error": message[:500],
                "last_error_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception:  # noqa: BLE001
        # last_error is best-effort — never let it kill the tick.
        logger.exception(
            "[p39-geotab-poll] failed to persist last_error for tenant=%s",
            tenant_id,
        )


async def poll_tenant_once(tenant_id: str) -> Dict[str, Any]:
    """Run one poll cycle for a single tenant.  Returns a summary
    dict useful for tests + metrics.

    Never raises — auth errors set cooldown; network errors log WARN;
    per-device parse failures are counted but don't abort the tick.
    """
    from routers.telematics_webhooks import persist_telematics_ping

    if _cooldown.get(tenant_id, 0) > 0:
        _cooldown[tenant_id] -= 1
        return {
            "tenant_id": tenant_id,
            "status": "cooldown",
            "remaining_cycles": _cooldown[tenant_id],
        }

    config = await load_provider_config(
        tenant_id=tenant_id, provider_key=GEOTAB_PROVIDER_KEY,
    )
    if not config:
        return {"tenant_id": tenant_id, "status": "no_config"}
    database = str(config.get("account_id") or "").strip()
    session_id = str(config.get("api_key") or "").strip()
    server_url = str(config.get("server_url") or "my.geotab.com").strip() or "my.geotab.com"
    if not database or not session_id:
        return {"tenant_id": tenant_id, "status": "missing_credentials"}

    try:
        rows = await _call_geotab_api(
            server_url=server_url,
            database=database,
            session_id=session_id,
        )
    except (httpx.HTTPStatusError, ValueError) as e:
        # Treat both as auth-class errors → cooldown.
        msg = str(e)
        logger.error(
            "[p39-geotab-poll] auth error tenant=%s server=%s: %s",
            tenant_id, server_url, msg,
        )
        await _record_last_error(tenant_id, msg)
        _cooldown[tenant_id] = _COOLDOWN_CYCLES
        return {"tenant_id": tenant_id, "status": "auth_error", "error": msg}
    except httpx.RequestError as e:
        # Network hiccup — retry next tick, no cooldown.
        logger.warning(
            "[p39-geotab-poll] network error tenant=%s server=%s: %s",
            tenant_id, server_url, e,
        )
        return {"tenant_id": tenant_id, "status": "network_error", "error": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "[p39-geotab-poll] unexpected error tenant=%s", tenant_id,
        )
        return {"tenant_id": tenant_id, "status": "unexpected_error", "error": str(e)}

    persisted = 0
    duplicates = 0
    unmapped = 0
    for row in rows:
        normalised = _normalise_device_status_info(row)
        if not normalised:
            continue
        res = await persist_telematics_ping(
            tenant_id=tenant_id,
            provider_short="geotab",
            source="telematics_geotab_poll",
            normalised=normalised,
        )
        if res["status"] == "persisted":
            persisted += 1
        elif res["status"] == "duplicate":
            duplicates += 1
        if not res.get("vehicle_mapped"):
            unmapped += 1
    logger.info(
        "[p39-geotab-poll] tick tenant=%s scanned=%s persisted=%s "
        "duplicates=%s unmapped=%s",
        tenant_id, len(rows), persisted, duplicates, unmapped,
    )
    return {
        "tenant_id": tenant_id,
        "status": "ok",
        "scanned": len(rows),
        "persisted": persisted,
        "duplicates": duplicates,
        "unmapped": unmapped,
    }


# ═════════════════════════════════════════════════════════════════
# Scheduler loop
# ═════════════════════════════════════════════════════════════════
_task: Optional[asyncio.Task] = None


async def _loop_forever() -> None:
    interval = poll_interval_sec()
    logger.info(
        "[p39-geotab-poll] scheduler started — interval_sec=%s", interval,
    )
    while True:
        try:
            tenants = await _list_geotab_tenants()
            for tid in tenants:
                await poll_tenant_once(tid)
        except asyncio.CancelledError:
            logger.info("[p39-geotab-poll] scheduler cancelled")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[p39-geotab-poll] loop error — will retry")
        await asyncio.sleep(interval)


def start_scheduler() -> bool:
    """Start the polling loop as a background asyncio task.  Returns
    True when started, False when ``poll_enabled()`` returned False.

    Idempotent — calling twice is a no-op after the first success.
    """
    global _task
    if not poll_enabled():
        logger.info(
            "[p39-geotab-poll] %s not truthy — poller disabled",
            _ENABLED_ENV,
        )
        return False
    if _task and not _task.done():
        return True
    _task = asyncio.create_task(_loop_forever(), name="p39_geotab_poller")
    return True


async def stop_scheduler() -> None:
    """Cancel + join the polling task if it's running.  Idempotent."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _task = None


def reset_cooldown_for_tests(tenant_id: Optional[str] = None) -> None:
    """Test hook — clears the in-memory cooldown map."""
    if tenant_id is None:
        _cooldown.clear()
    else:
        _cooldown.pop(tenant_id, None)


def get_cooldown_for_tests(tenant_id: str) -> int:
    """Test hook — expose the internal cooldown counter."""
    return _cooldown.get(tenant_id, 0)
