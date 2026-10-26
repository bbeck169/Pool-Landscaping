# ruff: noqa: F403,F405
"""Phase L3 · Feb-2026 — Text + Email from Leads.

Reuses the customer-side SMS + email providers so the operator can
compose a free-form message rooted at a lead without introducing any
new provider integration:

* SMS → ``services/sms/rc_adapter.send`` (RingCentral) — same adapter
  ``POST /customers/{cid}/send-sms`` uses.  Honors the K31 consent
  gate, marketing suppression, BYO cap, testmode mock, etc.
* Email → ``services/comms_email_adapter.send_email`` (Resend) — same
  adapter ``POST /customers/{cid}/send-email`` uses.

Endpoints (all guarded by admin / manager / super_admin / owner):

* ``POST /api/leads/{lead_id}/send-sms``
* ``POST /api/leads/{lead_id}/send-email``
* ``GET  /api/leads/{lead_id}/communications``

Row-insert-BEFORE-dispatch invariant (per Phase L3 acceptance): the
``lead_communications`` row is persisted with ``status="queued"``
before the provider adapter is called so a crash mid-call still
leaves a discoverable trail (the row's ``error`` field will be null
and the ``status`` will stay at ``queued`` — visible on the timeline
so ops know exactly which sends never returned).

Consent gates:

* ``lead.sms_ok`` / ``lead.email_ok`` default to ``True`` when the
  field is absent on the document (historical rows).  See ``.get(...
  True)`` pattern below.
* When either is explicitly ``False``, the endpoint returns HTTP 400
  with ``detail={"code":"consent_required", ...}`` unless the caller
  posts ``override_consent=true``.  The UI mirrors this gate with a
  red-ish warning + override checkbox.

RC provider_status → our uniform enum mapping (Phase L3 nudge #2):

    sent | queued | delivered → "sent"
    failed | invalid_phone  → "failed"
    suppressed | suppressed_not_demo | no_consent → "failed"
    mocked | dry_run        → "sent"      # the row body still ships
    cap_exceeded            → "failed"
    (unknown)               → "sent"      # coerce best-effort;
                                          #   raw stashed on the row

Timeline sources merged (Phase L3 nudge #1 — inbound-email TODO):

    * ``lead_communications`` (outbound SMS + email + any inbound row)
    * ``sms_inbound`` where ``matched_lead_id == lead_id``
    * ``leads.timeline[]`` entries whose ``kind`` is ``status_change``

Inbound-email path is not wired in this repo (Resend is outbound-only
via ``routers/resend_webhooks.py``).  A ``TODO(inbound-email):`` marker
sits at the aggregator site for grep discoverability.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

router = APIRouter()

# Roles who can compose ad-hoc SMS/email from a lead.  Mirrors the
# ``_INBOUND_MANAGER_ROLES`` set in ``routers/leads.py`` plus
# ``owner`` (which ``require_admin`` already treats as admin-equiv).
_ALLOWED_ROLES = {"admin", "super_admin", "manager", "owner"}


def _require_role(user: dict) -> None:
    if (user or {}).get("role") not in _ALLOWED_ROLES:
        raise HTTPException(403, "Not allowed")


# ─── Provider-status normalization ─────────────────────────────────
_PROVIDER_STATUS_SENT = {"sent", "queued", "delivered", "mocked", "dry_run"}
_PROVIDER_STATUS_FAILED = {
    "failed", "invalid_phone",
    "suppressed", "suppressed_not_demo",
    "no_consent", "skipped_opted_out",
    "cap_exceeded", "not_sent_missing_key",
}


def _normalize_status(raw: Optional[str]) -> str:
    """Coerce provider-side status strings into our uniform enum.

    Unknown values fall through to ``"sent"`` best-effort — the raw
    value is stashed on the row as ``provider_status_raw`` for
    observability so a mystery state doesn't crash the endpoint.
    """
    s = (raw or "").lower().strip()
    if s in _PROVIDER_STATUS_SENT:
        return "sent"
    if s in _PROVIDER_STATUS_FAILED:
        return "failed"
    return "sent"


async def _ensure_indexes() -> None:
    """Create the two indexes we sort/lookup by.  Idempotent."""
    try:
        await db.lead_communications.create_index(
            [("tenant_id", 1), ("lead_id", 1), ("created_at", -1)],
            name="lead_comms_by_lead",
        )
        await db.lead_communications.create_index(
            [("tenant_id", 1), ("provider_message_id", 1)],
            name="lead_comms_by_provider_id",
            sparse=True,
        )
    except Exception as exc:  # pragma: no cover — index may already exist
        logger.warning(f"[l3] ensure_indexes lead_communications failed: {exc}")


# ─── Request bodies ────────────────────────────────────────────────
class _SendSmsBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=1600)
    override_consent: bool = False


class _SendEmailBody(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=50_000)
    override_consent: bool = False


# ─── Helpers ───────────────────────────────────────────────────────
async def _load_lead(lead_id: str, tenant_id: str) -> Dict[str, Any]:
    doc = await db.leads.find_one(
        {"id": lead_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Lead not found")
    return doc


def _lead_channel_ok(lead: Dict[str, Any], channel: str) -> bool:
    """Return ``True`` when the lead has NOT explicitly opted out.

    Missing key on the document → treated as ``True`` (never migrated
    historical rows).  Explicit ``False`` → returns ``False`` and the
    caller must pass ``override_consent`` to send.
    """
    key = "sms_ok" if channel == "sms" else "email_ok"
    return bool(lead.get(key, True))


async def _persist_row(
    *, tenant_id: str, lead: Dict[str, Any], channel: str,
    from_identity: str, to_identity: str,
    body: str, subject: Optional[str], user_id: Optional[str],
) -> Dict[str, Any]:
    """Insert the ``queued`` row BEFORE dispatch so a crash mid-call
    still leaves a trail on the timeline."""
    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "lead_id": lead["id"],
        "direction": "outbound",
        "channel": channel,
        "from_identity": from_identity,
        "to_identity": to_identity,
        "subject": subject,
        "body": body,
        "status": "queued",
        "provider_message_id": None,
        "provider_status_raw": None,
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "sent_by_user_id": user_id,
    }
    await db.lead_communications.insert_one(dict(row))
    return row


async def _update_row_after_dispatch(
    row_id: str, tenant_id: str, *,
    status: str, provider_message_id: Optional[str],
    provider_status_raw: Optional[str], error: Optional[str],
) -> None:
    await db.lead_communications.update_one(
        {"id": row_id, "tenant_id": tenant_id},
        {"$set": {
            "status": status,
            "provider_message_id": provider_message_id,
            "provider_status_raw": provider_status_raw,
            "error": error,
            "updated_at": now_iso(),
        }},
    )


# ═════════════════════════ POST send-sms ═══════════════════════════
@router.post("/leads/{lead_id}/send-sms",
              operation_id="leads.sendSms")
async def send_sms_from_lead(
    lead_id: str, body: _SendSmsBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_role(user)
    await _ensure_indexes()
    lead = await _load_lead(lead_id, tenant["id"])

    phone = (lead.get("phone") or "").strip()
    if not phone:
        raise HTTPException(400, "Lead has no phone number on file")

    if not _lead_channel_ok(lead, "sms") and not body.override_consent:
        raise HTTPException(
            400, {"code": "consent_required",
                     "channel": "sms",
                     "message": "This lead has opted out of SMS. Pass override_consent=true to send anyway."},
        )

    from_identity = _resolve_from_sms(tenant)
    row = await _persist_row(
        tenant_id=tenant["id"], lead=lead, channel="sms",
        from_identity=from_identity, to_identity=phone,
        body=body.body, subject=None, user_id=user.get("id"),
    )

    # Dispatch AFTER the row is persisted.  ``rc_adapter.send`` never
    # raises — a transport failure returns an envelope with
    # ``provider_status="failed"`` and an ``error`` string.
    #
    # Ticket NN · Feb-2026 — resolve merge tags before dispatch so
    # ``{{CUSTOMER_FIRST_NAME}}`` / ``{{COMPANY_NAME}}`` / portal-
    # link tokens an operator typed into the compose textarea land
    # as the resolved values, not literal brace strings.  Leads
    # don't have the full customer schema, so we adapt the lead doc
    # to the customer shape the merge-tag catalog expects (name →
    # first/last split, phone/email passthrough).  Unknown tokens
    # fall back to empty (``missing="empty"``) matching every other
    # Phase 9 send path.
    from services.marketing.merge_tags import (
        render_template as _render_template,
        render_context as _render_context,
    )
    _lead_as_customer = {
        "id": lead.get("id"),
        "name": (lead.get("name") or "").strip(),
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "email": lead.get("email"),
        "phone": lead.get("phone"),
    }
    _nn_ctx = _render_context(
        customer=_lead_as_customer, tenant=tenant or {},
        lead=lead,
    )
    rendered_body, _unresolved = _render_template(
        body.body or "", _nn_ctx, missing="empty",
    )
    if _unresolved:
        logger.info(
            "[lead-comms] NN unresolved tokens lead=%s tokens=%s",
            lead_id, _unresolved,
        )

    from services.sms.rc_adapter import send as _sms_send
    envelope = await _sms_send(
        to=phone, body=rendered_body,
        category="transactional",
        tenant_id=tenant["id"],
        audience="customer",
    )
    raw_status = envelope.get("provider_status") or "unknown"
    normalized = _normalize_status(raw_status)
    await _update_row_after_dispatch(
        row["id"], tenant["id"],
        status=normalized,
        provider_message_id=envelope.get("provider_response_id"),
        provider_status_raw=raw_status,
        error=envelope.get("error"),
    )
    # Return the FRESH row so the caller renders the actual status.
    fresh = await db.lead_communications.find_one(
        {"id": row["id"], "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return fresh or row


# ═════════════════════════ POST send-email ═════════════════════════
@router.post("/leads/{lead_id}/send-email",
              operation_id="leads.sendEmail")
async def send_email_from_lead(
    lead_id: str, body: _SendEmailBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_role(user)
    await _ensure_indexes()
    lead = await _load_lead(lead_id, tenant["id"])

    email = (lead.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Lead has no email address on file")

    if not _lead_channel_ok(lead, "email") and not body.override_consent:
        raise HTTPException(
            400, {"code": "consent_required",
                     "channel": "email",
                     "message": "This lead has opted out of email. Pass override_consent=true to send anyway."},
        )

    from_identity = _resolve_from_email(tenant)
    row = await _persist_row(
        tenant_id=tenant["id"], lead=lead, channel="email",
        from_identity=from_identity, to_identity=email,
        body=body.body, subject=body.subject, user_id=user.get("id"),
    )

    from services.comms_email_adapter import send_email as _send_email
    html = (
        f"<pre style=\"font-family:inherit;white-space:pre-wrap\">"
        f"{_escape_html(body.body)}</pre>"
    )
    envelope = await _send_email(
        tenant["id"], email,
        subject=body.subject,
        html=html,
    )
    raw_status = envelope.get("status") or "unknown"
    normalized = _normalize_status(raw_status)
    await _update_row_after_dispatch(
        row["id"], tenant["id"],
        status=normalized,
        provider_message_id=envelope.get("provider_id"),
        provider_status_raw=raw_status,
        error=envelope.get("error"),
    )
    fresh = await db.lead_communications.find_one(
        {"id": row["id"], "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return fresh or row


def _escape_html(s: str) -> str:
    """Cheap HTML-escape so the raw compose body can't inject markup."""
    return (
        (s or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _resolve_from_sms(tenant: Dict[str, Any]) -> str:
    """Best-effort resolve the tenant's outbound SMS from-number.

    Falls back to an empty string when the tenant hasn't wired one —
    the RC adapter has its own resolver, we ONLY log this for the
    timeline display.
    """
    return (
        tenant.get("rc_sms_from_number")
        or tenant.get("support_phone_number")
        or ""
    )


def _resolve_from_email(tenant: Dict[str, Any]) -> str:
    return (
        tenant.get("outbound_email_from")
        or tenant.get("support_email")
        or tenant.get("email") or ""
    )


# ═════════════════════════ GET communications ══════════════════════
@router.get("/leads/{lead_id}/communications",
             operation_id="leads.communications")
async def get_communications(
    lead_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None,
        description="Opaque cursor — <iso>|<id> from the last page's tail row."),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_role(user)
    lead = await _load_lead(lead_id, tenant["id"])

    # Parse cursor.  Format: ``<iso>|<id>``.  Ties on ``created_at``
    # are broken by ``id`` so paging is deterministic when multiple
    # rows share a timestamp (Phase L3 nudge #4).
    cur_ts: Optional[str] = None
    cur_id: Optional[str] = None
    if cursor:
        try:
            cur_ts, cur_id = cursor.split("|", 1)
        except ValueError:
            raise HTTPException(400, "Invalid cursor")

    # ── lead_communications (outbound + any explicit inbound) ─────
    comm_q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "lead_id": lead_id,
    }
    if cur_ts and cur_id:
        comm_q["$or"] = [
            {"created_at": {"$lt": cur_ts}},
            {"created_at": cur_ts, "id": {"$lt": cur_id}},
        ]
    comm_rows: List[Dict[str, Any]] = []
    async for r in db.lead_communications.find(comm_q, {"_id": 0}) \
            .sort([("created_at", -1), ("id", -1)]).limit(limit + 1):
        comm_rows.append(r)

    # ── sms_inbound where the RC webhook matched this lead ────────
    # TODO(inbound-email): Resend has no inbound webhook in this repo
    # — extend this aggregator here when it lands (mirror the
    # sms_inbound query shape onto an ``email_inbound`` collection).
    inbound_q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "matched_lead_id": lead_id,
    }
    if cur_ts and cur_id:
        inbound_q["$or"] = [
            {"received_at": {"$lt": cur_ts}},
            {"received_at": cur_ts, "id": {"$lt": cur_id}},
        ]
    inbound_rows: List[Dict[str, Any]] = []
    async for r in db.sms_inbound.find(inbound_q, {"_id": 0}) \
            .sort([("received_at", -1), ("id", -1)]).limit(limit + 1):
        inbound_rows.append(r)

    # ── lead status_change entries from leads.timeline[] ──────────
    # Kept read-only (no separate audit collection).  We surface these
    # only on the FIRST page — timeline entries are typically <10
    # per lead so paging them out doesn't earn its keep.
    status_items: List[Dict[str, Any]] = []
    if not cursor:
        for ev in (lead.get("timeline") or []):
            if (ev or {}).get("kind") == "status_change":
                payload = ev.get("payload") or {}
                status_items.append({
                    "id": f"status:{ev.get('ts')}",
                    "type": "status_change",
                    "direction": None,
                    "channel": None,
                    "subject": None,
                    "body": None,
                    "status": payload.get("to"),
                    "from_identity": payload.get("from"),
                    "to_identity": payload.get("to"),
                    "created_at": ev.get("ts"),
                    "sent_by_user_id": ev.get("actor_user_id"),
                    "actor_name": None,
                    "provider_message_id": None,
                })

    # ── Merge + sort DESC ─────────────────────────────────────────
    items: List[Dict[str, Any]] = []
    for r in comm_rows:
        items.append({
            "id": r.get("id"),
            "type": r.get("channel"),  # "sms" | "email"
            "direction": r.get("direction"),
            "channel": r.get("channel"),
            "subject": r.get("subject"),
            "body": r.get("body"),
            "status": r.get("status"),
            "from_identity": r.get("from_identity"),
            "to_identity": r.get("to_identity"),
            "created_at": r.get("created_at"),
            "sent_by_user_id": r.get("sent_by_user_id"),
            "actor_name": None,
            "provider_message_id": r.get("provider_message_id"),
            "provider_status_raw": r.get("provider_status_raw"),
            "error": r.get("error"),
        })
    for r in inbound_rows:
        items.append({
            "id": r.get("id"),
            "type": "sms",
            "direction": "inbound",
            "channel": "sms",
            "subject": None,
            "body": r.get("text"),
            "status": "received",
            "from_identity": r.get("from_number"),
            "to_identity": r.get("to_number"),
            "created_at": r.get("received_at"),
            "sent_by_user_id": None,
            "actor_name": None,
            "provider_message_id": r.get("message_id"),
        })
    items += status_items
    items.sort(
        key=lambda i: ((i.get("created_at") or ""), (i.get("id") or "")),
        reverse=True,
    )

    # Pagination — pop the tail if we grabbed the +1 sentinel.
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    next_cursor: Optional[str] = None
    if has_more and items:
        tail = items[-1]
        next_cursor = f"{tail.get('created_at') or ''}|{tail.get('id') or ''}"

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
