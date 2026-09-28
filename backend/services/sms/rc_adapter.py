"""Phase 7B · Feb 2026 — RingCentral SMS adapter.

Drop-in replacement for the retired ``services/sms/twilio_adapter.py``.
Mirrors the same signature, return envelope, suppression semantics, and
compliance suffix rules — the ONLY differences are:

* ``provider`` field is now ``"ringcentral"`` (or ``"mock"`` when the
  RC client is not configured for this environment).
* ``provider_response_id`` is the RC message id (an integer stringified
  for compatibility with the previous ``str`` shape) — NOT a Twilio
  SM-prefixed SID.
* Retries look at RC's own transient statuses; the underlying
  ``RingCentralService`` client already handles 429 with Retry-After +
  401 token refresh internally, so the retry loop here focuses on
  network / transport transients (5xx, connection reset).

Suppression, STOP-suffix, phone normalization, and the graceful
``mocked`` mode when the provider isn't wired are IDENTICAL to the
old Twilio adapter — every existing caller / test that keyed on those
behaviors continues to pass. See ``tests/test_phase7b_rc_sms_adapter.py``
for the pinned invariants.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, Optional, TYPE_CHECKING

import httpx

from config import logger
from services.ringcentral.rc_client import RingCentralError, RingCentralService

if TYPE_CHECKING:
    from services.comms_env_guard import CommsContext

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3

# RC accepts up to 1000 characters per SMS body; use the same 1600 cap
# the Twilio adapter used so long-form messages keep the same behavior
# (client-side trim). Anything over 1000 will be rejected by RC but
# we trim to 1600 to preserve callers that may still send that long.
_BODY_HARD_CAP = 1600

_STOP_REQUIRED_CATEGORIES = {"marketing", "drip", "campaign"}
_STOP_SUFFIX = "\nReply STOP to unsubscribe."


def normalize_phone_e164(raw: Optional[str],
                          default_country: str = "1") -> Optional[str]:
    """Coerce human phone formats to E.164. Preserved verbatim from the
    Twilio adapter so callers keep the same behavior."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("+"):
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) < 10:
            return None
        return "+" + digits
    digits = re.sub(r"[^\d]", "", s)
    if len(digits) == 10:
        return f"+{default_country}{digits}"
    if len(digits) == 11:
        return f"+{digits}"
    if len(digits) < 10:
        return None
    return f"+{digits}"


def _ensure_stop_suffix(body: str, category: str) -> str:
    if category not in _STOP_REQUIRED_CATEGORIES:
        return body
    if "stop" in body.lower():
        return body
    remaining = _BODY_HARD_CAP - len(_STOP_SUFFIX)
    if len(body) > remaining:
        body = body[:remaining].rstrip()
    return body + _STOP_SUFFIX


