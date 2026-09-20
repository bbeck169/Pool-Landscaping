"""Phase C · Feb-2026 · Sales Pipeline Kanban Board.

Single read endpoint that fans out across the four canonical
CRM collections (``leads``, ``quotes``, ``jobs``, ``invoices``) +
``intelligence_alerts`` and returns a Kanban board:

``GET /api/pipeline/kanban?date_from=&date_to=&owner_id=``

Response shape
--------------
::

    {
      "columns": [
        {"key": "leads", "label": "Leads",  "total_amount_cents": 0,
          "total_currency": "USD", "count": 0, "cards": [KanbanCard...]},
        {"key": "quoted", ... },
        {"key": "scheduled", ... },
        {"key": "completed", ... },
        {"key": "follow_up", ... },
      ],
      "risk_swimlane": [KanbanCard with intelligence_alert reference],
      "generated_at": "ISO8601"
    }

Auth
----
Role in ``{admin, super_admin, manager}``. Anything else → 403
``insufficient_role_for_pipeline``.

Deviations from spec (grep-first — real code always wins)
---------------------------------------------------------
See ``/app/memory/PHASE_C_SALES_PIPELINE.md`` for full status-
vocabulary audit. Highlights:

*   Leads statuses are ``{new, contacted, quoted, closed_won,
    closed_lost}`` on disk — the "Leads" column uses ``{new,
    contacted}`` (still-open, not-yet-quoted). ``quoted``
    naturally lands in the Quoted column via the linked quote.
*   Quote statuses on disk include ``{draft, sent, issued,
    accepted, approved, declined, partial, paid}`` — the "Quoted"
    column uses ``{sent, issued, approved}`` (open, awaiting
    customer decision). ``accepted``/``paid`` implicitly promote
    to the linked job's column.
*   Jobs have no ``en_route`` state today — the "Scheduled" column
    uses ``{scheduled, pending, in_progress}``.
*   Jobs carry ``price`` (dollars) — cents conversion is
    ``round(price * 100)``. Leads carry ``est_value`` (dollars).
    Quotes carry ``total`` / ``adjusted_total`` (dollars).
    Invoices already store ``total_cents``.
*   ``jobs.completed_at`` is not populated end-to-end — we use
    ``auto_invoice_created_at`` as the completed pivot, falling
    back to ``scheduled_date``.
*   Jobs have no ``follow_up_at`` field yet. The Follow-up column
    is kept in the shape so callers/tests can seed one and it
    lights up — no-op today until the field is written.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["sales-pipeline"])

_ALLOWED_ROLES = {"admin", "super_admin", "manager", "owner"}
_DEFAULT_TRAILING_DAYS = 90
_COMPLETED_WINDOW_DAYS = 14
_FOLLOWUP_WINDOW_DAYS = 14

# Status vocabulary — grep-confirmed on disk 2026-02.
_LEAD_STATUSES = {"new", "contacted"}
_QUOTE_STATUSES = {"sent", "issued", "approved"}
_SCHEDULED_JOB_STATUSES = {"scheduled", "pending", "in_progress"}


def _require_pipeline_role(user: Dict[str, Any]) -> str:
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403, detail="insufficient_role_for_pipeline",
        )
    return role


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v)


def _dollars_to_cents(v: Any) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return 0


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        # Accept plain YYYY-MM-DD by promoting to midnight UTC.
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.fromisoformat(s + "T00:00:00+00:00")
        # Handle "Z" suffix which fromisoformat can't parse pre-3.11.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_date_param")
    # Always return TZ-aware — some code paths persist naive
    # ISO datetimes and downstream comparisons need consistency.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _tenant_currency(tenant: Dict[str, Any]) -> str:
    settings = tenant.get("settings") or {}
    biz = tenant.get("business_settings") or {}
    return (settings.get("currency") or biz.get("currency") or "USD").upper()


def _display_name(user_or_customer: Dict[str, Any]) -> str:
    if not user_or_customer:
        return ""
    if user_or_customer.get("name"):
        return user_or_customer["name"]
    first = user_or_customer.get("first_name") or ""
    last = user_or_customer.get("last_name") or ""
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    return (
        user_or_customer.get("display_name")
        or user_or_customer.get("email")
        or ""
    )


async def _resolve_tech_name(tenant_id: str, tech_id: str) -> Optional[str]:
    if not tech_id:
        return None
    row = await db.users.find_one(
        {"technician_id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1},
    )
    if row:
        return _display_name(row) or None
    row = await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1, "email": 1},
    )
    return _display_name(row or {}) or None


def _mk_card(
    *,
    id_: str,
    source: str,
    customer_id: str,
    customer_name: str,
    title: str,
    amount_cents: int,
    currency: str,
    assigned_to: Optional[str],
    status: str,
    occurred_at: Any,
    risk_alert_id: Optional[str] = None,
    risk_category: Optional[str] = None,
    risk_severity: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": id_,
        "source": source,
        "customer_id": customer_id or "",
        "customer_name": customer_name or "",
        "title": title or "",
        "amount_cents": int(amount_cents or 0),
        "currency": currency,
        "assigned_to_display_name": assigned_to,
        "status": status or "",
        "occurred_at": _iso(occurred_at),
        "risk_alert_id": risk_alert_id,
        "risk_category": risk_category,
        "risk_severity": risk_severity,
    }


async def _collect_leads(
    tenant_id: str,
    currency: str,
    since: datetime,
    until: datetime,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "status": {"$in": list(_LEAD_STATUSES)},
    }
    cursor = db.leads.find(q, {
        "_id": 0, "id": 1, "name": 1, "status": 1, "est_value": 1,
        "created_at": 1, "customer_id": 1, "notes": 1,
    })
    out: List[Dict[str, Any]] = []
    async for lead in cursor:
        occ = _parse_iso(lead.get("created_at"))
        if occ is None:
            continue
        if occ < since or occ > until:
            continue
        out.append(_mk_card(
            id_=str(lead.get("id") or ""),
            source="lead",
            customer_id=lead.get("customer_id") or "",
            customer_name=lead.get("name") or "",
            title=lead.get("notes") or "New lead",
            amount_cents=_dollars_to_cents(lead.get("est_value")),
            currency=currency,
            assigned_to=None,
            status=lead.get("status") or "",
            occurred_at=lead.get("created_at"),
        ))
    out.sort(key=lambda c: c["occurred_at"] or "", reverse=True)
    return out


async def _collect_quoted(
    tenant_id: str,
    currency: str,
    since: datetime,
    until: datetime,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "status": {"$in": list(_QUOTE_STATUSES)},
        "$or": [{"doc_type": "quote"}, {"doc_type": {"$exists": False}}],
    }
    cursor = db.quotes.find(q, {
        "_id": 0, "id": 1, "title": 1, "status": 1, "total": 1,
        "adjusted_total": 1, "created_at": 1, "customer_id": 1,
        "customer_name": 1,
    })
    out: List[Dict[str, Any]] = []
    async for qd in cursor:
        occ = _parse_iso(qd.get("created_at"))
        if occ is None:
            continue
        if occ < since or occ > until:
            continue
        amount = qd.get("adjusted_total")
        if amount is None:
            amount = qd.get("total")
        out.append(_mk_card(
            id_=str(qd.get("id") or ""),
            source="quote",
            customer_id=qd.get("customer_id") or "",
            customer_name=qd.get("customer_name") or "",
            title=qd.get("title") or "Quote",
            amount_cents=_dollars_to_cents(amount),
            currency=currency,
            assigned_to=None,
            status=qd.get("status") or "",
            occurred_at=qd.get("created_at"),
        ))
    out.sort(key=lambda c: c["occurred_at"] or "", reverse=True)
    return out


async def _collect_scheduled_and_completed(
    tenant_id: str,
    currency: str,
    since: datetime,
    until: datetime,
    owner_id: Optional[str],
    now: datetime,
) -> Dict[str, List[Dict[str, Any]]]:
    """Single sweep of ``jobs`` — one Mongo call for all three
    job-backed columns to avoid N+1. Returns a dict keyed
    ``{"scheduled": [...], "completed": [...], "follow_up": [...]}``.
    """
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if owner_id:
        q["technician_id"] = owner_id
    proj = {
        "_id": 0, "id": 1, "title": 1, "status": 1, "price": 1,
        "scheduled_date": 1, "auto_invoice_id": 1,
        "auto_invoice_created_at": 1, "completed_at": 1, "created_at": 1,
        "follow_up_at": 1, "needs_follow_up": 1,
        "customer_id": 1, "customer_name": 1, "service_type": 1,
        "technician_id": 1, "technician_name": 1,
    }
    jobs: List[Dict[str, Any]] = await db.jobs.find(q, proj).to_list(20_000)

    # Batch-load referenced invoices in one shot.
    inv_ids = [j.get("auto_invoice_id") for j in jobs
               if j.get("auto_invoice_id")]
    inv_by_id: Dict[str, Dict[str, Any]] = {}
    if inv_ids:
        async for inv in db.invoices.find(
            {"tenant_id": tenant_id, "id": {"$in": list(set(inv_ids))}},
            {"_id": 0, "id": 1, "total_cents": 1},
        ):
            inv_by_id[inv["id"]] = inv

    # Batch-resolve tech display names (one query for the whole set).
    tech_ids: Set[str] = {j.get("technician_id") for j in jobs
                              if j.get("technician_id")}
    tech_name_by_id: Dict[str, str] = {}
    for j in jobs:
        if j.get("technician_id") and j.get("technician_name"):
            tech_name_by_id[j["technician_id"]] = j["technician_name"]
    missing = tech_ids - set(tech_name_by_id.keys())
    if missing:
        cursor = db.users.find(
            {"tenant_id": tenant_id,
             "$or": [
                 {"technician_id": {"$in": list(missing)}},
                 {"id": {"$in": list(missing)}},
             ]},
            {"_id": 0, "id": 1, "technician_id": 1, "name": 1,
             "first_name": 1, "last_name": 1, "email": 1},
        )
        async for u in cursor:
            n = _display_name(u)
            if u.get("technician_id") in missing:
                tech_name_by_id.setdefault(u["technician_id"], n)
            if u.get("id") in missing:
                tech_name_by_id.setdefault(u["id"], n)

    scheduled_out: List[Dict[str, Any]] = []
    completed_out: List[Dict[str, Any]] = []
    followup_out: List[Dict[str, Any]] = []

    today_prefix = now.date().isoformat()
    completed_pivot = now - timedelta(days=_COMPLETED_WINDOW_DAYS)
    followup_cutoff = now + timedelta(days=_FOLLOWUP_WINDOW_DAYS)

    for j in jobs:
        status = (j.get("status") or "").lower()
        tech_id = j.get("technician_id") or ""
        assigned = (
            tech_name_by_id.get(tech_id)
            if tech_id else None
        )

        if status in _SCHEDULED_JOB_STATUSES:
            sd = str(j.get("scheduled_date") or "")
            # Compare YYYY-MM-DD prefix — jobs sometimes persist full
            # ISO datetimes, sometimes bare dates.
            if sd[:10] < today_prefix:
                continue
            occ_iso = j.get("scheduled_date") or j.get("created_at")
            occ = _parse_iso(occ_iso[:19] if isinstance(occ_iso, str)
                             and len(occ_iso) >= 19 else occ_iso)
            if occ is None or occ < since or occ > until:
                continue
            amt = _dollars_to_cents(j.get("price"))
            inv = inv_by_id.get(j.get("auto_invoice_id") or "")
            if inv and inv.get("total_cents"):
                amt = int(inv["total_cents"])
            scheduled_out.append(_mk_card(
                id_=str(j.get("id") or ""),
                source="job",
                customer_id=j.get("customer_id") or "",
                customer_name=j.get("customer_name") or "",
                title=(j.get("title") or j.get("service_type")
                        or "Scheduled job"),
                amount_cents=amt,
                currency=currency,
                assigned_to=assigned,
                status=status,
                occurred_at=occ_iso,
            ))
            continue

        if status == "completed":
            # Prefer real ``completed_at``; fall back to
            # ``auto_invoice_created_at`` (post-visit auto-invoice is
            # the current completion signal on-disk), else
            # ``scheduled_date``.
            pivot_raw = (j.get("completed_at")
                          or j.get("auto_invoice_created_at")
                          or j.get("scheduled_date"))
            pivot = _parse_iso(pivot_raw[:19] if isinstance(pivot_raw, str)
                                and len(pivot_raw) >= 19 else pivot_raw)
            if pivot is None:
                continue

            inv = inv_by_id.get(j.get("auto_invoice_id") or "")
            amt = int(inv["total_cents"]) if inv and inv.get("total_cents") \
                    else _dollars_to_cents(j.get("price"))

            # Follow-up column: completed + follow_up_at set + within
            # +14d OR ``needs_follow_up=True``.
            fu_raw = j.get("follow_up_at")
            fu = _parse_iso(fu_raw[:19] if isinstance(fu_raw, str)
                             and len(fu_raw) >= 19 else fu_raw)
            follow_up_flag = bool(j.get("needs_follow_up"))
            if (fu is not None and fu <= followup_cutoff) or follow_up_flag:
                followup_out.append(_mk_card(
                    id_=str(j.get("id") or ""),
                    source="job",
                    customer_id=j.get("customer_id") or "",
                    customer_name=j.get("customer_name") or "",
                    title=(j.get("title") or j.get("service_type")
                            or "Follow-up"),
                    amount_cents=amt,
                    currency=currency,
                    assigned_to=assigned,
                    status=status,
                    occurred_at=fu_raw or pivot_raw,
                ))
                continue

            # Otherwise: standard 14-day rolling completed window
            # intersected with the caller's date_from/date_to filter.
            if pivot < completed_pivot:
                continue
            if pivot < since or pivot > until:
                continue
            completed_out.append(_mk_card(
                id_=str(j.get("id") or ""),
                source="job",
                customer_id=j.get("customer_id") or "",
                customer_name=j.get("customer_name") or "",
                title=(j.get("title") or j.get("service_type")
                        or "Completed job"),
                amount_cents=amt,
                currency=currency,
                assigned_to=assigned,
                status=status,
                occurred_at=pivot_raw,
            ))

    scheduled_out.sort(key=lambda c: c["occurred_at"] or "", reverse=True)
    completed_out.sort(key=lambda c: c["occurred_at"] or "", reverse=True)
    followup_out.sort(key=lambda c: c["occurred_at"] or "", reverse=True)
    return {
        "scheduled": scheduled_out,
        "completed": completed_out,
        "follow_up": followup_out,
    }


async def _collect_risk_swimlane(
    tenant_id: str,
    currency: str,
    pipeline_customer_ids: Set[str],
) -> List[Dict[str, Any]]:
    if not pipeline_customer_ids:
        return []
    cursor = db.intelligence_alerts.find(
        {"tenant_id":    tenant_id,
         "dismissed_at": None,
         "customer_id":  {"$in": list(pipeline_customer_ids)}},
        {"_id": 1, "customer_id": 1, "title": 1, "body": 1,
         "category": 1, "severity": 1, "created_at": 1},
    ).sort("created_at", -1).limit(100)

    # Batch-resolve customer display names for the swimlane.
    cust_ids = list(pipeline_customer_ids)
    cust_name_by_id: Dict[str, str] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"tenant_id": tenant_id, "id": {"$in": cust_ids}},
            {"_id": 0, "id": 1, "name": 1,
             "first_name": 1, "last_name": 1},
        ):
            cust_name_by_id[c["id"]] = _display_name(c)

    out: List[Dict[str, Any]] = []
    async for a in cursor:
        cid = a.get("customer_id") or ""
        out.append(_mk_card(
            id_=str(a.get("_id")),
            source="alert",
            customer_id=cid,
            customer_name=cust_name_by_id.get(cid, ""),
            title=a.get("title") or "",
            amount_cents=0,
            currency=currency,
            assigned_to=None,
            status=a.get("severity") or "",
            occurred_at=a.get("created_at"),
            risk_alert_id=str(a.get("_id")),
            risk_category=a.get("category"),
            risk_severity=a.get("severity"),
        ))
    return out


def _column(key: str, label: str, cards: List[Dict[str, Any]],
             currency: str) -> Dict[str, Any]:
    total = sum(int(c["amount_cents"] or 0) for c in cards)
    return {
        "key":                key,
        "label":              label,
        "total_amount_cents": total,
        "total_currency":     currency,
        "count":              len(cards),
        "cards":              cards,
    }


@router.get("/pipeline/kanban")
async def get_kanban(
    date_from: Optional[str] = Query(
        None, description="Inclusive lower bound (ISO8601)"),
    date_to:   Optional[str] = Query(
        None, description="Inclusive upper bound (ISO8601)"),
    owner_id:  Optional[str] = Query(
        None, description="Filter jobs by technician_id"),
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_pipeline_role(user)
    tenant_id = tenant["id"]
    currency = _tenant_currency(tenant)
    now = datetime.now(timezone.utc)

    df = _parse_iso(date_from) or (now - timedelta(days=_DEFAULT_TRAILING_DAYS))
    dt = _parse_iso(date_to) or (now + timedelta(days=_DEFAULT_TRAILING_DAYS))
    if df.tzinfo is None:
        df = df.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    leads_cards = await _collect_leads(tenant_id, currency, df, dt)
    quoted_cards = await _collect_quoted(tenant_id, currency, df, dt)
    job_cols = await _collect_scheduled_and_completed(
        tenant_id, currency, df, dt, owner_id, now)

    # `owner_id` on Leads/Quotes is not stored on-disk today —
    # applying the filter would blank the columns.  Documented in
    # PHASE_C_SALES_PIPELINE.md; jobs are the authoritative source
    # for owner assignment.
    if owner_id:
        # Filter out lead/quote cards whose linked customer isn't
        # touched by this owner's jobs — keeps the swimlane and the
        # column contents coherent from the operator's point of view.
        touched_customers = {
            c["customer_id"] for c in job_cols["scheduled"]
        } | {
            c["customer_id"] for c in job_cols["completed"]
        } | {
            c["customer_id"] for c in job_cols["follow_up"]
        }
        leads_cards = [
            c for c in leads_cards if c["customer_id"]
            and c["customer_id"] in touched_customers
        ]
        quoted_cards = [
            c for c in quoted_cards if c["customer_id"]
            and c["customer_id"] in touched_customers
        ]

    columns = [
        _column("leads",     "Leads",     leads_cards,           currency),
        _column("quoted",    "Quoted",    quoted_cards,          currency),
        _column("scheduled", "Scheduled", job_cols["scheduled"], currency),
        _column("completed", "Completed", job_cols["completed"], currency),
        _column("follow_up", "Follow-up", job_cols["follow_up"], currency),
    ]

    customer_ids_in_pipeline: Set[str] = set()
    for col in columns:
        for c in col["cards"]:
            if c["customer_id"]:
                customer_ids_in_pipeline.add(c["customer_id"])
    risk = await _collect_risk_swimlane(
        tenant_id, currency, customer_ids_in_pipeline)

    return {
        "columns":       columns,
        "risk_swimlane": risk,
        "generated_at":  now.isoformat(),
    }
