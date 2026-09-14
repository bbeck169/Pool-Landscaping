"""Phase I7 · Wave A · Feb-2026 — Communication timeline.

``GET /api/customers/{customer_id}/communication-timeline`` — merges
per-customer SMS + email events across three log collections into
a single time-sorted stream:

  * ``notification_dispatch_log`` — primary. Per-message rows with
    ``channel`` = ``sms`` | ``email``, populated for every dispatch
    through the F7 idempotent notifier + the F5 marketing sequences.
    Linked to the customer via ``recipient_id`` OR via
    ``resolved_address`` matching a phone / email on the customer.
  * ``audit_events`` — supplementary. Surfaces ``portal_invite_bulk``
    rows whose payload lists this customer_id (so operators can see
    "portal invite email fired 3 days ago" without needing to open
    the dispatch log directly).
  * ``email_delivery_log`` — INTENTIONALLY EXCLUDED.  Audit surfaced
    that this collection stores weekly digest batches
    (``week_start`` / ``week_end`` / ``total_completed``) — a
    per-customer view is not extractable without denormalizing the
    ``recipients`` list, and the same per-email row also lives on
    ``notification_dispatch_log``.  Excluding it prevents duplicate
    rows and keeps the query surface honest.

Portal filtering: when the caller's role is ``customer`` the
response strips ``actor_user_id`` + ``delivery_error`` before
returning.  The frontend never sees those fields on the wire, so a
future portal regression can't accidentally leak them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()
logger = logging.getLogger("communication_timeline")

_ADMIN_ROLES = {"admin", "manager", "super_admin"}
_TECH_ROLES = {"tech", "technician"}
_MAX_PER_COLLECTION = 200
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# Phase K6 · Feb-2026 — ``job_edited_after_completion`` joined the
# ``portal_invite_bulk`` surface so late-edit history shows up on
# the customer timeline alongside emails, SMS, and portal
# invites.  See ``_audit_to_item`` for the item shape.
# Phase K14 · Feb-2026 — ``invoice_auto_charged`` joined so bulk
# Stripe charges surface on the customer's communication timeline
# next to emails/SMS/portal invites/late edits.
_AUDIT_EVENT_TYPES = (
    "portal_invite_bulk",
    "job_edited_after_completion",
    "invoice_auto_charged",
)


def _preview(text: Optional[str], n: int = 500) -> str:
    if not text:
        return ""
    s = str(text).strip()
    return s[:n]


async def _load_customer(customer_id: str, tenant_id: str) -> Dict[str, Any]:
    row = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "email": 1, "emails": 1,
            "phone": 1, "phones": 1, "mobile_phone": 1, "home_phone": 1},
    )
    if not row:
        raise HTTPException(404, "customer not found")
    return row


def _customer_addresses(customer: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Return (emails, phones) — lowercased/normalized for matching
    against ``notification_dispatch_log.resolved_address``."""
    emails: List[str] = []
    for k in ("email",):
        v = customer.get(k)
        if v:
            emails.append(str(v).strip().lower())
    for v in customer.get("emails") or []:
        if isinstance(v, dict):
            v = v.get("address") or v.get("email")
        if v:
            emails.append(str(v).strip().lower())
    phones: List[str] = []
    for k in ("phone", "mobile_phone", "home_phone"):
        v = customer.get(k)
        if v:
            phones.append(str(v).strip())
    for v in customer.get("phones") or []:
        if isinstance(v, dict):
            v = v.get("number") or v.get("phone")
        if v:
            phones.append(str(v).strip())
    return sorted(set(emails)), sorted(set(phones))


def _dispatch_to_item(row: Dict[str, Any]) -> Dict[str, Any]:
    channel = (row.get("channel") or "").lower()
    kind = "sms" if channel == "sms" else "email"
    ts = row.get("sent_at") or row.get("reserved_at") or ""
    meta = row.get("metadata") or {}
    actor_user_id = meta.get("actor_user_id") or meta.get("user_id")
    actor_email = meta.get("actor_email")
    if actor_email:
        actor_label = actor_email
        actor_kind = "user"
    elif actor_user_id:
        actor_label = "User"
        actor_kind = "user"
    else:
        actor_label = "System / Automation"
        actor_kind = "system"
    return {
        "id": row.get("id") or row.get("dedupe_key"),
        "type": kind,
        "occurred_at": ts,
        "actor_label": actor_label,
        "actor_kind": actor_kind,
        "actor_user_id": actor_user_id,
        "direction": "outbound",
        "channel_id": row.get("id"),
        "subject": row.get("subject") or None,
        "body_preview": _preview(meta.get("body") or meta.get("message")
                                        or row.get("subject")),
        "recipient": row.get("resolved_address") or "",
        "delivery_status": row.get("status") or "queued",
        "delivery_error": row.get("error"),
    }


