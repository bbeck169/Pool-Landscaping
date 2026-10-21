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


# TD-98-be-sources · Fork (b) rewrite · Phase-B shape helpers below
# supersede the legacy ``_dispatch_to_item`` / ``_audit_to_item`` /
# ``_strip_admin_fields`` triplet that was preserved on the retired
# endpoint. Those three helpers had zero live callers after this
# ship and are now DELETED; retrievable from ``2f22725e1^`` if the
# operator ever wants to A/B against the legacy shape. The still-
# load-bearing primitives (``_load_customer`` + ``_customer_addresses``
# + ``_preview``) remain as module-level utilities below — they are
# called by multiple Phase-B helpers (``_marketing_deliveries_to_items``
# uses ``_customer_addresses``; ``_job_notes_to_items`` +
# ``_customer_notes_to_items`` use ``_preview``; ``_build_full_timeline``
# uses ``_load_customer``), so the operator-dispatch "delete all 6"
# instruction was reality-checked down to "delete the 3 orphan
# helpers" during the Phase 2 ship.


@router.get(
    "/customers/{customer_id}/communication-timeline",
    include_in_schema=False,
    deprecated=True,
)
async def communication_timeline_retired(
    customer_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """TD-98-be-cleanup-retire · Feb-2026.

    The legacy per-customer communication-timeline endpoint has been
    retired. All known FE/mobile consumers migrated to
    ``GET /customers/{cid}/timeline`` (Phase B super-timeline) by
    `db6edd59f` (mobile adapter) + `e0bc500ae` (mobile component)
    + web ship `td98b-fe` (`CustomerDetail.jsx` CustomerFullTimeline
    mount) + `e0bc500ae` (mobile portal/messages migration).

    Three source types that this endpoint used to surface do NOT
    have a replacement reader on the Phase B super-timeline:
      * ``notification_dispatch_log`` dispatch rows.
      * ``audit_events`` with event_type ∈ ``_AUDIT_EVENT_TYPES``
        (portal_invite_bulk, K6 job_edited, K14 invoice_auto_charged).
      * ``delivery_error`` field on dispatch rows.
    Operator-approved regression per TD-98/99 close-out; the gap is
    bookmarked as **TD-98-be-sources (P2 backend)** in TECH_DEBT.md
    for history-preservation migration into the super-timeline when
    operator approves that ticket. See
    ``memory/td98_99_combined_communication_timeline_audit.md`` and
    the TD-98-be-cleanup-retire ship commit message.

    The ``_load_customer``, ``_customer_addresses``, and ``_preview``
    helpers above remain as module-level primitives for the Phase-B
    super-timeline helpers below. ``_dispatch_to_item``,
    ``_audit_to_item``, and ``_strip_admin_fields`` were deleted
    during the TD-98-be-sources Fork (b) rewrite (ship notes:
    recoverable from ``2f22725e1^`` if ever needed).
    """
    raise HTTPException(
        410,
        "Endpoint retired · migrate to GET /customers/{cid}/timeline · "
        "see TD-98-be-cleanup-retire + TD-98-be-sources (P2 candidate)",
    )


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

_TIMELINE_ALLOWED_KINDS = {"email", "sms", "invoice", "estimate",
                             "call", "note"}
_TIMELINE_DEFAULT_PAGE_SIZE = 20
_TIMELINE_MAX_PAGE_SIZE = 100
_TIMELINE_HARD_CAP = 500
# Phase B · Feb-2026 — Super Timeline. The extra two sources (call
# logs + internal job notes) are gated to admin/super_admin only.
# Manager sessions keep the pre-B 4-source view — no regression.
_FULL_TIMELINE_ROLES = {"admin", "super_admin"}


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


# ═════════════════════════════════════════════════════════════════════
# Phase B · Feb-2026 — Super Timeline aggregator additions
# (call_logs + internal job notes). Every new pull returns items in
# the D5-shape (kind, created_at, ref_type/ref_id, url, subject...)
# so the merge helper doesn't care whether an item came from the
# legacy pulls or the new ones. Callers then normalise the merged
# list via ``_normalise_existing_item`` which adds the B-required
# ``source_type / occurred_at / summary / detail / actor / id``
# fields WITHOUT renaming the legacy ones (backwards-compat).
# ═════════════════════════════════════════════════════════════════════


def _coerce_utc_iso(raw: Any) -> str:
    """Normalise any timestamp shape → ISO-8601 UTC string.

    Accepts:
      * ``str`` — already ISO-ish; coerce to UTC via
        ``datetime.fromisoformat`` (add ``+00:00`` when no offset
        present).
      * ``datetime`` — attach UTC when naive; convert to UTC when
        aware.
      * ``None`` / anything else → ``""``.
    """
    from datetime import datetime as _dt, timezone as _tz
    if raw is None:
        return ""
    if isinstance(raw, _dt):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=_tz.utc).isoformat()
        return raw.astimezone(_tz.utc).isoformat()
    s = str(raw).strip()
    if not s:
        return ""
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        parsed = _dt.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_tz.utc)
        return parsed.astimezone(_tz.utc).isoformat()
    except Exception:  # noqa: BLE001
        return s