class RingCentralSMSAdapter:
    """Stateless-ish adapter. Re-instantiating picks up ``.env`` env
    changes; the module-level singleton is stable per-process."""

    def __init__(self) -> None:
        self.default_from = os.environ.get("RC_SMS_DEFAULT_FROM", "")
        self.rc_client_id = os.environ.get("RC_CLIENT_ID", "")
        self.rc_jwt = os.environ.get("RC_JWT", "")
        self.rc_server = os.environ.get("RC_SERVER_URL", "")
        # Enabled when the RC client has enough config to open a JWT
        # bearer session. When any core env is missing we degrade to
        # ``mocked`` so unit tests + local dev keep working.
        self.enabled = bool(
            self.rc_client_id and self.rc_jwt and self.rc_server
        )

    async def _suppressed(self, *, tenant_id: Optional[str],
                            to_e164: str, category: str) -> bool:
        if category == "transactional" or not tenant_id or not to_e164:
            return False
        try:
            # Lazy import to break circular dep with utils.py which
            # imports send() from this module.  # noqa: E402
            from routers.marketing_preferences import is_suppressed
        except Exception as exc:  # pragma: no cover
            logger.warning("[rc-sms] is_suppressed import failed: %s", exc)
            return False
        try:
            return await is_suppressed(
                tenant_id, {"phone": to_e164},
                channel="sms", category=category,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[rc-sms] is_suppressed failed: %s", exc)
            return False

    async def _resolve_from(self, tenant_id: Optional[str]) -> Optional[str]:
        """Priority: tenant.rc_sms_from_number → env RC_SMS_DEFAULT_FROM
        → RC extension auto-lookup. Return ``None`` only when nothing is
        resolvable (RC client will raise inside send_sms in that case)."""
        if tenant_id:
            try:
                from config import db
                t = await db.tenants.find_one(
                    {"id": tenant_id},
                    {"_id": 0, "rc_sms_from_number": 1},
                )
                if t and t.get("rc_sms_from_number"):
                    return t["rc_sms_from_number"]
            except Exception as exc:  # pragma: no cover
                logger.warning("[rc-sms] tenant from lookup failed: %s", exc)
        if self.default_from:
            return self.default_from
        return None  # RC client will auto-resolve via phone-number list

    async def send(self, *, to: str, body: str,
                    category: str = "marketing",
                    idempotency_key: Optional[str] = None,
                    tenant_id: Optional[str] = None,
                    customer_id: Optional[str] = None,
                    audience: str = "customer",
                    # SAFE-SEND-C · Feb-2026 — accept optional
                    # CommsContext so callers can opt into the
                    # redirect gate.  ``None`` defaults to
                    # ``SYSTEM`` (production transactional).  Callers
                    # who need AGENT/TEST semantics — marketing
                    # test-send, AI-drafted sends — pass the value
                    # explicitly.  See
                    # ``services.comms_env_guard.CommsContext``.
                    context: Optional["CommsContext"] = None,
                    ) -> Dict[str, Any]:
        """Send an SMS via RingCentral. Never raises.

        P0 Fix 2b · Feb 2026 — when ``idempotency_key`` is provided the
        adapter consults ``db.sms_idempotency`` for a prior successful
        send with the same ``(tenant_id, idempotency_key)`` pair.  If
        one exists we return its cached envelope instead of hitting
        RC again — protecting against scheduler retry, worker
        crash-restart, and any other caller re-issue.  A fresh send
        upserts the record with the returned RC message id so future
        retries hit the cache.

        Phase K72 · Feb-2026 — ``audience`` (default ``"customer"``)
        marks whether the RECIPIENT is a customer or an internal
        admin/staff/system user. Consulted by
        ``comms_env_guard.guard_outbound`` — the customer-email
        kill-switch flag suppresses SMS just like it does email so
        the tenant's outbound comms stream is fully paused during
        an incident. Internal / admin SMS (staff alerts, on-call
        pager, etc.) pass ``audience="internal"`` to bypass.

        SAFE-SEND-C · Feb-2026 — ``context`` (optional
        ``CommsContext``, default ``SYSTEM``) enables the redirect
        gate.  When ``AGENT`` or ``TEST``, the recipient is rewritten
        to the tenant's admin sandbox target BEFORE any suppression /
        consent / cap gate fires; a ``[MARCO TEST]`` prefix is added
        to the body; ``audience`` is forced to ``"internal"`` so the
        K72 customer kill-switch doesn't suppress the visibility copy;
        every return envelope carries the six SAFE-SEND fields
        (``redirected``, ``safe_send_context``,
        ``intended_recipient_redacted``, ``actual_recipient_redacted``,
        ``provider_status``, ``was_mock``).  On
        ``RedirectTargetMissing`` the send is SUPPRESSED with
        ``provider_status="skipped_no_redirect_target"``.
        """
        addr_e164 = normalize_phone_e164(to)
        if not addr_e164:
            return {"provider": "ringcentral", "provider_status": "failed",
                    "provider_response_id": None, "attempts": 0,
                    "error": "invalid_phone"}

        # ═══ SAFE-SEND-C · Feb-2026 — redirect preflight ═════════════
        # Resolve the effective ``CommsContext`` — default ``SYSTEM``
        # for legacy callers who don't pass one.  If the context is
        # ``AGENT`` or ``TEST``, resolve the tenant's redirect target
        # (business_card.phone → admin-user fallback), rewrite
        # ``addr_e164`` + prepend ``[MARCO TEST]`` on the body, and
        # force ``audience="internal"`` so K72 doesn't suppress the
        # visibility copy.  Idempotency, consent, gate, kill-switch,
        # BYO probe, testmode, and mocked-mode all re-evaluate against
        # the redirected number below — which is what we want.
        #
        # On ``RedirectTargetMissing`` the send is SUPPRESSED
        # (never falls through to the customer) and the response
        # envelope carries ``skipped_no_redirect_target`` plus the
        # SAFE-SEND audit-metadata fields.
        from services.comms_env_guard import (
            CommsContext as _SafeCtx,
            RedirectTargetMissing as _SafeRedirMissing,
            get_redirect_targets as _safe_get_targets,
            should_redirect_to_admin as _safe_should_redir,
        )
        from services.comms_send_log import _redact as _safe_redact
        _safe_ctx = context if context is not None else _SafeCtx.SYSTEM
        _safe_original_to = addr_e164
        _safe_redirected = False
        if _safe_should_redir(_safe_ctx):
            try:
                from config import db as _safe_db
                _tenant_doc = None
                if tenant_id:
                    _tenant_doc = await _safe_db.tenants.find_one(
                        {"id": tenant_id}, {"_id": 0, "settings": 1},
                    )
                _tenant_settings = (
                    (_tenant_doc or {}).get("settings") or {}
                )
                _targets = await _safe_get_targets(
                    tenant_settings=_tenant_settings,
                    tenant_id=tenant_id, channel="sms", db=_safe_db,
                )
            except _SafeRedirMissing as _rex:
                logger.warning(
                    "[safe-send-c] rc-sms redirect target missing "
                    "context=%s tenant=%s original_to=%s err=%s — "
                    "SUPPRESSING send",
                    _safe_ctx.value, tenant_id, _safe_original_to, _rex,
                )
                return {
                    "provider": "ringcentral",
                    "provider_status": "skipped_no_redirect_target",
                    "provider_response_id": None,
                    "attempts": 0,
                    "error": str(_rex),
                    "redirected": True,
                    "safe_send_context": _safe_ctx.value,
                    "intended_recipient_redacted": _safe_redact(
                        _safe_original_to,
                    ),
                    "actual_recipient_redacted": None,
                    "original_to": _safe_original_to,
                }
            addr_e164 = _targets.phone or addr_e164
            body = f"[MARCO TEST] {body or ''}".strip()
            _safe_redirected = True
            # A redirected send is delivered to an internal admin.
            # Override ``audience`` locally so the K72 customer-comms
            # kill-switch + ``guard_outbound`` treat it as internal —
            # otherwise an incident would silently drop AGENT/TEST
            # visibility copies too.
            audience = "internal"
            logger.info(
                "[safe-send-c] rc-sms redirected context=%s tenant=%s "
                "original_to=%s redirected_to=%s",
                _safe_ctx.value, tenant_id, _safe_original_to, addr_e164,
            )

        # SAFE-SEND-C · Feb-2026 — envelope enrichment closure.  Every
        # return path below runs through ``_safe_env`` so the response
        # dict carries the six SAFE-SEND audit fields.  Adds keys —
        # never removes / renames — so legacy callers that only read
        # ``provider_status`` see zero change.
        def _safe_env(env: Dict[str, Any]) -> Dict[str, Any]:
            env.setdefault("redirected", _safe_redirected)
            env.setdefault("safe_send_context", _safe_ctx.value)
            env.setdefault(
                "intended_recipient_redacted",
                _safe_redact(_safe_original_to),
            )
            env.setdefault(
                "actual_recipient_redacted", _safe_redact(addr_e164),
            )
            return env

        # 0. Idempotency cache — return cached envelope on repeat.
        _terminal_ok = {"sent", "queued", "delivered", "mocked", "dry_run"}
        _idem_key = str(idempotency_key) if idempotency_key else ""
        if _idem_key and tenant_id:
            try:
                from config import db as _db
                await _ensure_sms_idempotency_index()
                cached = await _db.sms_idempotency.find_one(
                    {"tenant_id": tenant_id, "idempotency_key": _idem_key},
                    {"_id": 0, "envelope": 1},
                )
                if cached and cached.get("envelope"):
                    env = dict(cached["envelope"])
                    env["idempotent_replay"] = True
                    logger.info(
                        "[rc-sms] idempotency cache hit tenant=%s key=%s",
                        tenant_id, _idem_key,
                    )
                    return _safe_env(env)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "[rc-sms] idempotency lookup failed — continuing: %s", exc,
                )

        # 1. Suppression check (marketing only).
        if await self._suppressed(tenant_id=tenant_id, to_e164=addr_e164,
                                    category=category):
            return _safe_env({"provider": "ringcentral",
                              "provider_status": "suppressed",
                              "provider_response_id": None,
                              "attempts": 0, "error": None})

        # K31 · Feb-2026 — Affirmative-consent gate. Opt-IN per tenant
        # (``tenants.sms_consent_gate_enabled``). When the flag is off
        # (default) this is a no-op; when on, blocks outbound SMS to
        # customers without an ``sms_consent_captured_at`` timestamp
        # and without a prior successful outbound (grandfather).
        try:
            from services.comms.consent_gate import has_sms_consent
            _consent_ok = await has_sms_consent(
                tenant_id, customer_id, category=category,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rc-sms] consent gate errored — allowing: %s", exc)
            _consent_ok = True
        if not _consent_ok:
            env = {"provider": "ringcentral",
                    "provider_status": "no_consent",
                    "provider_response_id": None, "attempts": 0,
                    "error": None}
            await _cache_sms_envelope(tenant_id, _idem_key, env)
            return _safe_env(env)

        # Feb-2026 · Comms whitelist gate (P0 safety directive).
        try:
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier={
                    "customer_id": customer_id,
                    "phone": addr_e164,
                },
                comm_type="sms",
                tenant_id=tenant_id,
                provider="ringcentral",
                trigger_action=category,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rc-sms] gate errored — failing closed: %s", exc)
            allowed = False
        if not allowed:
            return _safe_env({"provider": "ringcentral",
                              "provider_status": "suppressed_not_demo",
                              "provider_response_id": None,
                              "attempts": 0, "error": None})

        # Phase 34 · Task L · Feb-2026 — outbound safety guard.
        # ``APP_ENV != production`` (or non-allow-listed number) blocks
        # the send. Prevents preview / dev / staging from firing SMS
        # at real customer phone numbers.
        from services.comms_env_guard import guard_outbound
        verdict = guard_outbound(kind="sms", to=addr_e164, audience=audience)
        if verdict.blocked:
            logger.info(
                "[DRY-RUN] rc-sms send SKIPPED to=%s cat=%s len=%d tenant=%s",
                addr_e164, category, len(body or ""), tenant_id,
            )
            env = verdict.dry_run_response(provider="ringcentral")
            await _cache_sms_envelope(tenant_id, _idem_key, env)
            return _safe_env(env)

        # Phase I1.7.e · chunk 1 · Feb-2026 — tenant-BYO first hop.
        # See the mirror comment in
        # ``services/email/resend_adapter.py::send``. Cap-exceeded
        # (HTTP 429) responses are normalized to
        # ``status="cap_exceeded"``. Falls through to the direct
        # RingCentral SDK path below when no tenant provider is
        # configured. Runs AFTER the gate / consent / kill-switch /
        # dry-run guard so a BYO provider cannot bypass any of those.
        try:
            from services.messaging.byo_passthrough import (
                try_dispatch_sms_tenant_byo,
            )
            _byo = await try_dispatch_sms_tenant_byo(
                tenant_id=tenant_id, to=addr_e164, body=body or "",
            )
        except Exception as _byo_exc:  # noqa: BLE001
            logger.warning(
                "[rc-sms] BYO probe raised — falling through: %s", _byo_exc,
            )
            _byo = None
        if _byo is not None:
            await _cache_sms_envelope(tenant_id, _idem_key, _byo)
            return _safe_env(_byo)

        # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit
        # for the platform (non-BYO) path. Runs AFTER every pre-flight
        # gate (suppression, consent, is_comm_allowed, guard_outbound,
        # BYO probe) so all safeties still fire; only the raw RC
        # send call in the retry loop below is skipped. Envelope is
        # also cached in ``sms_idempotency`` so replay behaves
        # identically to a real send.
        from services.messaging.testmode import (
            is_messaging_testmode as _tm_on,
            mock_sms_envelope as _tm_sms,
        )
        if _tm_on():
            _env = _tm_sms(
                tenant_id=tenant_id, to=addr_e164, body=body or "",
                routed_via="platform_testmode_mock",
            )
            env = {
                "provider": _env.get("provider") or "mock",
                "provider_status": _env["provider_status"],
                "provider_response_id": _env["provider_response_id"],
                "attempts": 1,
                "error": None,
                "routed_via": _env["routed_via"],
                "rc_status": "Queued",
            }
            await _cache_sms_envelope(tenant_id, _idem_key, env)
            return _safe_env(env)

        # 2. Graceful mocked mode when RC not configured.
        if not self.enabled:
            logger.info(
                "[rc-sms] disabled — would have sent to %s cat=%s len=%d",
                addr_e164, category, len(body or ""),
            )
            env = {"provider": "mock", "provider_status": "mocked",
                    "provider_response_id": None, "attempts": 0, "error": None}
            await _cache_sms_envelope(tenant_id, _idem_key, env)
            return _safe_env(env)

        # 3. Compliance suffix + hard cap.
        payload_body = _ensure_stop_suffix((body or "").strip(), category)
        if len(payload_body) > _BODY_HARD_CAP:
            payload_body = payload_body[:_BODY_HARD_CAP]

        from_number = await self._resolve_from(tenant_id)
        svc = RingCentralService(tenant_id)

        last_err: Optional[Exception] = None
        last_status: Optional[int] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                res = await svc.send_sms(addr_e164, payload_body,
                                            from_number=from_number)
                # RC returns messageStatus="Queued" for accepted messages
                # that are still being dispatched. Downstream marketing
                # ledger treats "Queued" / "Sent" / "Delivered" as
                # successful hand-offs.
                env = {"provider": "ringcentral",
                        "provider_status": "sent",
                        "provider_response_id": (
                            str(res["message_id"])
                            if res.get("message_id") is not None else None
                        ),
                        "attempts": attempt, "error": None,
                        "rc_status": res.get("status")}
                await _cache_sms_envelope(tenant_id, _idem_key, env)
                return _safe_env(env)
            except RingCentralError as exc:
                last_err = exc
                last_status = exc.status
                scope_missing = getattr(exc, "scope_missing", False)
                logger.warning(
                    "[rc-sms] attempt %s/%s to %s failed status=%s "
                    "scope_missing=%s",
                    attempt, _MAX_ATTEMPTS, addr_e164, last_status,
                    scope_missing,
                )
                # 4xx (except 429) are terminal — no retry.
                if (last_status not in _TRANSIENT_STATUS
                        or attempt == _MAX_ATTEMPTS):
                    break
                await asyncio.sleep(2 ** (attempt - 1))
            except Exception as exc:  # pragma: no cover — transport oddities
                last_err = exc
                last_status = None
                logger.warning(
                    "[rc-sms] attempt %s/%s to %s crashed: %s",
                    attempt, _MAX_ATTEMPTS, addr_e164, exc,
                )
                # Feb-2026 · Prod 502 hardening — httpx timeout / connect
                # errors on the OAuth path are TERMINAL. Retrying just
                # piles on latency (up to 3 × 15s = 45s) and blows past
                # the ~30s edge-gateway timeout, turning a clean 502
                # into an opaque HTML 502. Fail fast so the endpoint
                # layer can surface a JSON error.
                if isinstance(exc, (httpx.TimeoutException,
                                        httpx.ConnectError)):
                    break
                if attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(2 ** (attempt - 1))

        return _safe_env({"provider": "ringcentral",
                          "provider_status": "failed",
                          "provider_response_id": None,
                          "attempts": _MAX_ATTEMPTS if last_err else 1,
                          "error": f"{type(last_err).__name__}: {last_err}"
                          if last_err else "unknown",
                          "http_status": last_status})


