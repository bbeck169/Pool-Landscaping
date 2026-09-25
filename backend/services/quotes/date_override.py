"""Task H0 · Feb-2026 — Historical Invoice Date Backfill.

Shared helper for the ``created_at`` / ``paid_at`` optional
admin-only date overrides used by ``POST /quotes`` and
``POST /quotes/{qid}/record-payment``. Framework-agnostic — the
only FastAPI coupling is ``HTTPException`` for the validation
failure cases, which Task H (PDF Invoice Importer) will catch
and rewrap when it calls this helper directly (bypassing the
HTTP boundary) to preserve original PDF invoice dates during
bulk ingestion.

Contract summary (see also ``memory/PRD.md`` § Task H0):

  * ``resolve_date_override`` — pure resolution + validation for
    an optional user-supplied datetime. Coerces naive datetimes
    to UTC. Rejects future / ancient dates. Silently drops the
    override when the caller isn't in the admin allowlist.

  * Role allowlist: ``{"admin", "super_admin", "owner"}`` — matches
    ``utils.require_admin`` verbatim. An ``owner`` receiving a
    silent-drop would be surprising given owners already have
    admin-level trust everywhere else in the codebase; the PRD
    § Task H0 § "Role gate rationale" section documents the
    decision.

  * Future / ancient thresholds:
      * ``> now + 60s``  → 400 ``future_date_not_allowed``  (60s
        allows for clock skew between client + server).
      * ``< now - 10y``  → 400 ``date_too_old``.

  * Audit fields on the persisted doc (set only when the override
    was applied — never on the ``now()`` fallback path):
      * ``<field>_override_by`` — actor user id.
      * ``<field>_override_at`` — actor timestamp at override
        resolution (``now_iso``), NOT the override target value.

  * Logging shape (grep-friendly):
      * Applied path       → ``[<field>-override] tenant=<tid>
        user=<uid> entity=<kind>:<eid> applied=<iso>``.
      * Silent-drop path   → ``[<field>-override] tenant=<tid>
        user=<uid> entity=<kind>:<eid> deferred_reason=<why>``
        (used e.g. by ``record_payment`` on partial payments).
      * Naive-UTC coerce   → ``[<field>-override] tenant=<tid>
        user=<uid> entity=<kind>:<eid> naive_utc_coerced=1``.

  * Log level:
      * ``created_at`` — WARN on applied, INFO on silent-drop
        (empty-value case only; non-admin drop is completely
        silent from the caller's perspective).
      * ``paid_at``   — INFO on applied AND on deferred
        (partial-payment deferrals are legit workflows and
        must not spam WARN).

Task H (PDF importer) will call ``resolve_date_override``
directly from its ingest pipeline. Do not add any HTTP-specific
side effects (cookies / session lookups / request-scoped state)
in this module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException


_DEFAULT_ADMIN_ALLOWLIST = frozenset({"admin", "super_admin", "owner"})
_FUTURE_SLACK_SECONDS = 60
_ANCIENT_DAYS = 365 * 10   # ~10 years; the halt report allowed the
                            # ``timedelta`` approximation over
                            # ``relativedelta`` since the leap-year
                            # slop is trivial next to the 10-year bar.

logger = logging.getLogger("quotes.date_override")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_utc(dt: datetime) -> Tuple[datetime, bool]:
    """Return (UTC-aware datetime, naive_coerced_flag). Naive
    inputs are assumed UTC — the log trace makes the assumption
    observable so a future audit can trace where naive datetimes
    leaked from. Tenant-timezone inference is Phase P52.1's
    remit; deliberately NOT done here."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc), True
    return dt.astimezone(timezone.utc), False


def is_admin_role(user: Optional[dict]) -> bool:
    """Role predicate — used by both the helper and the frontend
    (the frontend duplicates the literal list in
    ``QuoteInvoiceNew.jsx`` / ``RecordPaymentModal``). Owner is
    included per Task H0 halt-report resolution 1."""
    role = str((user or {}).get("role") or "").lower()
    return role in _DEFAULT_ADMIN_ALLOWLIST


