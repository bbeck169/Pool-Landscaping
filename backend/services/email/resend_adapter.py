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
from typing import Any, Dict, Optional

from config import logger

# Known Resend error codes / status codes for retry classification.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


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
    ) -> Dict[str, Any]:
        """Send an email through Resend.  Never raises; every failure
        path yields a status string the caller can persist verbatim.

        Phase 21 · Feb 2026 — ``from_name`` / ``from_email`` are
        optional per-call overrides (typically resolved from
        ``tenant.settings.email_sender``). When the override's domain
        is NOT in ``RESEND_VERIFIED_DOMAINS`` we log a WARNING and
        fall back to the environment default so delivery is not
        blocked while DNS verification is still pending.
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
        params: Dict[str, Any] = {
            "from": f"{eff_from_name} <{eff_from_email}>",
            "to": [addr],
            "subject": subject or "",
            "html": html or "",
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
