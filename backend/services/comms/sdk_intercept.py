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
                return {"suppressed_by_gate": True,
                         "reason": "not_demo_account",
                         "recipient": r}

        # All recipients cleared the gate — pass to the real SDK.
        return original_send(payload, *args, **kwargs)

    _gated_send._aquaterra_original = original_send  # type: ignore[attr-defined]
    Emails.send = _gated_send  # type: ignore[assignment]
    setattr(Emails, _PATCH_MARKER, True)
    _LOG.info("[sdk_intercept] resend.Emails.send monkey-patched (gated)")
    return True