def _format_duration(seconds: Any) -> str:
    """``123`` → ``"2m 3s"``; ``59`` → ``"59s"``; ``0`` → ``"0s"``."""
    try:
        n = int(seconds or 0)
    except Exception:  # noqa: BLE001
        return ""
    if n < 0:
        n = 0
    if n < 60:
        return f"{n}s"
    m, s = divmod(n, 60)
    return f"{m}m {s}s" if s else f"{m}m"


async def _resolve_display_name(
    user_id: Optional[str], tenant_id: str,
) -> Tuple[str, str]:
    """Return ``(display_name, role)`` for a user id.  Empty strings
    when the id doesn't resolve. Used by note-actor mapping."""
    if not user_id:
        return "", ""
    u = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "role": 1},
    )
    if not u:
        return "", ""
    name = (
        u.get("name")
        or " ".join([u.get("first_name") or "",
                       u.get("last_name") or ""]).strip()
        or ""
    )
    return name, (u.get("role") or "").lower()


async def _call_logs_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
) -> List[Dict[str, Any]]:
    """Pull the customer's ``call_logs`` rows (read-only)."""
    if wanted_kinds is not None and "call" not in wanted_kinds:
        return []
    # Tenant hygiene — every call_log carries a tenant_id; the
    # filter excludes cross-tenant rows even when the customer id
    # happens to collide across tenants.
    query: Dict[str, Any] = {
        "tenant_id":   tenant_id,
        "customer_id": customer["id"],
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["started_at"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.call_logs.find(query, {"_id": 0}) \
            .sort("started_at", -1).limit(_TIMELINE_HARD_CAP):
        direction = (r.get("direction") or "").lower()
        other_party = (r.get("from_number") if direction == "inbound"
                        else r.get("to_number"))
        summary_parts = ["Inbound call" if direction == "inbound"
                          else "Outbound call"]
        if other_party:
            summary_parts.append(f"with {other_party}")
        dur_str = _format_duration(r.get("duration"))
        if dur_str and dur_str != "0s":
            summary_parts.append(f"· {dur_str}")
        occurred = _coerce_utc_iso(
            r.get("started_at") or r.get("created_at"))
        items.append({
            "id":          r.get("id") or r.get("session_id") or "",
            "source_type": "call",
            "occurred_at": occurred,
            "summary":     " ".join(summary_parts),
            "detail": {
                "direction":     direction or "unknown",
                "from_number":   r.get("from_number") or "",
                "to_number":     r.get("to_number") or "",
                "other_party":   other_party or "",
                "duration_sec":  r.get("duration") or 0,
                "duration":      dur_str,
                "recording_url": r.get("recording_url") or "",
                "disposition":   r.get("disposition") or "",
                "session_id":    r.get("session_id") or "",
                "customer_name": r.get("customer_name") or "",
            },
            "actor": None,
            # Legacy shape (backwards-compat).
            "kind":       "call",
            "subject":    " ".join(summary_parts),
            "created_at": occurred,
            "ref_type":   "call_log",
            "ref_id":     r.get("id") or "",
            "url":        "",
            "recipient":  other_party or "",
        })
    return items


def _note_item(
    *, note_id: str, occurred_at: str, body: str, job_id: str,
    service_type: str, actor: Optional[Dict[str, str]],
    note_kind: str,
) -> Dict[str, Any]:
    """Build a normalised ``source_type=note`` timeline item."""
    preview = _preview(body, n=140)
    label = "Internal note" if note_kind == "internal" else "Job note"
    if service_type:
        label = f"{label} · {service_type}"
    return {
        "id":          note_id,
        "source_type": "note",
        "occurred_at": occurred_at,
        "summary":     f"{label}: {preview}"
                          + ("…" if len(body) > 140 else ""),
        "detail": {
            "note_body":    body,
            "note_kind":    note_kind,
            "job_id":       job_id,
            "service_type": service_type,
        },
        "actor": actor,
        "kind":       "note",
        "subject":    label,
        "created_at": occurred_at,
        "ref_type":   "job_note",
        "ref_id":     note_id,
        "url":        f"/jobs/{job_id}" if job_id else "",
        "recipient":  "",
    }


async def _job_notes_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
) -> List[Dict[str, Any]]:
    """Pull internal notes attached to the customer's jobs.

    Handles both shapes:
      * Structured array — ``job.notes = [{id, body, author_id,
        created_at, ...}, ...]``.
      * Legacy string — ``job.notes = "one-liner"`` (production
        shape per ``seed.py``). Treated as ONE note authored at
        ``job.created_at`` by ``job.created_by``.
      * ``job.internal_notes`` (admin-only string) — a SECOND note
        item per job when non-empty (kind=``internal``).
    """
    if wanted_kinds is not None and "note" not in wanted_kinds:
        return []
    query: Dict[str, Any] = {
        "tenant_id":   tenant_id,
        "customer_id": customer["id"],
    }
    items: List[Dict[str, Any]] = []
    _author_cache: Dict[str, Tuple[str, str]] = {}

    async def _actor(uid: Optional[str]) -> Optional[Dict[str, str]]:
        if not uid:
            return None
        if uid not in _author_cache:
            _author_cache[uid] = await _resolve_display_name(uid, tenant_id)
        name, role = _author_cache[uid]
        if not name:
            return None
        return {"id": uid, "display_name": name, "role": role}

    def _in_range(ts_iso: str) -> bool:
        if not (from_iso or to_iso):
            return True
        if from_iso and ts_iso and ts_iso < from_iso:
            return False
        if to_iso and ts_iso and ts_iso > to_iso:
            return False
        return True

    async for job in db.jobs.find(query, {
        "_id": 0, "id": 1, "notes": 1, "internal_notes": 1,
        "created_at": 1, "created_by": 1, "assigned_technician_id": 1,
        "service_type": 1,
    }):
        job_id = job.get("id") or ""
        job_created = _coerce_utc_iso(job.get("created_at"))
        default_author = job.get("created_by") or \
            job.get("assigned_technician_id")

        # ── (a) structured note array ────────────────────────────
        notes_field = job.get("notes")
        if isinstance(notes_field, list):
            for n in notes_field:
                if not isinstance(n, dict):
                    body = str(n or "").strip()
                    if not body:
                        continue
                    occurred = job_created
                    if not _in_range(occurred):
                        continue
                    items.append(_note_item(
                        note_id=f"{job_id}-note-{len(items)}",
                        occurred_at=occurred, body=body,
                        job_id=job_id,
                        service_type=job.get("service_type") or "",
                        actor=await _actor(default_author),
                        note_kind="visit",
                    ))
                    continue
                body = str(
                    n.get("body") or n.get("note_body")
                    or n.get("note") or n.get("text") or ""
                ).strip()
                if not body:
                    continue
                occurred = _coerce_utc_iso(
                    n.get("created_at") or n.get("timestamp")
                    or job_created
                )
                if not _in_range(occurred):
                    continue
                items.append(_note_item(
                    note_id=str(n.get("id")
                                  or f"{job_id}-note-{len(items)}"),
                    occurred_at=occurred, body=body,
                    job_id=job_id,
                    service_type=job.get("service_type") or "",
                    actor=await _actor(
                        n.get("author_id") or default_author),
                    note_kind=str(n.get("kind") or "visit"),
                ))
        elif isinstance(notes_field, str) and notes_field.strip():
            occurred = job_created
            if _in_range(occurred):
                items.append(_note_item(
                    note_id=f"{job_id}-note-body",
                    occurred_at=occurred,
                    body=notes_field.strip(),
                    job_id=job_id,
                    service_type=job.get("service_type") or "",
                    actor=await _actor(default_author),
                    note_kind="visit",
                ))

        # ── (b) job.internal_notes admin-only string ─────────────
        internal = job.get("internal_notes")
        if isinstance(internal, str) and internal.strip():
            occurred = job_created
            if _in_range(occurred):
                items.append(_note_item(
                    note_id=f"{job_id}-note-internal",
                    occurred_at=occurred,
                    body=internal.strip(),
                    job_id=job_id,
                    service_type=job.get("service_type") or "",
                    actor=await _actor(default_author),
                    note_kind="internal",
                ))

    return items


# ─── Phase M1 · Feb-2026 — customer-scoped ``notes`` timeline source
async def _customer_notes_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
) -> List[Dict[str, Any]]:
    """Pull system + admin notes attached directly to the customer
    (as opposed to job-attached notes handled by
    :func:`_job_notes_to_items`). Currently populated by the merge
    wizard (``services.customer_merge.wizard``); the collection is
    intentionally generic so future admin-note surfaces can reuse
    it.
    """
    if wanted_kinds is not None and "note" not in wanted_kinds:
        return []
    query: Dict[str, Any] = {
        "tenant_id":   tenant_id,
        "customer_id": customer["id"],
    }
    items: List[Dict[str, Any]] = []
    async for n in db.customer_notes.find(query, {"_id": 0}):
        occurred = _coerce_utc_iso(
            n.get("occurred_at") or n.get("created_at"))
        if from_iso and occurred and occurred < from_iso:
            continue
        if to_iso and occurred and occurred > to_iso:
            continue
        author_id = n.get("author_id") or ""
        actor = None
        if author_id and author_id != "unknown":
            name, role = await _resolve_display_name(author_id, tenant_id)
            if name:
                actor = {"id": author_id, "display_name": name,
                            "role": role}
        body = str(n.get("body") or "").strip()
        if not body:
            continue
        note_kind = str(n.get("note_kind") or "admin")
        label = ("System · Customer merged"
                 if note_kind == "system_merge"
                 else "Customer note")
        preview = _preview(body, n=140)
        items.append({
            "id":          n.get("id") or f"cn-{len(items)}",
            "source_type": "note",
            "occurred_at": occurred,
            "summary":     f"{label}: {preview}"
                              + ("…" if len(body) > 140 else ""),
            "detail": {
                "note_body":    body,
                "note_kind":    note_kind,
                "customer_id":  customer["id"],
            },
            "actor":      actor,
            "kind":       "note",
            "subject":    label,
            "created_at": occurred,
            "ref_type":   "customer_note",
            "ref_id":     n.get("id") or "",
            "url":        "",
            "recipient":  "",
        })
    return items


