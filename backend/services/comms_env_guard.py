"""Phase 34 · Task L · Feb-2026 — Outbound comms safety guard.

Central helper that every email + SMS send-site consults BEFORE
actually hitting a third-party provider (Resend / RingCentral / any
future carrier).

Design goals
------------
* **Fail-safe default.** If the environment cannot be positively
  identified as ``production``, treat it as non-prod and DO NOT emit
  live traffic.
* **Allow-list opt-in.** Small comma-separated env vars let ops opt-in
  specific dev / staff addresses so QA can still smoke-test the live
  provider path when they need to. Everything else is dry-run.
* **Zero behavioural change in production.** When ``APP_ENV=production``
  the guard is a no-op — every existing send path continues to work
  identically.
* **Callers never crash.** The dry-run return matches the shape every
  adapter uses, so downstream code that persists provider status /
  attempts keeps working.

Usage
-----
::

    from services.comms_env_guard import guard_outbound

    verdict = guard_outbound(kind="email", to="user@example.com")
    if verdict.blocked:
        return verdict.dry_run_response(provider="resend")
    # ...real send...

    verdict = guard_outbound(kind="sms", to="+16025551234")
    if verdict.blocked:
        return verdict.dry_run_response(provider="ringcentral")

"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Set

from config import logger


def _app_env() -> str:
    return (os.environ.get("APP_ENV") or "preview").strip().lower()


def _split_env_list(name: str) -> Set[str]:
    raw = os.environ.get(name) or ""
    return {v.strip().lower() for v in raw.split(",") if v.strip()}


def _allowlist_emails() -> Set[str]:
    return _split_env_list("COMMS_TEST_ALLOWLIST_EMAILS")


def _allowlist_phones() -> Set[str]:
    """Phone numbers normalized to their digits only (last 10) so the
    check is tolerant to whether callers pass ``+16028874400`` or
    ``602-887-4400`` or ``(602) 887-4400``."""
    out: Set[str] = set()
    for v in _split_env_list("COMMS_TEST_ALLOWLIST_PHONES"):
        digits = "".join(ch for ch in v if ch.isdigit())
        if digits:
            out.add(digits[-10:])
    return out


def is_production() -> bool:
    return _app_env() == "production"


@dataclass(frozen=True)
class GuardVerdict:
    """Return value of :func:`guard_outbound`.

    Attributes
    ----------
    blocked:
        ``True`` when the send should be short-circuited to a dry-run
        response. ``False`` when the caller is free to hit the live
        provider.
    reason:
        Human-readable string, e.g. ``"preview_no_allowlist_match"``
        or ``"production_live"``. Never ``None`` — makes logs greppable.
    to:
        The normalized address the guard evaluated. Included in the
        dry-run response so callers don't have to re-thread it.
    kind:
        ``"email"`` or ``"sms"``.
    """
    blocked: bool
    reason: str
    to: str
    kind: str

    def dry_run_response(self, provider: str) -> Dict[str, Any]:
        """Return the standard adapter envelope for a blocked send.

        ``provider_status="dry_run"`` is a NEW status callers can key
        on if they want to distinguish "we intentionally did nothing"
        from "the provider actually accepted the message" (``"sent"``)
        or "the provider is not configured" (``"mocked"``).
        """
        return {
            "provider": provider,
            "provider_status": "dry_run",
            "provider_response_id": None,
            "attempts": 0,
            "error": None,
            "dry_run": True,
            "dry_run_reason": self.reason,
            "dry_run_to": self.to,
        }


def is_customer_email_kill_switch_on() -> bool:
    """Phase K72 · Feb-2026 — Emergency customer-email kill switch.

    Reads ``FEATURE_CUSTOMER_EMAIL_KILL_SWITCH`` from the environment
    (default OFF). When ON, ``guard_outbound`` short-circuits every
    ``audience="customer"`` send regardless of ``APP_ENV`` — the
    switch is a P0 safety break for incident-response, unrelated to
    the normal preview allow-list gate.

    Truthy values: ``on``, ``true``, ``1``, ``yes``. Anything else
    (including missing) reads as OFF.
    """
    val = (os.environ.get("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH") or "")\
        .strip().lower()
    return val in ("on", "true", "1", "yes")


def guard_outbound(*, kind: str, to: str,
                     audience: str = "customer") -> GuardVerdict:
    """Decide whether an outbound comms call may hit the live provider.

    Rules
    -----
    * **Phase K72 kill switch** — if
      ``FEATURE_CUSTOMER_EMAIL_KILL_SWITCH`` is ON AND
      ``audience="customer"``, the send is **always blocked**
      regardless of ``APP_ENV``. Internal / admin-facing sends
      (``audience="internal"``) pass through this check unchanged.
    * ``APP_ENV=production`` → **never** blocked (post-kill-switch).
    * Any other ``APP_ENV`` → blocked, unless the recipient matches
      the corresponding allow-list env var:
        - ``COMMS_TEST_ALLOWLIST_EMAILS`` for ``kind="email"``
        - ``COMMS_TEST_ALLOWLIST_PHONES`` for ``kind="sms"``
          (compared on last-10-digits after stripping non-digits).

    The function ALSO emits a single INFO-level log line per blocked
    send with a ``[DRY-RUN preview]`` prefix so it's obvious in the
    logs what would have gone out and to whom. The K72 kill-switch
    block emits a distinct WARN-level line prefixed with
    ``[K72 KILL-SWITCH]`` so ops can grep for it separately.
    """
    env = _app_env()
    normalized_to = (to or "").strip()
    normalized_audience = (audience or "customer").strip().lower()

    # Phase K72 · Feb-2026 — customer-facing outbound kill switch.
    # Fires BEFORE the production-live short-circuit so it works in
    # every environment during an incident.
    if (normalized_audience == "customer"
            and is_customer_email_kill_switch_on()):
        logger.warning(
            "[K72 KILL-SWITCH] customer_email_suppressed_kill_switch "
            "kind=%s to=%s env=%s audience=%s",
            kind, normalized_to, env, normalized_audience,
        )
        return GuardVerdict(
            blocked=True,
            reason="customer_email_suppressed_kill_switch",
            to=normalized_to,
            kind=kind,
        )

    if env == "production":
        return GuardVerdict(blocked=False, reason="production_live",
                             to=normalized_to, kind=kind)

    if kind == "email":
        allow = _allowlist_emails()
        if normalized_to.lower() in allow:
            return GuardVerdict(blocked=False, reason=f"{env}_allowlist_email",
                                 to=normalized_to, kind=kind)
    elif kind == "sms":
        digits = "".join(ch for ch in normalized_to if ch.isdigit())
        last10 = digits[-10:] if digits else ""
        if last10 and last10 in _allowlist_phones():
            return GuardVerdict(blocked=False, reason=f"{env}_allowlist_sms",
                                 to=normalized_to, kind=kind)
    else:
        # Unknown kind — be conservative and block.
        pass

    logger.info(
        "[DRY-RUN %s] blocked outbound %s to=%s (add to COMMS_TEST_ALLOWLIST_%s to opt-in)",
        env, kind, normalized_to, "EMAILS" if kind == "email" else "PHONES",
    )
    return GuardVerdict(
        blocked=True,
        reason=f"{env}_no_allowlist_match",
        to=normalized_to,
        kind=kind,
    )


def startup_banner() -> str:
    """One-line summary logged at backend boot so it's immediately
    obvious whether the current process is live or dry-run."""
    global _LAST_STARTUP_BANNER_ISO
    env = _app_env()
    ae = len(_allowlist_emails())
    ap = len(_allowlist_phones())
    mode = "LIVE" if env == "production" else "DRY-RUN"
    from datetime import datetime, timezone
    _LAST_STARTUP_BANNER_ISO = datetime.now(timezone.utc).isoformat()
    return f"[COMMS] mode={mode} env={env} allowlist_emails={ae} allowlist_phones={ap}"


# Feb-2026 P0 · timestamp of the most recent ``startup_banner()``
# call. Read by the ``/api/settings/integrations/health/comms``
# admin endpoint so ops can confirm the running process actually
# booted after the last env change. ``None`` until first banner
# emit; ISO 8601 UTC string thereafter.
_LAST_STARTUP_BANNER_ISO: "str | None" = None


def last_startup_banner_iso() -> "str | None":
    return _LAST_STARTUP_BANNER_ISO