def resolve_date_override(
    override: Optional[datetime],
    *,
    user: dict,
    tenant_id: str,
    field_name: str,
    entity_kind: str,
    entity_id: str,
    log_level: str = "warn",
) -> Tuple[str, Optional[str], Optional[str]]:
    """Resolve an optional date-override into an effective ISO
    timestamp + audit metadata.

    Returns::

        (effective_iso, override_by_user_id, override_at_iso)

    Where ``override_by_user_id`` and ``override_at_iso`` are
    both ``None`` when the override was absent OR silently
    dropped (non-admin caller). Callers should only stamp the
    ``<field>_override_by`` / ``<field>_override_at`` audit
    fields when both are non-None.

    Raises ``HTTPException(400, {"error": ..., "message": ...})``
    on future / ancient input. Framework consumers (routers)
    let this bubble; non-HTTP consumers (Task H importer) should
    catch + rewrap.

    Args:
        override:      the incoming datetime (or None).
        user:          the authenticated user dict; ``role`` is
                       the only key consulted.
        tenant_id:     for log-trace scoping only — never mutated.
        field_name:    ``"created_at"`` | ``"paid_at"`` — drives
                       the log-line prefix.
        entity_kind:   ``"quote"`` | ``"invoice"`` | ``"payment"``
                       — cosmetic; grep-friendly.
        entity_id:     the doc id (or ``"<new>"`` on create).
        log_level:     ``"warn"`` (default, for ``created_at``) or
                       ``"info"`` (for ``paid_at`` per Task H0
                       resolution 2 — partial-payment deferrals
                       must not spam WARN).
    """
    if override is None:
        return _now_iso(), None, None

    # Silent-drop path — non-admin sender. Deliberately no log
    # emission on this branch: the halt-report resolution
    # specifies non-admin drops are "silent from the user-facing
    # standpoint" but debuggable via `[..deferred_reason=..]`
    # only for paid-at partials. Non-admin created_at drops
    # produce zero log noise (a phishing scanner or curl
    # smoke could otherwise DoS the log volume).
    if not is_admin_role(user):
        return _now_iso(), None, None

    coerced, naive = _coerce_utc(override)
    if naive:
        _emit(
            "info",
            f"[{field_name}-override] tenant={tenant_id} "
            f"user={(user or {}).get('id')} "
            f"entity={entity_kind}:{entity_id} naive_utc_coerced=1",
        )

    now = datetime.now(timezone.utc)
    if coerced > now + timedelta(seconds=_FUTURE_SLACK_SECONDS):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "future_date_not_allowed",
                "message": (
                    f"{field_name} override may not be in the future "
                    f"(received={coerced.isoformat()})."
                ),
                "field": field_name,
            },
        )
    if coerced < now - timedelta(days=_ANCIENT_DAYS):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "date_too_old",
                "message": (
                    f"{field_name} override may not be more than 10 "
                    f"years in the past (received={coerced.isoformat()})."
                ),
                "field": field_name,
            },
        )

    effective_iso = coerced.isoformat()
    _emit(
        log_level,
        f"[{field_name}-override] tenant={tenant_id} "
        f"user={(user or {}).get('id')} "
        f"entity={entity_kind}:{entity_id} applied={effective_iso}",
    )
    return effective_iso, (user or {}).get("id"), _now_iso()


def log_paid_at_deferred(
    *, user: dict, tenant_id: str, quote_id: str, reason: str,
) -> None:
    """Grep-friendly single-line trace for the partial-payment
    silent-drop branch inside ``record_payment``. Kept as a tiny
    named helper so a future migration to structured logs has
    exactly one call site to touch."""
    logger.info(
        f"[paid_at-override] tenant={tenant_id} "
        f"user={(user or {}).get('id')} "
        f"entity=payment:{quote_id} deferred_reason={reason}"
    )


def _emit(level: str, msg: str) -> None:
    """Level dispatch. Not exposed — internal to the helper."""
    fn = {"warn": logger.warning, "warning": logger.warning,
          "info": logger.info}.get(level, logger.info)
    fn(msg)