# ═════════════════════════════════════════════════════════════════════
# TD-98/99-xref · Feb-2026 — Cross-visibility aggregator
# Surface pre-conversion lead-era comms (SMS + email + inbound SMS)
# on the converted customer's super-timeline. Join via reverse
# lookup: ``leads.find({converted_customer_id: cid, tenant_id})``
# → ``$in`` on ``lead_communications.lead_id`` and
# ``sms_inbound.matched_lead_id``.
# Edge cases:
#   * Multi-lead-to-one-customer (merge branch of
#     ``_run_close_won_pipeline``) handled naturally by ``$in``.
#   * Hard-deleted leads cannot sever the join —
#     ``_hard_delete_lead`` refuses converted leads at
#     ``routers/leads.py:1274``.
#   * Zero converted leads → helpers short-circuit (empty ``$in``)
#     with no DB roundtrip past the empty list check.
#   * Tenant isolation preserved at BOTH the reverse-lookup query
#     AND the ``$in`` collection query.
# Portal-safety: helpers never emit ``actor_user_id`` or
# ``delivery_error`` top-level — admin provenance
# (``sent_by_user_id``) is normalized into the ``actor`` object via
# ``_resolve_display_name`` which the Phase B pipeline already
# treats as portal-safe.
# ═════════════════════════════════════════════════════════════════════
async def _converted_lead_ids_for_customer(
    customer_id: str, tenant_id: str,
) -> List[str]:
    """Reverse-lookup for all leads converted to this customer in
    this tenant. Returns empty list when the customer has no
    pre-conversion lead history (never-was-a-lead path)."""
    lead_ids: List[str] = []
    async for lead in db.leads.find(
        {"tenant_id": tenant_id, "converted_customer_id": customer_id},
        {"_id": 0, "id": 1},
    ):
        lid = lead.get("id")
        if lid:
            lead_ids.append(lid)
    return lead_ids


