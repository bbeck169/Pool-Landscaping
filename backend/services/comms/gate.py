"""Feb-2026 · Comms whitelist gate (Phase P0 safety directive).

Central helper that every outbound customer/user comm chokepoint
MUST call before dispatching to Resend / RingCentral / any other
external provider. Fails closed on any error — silent no-op is
always safer than an accidental blast to a real customer.

The rule (revised by user Feb-2026 P0 dispatch — production bypass):
  * ``APP_ENV=production`` → gate returns True (real customers are
    the intended recipients). ``gate_policy="prod_bypass"``.
  * Any other ``APP_ENV`` → a comm may leave the system only if the
    recipient record has ``is_demo_account = True``. That flag is
    opt-in per record; only demo staff + emails whose domain matches
    the tenant allowlist are auto-flagged. Everyone else silently
    no-ops with a row in ``comms_suppression_log``.
    ``gate_policy="demo_only"``.

Rationale for the split: preview / dev / staging deploys share the
same codebase as production; the whitelist stays active there to
prevent developer / QA activity from accidentally emailing or
texting real customers. Production is where real customer comms are
supposed to go out.

Recipient resolver order (locked):
  1. explicit customer_id lookup
  2. explicit user_id lookup
  3. email match against ``users.email`` in tenant
  4. email match against ``customers.email`` in tenant
  5. ``unknown`` → False

Suppression-log row shape (locked): see ``_write_suppression`` below.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db, logger  # type: ignore

# Feb-2026 · P0 whitelist scope-narrowing — reuse the same
# ``APP_ENV`` truth-source that ``/api/config/public`` and
# ``services/comms_env_guard.guard_outbound`` already consult so
# the three gates stay in lock-step. Reading through the helper
# (not a captured constant) means a supervisor reload of ``.env``
# takes effect without a Python-import cycle on this module.
from services.comms_env_guard import is_production

_LOG = logging.getLogger("comms.gate")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_of(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


def _last4(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


# ── Suppression log ──────────────────────────────────────────────────
_SUPPRESSION_TTL_DAYS = 90
_SUPPRESSION_HARD_CAP_PER_TENANT = 100_000


async def _write_suppression(*,
                              tenant_id: Optional[str],
                              comm_type: str,
                              provider: Optional[str],
                              trigger_action: Optional[str],
                              recipient_type: str,
                              recipient_id: Optional[str],
                              recipient_email_domain: Optional[str],
                              recipient_phone_last4: Optional[str],
                              reason: str) -> None:
    """Insert a suppression row. Best-effort — logging failures never
    propagate up to the caller (we don't want a broken log to break
    an already-blocked comm attempt). Applies a coarse per-tenant
    hard cap by dropping the write when the cap is exceeded."""
    doc = {
        "tenant_id": tenant_id,
        "created_at": datetime.now(timezone.utc),
        "created_at_iso": _now_iso(),
        "comm_type": comm_type,
        "provider": provider,
        "trigger_action": trigger_action,
        "recipient_type": recipient_type,
        "recipient_id": recipient_id,
        "recipient_email_domain": recipient_email_domain,
        "recipient_phone_last4": recipient_phone_last4,
        "was_would_have_been_sent": True,
        "reason": reason,
    }
    try:
        # Per-tenant hard cap — cheap count on tenant_id (indexed).
        if tenant_id:
            n = await db.comms_suppression_log.count_documents(
                {"tenant_id": tenant_id},
                limit=_SUPPRESSION_HARD_CAP_PER_TENANT + 1,
            )
            if n >= _SUPPRESSION_HARD_CAP_PER_TENANT:
                _LOG.warning(
                    "[comms.gate] suppression log hard-cap hit for "
                    "tenant=%s cap=%d — dropping write",
                    tenant_id, _SUPPRESSION_HARD_CAP_PER_TENANT,
                )
                return
        await db.comms_suppression_log.insert_one(doc)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[comms.gate] suppression insert failed: %s", exc)


async def _ensure_indexes() -> None:
    """Called lazily on first gate use. Idempotent."""
    try:
        await db.comms_suppression_log.create_index("tenant_id")
        # TTL: mongo enforces on the ``created_at`` datetime field.
        await db.comms_suppression_log.create_index(
            "created_at",
            expireAfterSeconds=_SUPPRESSION_TTL_DAYS * 86400,
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[comms.gate] index setup failed: %s", exc)


_indexes_ready = False


# ── Recipient resolver ───────────────────────────────────────────────
async def _resolve_recipient(
    identifier: Any,
    tenant_id: Optional[str],
) -> Dict[str, Any]:
    """Return a dict describing the recipient. Shape:
        {"type": "user"|"customer"|"unknown", "id": str|None,
         "email": str|None, "phone": str|None, "is_demo_account": bool}
    Never raises — errors resolve to unknown/False.
    """
    out = {"type": "unknown", "id": None, "email": None, "phone": None,
           "is_demo_account": False}
    try:
        if isinstance(identifier, dict):
            # Structured input: {"customer_id": ..., "user_id": ...,
            # "email": ..., "phone": ...}. Try in the locked order.
            cust_id = identifier.get("customer_id")
            user_id = identifier.get("user_id")
            email = identifier.get("email")
            phone = identifier.get("phone")
            q_base = {"tenant_id": tenant_id} if tenant_id else {}

            if cust_id:
                row = await db.customers.find_one(
                    {"id": cust_id, **q_base},
                    {"id": 1, "email": 1, "phone": 1, "is_demo_account": 1},
                )
                if row:
                    return {"type": "customer", "id": row.get("id"),
                             "email": row.get("email"),
                             "phone": row.get("phone"),
                             "is_demo_account": bool(row.get("is_demo_account"))}
            if user_id:
                row = await db.users.find_one(
                    {"id": user_id, **q_base},
                    {"id": 1, "email": 1, "phone": 1, "is_demo_account": 1},
                )
                if row:
                    return {"type": "user", "id": row.get("id"),
                             "email": row.get("email"),
                             "phone": row.get("phone"),
                             "is_demo_account": bool(row.get("is_demo_account"))}
            if email:
                # Users first per the locked resolver order.
                urow = await db.users.find_one(
                    {"email": email, **q_base},
                    {"id": 1, "email": 1, "phone": 1, "is_demo_account": 1},
                )
                if urow:
                    return {"type": "user", "id": urow.get("id"),
                             "email": urow.get("email"),
                             "phone": urow.get("phone"),
                             "is_demo_account": bool(urow.get("is_demo_account"))}
                crow = await db.customers.find_one(
                    {"email": email, **q_base},
                    {"id": 1, "email": 1, "phone": 1, "is_demo_account": 1},
                )
                if crow:
                    return {"type": "customer", "id": crow.get("id"),
                             "email": crow.get("email"),
                             "phone": crow.get("phone"),
                             "is_demo_account": bool(crow.get("is_demo_account"))}
            return {**out, "email": email, "phone": phone}
        # Bare string identifier — treat as email if it contains @,
        # otherwise as phone.
        s = str(identifier or "").strip()
        if "@" in s:
            return await _resolve_recipient({"email": s}, tenant_id)
        # Phone match — no explicit tenant index, best-effort.
        if s:
            crow = await db.customers.find_one(
                {"phone": s, **({"tenant_id": tenant_id} if tenant_id else {})},
                {"id": 1, "email": 1, "phone": 1, "is_demo_account": 1},
            )
            if crow:
                return {"type": "customer", "id": crow.get("id"),
                         "email": crow.get("email"),
                         "phone": crow.get("phone"),
                         "is_demo_account": bool(crow.get("is_demo_account"))}
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[comms.gate] resolve failed: %s", exc)
    return out


# ── Public API ───────────────────────────────────────────────────────
def current_gate_policy() -> str:
    """Return the string label for the currently active gate policy.

    * ``"prod_bypass"`` — ``APP_ENV=production``; every comm allowed
      through (real customers are the intended recipients).
    * ``"demo_only"``  — any other ``APP_ENV``; only recipients with
      ``is_demo_account=True`` clear the gate.

    Exposed for the ``/api/settings/integrations/health/comms``
    admin endpoint so ops can see at a glance which policy is
    active in the running process.
    """
    return "prod_bypass" if is_production() else "demo_only"


async def is_comm_allowed(
    *,
    recipient_identifier: Any,
    comm_type: str,
    tenant_id: Optional[str] = None,
    provider: Optional[str] = None,
    trigger_action: Optional[str] = None,
) -> bool:
    """Return True iff the send is allowed to reach the live provider.

    Policy (Feb-2026 P0 revision):
      * ``APP_ENV=production`` → always allowed. Real customers are
        the intended recipients; the demo-account whitelist is
        scoped to non-prod only.
      * Otherwise → allowed iff the resolved recipient has
        ``is_demo_account=True``.

    Every False return writes a suppression-log row. Fails closed
    on any error path (resolution failure, DB failure, unexpected
    input) — silent no-op is always safer than an accidental send.
    """
    # Feb-2026 P0 whitelist scoped to non-prod only per user directive.
    # In production, real customers are the intended recipients.
    # Preview stays fail-closed to prevent accidental sends.
    if is_production():
        # Emit the same audit canary as the whitelist-pass path so
        # ``grep [COMMS_SEND]`` still shows every allowed send in
        # the log stream. Recipient identity kept minimal (domain +
        # last4) so we don't PII-tax the log volume.
        _email = None
        _phone = None
        if isinstance(recipient_identifier, dict):
            _email = recipient_identifier.get("email")
            _phone = recipient_identifier.get("phone")
        elif isinstance(recipient_identifier, str):
            if "@" in recipient_identifier:
                _email = recipient_identifier
            else:
                _phone = recipient_identifier
        _LOG.info(
            "[COMMS_SEND] policy=prod_bypass type=%s provider=%s "
            "trigger=%s domain=%s last4=%s",
            comm_type, provider, trigger_action,
            _domain_of(_email), _last4(_phone),
        )
        return True

    global _indexes_ready
    if not _indexes_ready:
        await _ensure_indexes()
        _indexes_ready = True

    try:
        r = await _resolve_recipient(recipient_identifier, tenant_id)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[comms.gate] unexpected resolve error: %s", exc)
        await _write_suppression(
            tenant_id=tenant_id, comm_type=comm_type, provider=provider,
            trigger_action=trigger_action, recipient_type="unknown",
            recipient_id=None,
            recipient_email_domain=None,
            recipient_phone_last4=None, reason="gate_error",
        )
        return False

    if r.get("type") == "unknown":
        await _write_suppression(
            tenant_id=tenant_id, comm_type=comm_type, provider=provider,
            trigger_action=trigger_action, recipient_type="unknown",
            recipient_id=None,
            recipient_email_domain=_domain_of(r.get("email")),
            recipient_phone_last4=_last4(r.get("phone")),
            reason="recipient_not_found",
        )
        return False

    if r.get("is_demo_account"):
        # Safety canary log — grep for "[COMMS_SEND]" to audit
        # everything that was allowed out.
        _LOG.info(
            "[COMMS_SEND] type=%s provider=%s trigger=%s "
            "recipient_type=%s recipient_id=%s domain=%s last4=%s",
            comm_type, provider, trigger_action, r.get("type"),
            r.get("id"), _domain_of(r.get("email")),
            _last4(r.get("phone")),
        )
        return True

    await _write_suppression(
        tenant_id=tenant_id, comm_type=comm_type, provider=provider,
        trigger_action=trigger_action,
        recipient_type=r.get("type") or "unknown",
        recipient_id=r.get("id"),
        recipient_email_domain=_domain_of(r.get("email")),
        recipient_phone_last4=_last4(r.get("phone")),
        reason="not_demo_account",
    )
    return False


# Sync convenience for legacy sync callers. The Resend SDK monkey-
# patch in ``services/comms/sdk_intercept.py`` calls this from a
# ``asyncio.to_thread`` worker (Resend SDK is sync), which means the
# caller may or may not be running inside an active event loop
# depending on how far up the stack the ``to_thread`` boundary was.
#
# Previous implementation created a fresh loop via
# ``asyncio.new_event_loop()`` + ``loop.run_until_complete(...)`` on
# the current thread. That works when there is no running loop on
# the current thread, but raises ``RuntimeError: This event loop is
# already running`` when the caller IS inside a running loop (any
# ``await``ing FastAPI handler stack that reaches a direct
# ``resend.Emails.send`` bypass). The bare ``except`` at the bottom
# then swallowed the RuntimeError and returned ``False`` — real
# demo-account sends were being fail-closed silently.
#
# Fix: run the async gate on a **worker thread** with its own fresh
# event loop, using ``concurrent.futures.ThreadPoolExecutor``. This
# is safe regardless of whether the calling thread already has a
# running loop (the worker thread has its own thread-local loop).
# Uses stdlib only — no new dependency.
_SYNC_EXECUTOR: "Optional[Any]" = None


def _get_sync_executor():
    """Lazy singleton worker-thread pool for :func:`is_comm_allowed_sync`.
    Sized to 4 workers — the SDK monkey-patch is the sole caller,
    burst-fires at most once per outbound email, and blocks the
    caller until the gate resolves. 4 concurrent workers is plenty
    to absorb any realistic burst without contention."""
    global _SYNC_EXECUTOR
    if _SYNC_EXECUTOR is None:
        from concurrent.futures import ThreadPoolExecutor
        _SYNC_EXECUTOR = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="comms-gate-sync",
        )
    return _SYNC_EXECUTOR


def is_comm_allowed_sync(
    *,
    recipient_identifier: Any,
    comm_type: str,
    tenant_id: Optional[str] = None,
    provider: Optional[str] = None,
    trigger_action: Optional[str] = None,
) -> bool:
    """Synchronous wrapper around :func:`is_comm_allowed`.

    Runs the async gate on a worker thread with its own fresh event
    loop so it's safe to call from within an already-running loop
    (the previous implementation silently fail-closed in that case).

    Fails closed on any unexpected error, but the exception is
    logged at WARN level with the exception class name + message so
    the failure surfaces loudly instead of masquerading as a normal
    ``is_demo_account=False`` suppression.
    """
    import asyncio

    def _worker() -> bool:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(is_comm_allowed(
                recipient_identifier=recipient_identifier,
                comm_type=comm_type, tenant_id=tenant_id,
                provider=provider, trigger_action=trigger_action,
            ))
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
            asyncio.set_event_loop(None)

    try:
        future = _get_sync_executor().submit(_worker)
        # No timeout: the gate is cheap (single Mongo point-read on
        # customers/users). A pathological Mongo hang would already
        # be visible in the caller's own timeout budget.
        return future.result()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "[comms.gate] sync-wrapper failed closed: %s: %s",
            type(exc).__name__, exc,
        )
        return False
