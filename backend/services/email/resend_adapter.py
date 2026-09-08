"""Feb 2026 · Slice N — Resend email adapter (real send).

Single async entry point (:func:`send`) shared by every marketing +
transactional email path in the app.  Adds four things the older
``services/comms_email_adapter`` never had:

1. **Category-aware suppression** — pre-check against
   ``marketing_suppressions`` via
   :func:`routers.marketing_preferences.is_suppressed`.  Callers with
   ``category="transactional"`` skip the check entirely (invoices,
   receipts, admin escalations must always reach the recipient).
2. **Non-blocking send** — the Resend SDK is sync; we wrap in
   ``asyncio.to_thread`` so the event loop stays free.
3. **Retry with exponential backoff** — up to 3 attempts on 429 /
   5xx.  Permanent 4xx errors (bad request / no verified domain)
   fail fast, no retry.
4. **Idempotency-key header** — surface for callers that need to
   defend against double-sends across retries.

The adapter also feeds back a standardised delivery record so
callers can persist it into ``marketing_deliveries``:

.. code-block:: python

    {
        "provider": "resend" | "mock",
        "provider_status": "sent" | "suppressed" | "failed" | "mocked",
        "provider_response_id": str | None,   # Resend's email id
        "attempts": int,
        "error": str | None,
    }
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from config import logger

# Known Resend error codes / status codes for retry classification.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3

# Phase 34 · Task M — belt-and-braces regex used to catch any
# ``{{TAG}}`` markers that make it past the earlier renderer stages.
_LEFTOVER_TAG_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")


def _scrub_leftover_tags(subject: str, html: str) -> Tuple[str, str, List[str]]:
    """Final-scrub pass right before we hand a payload to Resend.

    Runs the canonical merge-tag renderer once more with an empty
    context — any tag whose resolver can produce a value from an
    empty context (currently none) would substitute; everything else
    is deliberately replaced with an empty string. Then a defensive
    regex strips ANY leftover ``{{...}}`` markers so mis-typed /
    unknown tags cannot leak literal to a real inbox.

    Returns ``(safe_subject, safe_html, [stripped_token_names])``.
    """
    stripped: List[str] = []
    try:
        # Local import — avoids a circular dep at module load and lets
        # test suites monkey-patch the renderer if they need to.
        from services.marketing.merge_tags import render_template as _rt

        s_rendered, s_missing = _rt(subject or "", {}, missing="empty")
        h_rendered, h_missing = _rt(html or "", {}, missing="empty")
    except Exception:  # pragma: no cover — renderer must never crash send
        s_rendered, h_rendered = subject or "", html or ""
        s_missing, h_missing = [], []

    # Defensive strip in case the renderer's token grammar doesn't
    # catch something (e.g. a tag with spaces, hyphens, or a raw
    # backtick — anything the strict regex rejects).
    def _strip(x: str) -> str:
        def _sub(m: "re.Match[str]") -> str:
            stripped.append(m.group(1))
            return ""
        return _LEFTOVER_TAG_RE.sub(_sub, x or "")

    safe_subject = _strip(s_rendered)
    safe_html = _strip(h_rendered)
    # Include the renderer's declared missing tokens for accurate logs.
    all_missing: List[str] = sorted(set(list(s_missing) + list(h_missing) + stripped))
    return safe_subject, safe_html, all_missing


class ResendEmailAdapter:
    """Stateless adapter — construct once (or per-call, both are safe).

    ``enabled`` is derived from the environment at construction time;
    tests that hot-swap ``RESEND_API_KEY`` should re-instantiate the
    adapter to observe the new state.
    """

    def __init__(self) -> None:
        api_key = os.environ.get("RESEND_API_KEY", "")
        self.enabled = bool(api_key) and not api_key.startswith("re_placeholder")
        self._api_key = api_key if self.enabled else None
        self.from_addr = os.environ.get(
            "RESEND_FROM_ADDRESS",
            os.environ.get("EMAIL_FROM", "onboarding@resend.dev"),
        ).strip('"').strip("'")
        self.from_name = os.environ.get(
            "RESEND_FROM_NAME", "Pool & Landscaping of Vistancia",
        ).strip('"').strip("'")
        # Phase 21 · Feb 2026 — comma-separated list of Resend-verified
        # sender domains. Used to decide whether a tenant-overridden
        # ``from_email`` can be used or must fall back to the app default.
        # Always include resend.dev (the sandbox sender) so the mocked
        # onboarding address never trips the check.
        raw = os.environ.get("RESEND_VERIFIED_DOMAINS", "resend.dev").strip()
        self.verified_domains = {
            d.strip().lower() for d in raw.split(",") if d.strip()
        }
        logger.info(
            "[resend] verified domains: %s",
            ", ".join(sorted(self.verified_domains)) or "(none)",
        )

    # ── Suppression ────────────────────────────────────────────────
    async def _suppressed(
        self,
        *,
        tenant_id: Optional[str],
        to: str,
        category: str,
    ) -> bool:
        """Consult the Slice F suppression list.  Marketing categories
        respect the list; ``transactional`` never does."""
        if category == "transactional" or not tenant_id or not to:
            return False
        try:
            from routers.marketing_preferences import is_suppressed
        except Exception as exc:  # pragma: no cover
            logger.warning("[resend] is_suppressed import failed: %s", exc)
            return False
        # is_suppressed expects a customer-ish dict; we synthesise one
        # from the address so bare-string callers (H1 form submit,
        # widget escalation) can still be filtered by the same rules.
        try:
            return await is_suppressed(
                tenant_id, {"email": to},
                channel="email", category=category,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[resend] is_suppressed failed: %s", exc)
            return False

    # ── Send ───────────────────────────────────────────────────────
    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        category: str = "marketing",
        idempotency_key: Optional[str] = None,
        tenant_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
        from_name: Optional[str] = None,
        from_email: Optional[str] = None,
        allow_off_allowlist: bool = False,
        audience: str = "customer",
    ) -> Dict[str, Any]:
        """Send an email through Resend.  Never raises; every failure
        path yields a status string the caller can persist verbatim.

        Phase 21 · Feb 2026 — ``from_name`` / ``from_email`` are
        optional per-call overrides (typically resolved from
        ``tenant.settings.email_sender``). When the override's domain
        is NOT in ``RESEND_VERIFIED_DOMAINS`` we log a WARNING and
        fall back to the environment default so delivery is not
        blocked while DNS verification is still pending.

        Phase K30 · Feb-2026 — ``allow_off_allowlist`` (default False)
        lets **admin-triggered** transactional sends bypass BOTH the
        ``is_comm_allowed`` demo-account gate AND the
        ``COMMS_TEST_ALLOWLIST_EMAILS`` env-guard so the message
        actually leaves the preview environment. Only call-sites that
        are guarded by ``require_admin`` (or equivalent server-side
        auth) should set this to True — never propagate from a
        user-controlled request body.

        Phase K72 · Feb-2026 — ``audience`` (default ``"customer"``)
        marks whether the RECIPIENT is a customer or an internal
        admin/staff/system user. When
        ``FEATURE_CUSTOMER_EMAIL_KILL_SWITCH`` is ON, any send with
        ``audience="customer"`` is short-circuited to a dry-run
        (``comms_env_guard.guard_outbound`` enforces this before
        ``APP_ENV`` is consulted). Internal senders (K63 lead
        notifications, K30 password reset, staff invites, super-admin
        alerts, admin digests) pass ``audience="internal"`` to
        bypass the kill switch. Default is ``"customer"`` — safe:
        an unaudited caller stays blocked when the switch is on.
        """
        addr = (to or "").strip()
        if not addr:
            return {"provider": "resend", "provider_status": "failed",
                    "provider_response_id": None, "attempts": 0,
                    "error": "empty recipient"}

        # 1. Suppression pre-check (marketing only).
        if await self._suppressed(tenant_id=tenant_id, to=addr.lower(),
                                    category=category):
            return {"provider": "resend", "provider_status": "suppressed",
                    "provider_response_id": None, "attempts": 0,
                    "error": None}

        # Feb-2026 · Comms whitelist gate (P0 safety directive).
        # Only recipients flagged ``is_demo_account=True`` may receive
        # comms; everyone else silently no-ops with a
        # ``comms_suppression_log`` row. Fail-closed on any error.
        # Phase K30 · Feb-2026 — admin-triggered sends (with
        # ``allow_off_allowlist=True``) bypass the gate. Log a WARN so
        # the bypass is greppable in the audit stream — this must
        # never fire from a user-controlled path.
        if allow_off_allowlist:
            logger.warning(
                "[resend] allow_off_allowlist=True — bypassing is_comm_allowed gate "
                "to=%s cat=%s tenant=%s customer_id=%s",
                addr, category, tenant_id, customer_id,
            )
        else:
            try:
                from services.comms.gate import is_comm_allowed
                allowed = await is_comm_allowed(
                    recipient_identifier={
                        "customer_id": customer_id,
                        "email": addr,
                    },
                    comm_type="email",
                    tenant_id=tenant_id,
                    provider="resend",
                    trigger_action=category,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[resend] gate errored — failing closed: %s", exc)
                allowed = False
            if not allowed:
                return {"provider": "resend",
                        "provider_status": "suppressed_not_demo",
                        "provider_response_id": None, "attempts": 0,
                        "error": None}

        # Phase 34 · Task L · Feb-2026 — outbound safety guard.
        # When ``APP_ENV != production`` (or when the recipient is not
        # explicitly allow-listed via ``COMMS_TEST_ALLOWLIST_EMAILS``),
        # short-circuit to a dry-run response so we never accidentally
        # email a real customer from preview / dev / staging. The
        # returned envelope keeps ``provider_status="dry_run"`` distinct
        # from ``"mocked"`` (no API key) and ``"sent"`` (live delivery).
        # Phase K30 · Feb-2026 — admin-triggered sends bypass this
        # guard too. WARN log emitted so we can audit every bypass.
        # Phase K72 · Feb-2026 — the customer-email kill switch is
        # enforced BEFORE the allow_off_allowlist bypass so an admin-
        # triggered customer-facing send (invoice email, etc.) is
        # still suppressed when the flag is ON.
        from services.comms_env_guard import (
            guard_outbound as _k72_guard,
            is_customer_email_kill_switch_on as _k72_flag_on,
        )
        if (audience == "customer") and _k72_flag_on():
            verdict = _k72_guard(kind="email", to=addr,
                                    audience=audience)
            # guard_outbound returns blocked here by construction.
            logger.warning(
                "[K72 KILL-SWITCH] resend send SUPPRESSED to=%s "
                "subject=%r cat=%s tenant=%s (allow_off_allowlist=%s)",
                addr, subject, category, tenant_id, allow_off_allowlist,
            )
            return verdict.dry_run_response(provider="resend")
        if allow_off_allowlist:
            logger.warning(
                "[resend] allow_off_allowlist=True — bypassing guard_outbound "
                "env allowlist to=%s cat=%s tenant=%s",
                addr, category, tenant_id,
            )
        else:
            from services.comms_env_guard import guard_outbound
            verdict = guard_outbound(kind="email", to=addr, audience=audience)
            if verdict.blocked:
                logger.info(
                    "[DRY-RUN] resend send SKIPPED to=%s subject=%r cat=%s tenant=%s reason=%s",
                    addr, subject, category, tenant_id, verdict.reason,
                )
                return verdict.dry_run_response(provider="resend")

        # Phase I1.7.e · chunk 1 · Feb-2026 — tenant-BYO first hop.
        # If the tenant has a BYO email provider configured, route
        # the send through it. Cap-exceeded (HTTP 429) responses are
        # normalized so a transactional caller can translate to
        # HTTPException(429) and a bulk caller can log
        # ``skipped_cap_exceeded`` in its ledger. Falls through to
        # the direct Resend SDK path below when no tenant provider
        # is configured. Runs AFTER the gate / kill-switch / dry-run
        # guard so a BYO provider cannot bypass any of those.
        try:
            from services.messaging.byo_passthrough import (
                try_dispatch_email_tenant_byo,
            )
            _byo = await try_dispatch_email_tenant_byo(
                tenant_id=tenant_id, to=addr, subject=subject,
                html=html, text=text, from_addr=from_email,
                from_name=from_name, reply_to=reply_to,
            )
        except Exception as _byo_exc:  # noqa: BLE001
            logger.warning(
                "[resend] BYO probe raised — falling through: %s", _byo_exc,
            )
            _byo = None
        if _byo is not None:
            return _byo

        # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit
        # for the platform (non-BYO) path. Runs AFTER every pre-flight
        # gate (suppression, is_comm_allowed, K72 kill-switch,
        # guard_outbound, BYO probe) so all safeties still fire; only
        # the raw Resend SDK call in the retry loop below is skipped.
        from services.messaging.testmode import (
            is_messaging_testmode as _tm_on,
            mock_email_envelope as _tm_email,
        )
        if _tm_on():
            _env = _tm_email(
                tenant_id=tenant_id, to=addr, subject=subject,
                routed_via="platform_testmode_mock",
            )
            # Modern adapter shape — map legacy keys to modern names
            # so the adapter's contract (provider / provider_status /
            # provider_response_id) is preserved.
            return {
                "provider": _env.get("provider") or "mock",
                "provider_status": _env["provider_status"],
                "provider_response_id": _env["provider_response_id"],
                "attempts": 1,
                "error": None,
                "routed_via": _env["routed_via"],
            }

        # 2. Graceful mocked mode — no API key set. Log + return.
        if not self.enabled:
            logger.info(
                "[resend] disabled — would have sent to %s subj=%r cat=%s",
                addr, subject, category,
            )
            return {"provider": "mock", "provider_status": "mocked",
                    "provider_response_id": None, "attempts": 0,
                    "error": None}

        # Phase 21 — resolve sender identity with verified-domain
        # fallback. Overrides are honored only when their domain is
        # verified; otherwise fall back and log a WARNING (once per
        # send is acceptable — a re-verified domain flip is rare).
        eff_from_email = from_email or self.from_addr
        eff_from_name = from_name or self.from_name
        if from_email and not self._is_verified(from_email):
            logger.warning(
                "[resend] %r not verified — falling back to %r for tenant=%s",
                from_email, self.from_addr, tenant_id,
            )
            eff_from_email = self.from_addr
            # Keep the tenant name in the From line for brand fidelity
            # even when the address falls back — Resend allows any
            # display name.
            eff_from_name = from_name or self.from_name

        # 3. Build params — resend expects a plain dict, sync SDK.
        # Phase 34 · Task M · Feb-2026 — belt-and-braces final scrub.
        # Even though every registered send path in the codebase runs
        # merge-tag rendering before we get here, a single missed
        # code path used to leak literal ``{{TAG}}`` markers into a
        # customer's inbox. This safety net looks at the SUBJECT +
        # HTML about to leave the process and:
        #   1. Runs one final render pass with an empty ctx so any
        #      tag that has a catalog resolver keying off ``ctx`` will
        #      still return "" (never leave the raw marker).
        #   2. Aggressively strips ANY remaining ``{{...}}`` markers
        #      (unknown / typo tags) so they cannot reach a real
        #      recipient.
        #   3. Logs a WARN listing the stripped tokens so the source
        #      template can be corrected.
        safe_subject, safe_html, stripped = _scrub_leftover_tags(
            subject or "", html or ""
        )
        if stripped:
            logger.warning(
                "[resend] final-scrub stripped %s leftover tag(s) from "
                "email to %s tenant=%s subj=%r tags=%s",
                len(stripped), addr, tenant_id, safe_subject[:60], stripped,
            )
        params: Dict[str, Any] = {
            "from": f"{eff_from_name} <{eff_from_email}>",
            "to": [addr],
            "subject": safe_subject,
            "html": safe_html,
        }
        if text:
            params["text"] = text
        if reply_to:
            params["reply_to"] = reply_to
        if idempotency_key:
            params.setdefault("headers", {})["Idempotency-Key"] = idempotency_key

        # 4. Retry loop with exponential backoff for transient failures.
        last_err = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                import resend  # local import so tests can monkeypatch
                resend.api_key = self._api_key
                result = await asyncio.to_thread(resend.Emails.send, params)
                rid = None
                if isinstance(result, dict):
                    rid = result.get("id") or (result.get("data") or {}).get("id")
                return {"provider": "resend", "provider_status": "sent",
                        "provider_response_id": rid, "attempts": attempt,
                        "error": None}
            except Exception as exc:  # pragma: no cover — network path
                last_err = exc
                code = _extract_status(exc)
                logger.warning(
                    "[resend] attempt %s/%s to %s failed status=%s err=%s",
                    attempt, _MAX_ATTEMPTS, addr, code, exc,
                )
                if code not in _TRANSIENT_STATUS or attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s

        return {"provider": "resend", "provider_status": "failed",
                "provider_response_id": None,
                "attempts": _MAX_ATTEMPTS if last_err else 1,
                "error": f"{type(last_err).__name__}: {last_err}"
                if last_err else "unknown"}


def _extract_status(exc: Any) -> Optional[int]:
    """Best-effort extraction of the HTTP status code from a Resend
    SDK exception.  The SDK exposes ``.status_code`` on most error
    classes; some transport errors bubble up as ``requests`` errors
    with ``.response.status_code``."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    resp = getattr(exc, "response", None)
    if resp is not None:
        rc = getattr(resp, "status_code", None)
        if isinstance(rc, int):
            return rc
    return None