async def _lead_communications_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """TD-98/99-xref · lead-era outbound SMS + email surfacing on the
    converted customer's super-timeline. Writes stay lead-scoped
    (TD-96 §6 touch-map); this read joins via
    ``leads.converted_customer_id``."""
    want_sms = wanted_kinds is None or "sms" in wanted_kinds
    want_email = wanted_kinds is None or "email" in wanted_kinds
    if not (want_sms or want_email):
        return []

    lead_ids = await _converted_lead_ids_for_customer(
        customer["id"], tenant_id,
    )
    if not lead_ids:
        return []

    channel_filters: List[str] = []
    if want_sms:
        channel_filters.append("sms")
    if want_email:
        channel_filters.append("email")

    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "lead_id":   {"$in": lead_ids},
        "channel":   {"$in": channel_filters},
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["created_at"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.lead_communications.find(query, {"_id": 0}) \
            .sort("created_at", -1).limit(_TIMELINE_HARD_CAP):
        channel = (r.get("channel") or "").lower()
        kind = "sms" if channel == "sms" else "email"
        rid = r.get("id") or ""
        items.append({
            "kind":            kind,
            "subject":         r.get("subject") or "",
            "template_name":   "",
            "delivery_status": r.get("status") or "queued",
            "created_at":      r.get("created_at") or "",
            "ref_type":        "lead_communication",
            "ref_id":          rid,
            "recipient":       r.get("to_identity") or "",
            "trigger_kind":    "",
            "related_ref":     {"kind": "lead",
                                  "id":   r.get("lead_id") or ""},
            "url":             "",
            # Pre-populated body so FE DefaultRow + the shared
            # CommunicationDetailModal both work without an extra
            # fetch. Portal path strips nothing additional — body
            # was already visible to the recipient at send time.
            "body":            r.get("body") or "",
        })
    return items


async def _lead_inbound_sms_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
) -> List[Dict[str, Any]]:
    """TD-98/99-xref · lead-era inbound SMS (from ``sms_inbound``
    matched to the converted lead) surfacing on the customer
    super-timeline."""
    if wanted_kinds is not None and "sms" not in wanted_kinds:
        return []

    lead_ids = await _converted_lead_ids_for_customer(
        customer["id"], tenant_id,
    )
    if not lead_ids:
        return []

    query: Dict[str, Any] = {
        "tenant_id":       tenant_id,
        "matched_lead_id": {"$in": lead_ids},
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["received_at"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.sms_inbound.find(query, {"_id": 0}) \
            .sort("received_at", -1).limit(_TIMELINE_HARD_CAP):
        rid = r.get("id") or ""
        items.append({
            "kind":            "sms",
            "subject":         "",
            "template_name":   "",
            "delivery_status": "received",
            "created_at":      r.get("received_at") or "",
            "ref_type":        "lead_sms_inbound",
            "ref_id":          rid,
            "recipient":       r.get("from_identity")
                                or r.get("from_number") or "",
            "trigger_kind":    "",
            "related_ref":     {"kind": "lead",
                                  "id":   r.get("matched_lead_id") or ""},
            "url":             "",
            "body":            r.get("message_text")
                                or r.get("body") or "",
        })
    return items


def _normalise_existing_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if "source_type" in item and "occurred_at" in item:
        return item
    kind = (item.get("kind") or "").lower()
    src = {"email": "email", "sms": "sms",
           "invoice": "invoice", "estimate": "quote",
           "call": "call", "note": "note"}.get(kind, kind or "unknown")
    occurred = _coerce_utc_iso(item.get("created_at"))
    subj = item.get("subject") or ""
    stat = item.get("delivery_status") or item.get("payment_status") or ""
    summary_bits = [p for p in (subj, stat) if p]
    detail = {
        "recipient":       item.get("recipient") or "",
        "template_name":   item.get("template_name") or "",
        "delivery_status": item.get("delivery_status") or "",
        "payment_status":  item.get("payment_status") or "",
        "total":           item.get("total") or 0,
        "trigger_kind":    item.get("trigger_kind") or "",
        "related_ref":     item.get("related_ref") or None,
        "url":             item.get("url") or "",
    }
    item.setdefault("id", item.get("ref_id") or "")
    item["source_type"] = src
    item["occurred_at"] = occurred
    item.setdefault("summary", " · ".join(summary_bits))
    item.setdefault("detail", detail)
    item.setdefault("actor", None)
    return item



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


async def _notification_dispatch_log_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """TD-98-be-sources · Phase-B shape rewrite of the legacy
    ``_dispatch_to_item`` reader. Surfaces ``notification_dispatch_log``
    rows (transactional sends — service-report emails, on-my-way SMS,
    F7 idempotent notifier output) as super-timeline items.

    Portal visibility: **YES** (customers see their own transactional
    notifications). ``delivery_error`` and ``actor_user_id`` are
    emitted top-level only when ``role in _FULL_TIMELINE_ROLES``;
    portal callers get the item with those fields stripped at source
    (never emitted → zero chance of accidental leak downstream).
    """
    want_sms = wanted_kinds is None or "sms" in wanted_kinds
    want_email = wanted_kinds is None or "email" in wanted_kinds
    if not (want_sms or want_email):
        return []

    emails, phones = _customer_addresses(customer)
    channel_filters: List[str] = []
    if want_sms:
        channel_filters.append("sms")
    if want_email:
        channel_filters.append("email")

    # Legacy ``$or`` on ``(recipient_id, resolved_address)`` preserved
    # verbatim from the retired endpoint. ``resolved_address`` match
    # catches sends keyed off customer email/phone when
    # ``recipient_id`` was not resolved at dispatch time.
    or_clauses: List[Dict[str, Any]] = [{"recipient_id": customer["id"]}]
    if emails or phones:
        or_clauses.append({"resolved_address": {"$in": emails + phones}})

    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "channel":   {"$in": channel_filters},
        "$or":       or_clauses,
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["sent_at"] = _range

    is_admin = role in _FULL_TIMELINE_ROLES
    items: List[Dict[str, Any]] = []
    async for r in db.notification_dispatch_log.find(query, {"_id": 0}) \
            .sort([("sent_at", -1), ("reserved_at", -1)]) \
            .limit(_TIMELINE_HARD_CAP):
        channel = (r.get("channel") or "").lower()
        kind = "sms" if channel == "sms" else "email"
        rid = r.get("id") or r.get("dedupe_key") or ""
        meta = r.get("metadata") or {}
        occurred = r.get("sent_at") or r.get("reserved_at") or ""
        body = (meta.get("body") or meta.get("message")
                or r.get("subject") or "")
        actor_user_id = meta.get("actor_user_id") or meta.get("user_id")
        item: Dict[str, Any] = {
            "kind":            kind,
            "subject":         r.get("subject") or "",
            "template_name":   r.get("template_name") or "",
            "delivery_status": r.get("status") or "queued",
            "created_at":      occurred,
            "ref_type":        "notification_dispatch",
            "ref_id":          rid,
            "recipient":       r.get("resolved_address") or "",
            "trigger_kind":    r.get("trigger_kind") or "",
            "related_ref":     None,
            "url":             "",
            "body":            _preview(body),
        }
        if is_admin:
            # Admin surface only. Portal path never sees these — no
            # downstream strip required because they're never emitted.
            if r.get("error"):
                item["delivery_error"] = r.get("error")
            if actor_user_id:
                item["actor_user_id"] = actor_user_id
        items.append(item)
    return items


# TD-98-be-sources portal-visibility split per audit §4.d.
#   portal_invite_bulk          → admin-only (back-office op).
#   job_edited_after_completion → admin-only (K6 provenance).
#   invoice_auto_charged        → portal YES (customer's own charge).
_AUDIT_EVENT_PORTAL_VISIBLE = frozenset({"invoice_auto_charged"})


async def _audit_events_to_items(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_iso: Optional[str], to_iso: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """TD-98-be-sources · Phase-B shape rewrite of the legacy
    ``_audit_to_item`` reader. Surfaces ``audit_events`` rows whose
    ``event_type ∈ _AUDIT_EVENT_TYPES`` (portal invite bulk / K6 job
    edited after completion / K14 invoice auto-charged) as super-
    timeline items.

    Event-type → ``kind`` mapping per audit §4.b default (α):
      - ``portal_invite_bulk``          → kind=email
      - ``job_edited_after_completion`` → kind=note
      - ``invoice_auto_charged``        → kind=note

    Portal visibility is filtered PER EVENT TYPE at the helper level
    (``_AUDIT_EVENT_PORTAL_VISIBLE`` whitelist) — matches the TD-98/99-
    xref posture of "customer's own interactions visible; admin audit
    on their account admin-only".
    """
    want_email = wanted_kinds is None or "email" in wanted_kinds
    want_note = wanted_kinds is None or "note" in wanted_kinds
    if not (want_email or want_note):
        return []

    is_admin = role in _FULL_TIMELINE_ROLES
    allowed_types: List[str] = []
    for et in _AUDIT_EVENT_TYPES:
        if (not is_admin) and (et not in _AUDIT_EVENT_PORTAL_VISIBLE):
            continue
        allowed_types.append(et)
    if not allowed_types:
        return []

    query: Dict[str, Any] = {
        "tenant_id":  tenant_id,
        "event_type": {"$in": allowed_types},
        "$or": [
            {"payload.customer_ids": customer["id"]},
            {"payload.customer_id":  customer["id"]},
        ],
    }
    if from_iso or to_iso:
        _range: Dict[str, Any] = {}
        if from_iso:
            _range["$gte"] = from_iso
        if to_iso:
            _range["$lte"] = to_iso
        query["timestamp"] = _range

    items: List[Dict[str, Any]] = []
    async for r in db.audit_events.find(query, {"_id": 0}) \
            .sort("timestamp", -1).limit(_TIMELINE_HARD_CAP):
        event_type = r.get("event_type") or ""
        payload = r.get("payload") or {}
        actor_email = r.get("actor_email")
        actor_user_id = r.get("actor_id")
        label = (actor_email
                 or ("User" if actor_user_id else "System / Automation"))
        occurred = r.get("timestamp") or ""
        rid = r.get("id") or ""

        if event_type == "job_edited_after_completion":
            # K6: never leaks before/after values.
            fields = payload.get("fields_changed") or []
            subject = "Job edited after completion"
            body = (
                f"{label} edited {len(fields)} field"
                f"{'' if len(fields) == 1 else 's'} on a completed job"
                f"{': ' + ', '.join(fields) if fields else '.'}"
            )
            if payload.get("invoice_recalculated"):
                body += " (invoice total recalculated)"
            kind = "note"
            related: Optional[Dict[str, Any]] = None
            if payload.get("job_id"):
                related = {"kind": "job", "id": payload["job_id"]}
        elif event_type == "invoice_auto_charged":
            # K14 payment card (§4.b α: folded into note kind).
            amount_cents = int(payload.get("amount_cents") or 0)
            currency = (payload.get("currency") or "usd").upper()
            amount_str = f"${amount_cents / 100:,.2f} {currency}"
            pi = payload.get("payment_intent_id") or ""
            pi_tail = pi[-6:] if pi else ""
            via_imp = bool(r.get("via_impersonation"))
            stamp = " (via impersonation)" if (via_imp and is_admin) else ""
            subject = "Invoice auto-charged"
            body = (
                f"{label if is_admin else 'System'} charged {amount_str}"
                f" to card on file{stamp} · pi_…{pi_tail}"
            )
            kind = "note"
            related = None
            if payload.get("invoice_id"):
                related = {"kind": "invoice", "id": payload["invoice_id"]}
        else:
            # Default: portal_invite_bulk — portal-filtered out above,
            # so this branch runs for admin only (but keep is_admin
            # gate defensive against future type additions).
            subject = "Portal invite"
            body = (
                f"Bulk portal invite fired by {label}. "
                f"Sent to {payload.get('sent', 0)} customer(s); "
                f"skipped {payload.get('skipped_already_activated', 0)} "
                "already active."
            )
            kind = "email"
            related = None

        if not ((kind == "email" and want_email)
                or (kind == "note" and want_note)):
            continue

        item: Dict[str, Any] = {
            "kind":            kind,
            "subject":         subject,
            "template_name":   "",
            "delivery_status": "logged",
            "created_at":      occurred,
            "ref_type":        "audit_event",
            "ref_id":          rid,
            "recipient":       "",
            "trigger_kind":    event_type,
            "related_ref":     related,
            "url":             "",
            "body":            _preview(body),
        }
        if is_admin:
            if r.get("reason"):
                item["delivery_error"] = r.get("reason")
            if actor_user_id:
                item["actor_user_id"] = actor_user_id
        items.append(item)
    return items


async def _build_full_timeline(
    customer: Dict[str, Any], tenant_id: str,
    wanted_kinds: Optional[set],
    from_: Optional[str], to_: Optional[str],
    role: str,
) -> List[Dict[str, Any]]:
    """Shared merge helper for the admin + portal endpoints.

    Phase B · Feb-2026 — admins + super_admins additionally see the
    ``call`` and ``note`` sources merged in. Managers and portal
    (customer) sessions keep the pre-B 4-source view — the two new
    pulls are only invoked when the caller is in
    :data:`_FULL_TIMELINE_ROLES`.
    """
    from_iso, to_iso = _iso_bounds(from_, to_)
    marketing = await _marketing_deliveries_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso,
    )
    quote_items = await _quotes_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso, role,
    )
    merged = marketing + quote_items
    # TD-98/99-xref · Feb-2026 — Cross-visibility aggregator.
    # Surface pre-conversion lead-era comms (outbound SMS/email +
    # inbound SMS matched to the converted lead) on both admin and
    # portal paths. Portal visibility is intentional: these ARE the
    # customer's own historical interactions with the company. The
    # helpers never emit admin-only fields (actor_user_id,
    # delivery_error) top-level, so no additional stripping is
    # required beyond the Phase B defaults.
    merged += await _lead_communications_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso, role,
    )
    merged += await _lead_inbound_sms_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso,
    )
    # TD-98-be-sources · Feb-2026 — notification_dispatch_log +
    # audit_events restored to the super-timeline. Both helpers
    # handle portal visibility at their own helper level (dispatch
    # log: portal YES with admin-field strip at source; audit events:
    # portal visibility via ``_AUDIT_EVENT_PORTAL_VISIBLE`` whitelist
    # filtered inside the helper). No admin-only gate here.
    merged += await _notification_dispatch_log_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso, role,
    )
    merged += await _audit_events_to_items(
        customer, tenant_id, wanted_kinds, from_iso, to_iso, role,
    )
    # Phase B — call_logs + job internal notes, admin/super_admin only.
    if role in _FULL_TIMELINE_ROLES:
        merged += await _call_logs_to_items(
            customer, tenant_id, wanted_kinds, from_iso, to_iso,
        )
        merged += await _job_notes_to_items(
            customer, tenant_id, wanted_kinds, from_iso, to_iso,
        )
        # Phase M1 · Feb-2026 — customer-scoped admin/system notes.
        merged += await _customer_notes_to_items(
            customer, tenant_id, wanted_kinds, from_iso, to_iso,
        )
    # Backfill the B-required fields on legacy items (marketing /
    # quotes) so every entry ships ``source_type / occurred_at /
    # summary / detail / actor / id`` — call + note items already
    # include them.
    for it in merged:
        _normalise_existing_item(it)
    # DESC sort — prefer ``occurred_at`` (UTC-normalised) with
    # ``created_at`` fallback for callers that only threaded the
    # legacy field.
    merged.sort(
        key=lambda i: i.get("occurred_at") or i.get("created_at") or "",
        reverse=True,
    )
    return _dedupe_by_ref(merged)