def _audit_to_item(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload") or {}
    actor_email = row.get("actor_email")
    actor_user_id = row.get("actor_id")
    label = actor_email or ("User" if actor_user_id else "System / Automation")
    kind = "user" if (actor_email or actor_user_id) else "system"
    event_type = row.get("event_type") or ""

    # Phase K6 · Feb-2026 — job_edited_after_completion branch.
    # Renders a compact "Job edited after completion" timeline card
    # listing the fields the operator touched.  Never leaks
    # before/after values (K6 privacy constraint).
    if event_type == "job_edited_after_completion":
        fields = payload.get("fields_changed") or []
        subject = "Job edited after completion"
        body = (
            f"{label} edited {len(fields)} field"
            f"{'' if len(fields) == 1 else 's'} on a completed job"
            f"{': ' + ', '.join(fields) if fields else '.'}"
        )
        if payload.get("invoice_recalculated"):
            body += " (invoice total recalculated)"
        return {
            "id": row.get("id"),
            "type": "job_edited",
            "occurred_at": row.get("timestamp") or "",
            "actor_label": label,
            "actor_kind": kind,
            "actor_user_id": actor_user_id,
            "direction": "internal",
            "channel_id": row.get("id"),
            "subject": subject,
            "body_preview": _preview(body),
            "recipient": "",
            "delivery_status": "logged",
            "delivery_error": None,
            "job_id": payload.get("job_id"),
            "fields_changed": fields,
            "invoice_recalculated": bool(payload.get("invoice_recalculated")),
        }
    # Phase K14 · Feb-2026 — ``invoice_auto_charged`` branch. Renders a
    # compact "Invoice auto-charged" card with the dollar amount and
    # the last-4 of the payment intent id so operators can eyeball
    # which bulk run touched this customer. Impersonation stamps come
    # from the row's top-level ``via_impersonation`` /
    # ``acting_admin_id`` fields (already excluded from the customer
    # portal via ``_strip_admin_fields`` on ``actor_user_id``).
    if event_type == "invoice_auto_charged":
        amount_cents = int(payload.get("amount_cents") or 0)
        currency = (payload.get("currency") or "usd").upper()
        amount_str = f"${amount_cents / 100:,.2f} {currency}"
        pi = payload.get("payment_intent_id") or ""
        pi_tail = pi[-6:] if pi else ""
        via_imp = bool(row.get("via_impersonation"))
        stamp = " (via impersonation)" if via_imp else ""
        subject = "Invoice auto-charged"
        body = (
            f"{label} charged {amount_str} to card on file"
            f"{stamp} · pi_…{pi_tail}"
        )
        return {
            "id": row.get("id"),
            "type": "payment",
            "occurred_at": row.get("timestamp") or "",
            "actor_label": label,
            "actor_kind": kind,
            "actor_user_id": actor_user_id,
            "direction": "internal",
            "channel_id": row.get("id"),
            "subject": subject,
            "body_preview": _preview(body),
            "recipient": "",
            "delivery_status": "charged",
            "delivery_error": None,
            "invoice_id": payload.get("invoice_id"),
            "amount_cents": amount_cents,
            "currency": currency,
            "payment_intent_id": pi,
            "bulk_run_id": payload.get("bulk_run_id"),
            "via_impersonation": via_imp,
        }
    # Default (portal_invite_bulk) — unchanged.
    return {
        "id": row.get("id"),
        "type": "email",  # portal invites are emails
        "occurred_at": row.get("timestamp") or "",
        "actor_label": label,
        "actor_kind": kind,
        "actor_user_id": actor_user_id,
        "direction": "outbound",
        "channel_id": row.get("id"),
        "subject": "Portal invite",
        "body_preview": _preview(
            f"Bulk portal invite fired by {label}. "
            f"Sent to {payload.get('sent', 0)} customer(s); "
            f"skipped {payload.get('skipped_already_activated', 0)} already "
            "active."
        ),
        "recipient": "",  # not stored on audit_events
        "delivery_status": "sent" if payload.get("sent") else "failed",
        "delivery_error": row.get("reason") or None,
    }


def _strip_admin_fields(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Portal role: never leak actor_user_id + delivery_error over
    the wire.  Applied server-side so a frontend regression can't
    accidentally surface them."""
    stripped = []
    for it in items:
        clean = dict(it)
        clean.pop("actor_user_id", None)
        clean.pop("delivery_error", None)
        stripped.append(clean)
    return stripped


@router.get("/customers/{customer_id}/communication-timeline")
async def communication_timeline(
    customer_id: str,
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    before: Optional[str] = Query(None),
    types: Optional[str] = Query(None,
                                       description="csv: sms,email"),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").lower()
    if role in _TECH_ROLES:
        raise HTTPException(403, "Technicians cannot access comms timeline")
    is_admin = role in _ADMIN_ROLES
    is_customer = role == "customer"
    if is_customer and user.get("customer_id") != customer_id:
        raise HTTPException(403, "Not allowed")
    if not (is_admin or is_customer):
        raise HTTPException(403, "Not allowed")

    customer = await _load_customer(customer_id, tenant["id"])
    emails, phones = _customer_addresses(customer)

    wanted_types = None
    if types:
        wanted_types = {t.strip().lower() for t in types.split(",")
                             if t.strip()}

    # ── notification_dispatch_log ─────────────────────────────────
    dispatch_filter: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "$or": [
            {"recipient_id": customer_id},
        ],
    }
    if emails or phones:
        dispatch_filter["$or"].append(
            {"resolved_address": {"$in": emails + phones}},
        )
    if wanted_types:
        dispatch_filter["channel"] = {"$in": list(wanted_types)}
    if before:
        dispatch_filter["$and"] = [
            {"$or": [{"sent_at": {"$lt": before}},
                        {"sent_at": None,
                             "reserved_at": {"$lt": before}}]},
        ]
    dispatch_rows: List[Dict[str, Any]] = []
    async for r in db.notification_dispatch_log.find(
        dispatch_filter, {"_id": 0},
    ).sort([("sent_at", -1), ("reserved_at", -1)]).limit(_MAX_PER_COLLECTION):
        dispatch_rows.append(r)

    # ── audit_events (portal_invite_bulk + K6 job_edited) ────────
    audit_rows: List[Dict[str, Any]] = []
    # Phase K6 · Feb-2026 — the timeline surfaces audit rows when
    # the caller either doesn't filter by type OR asks for "email"
    # (portal invites) or "job_edited" (K6 completion edits).
    # Phase K14 · Feb-2026 — "payment" (invoice_auto_charged) joined.
    include_audit = (wanted_types is None) or bool(
        set(wanted_types) & {"email", "job_edited", "payment"})
    if include_audit:
        audit_filter: Dict[str, Any] = {
            "tenant_id": tenant["id"],
            "event_type": {"$in": list(_AUDIT_EVENT_TYPES)},
            "$or": [
                {"payload.customer_ids": customer_id},
                {"payload.customer_id": customer_id},
            ],
        }
        if before:
            audit_filter["timestamp"] = {"$lt": before}
        async for r in db.audit_events.find(
            audit_filter, {"_id": 0},
        ).sort("timestamp", -1).limit(_MAX_PER_COLLECTION):
            audit_rows.append(r)

    # ── Merge + sort desc ────────────────────────────────────────
    items = [_dispatch_to_item(r) for r in dispatch_rows]
    items += [_audit_to_item(r) for r in audit_rows]
    items.sort(key=lambda i: i["occurred_at"] or "", reverse=True)

    # Pagination cursor: return one extra row to detect ``has_more``.
    page = items[:limit]
    has_more = len(items) > limit
    next_before = page[-1]["occurred_at"] if (has_more and page) else None

    if is_customer:
        page = _strip_admin_fields(page)

    return {
        "customer_id": customer_id,
        "items": page,
        "has_more": has_more,
        "next_before": next_before,
    }


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Customer Communication Timeline — full history endpoints
# ═══════════════════════════════════════════════════════════════════════
# Two new endpoints, one shared merge helper (no fork):
#   * ``GET /api/customers/{id}/timeline``      — admin/manager
#   * ``GET /api/customers/me/timeline``        — customer session
#
# Pulls from THREE sources filtered by customer_id + tenant, merges
# into a single chronological feed, sorted ``created_at DESC``:
#
#   1. ``marketing_deliveries`` — every email/SMS delivery record
#      (kind ∈ {"email","sms"} based on ``channel``).
#   2. ``quotes`` where ``doc_type == "invoice"``     — invoice history.
#   3. ``quotes`` where ``doc_type != "invoice"``     — estimate history
#      (the historical single-collection convention in this codebase;
#      the dedicated ``estimates`` collection sits mostly empty except
#      for a small legacy backfill).
#
# Dedup rule: ``(ref_type, ref_id)`` — a single marketing_delivery row
# for an invoice send never renders twice when the invoice send hook
# and the delivery log both fire. Marketing wins on tie (it carries
# the delivery status).
#
# Portal filter — customer session can only see their OWN records.
# Marketing rows: matched by ``customer_id`` OR ``recipient_address``
# in the customer's known emails/phones. Quote rows: matched by
# ``customer_id`` (strict).
# ═══════════════════════════════════════════════════════════════════════

_TIMELINE_ALLOWED_KINDS = {"email", "sms", "invoice", "estimate"}
_TIMELINE_DEFAULT_PAGE_SIZE = 20
_TIMELINE_MAX_PAGE_SIZE = 100
_TIMELINE_HARD_CAP = 500


def _parse_kinds(csv: Optional[str]) -> Optional[set]:
    """Parse a ``kind`` query CSV → validated set. ``None`` = no
    filter (return all four kinds)."""
    if not csv:
        return None
    parts = {p.strip().lower() for p in csv.split(",") if p.strip()}
    parts &= _TIMELINE_ALLOWED_KINDS
    return parts or None


def _iso_bounds(from_: Optional[str], to_: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Turn ``from``/``to`` YYYY-MM-DD query params into ISO bounds.
    ``to`` is padded to end-of-day (23:59:59) so the range is
    inclusive at both ends — same convention as the customer
    service-reports list."""
    _from = None
    _to = None
    if from_:
        _from = f"{from_[:10]}T00:00:00+00:00"
    if to_:
        _to = f"{to_[:10]}T23:59:59+00:00"
    return _from, _to


def _make_url(kind: str, ref_id: str, role: str) -> str:
    """Return a client-facing deep link for an invoice / estimate row.
    Admin timeline → admin viewer path; customer portal → portal
    viewer path. Marketing deliveries return an empty string
    (no dedicated viewer)."""
    if kind == "invoice":
        return f"/portal/invoices/{ref_id}" if role == "customer" else f"/invoices/{ref_id}"
    if kind == "estimate":
        return f"/portal/estimates/{ref_id}" if role == "customer" else f"/quotes/{ref_id}"
    return ""


async def _marketing_deliveries_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
) -> List[Dict[str, Any]]:
    """Pull the customer's email + SMS deliveries."""
    channel_filters = []
    if wanted_kinds is None or "email" in wanted_kinds:
        channel_filters.append("email")
    if wanted_kinds is None or "sms" in wanted_kinds:
        channel_filters.append("sms")
    if not channel_filters:
        return []

    emails, phones = _customer_addresses(customer)
    _or: List[Dict[str, Any]] = [{"customer_id": customer["id"]}]
    if emails:
        _or.append({"recipient_address": {"$in": emails}})
        _or.append({"recipient_email": {"$in": emails}})
    if phones:
        _or.append({"recipient_address": {"$in": phones}})
    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "channel":   {"$in": channel_filters},
        "$or":       _or,
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["created_at"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.marketing_deliveries.find(query, {"_id": 0}) \
            .sort("created_at", -1).limit(_TIMELINE_HARD_CAP):
        kind = "sms" if (r.get("channel") or "").lower() == "sms" else "email"
        trig = r.get("trigger_entity") or {}
        items.append({
            "kind":            kind,
            "subject":         r.get("subject") or "",
            "template_name":   r.get("template_code") or "",
            "delivery_status": r.get("delivery_status")
                                or r.get("provider_status") or "unknown",
            "created_at":      r.get("created_at") or "",
            "ref_type":        "marketing_delivery",
            "ref_id":          r.get("id") or "",
            "recipient":       r.get("recipient_address")
                                or r.get("recipient_email") or "",
            "trigger_kind":    r.get("trigger_kind") or "",
            "related_ref":     ({"kind": trig.get("kind"),
                                    "id":   trig.get("id")}
                                    if isinstance(trig, dict) and trig else None),
            "url":             "",
        })
    return items


async def _quotes_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """Pull the customer's invoice + estimate rows from ``quotes``."""
    want_invoice  = wanted_kinds is None or "invoice"  in wanted_kinds
    want_estimate = wanted_kinds is None or "estimate" in wanted_kinds
    if not (want_invoice or want_estimate):
        return []

    query: Dict[str, Any] = {
        "tenant_id":   tenant_id,
        "customer_id": customer["id"],
        "$or":         [{"deleted_at": {"$exists": False}},
                          {"deleted_at": None}],
    }
    if want_invoice and want_estimate:
        pass  # no doc_type filter — return everything not deleted.
    elif want_invoice:
        query["doc_type"] = "invoice"
    else:
        query["doc_type"] = {"$ne": "invoice"}

    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["created_at"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.quotes.find(query, {"_id": 0}) \
            .sort("created_at", -1).limit(_TIMELINE_HARD_CAP):
        dt = (r.get("doc_type") or "").lower()
        kind = "invoice" if dt == "invoice" else "estimate"
        number = r.get("number") or r.get("invoice_number") \
            or (r.get("id") or "")[:8]
        subject = ("Invoice #" if kind == "invoice" else "Estimate #") + str(number)
        ref_id = r.get("id") or ""
        items.append({
            "kind":            kind,
            "subject":         subject,
            "template_name":   "",
            "delivery_status": r.get("status") or "",
            "payment_status":  r.get("payment_status") or "",
            "total":           r.get("total") or 0,
            "created_at":      r.get("created_at") or "",
            "ref_type":        kind,
            "ref_id":          ref_id,
            "url":             _make_url(kind, ref_id, role),
            "recipient":       "",
        })
    return items


def _dedupe_by_ref(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedup by ``(ref_type, ref_id)`` — first occurrence wins.
    Additionally suppresses a raw invoice/estimate row when a
    marketing_delivery row already surfaced the SAME ref via
    ``related_ref`` — the delivery entry carries send status and
    is the canonical timeline card for the send event.
    """
    marketing_refs = set()
    for m in items:
        rel = m.get("related_ref") or {}
        rk = (rel.get("kind") or "").lower()
        ri = rel.get("id")
        if rk in ("invoice", "estimate", "quote") and ri:
            marketing_refs.add(("invoice" if rk == "invoice" else "estimate", ri))
    seen_refs = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        key = (it.get("ref_type"), it.get("ref_id"))
        if key in seen_refs:
            continue
        if it.get("ref_type") in ("invoice", "estimate"):
            if (it.get("ref_type"), it.get("ref_id")) in marketing_refs:
                continue
        seen_refs.add(key)
        out.append(it)
    return out


async def _build_full_timeline(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_: Optional[str], to_: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """Shared merge helper for the admin + portal endpoints."""
    from_iso, to_iso = _iso_bounds(from_, to_)
    marketing = await _marketing_deliveries_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso,
    )
    quote_items = await _quotes_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso, role,
    )
    merged = marketing + quote_items
    merged.sort(key=lambda i: i.get("created_at") or "", reverse=True)
    return _dedupe_by_ref(merged)


async def _paginated_timeline_response(
    customer: Dict[str, Any], tenant_id: str,
    kind: Optional[str],
    from_: Optional[str], to_: Optional[str],
    page: int, page_size: int,
    role: str,
) -> Dict[str, Any]:
    wanted = _parse_kinds(kind)
    all_items = await _build_full_timeline(
        customer, tenant_id, wanted, from_, to_, role,
    )
    total = len(all_items)
    page_size = max(1, min(page_size, _TIMELINE_MAX_PAGE_SIZE))
    page = max(1, page)
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 0
    start = (page - 1) * page_size
    slice_ = all_items[start:start + page_size]
    return {
        "items":       slice_,
        "page":        page,
        "page_size":   page_size,
        "total":       total,
        "total_pages": total_pages,
    }


@router.get("/customers/me/timeline")
async def customer_portal_timeline(
    page: int = Query(1, ge=1),
    page_size: int = Query(_TIMELINE_DEFAULT_PAGE_SIZE, ge=1,
                             le=_TIMELINE_MAX_PAGE_SIZE),
    kind: Optional[str] = Query(None,
                                     description="csv: email,sms,invoice,estimate"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Full communication history for the current customer session.

    Customer role only. Never mounts admin-only fields on the wire
    (the merge helper never emits ``actor_user_id`` /
    ``delivery_error`` — those live only on the legacy
    ``/communication-timeline`` endpoint).
    """
    role = (user.get("role") or "").lower()
    if role != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customer portal only")
    customer = await _load_customer(user["customer_id"], tenant["id"])
    return await _paginated_timeline_response(
        customer, tenant["id"], kind, from_, to, page, page_size, role,
    )


@router.get("/customers/{customer_id}/timeline")
async def admin_customer_timeline(
    customer_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(_TIMELINE_DEFAULT_PAGE_SIZE, ge=1,
                             le=_TIMELINE_MAX_PAGE_SIZE),
    kind: Optional[str] = Query(None,
                                     description="csv: email,sms,invoice,estimate"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Full customer communication history — admin/manager only.

    Merges marketing_deliveries + invoices + estimates into a single
    chronological feed. Response shape:
    ``{items, page, page_size, total, total_pages}``.
    """
    role = (user.get("role") or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin timeline only")
    customer = await _load_customer(customer_id, tenant["id"])
    return await _paginated_timeline_response(
        customer, tenant["id"], kind, from_, to, page, page_size, role,
    )