# Phase 21 · Feb 2026 — verified-domain check attached to
# ResendEmailAdapter so ``send()`` can consult it via ``self.``.
def _adapter_is_verified(self: "ResendEmailAdapter", addr: str) -> bool:
    """True when the from-address's domain is in
    ``RESEND_VERIFIED_DOMAINS``. Never raises — malformed addresses
    are treated as unverified so they trigger the fallback path."""
    if not addr or "@" not in addr:
        return False
    domain = addr.rsplit("@", 1)[1].strip().lower()
    return domain in self.verified_domains


ResendEmailAdapter._is_verified = _adapter_is_verified  # type: ignore[attr-defined]


async def resolve_email_sender_for_tenant(tenant: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Phase 21 — read the per-tenant transactional sender identity.

    Returns ``{from_name, from_email, reply_to}`` — each may be
    ``None`` when the tenant hasn't opted into an override, in which
    case the adapter's env defaults apply.
    """
    settings = ((tenant or {}).get("settings") or {})
    sender = settings.get("email_sender") or {}
    return {
        "from_name": sender.get("from_name"),
        "from_email": sender.get("from_email"),
        "reply_to": sender.get("reply_to"),
    }


# Module-level singleton — every callsite gets the same instance so
# a single process-wide restart picks up ``.env`` changes.  Tests
# needing a fresh adapter can just call ``ResendEmailAdapter()``.
_default = ResendEmailAdapter()


async def send(**kwargs) -> Dict[str, Any]:
    """Thin module-level entry point delegating to the singleton."""
    return await _default.send(**kwargs)
