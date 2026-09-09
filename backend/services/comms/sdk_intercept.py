"""Feb-2026 · Comms whitelist — SDK-level monkey-patch (safety net).

Even though every "official" send path in the codebase has been
gated at its chokepoint (see the 6 sites documented in the P0
dispatch), a couple of dozen files still call
``resend.Emails.send({...})`` directly.  Refactoring each of them to
route through the adapter would take another 2-3 hours; the safer
and more DRY move is to patch the SDK entry point ONCE so every
direct caller inherits the gate for free.

Fail-closed by construction: any exception in the gate → we do NOT
call the SDK. That's the whole point.

Idempotent: safe to import multiple times — the patched marker is
set on the ``resend.Emails`` class the first time through.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

_LOG = logging.getLogger("comms.sdk_intercept")

_PATCH_MARKER = "_aquaterra_gated_send"


def install_resend_gate() -> bool:
    """Patch ``resend.Emails.send`` so every direct caller runs
    through :func:`services.comms.gate.is_comm_allowed` first.

    Returns True when the patch was applied (or was already in
    place); False when the SDK isn't importable in this environment
    (dev containers without ``RESEND_API_KEY`` won't have installed
    it).
    """
    try:
        import resend  # type: ignore
    except Exception:  # pragma: no cover — SDK optional in some envs
        _LOG.info("[sdk_intercept] resend SDK not importable — skipping")
        return False

    Emails = getattr(resend, "Emails", None)
    if Emails is None:
        _LOG.warning("[sdk_intercept] resend.Emails missing — skipping")
        return False

    if getattr(Emails, _PATCH_MARKER, False):
        return True  # already patched

    original_send = Emails.send

    def _gated_send(payload: Dict[str, Any], *args, **kwargs):
        """Sync wrapper — resend.Emails.send is sync so we can call
        the sync gate helper directly."""
        try:
            from services.comms.gate import is_comm_allowed_sync
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "[sdk_intercept] gate import failed — failing closed: %s",
                exc,
            )
            return {"suppressed_by_gate": True,
                     "reason": "gate_import_failed"}

        # Extract the recipient email from the SDK payload.
        recipients = []
        if isinstance(payload, dict):
            to_field = payload.get("to")
            if isinstance(to_field, list):
                recipients = [str(x) for x in to_field if x]
            elif isinstance(to_field, str) and to_field:
                recipients = [to_field]

        if not recipients:
            _LOG.warning("[sdk_intercept] no recipient in payload — blocking")
            return {"suppressed_by_gate": True, "reason": "no_recipient"}

        # Per-recipient gate: iterate. If ANY recipient is not demo,
        # block the whole send — resend batches don't support partial
        # sends, and letting a batch through means a real customer
        # gets the mail. Log each blocked recipient individually.
        for r in recipients:
            try:
                ok = is_comm_allowed_sync(
                    recipient_identifier=r,
                    comm_type="email",
                    provider="resend",
                    trigger_action="direct_sdk_call",
                )
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "[sdk_intercept] gate errored for %s — failing closed: %s",
                    r, exc,
                )
                ok = False
            if not ok:
                _LOG.info(
                    "[sdk_intercept] blocked resend send to %s (not demo)",
                    r,
                )
                # Feb-2026 · P0 comms — record blocked send in the
                # audit log so ops can see WHY Brian got nothing.
                try:
                    from services.comms_send_log import record_attempt as _rec2
                    _tid = None
                    if isinstance(payload, dict):
                        _h = payload.get("headers") or {}
                        if isinstance(_h, dict):
                            _tid = _h.get("X-Tenant-Id") or None
                    _rec2(
                        "email", ok=False, tenant_id=_tid, recipient=r,
                        template="direct_sdk_call",
                        provider="resend",
                        provider_status="suppressed_by_gate",
                        was_mock=False, routed_via="sdk_intercept",
                        error="Gate blocked: not_demo_account (non-prod)",
                    )
                except Exception:  # noqa: BLE001
                    pass
                return {"suppressed_by_gate": True,
                         "reason": "not_demo_account",
                         "recipient": r}

        # All recipients cleared the gate — pass to the real SDK.
        # Feb-2026 · P0 comms — also record the attempt to
        # ``db.comms_send_log`` so direct SDK callers (estimator,
        # signatures, jobs, dunning, etc.) surface in the customer
        # audit endpoint. Best-effort; never blocks the send.
        try:
            from services.comms_send_log import (
                record_attempt as _rec,
                format_exc as _fmt,
            )
        except Exception:  # noqa: BLE001
            _rec = None
            _fmt = None

        _to_first = recipients[0] if recipients else None
        _subject = payload.get("subject") if isinstance(payload, dict) else None
        _tenant = None
        _template = None
        if isinstance(payload, dict):
            _hdrs = payload.get("headers") or {}
            if isinstance(_hdrs, dict):
                _template = _hdrs.get("X-Template") or None
                _tenant = _hdrs.get("X-Tenant-Id") or None

        try:
            resp = original_send(payload, *args, **kwargs)
            provider_id = None
            if isinstance(resp, dict):
                provider_id = resp.get("id") or resp.get("data", {}).get("id") if isinstance(resp.get("data"), dict) else resp.get("id")
            if _rec:
                _rec(
                    "email", ok=True,
                    tenant_id=_tenant, recipient=_to_first,
                    template=_template or "direct_sdk_call",
                    provider="resend", provider_status="sent",
                    provider_response_id=provider_id, was_mock=False,
                    routed_via="sdk_intercept",
                )
            return resp
        except Exception as exc:
            if _rec and _fmt:
                _rec(
                    "email", ok=False,
                    tenant_id=_tenant, recipient=_to_first,
                    template=_template or "direct_sdk_call",
                    provider="resend", provider_status="failed",
                    was_mock=False, routed_via="sdk_intercept",
                    **_fmt(exc),
                )
            raise

    _gated_send._aquaterra_original = original_send  # type: ignore[attr-defined]
    Emails.send = _gated_send  # type: ignore[assignment]
    setattr(Emails, _PATCH_MARKER, True)
    _LOG.info("[sdk_intercept] resend.Emails.send monkey-patched (gated)")
    return True