# ─── SMS idempotency cache (Fix 2b) ──────────────────────────────────
_SMS_IDEM_INDEX_READY = False


async def _ensure_sms_idempotency_index() -> None:
    """Idempotent index bootstrap for the ``sms_idempotency``
    collection.  Called lazily from :meth:`RingCentralSMSAdapter.send`."""
    global _SMS_IDEM_INDEX_READY
    if _SMS_IDEM_INDEX_READY:
        return
    try:
        from config import db as _db
        await _db.sms_idempotency.create_index(
            [("tenant_id", 1), ("idempotency_key", 1)],
            unique=True, name="uniq_tenant_idem_key",
        )
        _SMS_IDEM_INDEX_READY = True
    except Exception as exc:  # pragma: no cover
        logger.warning("[rc-sms] idempotency index bootstrap failed: %s", exc)


async def _cache_sms_envelope(
    tenant_id: Optional[str],
    idempotency_key: str,
    envelope: Dict[str, Any],
) -> None:
    """Best-effort upsert of a send result into ``sms_idempotency``.

    We ONLY cache envelopes whose ``provider_status`` is a terminal
    success (``sent`` / ``queued`` / ``delivered`` / ``mocked`` /
    ``dry_run``) — a ``failed`` result must not poison a future
    retry.  Never raises.
    """
    if not (idempotency_key and tenant_id):
        return
    if (envelope or {}).get("provider_status") not in {
        "sent", "queued", "delivered", "mocked", "dry_run",
    }:
        return
    try:
        from datetime import datetime as _dt, timezone as _tz
        from config import db as _db
        await _ensure_sms_idempotency_index()
        await _db.sms_idempotency.update_one(
            {"tenant_id": tenant_id, "idempotency_key": idempotency_key},
            {"$set": {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "envelope": envelope,
                "cached_at": _dt.now(_tz.utc).isoformat(),
            }},
            upsert=True,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[rc-sms] idempotency cache write failed: %s", exc)


_default = RingCentralSMSAdapter()


async def send(**kwargs) -> Dict[str, Any]:
    return await _default.send(**kwargs)
