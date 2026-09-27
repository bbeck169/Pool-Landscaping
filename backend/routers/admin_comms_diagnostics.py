"""Feb-2026 · P0/2 recurrence — comms diagnostic endpoints.

Read-only view of every comms-related env var boolean + the in-mem
last-send state maintained by ``services.comms_send_log``, plus a
POST test-send action to fire a real provider call marked
``diagnostic=True`` in the audit row.

All routes are admin-gated. Values that would leak an API key are
returned as booleans + short prefixes only.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils import require_admin
from services.comms_send_log import get_state, record_attempt, format_exc, _redact

router = APIRouter()


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _present(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _prefix(name: str, n: int = 6) -> Optional[str]:
    v = (os.environ.get(name) or "").strip()
    return v[:n] if v else None


@router.get("/admin/comms-diagnostics")
async def comms_diagnostics(user: dict = Depends(require_admin)):
    """Env + state visibility for the ``*_TESTMODE_MOCK`` flags and
    provider credentials. Admin/super_admin only. Never returns the
    actual secret values.
    """
    state = get_state()
    return {
        "env": os.environ.get("APP_ENV") or None,
        # Testmode mocks (must ALL be False on prod).
        "messaging_testmode_mock": _truthy("MESSAGING_TESTMODE_MOCK"),
        "ai_testmode_mock":        _truthy("AI_TESTMODE_MOCK"),
        "calendars_testmode_mock": _truthy("CALENDARS_TESTMODE_MOCK"),
        "payments_testmode_mock":  _truthy("PAYMENTS_TESTMODE_MOCK"),
        "zillow_testmode_mock":    _truthy("ZILLOW_TESTMODE_MOCK"),
        # Companion flags asked-for by the diagnostic contract.
        "health_ready_integrity_check": _truthy("HEALTH_READY_INTEGRITY_CHECK"),
        "public_frontend_origin": os.environ.get("PUBLIC_FRONTEND_ORIGIN") or None,
        # Resend
        "resend_api_key_present": _present("RESEND_API_KEY"),
        "resend_api_key_prefix":  _prefix("RESEND_API_KEY", 6),
        "resend_from_email":      os.environ.get("EMAIL_FROM") or None,
        # RingCentral
        "ringcentral_client_id_present": _present("RC_CLIENT_ID"),
        "ringcentral_jwt_present":       _present("RC_JWT"),
        "ringcentral_env":               os.environ.get("RC_ENVIRONMENT") or None,
        # Last-send state (in-memory since boot; cleared on restart).
        "last_email_send_ok_at":    state.get("email", {}).get("last_ok_at"),
        "last_email_send_error":    state.get("email", {}).get("last_error"),
        "last_email_send_error_at": state.get("email", {}).get("last_error_at"),
        "last_email_provider_id":   state.get("email", {}).get("last_provider_id"),
        "last_sms_send_ok_at":      state.get("sms", {}).get("last_ok_at"),
        "last_sms_send_error":      state.get("sms", {}).get("last_error"),
        "last_sms_send_error_at":   state.get("sms", {}).get("last_error_at"),
        "last_sms_provider_id":     state.get("sms", {}).get("last_provider_id"),
    }


class _TestSendIn(BaseModel):
    channel: str  # "email" | "sms"
    to: str
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/admin/comms-diagnostics/test")
async def comms_diagnostics_test(payload: _TestSendIn,
                                    user: dict = Depends(require_admin)):
    """Fire a real provider call. Diagnostic flag on the audit row so
    it can be filtered out of business reports. Never bypasses
    ``comms_env_guard`` or the testmode short-circuit — that's the
    whole point of the diagnostic.
    """
    channel = (payload.channel or "").strip().lower()
    if channel not in ("email", "sms"):
        raise HTTPException(400, "channel must be email or sms")
    if not (payload.to or "").strip():
        raise HTTPException(400, "recipient 'to' required")
    subject = payload.subject or "Comms diagnostic test"
    body = payload.body or "This is a comms diagnostic test from the CRM."
    tenant_id = user.get("tenant_id")

    if channel == "email":
        try:
            from services.comms_email_adapter import send_email
            from services.comms_env_guard import CommsContext
            res = await send_email(
                to_email=payload.to,
                subject=subject,
                html=f"<p>{body}</p>",
                tenant_id=tenant_id,
                context=CommsContext.TEST,
            )
            status = (res or {}).get("status")
            ok = status == "sent"
            record_attempt(
                "email", ok=ok,
                tenant_id=tenant_id, recipient=payload.to,
                template="_diagnostic_test",
                provider="resend",
                provider_status=status,
                provider_response_id=(res or {}).get("provider_id"),
                was_mock=str(status).startswith("mock"),
                routed_via=(res or {}).get("routed_via"),
                error=None if ok else str(res)[:500],
                diagnostic=True,
            )
            return {"ok": ok, "channel": "email", "provider_response": res}
        except Exception as e:
            record_attempt("email", ok=False,
                             tenant_id=tenant_id, recipient=payload.to,
                             template="_diagnostic_test", diagnostic=True,
                             **format_exc(e))
            raise HTTPException(500, f"email diagnostic failed: {e}")

    # channel == "sms"
    try:
        from services.sms.rc_adapter import send as _sms_send
        res = await _sms_send(
            to=payload.to, body=body,
            category="transactional",
            tenant_id=tenant_id,
        )
        provider = (res or {}).get("provider")
        status = (res or {}).get("provider_status")
        ok = (provider == "ringcentral"
              and status in ("queued", "sent", "delivered", "accepted"))
        record_attempt(
            "sms", ok=ok,
            tenant_id=tenant_id, recipient=payload.to,
            template="_diagnostic_test",
            provider=provider, provider_status=status,
            provider_response_id=(res or {}).get("provider_response_id"),
            was_mock=(provider == "mock"),
            routed_via=(res or {}).get("routed_via"),
            error=None if ok else str(res)[:500],
            diagnostic=True,
        )
        return {"ok": ok, "channel": "sms", "provider_response": res}
    except Exception as e:
        record_attempt("sms", ok=False,
                         tenant_id=tenant_id, recipient=payload.to,
                         template="_diagnostic_test", diagnostic=True,
                         **format_exc(e))
        raise HTTPException(500, f"sms diagnostic failed: {e}")


# ─── Customer-scoped audit + test-send (Feb-2026 P0 recurrence) ─────
#
# The generic ``/comms-diagnostics`` returns per-process in-memory
# last-send state. Ops on prod need to answer: "does the audit log
# show any attempts for Brian Beckman today, and what did the
# provider say?" — hence these two endpoints.


def _match_prefix_for_recipient(v: str) -> str | None:
    """Best-effort exact-match key for ``comms_send_log.recipient_redacted``.

    ``services.comms_send_log._redact`` is deterministic — feed the
    same input and we get the same output. Reuse it so the audit
    query is an exact-string equality (indexed) rather than a
    regex/scan.
    """
    if not v:
        return None
    return _redact(v.strip())


async def _lookup_customer(customer_id: str | None,
                             customer_email: str | None,
                             tenant_id: str | None) -> dict | None:
    """Find a customer by id or email. Preserves tenant scope."""
    from config import db  # lazy
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if customer_id:
        q["id"] = customer_id
    elif customer_email:
        q["email"] = customer_email.strip().lower()
    else:
        return None
    return await db.customers.find_one(q, {
        "_id": 0, "id": 1, "email": 1, "phone": 1,
        "name": 1, "tenant_id": 1, "is_demo_account": 1,
    })


@router.get("/admin/comms-diagnostics/audit")
async def comms_diagnostics_audit(
    customer_id: str | None = Query(default=None),
    customer_email: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: dict = Depends(require_admin),
):
    """Return recent ``comms_send_log`` + ``comms_suppression_log``
    rows for a single customer, plus a summary. Admin-gated.

    Look-up order: ``customer_id`` → ``customer_email``. Either one
    is required. Tenant scope always applied (super_admin still
    sees only their own tenant via ``require_admin`` semantics).

    The endpoint queries by the ``recipient_redacted`` field, which
    ``services.comms_send_log`` writes for every ``record_attempt``.
    ``_redact`` is deterministic, so we can compute the exact key
    from the customer's email or phone and match on equality.
    """
    from config import db  # lazy
    if not customer_id and not customer_email:
        raise HTTPException(400, "provide customer_id or customer_email")

    tenant_id = user.get("tenant_id")
    cust = await _lookup_customer(customer_id, customer_email, tenant_id)
    if not cust:
        raise HTTPException(404, "customer_not_found")

    email = (cust.get("email") or "").strip()
    phone = (cust.get("phone") or "").strip()
    email_key = _match_prefix_for_recipient(email) if email else None
    phone_key = _match_prefix_for_recipient(phone) if phone else None

    recipient_keys = [k for k in (email_key, phone_key) if k]
    if not recipient_keys:
        return {
            "customer": {
                "id": cust.get("id"), "name": cust.get("name"),
                "email_domain": (email.split("@")[-1] if "@" in email else None),
                "phone_last4": phone[-4:] if phone else None,
                "is_demo_account": bool(cust.get("is_demo_account")),
            },
            "attempts": [],
            "suppressions": [],
            "summary": {
                "total_attempts": 0, "success_count": 0,
                "failure_count": 0, "suppression_count": 0,
                "last_success_at": None, "last_failure_at": None,
                "distinct_failure_reasons": [],
            },
            "note": "customer has neither email nor phone on file",
        }

    # 1. comms_send_log rows.
    send_q: dict = {"recipient_redacted": {"$in": recipient_keys}}
    if tenant_id:
        send_q["tenant_id"] = tenant_id
    attempts: list[dict] = []
    cursor = db.comms_send_log.find(send_q, {"_id": 0}).sort("at", -1).limit(limit)
    async for row in cursor:
        # Truncate exception traces so admin UI doesn't get flooded.
        if row.get("exc_trace"):
            row["exc_trace"] = row["exc_trace"][:1500]
        if row.get("error"):
            row["error"] = row["error"][:500]
        attempts.append(row)

    # 2. comms_suppression_log rows — gate-blocked sends.
    supp_q: dict = {}
    if tenant_id:
        supp_q["tenant_id"] = tenant_id
    if cust.get("id"):
        supp_q["recipient_id"] = cust.get("id")
    email_domain = email.split("@")[-1] if "@" in email else None
    phone_last4 = phone[-4:] if phone else None
    supp_or: list[dict] = []
    if email_domain:
        supp_or.append({"recipient_email_domain": email_domain})
    if phone_last4:
        supp_or.append({"recipient_phone_last4": phone_last4})
    if supp_or and not supp_q.get("recipient_id"):
        supp_q["$or"] = supp_or
    suppressions: list[dict] = []
    if supp_q:
        cursor2 = db.comms_suppression_log.find(supp_q, {"_id": 0}).sort(
            "created_at", -1).limit(limit)
        async for row in cursor2:
            # Serialize datetime → iso.
            _ca = row.get("created_at")
            if _ca and not isinstance(_ca, str):
                try:
                    row["created_at"] = _ca.isoformat()
                except Exception:  # noqa: BLE001
                    row["created_at"] = str(_ca)
            suppressions.append(row)

    # 3. Summary.
    success = sum(1 for a in attempts if a.get("ok"))
    failure = sum(1 for a in attempts if not a.get("ok"))
    last_ok = next((a.get("at") for a in attempts if a.get("ok")), None)
    last_err = next((a.get("at") for a in attempts if not a.get("ok")), None)
    reasons: dict[str, int] = {}
    for a in attempts:
        if a.get("ok"):
            continue
        key = a.get("provider_status") or a.get("exc_type") or "unknown"
        reasons[key] = reasons.get(key, 0) + 1
    for s in suppressions:
        key = s.get("reason") or "suppressed"
        reasons[key] = reasons.get(key, 0) + 1

    return {
        "customer": {
            "id": cust.get("id"), "name": cust.get("name"),
            "email_domain": email_domain,
            "phone_last4": phone_last4,
            "is_demo_account": bool(cust.get("is_demo_account")),
            "tenant_id": cust.get("tenant_id"),
        },
        "attempts": attempts,
        "suppressions": suppressions,
        "summary": {
            "total_attempts": len(attempts),
            "success_count": success,
            "failure_count": failure,
            "suppression_count": len(suppressions),
            "last_success_at": last_ok,
            "last_failure_at": last_err,
            "distinct_failure_reasons": sorted(
                [{"reason": k, "count": v} for k, v in reasons.items()],
                key=lambda r: -r["count"],
            ),
        },
    }


class _CustomerTestSendIn(BaseModel):
    customer_id: str
    channel: str          # "email" | "sms"
    template: str = "test"  # "test" | "add_card_link" | "estimate_send"


@router.post("/admin/comms-diagnostics/send-to-customer")
async def comms_diagnostics_send_to_customer(
    payload: _CustomerTestSendIn,
    user: dict = Depends(require_admin),
):
    """Trigger the exact production send path for a named customer.

    Goes through the same shims (``services.comms_email_adapter.send_email``
    for email, ``utils.send_sms`` for SMS) that carry the audit
    logging + gate checks. The template names map to short, safe
    payloads — the endpoint never fires the *real* transactional
    template (avoids side-effects like marking an estimate ``sent``);
    instead it uses a diagnostic-tagged copy so ops can reproduce
    the failure envelope without polluting business tables.
    """
    from config import db  # lazy
    channel = (payload.channel or "").strip().lower()
    template = (payload.template or "test").strip().lower()
    if channel not in ("email", "sms"):
        raise HTTPException(400, "channel must be email or sms")

    tenant_id = user.get("tenant_id")
    cust = await _lookup_customer(payload.customer_id, None, tenant_id)
    if not cust:
        raise HTTPException(404, "customer_not_found")

    if channel == "email":
        to_email = (cust.get("email") or "").strip()
        if not to_email:
            raise HTTPException(422, "customer has no email on file")
        subject_map = {
            "test": "[Diagnostic] CRM comms test",
            "add_card_link": "[Diagnostic] Add card link (test)",
            "estimate_send": "[Diagnostic] Estimate send (test)",
        }
        subject = subject_map.get(template, subject_map["test"])
        html = (
            f"<p>This is a comms diagnostic test-send from the CRM.</p>"
            f"<p>Template simulated: <b>{template}</b></p>"
            f"<p>Customer: {cust.get('name') or cust.get('id')}</p>"
            f"<p><em>If you received this, outbound email is working "
            f"for your account.</em></p>"
        )
        try:
            from services.comms_email_adapter import send_email
            from services.comms_env_guard import CommsContext
            res = await send_email(
                tenant_id=tenant_id or cust.get("tenant_id"),
                to_email=to_email, subject=subject, html=html,
                headers={"X-Template": f"_diagnostic_{template}",
                          "X-Tenant-Id": tenant_id or cust.get("tenant_id") or ""},
                context=CommsContext.TEST,
            )
            status = (res or {}).get("status")
            ok = status == "sent"
            record_attempt(
                "email", ok=ok,
                tenant_id=tenant_id or cust.get("tenant_id"),
                recipient=to_email,
                template=f"_diagnostic_{template}",
                provider="resend", provider_status=status,
                provider_response_id=(res or {}).get("provider_id"),
                was_mock=str(status).startswith("mock"),
                routed_via=(res or {}).get("routed_via"),
                error=None if ok else str(res)[:500],
                diagnostic=True,
            )
            return {
                "ok": ok, "channel": "email",
                "customer_id": cust.get("id"),
                "recipient_domain": to_email.split("@")[-1],
                "template": f"_diagnostic_{template}",
                "provider_response": res,
            }
        except Exception as e:
            record_attempt(
                "email", ok=False,
                tenant_id=tenant_id or cust.get("tenant_id"),
                recipient=to_email,
                template=f"_diagnostic_{template}", diagnostic=True,
                **format_exc(e),
            )
            raise HTTPException(500, f"email diagnostic failed: {e}")

    # channel == "sms"
    to_phone = (cust.get("phone") or "").strip()
    if not to_phone:
        raise HTTPException(422, "customer has no phone on file")
    body = (
        f"[Diagnostic {template}] CRM comms test — if you got this, "
        f"outbound SMS is working."
    )
    try:
        from services.sms.rc_adapter import send as _sms_send
        res = await _sms_send(
            to=to_phone, body=body,
            category="transactional",
            tenant_id=tenant_id or cust.get("tenant_id"),
        )
        provider = (res or {}).get("provider")
        status = (res or {}).get("provider_status")
        ok = (provider == "ringcentral"
              and status in ("queued", "sent", "delivered", "accepted"))
        record_attempt(
            "sms", ok=ok,
            tenant_id=tenant_id or cust.get("tenant_id"),
            recipient=to_phone,
            template=f"_diagnostic_{template}",
            provider=provider, provider_status=status,
            provider_response_id=(res or {}).get("provider_response_id"),
            was_mock=(provider == "mock"),
            routed_via=(res or {}).get("routed_via"),
            error=None if ok else str(res)[:500],
            diagnostic=True,
        )
        return {
            "ok": ok, "channel": "sms",
            "customer_id": cust.get("id"),
            "recipient_last4": to_phone[-4:] if to_phone else None,
            "template": f"_diagnostic_{template}",
            "provider_response": res,
        }
    except Exception as e:
        record_attempt(
            "sms", ok=False,
            tenant_id=tenant_id or cust.get("tenant_id"),
            recipient=to_phone,
            template=f"_diagnostic_{template}", diagnostic=True,
            **format_exc(e),
        )
        raise HTTPException(500, f"sms diagnostic failed: {e}")




# ─── Recent failures + Resend key/domain probe (Feb-2026 P0 recurrence) ─
#
# Two more admin-only reads for triage:
#   • recent failures across the whole audit log (not customer-scoped)
#   • Resend ``/domains`` probe using the POD-level ``RESEND_API_KEY``,
#     surfacing the raw body + parsed verified domain list so ops
#     can tell "wrong project" from "unverified domain" from
#     "revoked key" without SSHing into the pod.


@router.get("/admin/comms-diagnostics/recent-failures")
async def comms_diagnostics_recent_failures(
    provider: str | None = Query(default=None,
                                    description="e.g. resend, ringcentral"),
    channel: str | None = Query(default=None,
                                   description="email | sms"),
    limit: int = Query(default=10, ge=1, le=100),
    user: dict = Depends(require_admin),
):
    """Return the most recent ``ok=false`` rows from
    ``db.comms_send_log`` for the current tenant.

    Includes full ``error``, ``exc_type``, and ``exc_trace`` so ops
    can pull the provider's 4xx body straight out of the audit log
    (which now records direct-SDK calls too, via ``sdk_intercept``).
    """
    from config import db  # lazy
    q: dict = {"ok": False}
    if user.get("tenant_id"):
        q["tenant_id"] = user["tenant_id"]
    if provider:
        q["provider"] = provider.strip().lower()
    if channel:
        q["channel"] = channel.strip().lower()
    out: list[dict] = []
    cursor = db.comms_send_log.find(q, {"_id": 0}).sort("at", -1).limit(limit)
    async for row in cursor:
        if row.get("exc_trace"):
            row["exc_trace"] = row["exc_trace"][:1500]
        if row.get("error"):
            row["error"] = row["error"][:1500]
        out.append(row)
    return {"count": len(out), "items": out,
             "filter": {"provider": provider, "channel": channel,
                         "tenant_id": user.get("tenant_id")}}


@router.get("/admin/comms-diagnostics/resend-domains")
async def comms_diagnostics_resend_domains(
    user: dict = Depends(require_admin),
):
    """Probe Resend ``GET /domains`` using the pod-level
    ``RESEND_API_KEY``. Returns the parsed domain list with
    verification status, plus the redacted key prefix so ops can
    cross-check the pod is running with the expected key.

    Never returns the full API key. Never returns response headers.
    """
    import httpx  # lazy — keeps the module import cheap.
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    key_prefix = f"{key[:6]}..." if key else None
    key_len = len(key) if key else 0
    from_addr = os.environ.get("RESEND_FROM") or os.environ.get(
        "RESEND_FROM_ADDRESS") or None
    if not key:
        return {
            "ok": False,
            "reason": "RESEND_API_KEY_missing_on_pod",
            "key_prefix": None, "key_len": 0,
            "from_address_env": from_addr,
            "domains": [],
        }
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {key}"},
            )
    except Exception as e:
        return {
            "ok": False, "reason": f"probe_exception:{type(e).__name__}",
            "key_prefix": key_prefix, "key_len": key_len,
            "from_address_env": from_addr, "domains": [],
        }
    body_text = (r.text or "")[:1000]
    if key and key in body_text:
        body_text = body_text.replace(key, f"{key_prefix}(redacted)")
    if r.status_code >= 400:
        return {
            "ok": False, "status_code": r.status_code,
            "reason": f"resend_probe_http_{r.status_code}",
            "response_body": body_text,
            "key_prefix": key_prefix, "key_len": key_len,
            "from_address_env": from_addr, "domains": [],
        }
    try:
        parsed = r.json()
    except Exception:
        parsed = {}
    domains = []
    from_domain = None
    if from_addr and "@" in from_addr:
        from_domain = from_addr.split("@", 1)[1].strip().lower()
    from_domain_verified = None
    for d in (parsed.get("data") or []):
        _name = d.get("name")
        _status = d.get("status")
        domains.append({"name": _name, "status": _status,
                          "region": d.get("region"),
                          "sending": (d.get("capabilities") or {}).get("sending")})
        if from_domain and _name == from_domain:
            from_domain_verified = (_status == "verified")
    return {
        "ok": True, "status_code": r.status_code,
        "key_prefix": key_prefix, "key_len": key_len,
        "from_address_env": from_addr,
        "from_domain": from_domain,
        "from_domain_verified": from_domain_verified,
        "domains": domains,
    }
