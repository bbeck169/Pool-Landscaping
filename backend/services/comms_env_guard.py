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



# ═══════════════════════════════════════════════════════════════════
# SAFE-SEND-A · Feb-2026 — Context-based Comms Safety Gate
# ═══════════════════════════════════════════════════════════════════
# Layered ON TOP of the Phase 34 / K72 primitives above — different
# purpose, different primitives.  Phase 34 is an ``APP_ENV`` allowlist
# guard; SAFE-SEND-A is a ``context`` gate that redirects AI-generated
# and admin-test-mode comms to the tenant admin regardless of
# environment.  Both gates fire in every adapter (K72 first, then
# SAFE-SEND) — additive, not exclusive.
import enum as _sf_enum


class CommsContext(str, _sf_enum.Enum):
    """Explicit send-time provenance stamped by every
    ``send_email`` / ``send_sms`` call.

    Values are strings so admin surfaces render / log them
    directly (``str`` inheritance) and Pydantic can validate
    request bodies against the enum.
    """
    SYSTEM = "system"
    AGENT = "agent"
    TEST = "test"


class RedirectTargetMissing(RuntimeError):
    """Neither ``business_card.email/phone`` nor an admin-user
    contact is available on the tenant.  The adapter logs +
    skips the send rather than defaulting to customer's
    recipient — safer than accidental customer sends.
    """


@dataclass(frozen=True)
class RedirectTargets:
    """Resolved (email, phone) admin fallback destinations."""
    email: "str | None" = None
    phone: "str | None" = None


# One function, three inputs, no side effects.
def should_redirect_to_admin(context: CommsContext) -> bool:
    """``AGENT`` + ``TEST`` redirect. ``SYSTEM`` passes through.
    No other conditions."""
    return context in (CommsContext.AGENT, CommsContext.TEST)


async def get_redirect_targets(
    *,
    tenant_settings: "dict | None" = None,
    tenant_id: "str | None" = None,
    channel: str = "email",   # "email" | "sms"
    db=None,
) -> RedirectTargets:
    """Resolve the admin redirect target for a given channel.

    Priority chain:
      1. ``tenant_settings["business_card"][channel]`` verbatim.
      2. First ``users`` row with matching ``tenant_id`` and
         ``role in {admin, super_admin, super}`` — reads
         ``email`` or ``phone`` per channel.
      3. Otherwise: raise ``RedirectTargetMissing`` — the
         adapter treats this as "log + skip", never falls
         through to customer.

    ``channel`` gates WHICH field we read.  ``email`` mode
    only errors when no email is resolvable; ``sms`` mode
    only errors when no phone is resolvable.  Keeps unit tests
    from paying for a lookup they'll never use.
    """
    if channel not in ("email", "sms"):
        raise ValueError(f"unsupported channel: {channel}")

    card = ((tenant_settings or {}).get("business_card") or {})
    target_email = (card.get("email") or "").strip() or None
    target_phone = (card.get("phone") or "").strip() or None

    primary = target_email if channel == "email" else target_phone
    if primary:
        return RedirectTargets(email=target_email, phone=target_phone)

    # Fallback — admin user contact via ``users`` collection.
    if tenant_id and db is not None:
        try:
            admin_user = await db.users.find_one(
                {
                    "tenant_id": tenant_id,
                    "role": {"$in": ["admin", "super_admin", "super"]},
                },
                {"_id": 0, "email": 1, "phone": 1},
            )
        except Exception:  # noqa: BLE001 — best-effort
            admin_user = None
        if admin_user:
            fb = (admin_user.get(
                "email" if channel == "email" else "phone",
            ) or "").strip()
            if fb:
                if channel == "email":
                    return RedirectTargets(email=fb, phone=target_phone)
                return RedirectTargets(email=target_email, phone=fb)

    raise RedirectTargetMissing(
        f"no_redirect_target: tenant={tenant_id!r} "
        f"channel={channel!r} (business_card.{channel} empty "
        f"and no admin user contact)"
    )