async def _paginated_timeline_response(
    customer: Dict[str, Any], tenant_id: str,
    kind: Optional[str],
    from_: Optional[str], to_: Optional[str],
    page: int, page_size: int,
    role: str,
    limit: Optional[int] = None,
    before: Optional[str] = None,
) -> Dict[str, Any]:
    """Paginated envelope. When ``before`` is supplied, cursor mode
    kicks in: items strictly earlier than ``before`` (compared as
    UTC ISO strings via :func:`_coerce_utc_iso`) are returned, up
    to ``limit`` (default 50, max 200). Legacy ``page/page_size``
    mode is untouched when ``before`` is absent."""
    wanted = _parse_kinds(kind)
    all_items = await _build_full_timeline(
        customer, tenant_id, wanted, from_, to_, role,
    )
    if before:
        # Cursor pagination — items strictly earlier than the cursor.
        cursor_iso = _coerce_utc_iso(before)
        _limit = max(1, min(int(limit or 50), 200))
        subset = [i for i in all_items
                    if (i.get("occurred_at") or i.get("created_at") or "")
                       < cursor_iso][:_limit]
        next_cursor = (subset[-1].get("occurred_at")
                        or subset[-1].get("created_at")) if subset else None
        return {
            "items":       subset,
            "page":        1,
            "page_size":   len(subset),
            "total":       len(all_items),
            "total_pages": 0,
            "next_before": next_cursor,
        }
    total = len(all_items)
    page_size = max(1, min(page_size, _TIMELINE_MAX_PAGE_SIZE))
    page = max(1, page)
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 0
    start = (page - 1) * page_size
    slice_ = all_items[start:start + page_size]
    next_before = (slice_[-1].get("occurred_at")
                    or slice_[-1].get("created_at")) if slice_ else None
    return {
        "items":       slice_,
        "page":        page,
        "page_size":   page_size,
        "total":       total,
        "total_pages": total_pages,
        "next_before": next_before,
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
    kind: Optional[str] = Query(
        None,
        description="csv: email,sms,invoice,estimate,call,note",
    ),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=200,
                                     description="cursor-mode page size"),
    before: Optional[str] = Query(
        None, description="ISO cursor — return items strictly earlier"),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Full customer communication history — admin/manager only.

    Phase B · Feb-2026 · Super Timeline —  ``admin`` and
    ``super_admin`` sessions additionally see ``call`` (call_logs)
    and ``note`` (internal job notes) sources. Manager sessions
    keep the pre-B 4-source view (no regression). All other roles
    → 403 with ``detail=insufficient_role_for_full_timeline``.

    Response shape adds per-item ``id / source_type / occurred_at /
    summary / detail / actor`` without renaming the legacy
    ``kind / created_at / ref_type / ref_id`` fields.

    Cursor pagination — pass ``before=<ISO>`` (+ optional
    ``limit``) to page by ``occurred_at``. Absent both → the
    legacy ``page / page_size`` envelope is returned unchanged.
    """
    role = (user.get("role") or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(
            403, "insufficient_role_for_full_timeline",
        )
    customer = await _load_customer(customer_id, tenant["id"])
    return await _paginated_timeline_response(
        customer, tenant["id"], kind, from_, to, page, page_size, role,
        limit=limit, before=before,
    )
