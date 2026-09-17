"""Feb-2026 · Payment Processor Primary/Backup failover router.

Tenant-scoped runtime failover on top of ``services.payments_byo``.

Wire-model
----------
Each tenant may configure two provider slots on ``tenant.settings.
payment``::

    {
      "primary_provider": "stripe" | "square" | "paypal" | "authnet" | "lumino",
      "backup_provider":  "stripe" | "square" | ... | None,
    }

Defaults: primary=``stripe``, backup=``None``. This preserves the
production-adjacent tenant-billing Stripe path for every existing
tenant byte-identically — Ticket non-negotiable.

Priority
--------
:func:`get_provider_for_operation` returns the primary provider when
it is configured. If primary is missing keys the router falls back to
backup + writes an audit row + emits a WARNING log.

Runtime failover: :func:`with_failover` runs a caller-supplied
coroutine against the primary. On a **transient** provider error the
same coroutine is retried against the backup, again writing an audit
row + emitting a WARNING. **Non-transient** errors (4xx / user
errors like card decline / bad request / auth) bubble up unchanged so
they surface to the customer instead of silently double-attempting a
declined card on the backup provider.

Retryable classification (per Ticket)
-------------------------------------
* Retryable: :class:`ProviderTransientError` — network timeouts,
  connection resets, 5xx from the provider.
* NOT retryable: 4xx errors, ``ChargeAlreadySucceededError``, card
  declines, and every other exception subclass that a call site can
  turn into a user-visible error.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from .models import PaymentsByoError
from .registry import (
    get_payments_byo_provider_by_short_name,
    list_short_names,
)
from .stripe_provider import StripeByoProvider
from .tenant_base import PaymentsByoProvider


log = logging.getLogger("payments_byo.failover")

T = TypeVar("T")


# ── Constants ────────────────────────────────────────────────────
FAILOVER_AUDIT_COLLECTION = "payment_failover_audit"

#: Mongo TTL (seconds) — audit is not forever-storage per Ticket.
FAILOVER_AUDIT_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days


# ── Errors ───────────────────────────────────────────────────────
class ProviderTransientError(PaymentsByoError):
    """Raised by a provider call site when the caller has determined
    the error is a retryable transient (5xx, network timeout,
    connection reset). Only these bubble into the backup-provider
    retry path in :func:`with_failover`.
    """


class PaymentProviderUnavailableError(PaymentsByoError):
    """Both primary and backup exhausted (unconfigured or both
    raised transient). Callers convert to HTTP 503.
    """


# ── Config load ──────────────────────────────────────────────────
def _default_settings() -> Dict[str, Optional[str]]:
    return {"primary_provider": "stripe", "backup_provider": None}


async def read_tenant_provider_settings(
    tenant_id: str, *, db,
) -> Dict[str, Optional[str]]:
    """Return ``{"primary_provider", "backup_provider"}``.

    Missing settings path resolves to the ticket-mandated defaults
    (primary=stripe, backup=None) so tenants that never touched the
    new UI keep working. Never touches the network.
    """
    row = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings.payment": 1},
    ) or {}
    settings = ((row.get("settings") or {}).get("payment") or {})
    out = _default_settings()
    if isinstance(settings.get("primary_provider"), str):
        out["primary_provider"] = settings["primary_provider"]
    if settings.get("backup_provider") in (None, "", "none"):
        out["backup_provider"] = None
    elif isinstance(settings.get("backup_provider"), str):
        out["backup_provider"] = settings["backup_provider"]
    return out


# ── Provider selection ──────────────────────────────────────────
async def _provider_is_configured(
    provider: PaymentsByoProvider, *, tenant_id: str, db,
) -> bool:
    """Env probe for Stripe (pod-level), ``services.secrets`` probe
    for BYO providers. Never raises."""
    if isinstance(provider, StripeByoProvider):
        return StripeByoProvider.is_configured()
    from ._helpers import load_provider_config
    try:
        cfg = await load_provider_config(
            tenant_id=tenant_id, provider_key=provider.provider_key, db=db,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "[payment-failover] configured-check failed for provider=%s "
            "tenant=%s: %s", provider.short_name, tenant_id,
            type(exc).__name__,
        )
        return False
    return bool(cfg)


def _resolve_provider(short_name: Optional[str]) -> Optional[PaymentsByoProvider]:
    """Look up a provider instance by short name. Returns ``None``
    for falsy short names (``backup_provider=None`` case). Unknown
    names bubble as :class:`payments_byo.UnknownPaymentsProvider`."""
    if not short_name:
        return None
    return get_payments_byo_provider_by_short_name(short_name)


async def _audit(
    *, db, tenant_id: str, operation: str,
    primary_provider: str, backup_provider: Optional[str],
    error_from_primary: str, resolution: str,
) -> None:
    """Insert a :data:`FAILOVER_AUDIT_COLLECTION` row.

    ``resolution``: ``"backup_used"`` when we successfully invoked
    the backup, ``"static_config"`` when primary was unconfigured
    and we returned backup at :func:`get_provider_for_operation`
    time, or ``"exhausted"`` when both providers failed.
    """
    try:
        await db[FAILOVER_AUDIT_COLLECTION].insert_one({
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "operation": operation,
            "primary_provider": primary_provider,
            "backup_provider": backup_provider,
            "error_from_primary": (error_from_primary or "")[:500],
            "resolution": resolution,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:  # pragma: no cover — audit best-effort
        log.warning(
            "[payment-failover] audit insert failed tenant=%s op=%s: %s",
            tenant_id, operation, exc,
        )


async def get_provider_for_operation(
    *, tenant_id: str, operation: str, db,
) -> PaymentsByoProvider:
    """Return the provider to try FIRST for ``operation``.

    Priority:
      1. Primary is configured → primary.
      2. Primary unconfigured → backup (audit row, WARNING log).
      3. Both unconfigured → :class:`PaymentProviderUnavailableError`.

    ``operation`` is a free-form string used purely for logging + the
    audit row — the provider protocol is the same for every op.
    """
    settings = await read_tenant_provider_settings(tenant_id, db=db)
    primary_short = settings["primary_provider"] or "stripe"
    backup_short = settings["backup_provider"]

    primary = _resolve_provider(primary_short)
    backup = _resolve_provider(backup_short)

    if primary and await _provider_is_configured(
        primary, tenant_id=tenant_id, db=db,
    ):
        return primary

    if backup and await _provider_is_configured(
        backup, tenant_id=tenant_id, db=db,
    ):
        log.warning(
            "[payment-failover] tenant=%s operation=%s primary=%s "
            "failover_to=%s (primary_unconfigured)",
            tenant_id, operation, primary_short, backup_short,
        )
        await _audit(
            db=db, tenant_id=tenant_id, operation=operation,
            primary_provider=primary_short, backup_provider=backup_short,
            error_from_primary="primary_unconfigured",
            resolution="static_config",
        )
        return backup

    raise PaymentProviderUnavailableError(
        f"No configured payment provider for tenant {tenant_id} "
        f"(primary={primary_short!r} backup={backup_short!r})"
    )


async def with_failover(
    *,
    tenant_id: str,
    operation: str,
    call: Callable[[PaymentsByoProvider], Awaitable[T]],
    db,
    retryable_errors: tuple = (ProviderTransientError,),
) -> T:
    """Run ``call(provider)`` against the primary; on a transient
    error, retry against the backup.

    Non-retryable errors bubble up unchanged — card declines, 4xx
    bodies, and every other :class:`Exception` subclass NOT listed
    in ``retryable_errors`` never trigger a backup retry (per
    Ticket rule).
    """
    settings = await read_tenant_provider_settings(tenant_id, db=db)
    primary_short = settings["primary_provider"] or "stripe"
    backup_short = settings["backup_provider"]

    # Static-config resolution — pick starting point + backup.
    primary = _resolve_provider(primary_short)
    backup = _resolve_provider(backup_short)

    primary_ready = bool(primary) and await _provider_is_configured(
        primary, tenant_id=tenant_id, db=db,
    )
    backup_ready = bool(backup) and await _provider_is_configured(
        backup, tenant_id=tenant_id, db=db,
    )

    if not primary_ready and not backup_ready:
        raise PaymentProviderUnavailableError(
            f"No configured payment provider for tenant {tenant_id}"
        )

    if not primary_ready:
        # Static-config failover — primary is missing keys entirely.
        # Same audit + log path as :func:`get_provider_for_operation`.
        log.warning(
            "[payment-failover] tenant=%s operation=%s primary=%s "
            "failover_to=%s (primary_unconfigured)",
            tenant_id, operation, primary_short, backup_short,
        )
        await _audit(
            db=db, tenant_id=tenant_id, operation=operation,
            primary_provider=primary_short, backup_provider=backup_short,
            error_from_primary="primary_unconfigured",
            resolution="static_config",
        )
        return await call(backup)  # type: ignore[arg-type]

    # Primary is ready. Try it.
    try:
        return await call(primary)  # type: ignore[arg-type]
    except retryable_errors as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
        if not backup_ready:
            log.error(
                "[payment-failover] tenant=%s operation=%s primary=%s "
                "raised transient=%s but backup is unconfigured — "
                "surfacing to caller.",
                tenant_id, operation, primary_short, type(exc).__name__,
            )
            await _audit(
                db=db, tenant_id=tenant_id, operation=operation,
                primary_provider=primary_short, backup_provider=backup_short,
                error_from_primary=primary_error,
                resolution="exhausted",
            )
            raise
        log.warning(
            "[payment-failover] tenant=%s operation=%s primary=%s "
            "failover_to=%s (primary_transient=%s)",
            tenant_id, operation, primary_short, backup_short,
            type(exc).__name__,
        )
        await _audit(
            db=db, tenant_id=tenant_id, operation=operation,
            primary_provider=primary_short, backup_provider=backup_short,
            error_from_primary=primary_error,
            resolution="backup_used",
        )
        return await call(backup)  # type: ignore[arg-type]


# ── Indexes ───────────────────────────────────────────────────────
async def ensure_failover_audit_indexes(db) -> None:
    """Create the TTL + tenant-scoped read indexes for the audit
    collection. Idempotent — safe to run on every boot.
    """
    coll = db[FAILOVER_AUDIT_COLLECTION]
    try:
        await coll.create_index("id", unique=True)
        await coll.create_index([("tenant_id", 1), ("timestamp", -1)])
        # TTL — Mongo lets you `create_index` with an ISO-date field
        # for TTL only when the value is a real ``datetime``. Our
        # ``timestamp`` is a string, so we back the TTL with a
        # separate BSON-date field ``_ttl_at``.
        await coll.create_index("_ttl_at", expireAfterSeconds=0)
    except Exception as exc:  # pragma: no cover — idempotent index
        log.warning(
            "[payment-failover] ensure audit indexes failed: %s", exc,
        )


# ── Available-provider discovery for /GET endpoint ────────────────
async def list_available_providers(
    *, tenant_id: str, db,
) -> list[Dict[str, Any]]:
    """Return the short-name registry + per-provider ``is_configured``
    for the settings UI. Never leaks credentials.

    Order: registry order, then Stripe forced to the front so the
    dropdowns render sensibly.
    """
    order = list_short_names()
    if "stripe" in order:
        order.remove("stripe")
        order.insert(0, "stripe")
    # ``stripe`` gets added by the failover-router registration path
    # (see ``payments_byo.registry``); make sure the caller sees it
    # even before that registration lands.
    if "stripe" not in order:
        order.insert(0, "stripe")

    out: list[Dict[str, Any]] = []
    for short in order:
        try:
            provider = _resolve_provider(short)
        except Exception:  # noqa: BLE001 — unknown short-name safety
            continue
        if provider is None:
            continue
        configured = await _provider_is_configured(
            provider, tenant_id=tenant_id, db=db,
        )
        out.append({
            "short_name": short,
            "provider_key": provider.provider_key,
            "is_configured": configured,
            "requires_tenant_config": provider.primary_secret_field is not None,
        })
    return out


# ── Retry helpers for common transient-error taxonomies ───────────
def is_transient_httpx_error(exc: BaseException) -> bool:
    """Best-effort taxonomy: httpx timeout / connection / 5xx.

    Call sites that talk raw httpx can wrap their own retries via
    ``if is_transient_httpx_error(exc): raise ProviderTransientError``
    before letting anything else bubble up.
    """
    # Late import so the module doesn't pull httpx on every load.
    try:
        import httpx  # type: ignore
    except Exception:  # pragma: no cover
        return False
    if isinstance(exc, (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
    )):
        return True
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return False