# Client-side enforcement — request bodies may ONLY carry
# ``TEST``. ``SYSTEM`` and ``AGENT`` are set server-side by
# the codepath itself.  Prevents an authenticated user from
# spoofing a customer send via a hand-crafted request body.
_CLIENT_ALLOWED_CONTEXTS = frozenset({CommsContext.TEST})


class ClientContextNotAllowedError(ValueError):
    """Raised when a client request body attempts to supply
    ``context=SYSTEM`` or ``context=AGENT`` — only server-side
    codepaths may stamp those values.

    Carries ``error_code = "invalid_comms_context"`` for the
    ``server.py`` ``RequestValidationError`` handler to
    fingerprint + return HTTP 400 with the SAFE-SEND-A error
    envelope instead of Pydantic's default 422.  Subclasses
    ``ValueError`` so Pydantic's ``field_validator`` machinery
    accepts it cleanly.
    """

    error_code: str = "invalid_comms_context"

    def __init__(
        self,
        supplied: "CommsContext | str | None" = None,
        detail: "str | None" = None,
    ):
        # Normalize the offending value for the audit message.
        if isinstance(supplied, CommsContext):
            supplied_str = supplied.value
        else:
            supplied_str = str(supplied) if supplied is not None else "<missing>"
        self.supplied = supplied_str
        self.detail = detail or (
            "context=SYSTEM|AGENT is server-controlled and cannot "
            "be supplied by client requests"
        )
        super().__init__(
            f"client_context_not_allowed: {supplied_str!r} — {self.detail}"
        )


def assert_client_supplied_context_allowed(
    context: CommsContext,
) -> None:
    """Raise ``ClientContextNotAllowedError`` if a client tried
    to spoof ``SYSTEM`` or ``AGENT`` from a request body.  Wire
    into FastAPI request-model Pydantic validators.  The
    server-side handler maps this to HTTP 400 with the
    SAFE-SEND-A error envelope."""
    if context not in _CLIENT_ALLOWED_CONTEXTS:
        raise ClientContextNotAllowedError(supplied=context)


# ─── SAFE-SEND-A · Pydantic request-body mixin ──────────────────────
# Single source of truth for client-facing "context" enforcement.
# Any FastAPI request body that exposes a ``context`` field to
# clients MUST inherit from ``CommsSendRequestBase`` (or copy the
# validator verbatim) — never sprinkle ``if context == ...`` checks
# across individual routes.  The validator raises
# ``ClientContextNotAllowedError``; ``server.py`` maps that to a
# HTTP 400 with ``{"error_code": "invalid_comms_context", ...}``.
try:
    from pydantic import BaseModel as _SafeSendBaseModel, field_validator
except Exception:  # pragma: no cover — pydantic is a hard dep
    _SafeSendBaseModel = None  # type: ignore[assignment]
    field_validator = None  # type: ignore[assignment]


if _SafeSendBaseModel is not None and field_validator is not None:

    class CommsSendRequestBase(_SafeSendBaseModel):
        """Base model for any client-facing comms-send request body.

        Exposes an optional ``context`` field validated against the
        client-allow-list.  ``None`` is permitted — routes default
        server-side to whatever context is appropriate for the
        codepath.  ``TEST`` is the only client-supplied value that
        passes.  ``SYSTEM`` / ``AGENT`` from a client body raise
        ``ClientContextNotAllowedError`` at parse time.
        """

        context: "CommsContext | None" = None

        @field_validator("context", mode="after")
        @classmethod
        def _reject_privileged_client_contexts(
            cls, v: "CommsContext | None",
        ) -> "CommsContext | None":
            if v is None:
                return v
            assert_client_supplied_context_allowed(v)
            return v


def stamp_agent_context() -> CommsContext:
    """Return ``CommsContext.AGENT``.  Trivial by design — its
    real purpose is to give AI codepaths one grep-anchor so a
    future safety audit can confirm every AI-driven send
    flows through it."""
    return CommsContext.AGENT
