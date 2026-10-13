from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response,
                   not_deleted_filter as _nd)
from routers.tenants import get_current_tenant
# Bucket A2 · Feb-2026 — wildcard removed; dashboard.py does not reference
# any symbol from ``models`` (verified via AST diff against models exports).

router = APIRouter()


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    if user.get("role") == "technician":
        techn_id = user.get("technician_id")
        base = {"technician_id": techn_id, "tenant_id": tid}
        pending = await db.jobs.count_documents({**base, "status": "pending"})
        active = await db.jobs.count_documents({**base, "status": "active"})
        completed = await db.jobs.count_documents({**base, "status": "completed"})
        upcoming = await db.jobs.find(
            {**base, "status": {"$in": ["pending", "active"]}, **_nd()}, {"_id": 0}
        ).sort("scheduled_date", 1).to_list(10)
        return {
            "role": "technician",
            "pending_jobs": pending,
            "active_jobs": active,
            "completed_jobs": completed,
            "upcoming_jobs": upcoming,
        }

    if user.get("role") == "customer":
        cid = user.get("customer_id")
        base = {"customer_id": cid, "tenant_id": tid}
        active = await db.jobs.count_documents({**base, "status": {"$in": ["pending", "active"]}})
        completed = await db.jobs.count_documents({**base, "status": "completed"})
        unpaid_docs = await db.quotes.find(
            {**base, "doc_type": "invoice", "payment_status": "unpaid", **_nd()}, {"_id": 0}
        ).to_list(1000)
        outstanding = round(sum(q["total"] for q in unpaid_docs), 2)
        pending_estimates = await db.quotes.count_documents(
            {**base, "doc_type": "quote", "status": {"$nin": ["accepted", "declined"]}, **_nd()}
        )
        upcoming = await db.jobs.find(
            {**base, "status": {"$in": ["pending", "active", "requested"]}, **_nd()}, {"_id": 0}
        ).sort("scheduled_date", 1).to_list(20)
        next_service = upcoming[0] if upcoming else None
        recent = await db.jobs.find(base, {"_id": 0, "photos.data": 0}).sort("created_at", -1).to_list(5)
        cust = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0}) or {}
        unread_messages = await db.messages.count_documents(
            {**base, "sender": "business", "read_by_customer": False}
        )
        documents_count = await db.documents.count_documents(base)
        return {
            "role": "customer",
            "active_jobs": active,
            "completed_jobs": completed,
            "outstanding": outstanding,
            "unpaid_invoices": len(unpaid_docs),
            "pending_estimates": pending_estimates,
            "account_credit": round(cust.get("account_credit", 0.0), 2),
            "unread_messages": unread_messages,
            "documents_count": documents_count,
            "next_service": next_service,
            "recent_jobs": recent,
        }

    # Admin / super_admin
    tenant_q = {"tenant_id": tid}
    # Feb-2026 · P2 Item 2 — revenue calc MUST exclude soft-deleted
    # invoices. Same guard applied to outstanding below.
    paid = await db.quotes.find({**tenant_q, "payment_status": "paid", **_nd()}, {"_id": 0}).to_list(1000)
    revenue = round(sum(q["total"] for q in paid), 2)
    outstanding_docs = await db.quotes.find(
        {**tenant_q, "doc_type": "invoice", "payment_status": "unpaid", **_nd()}, {"_id": 0}
    ).to_list(1000)
    outstanding = round(sum(q["total"] for q in outstanding_docs), 2)
    active = await db.jobs.count_documents({**tenant_q, "status": "active"})
    pending = await db.jobs.count_documents({**tenant_q, "status": "pending"})
    completed = await db.jobs.count_documents({**tenant_q, "status": "completed"})
    requested = await db.jobs.count_documents({**tenant_q, "status": "requested"})
    total_customers = await db.customers.count_documents(tenant_q)
    total_techs = await db.technicians.count_documents(tenant_q)

    # ── Feb-2026 · Dashboard tile — Active vs Inactive Customers ──
    # SECOND PASS (Feb-2026) — definition REDEFINED to match the
    # customer-level activation TOGGLE, not the recurring-service
    # contract signal used in the first pass.
    #
    # * Active   = ``is_active != False`` + not soft-deleted.
    #              Matches True, missing, AND null so legacy rows
    #              that never had ``is_active`` stamped still count
    #              as active — same read semantics as ``models.py:96``
    #              ("Missing/legacy docs read back as True (assumed
    #              active)") and ``ActivationControl.jsx:33``
    #              (``customer?.is_active !== false``).
    # * Inactive = ``is_active == False`` + not muted + not
    #              soft-deleted. Explicit deactivations only.
    #
    # NO SUM INVARIANT — muted-inactive customers and soft-deleted
    # customers are EXCLUDED from BOTH buckets. Callers must not
    # assume ``active + inactive == total_customers``.
    #
    # Covering index: ``customers_dashboard_active_inactive_idx`` on
    # ``(tenant_id, is_active, is_muted, deleted_at)`` shipped by
    # ``services/migrations/customers_dashboard_active_inactive_idx.py``
    # (sentinel ``customers_dashboard_active_inactive_idx_v1``).
    _not_deleted = _nd()
    _not_muted = {"$or": [{"is_muted": {"$ne": True}},
                             {"is_muted": {"$exists": False}}]}
    active_customers_count = await db.customers.count_documents({
        **tenant_q,
        # ``is_active != False`` matches True + missing + null in
        # MongoDB's ``$ne`` semantics. Explicit for clarity.
        "$and": [
            {"$or": [{"is_active": True},
                      {"is_active": None},
                      {"is_active": {"$exists": False}}]},
            _not_deleted,
        ],
    })
    inactive_customers_count = await db.customers.count_documents({
        **tenant_q,
        "is_active": False,
        "$and": [_not_deleted, _not_muted],
    })

    # ── Feb-2026 · Pool + Landscaping customer tiles ──────
    # Two additional count buckets rendered as sibling KPI tiles
    # directly below Active / Inactive. Shares the ``is_active !=
    # False`` + ``not soft-deleted`` filter above so the three
    # customer-count tiles tell a consistent "active roster" story.
    #
    # Union semantics (P2 #6 · ``615339ab5``): a customer with
    # ``service_category == "both"`` is counted on BOTH tiles —
    # mirrors the ``?service_category=pool`` list filter so the
    # tile total matches the deep-linked list total exactly.
    #
    # Case-insensitive match: legacy rows with ``"Pool"`` /
    # ``"POOL"`` land in the same bucket as the canonical lowercase
    # enum (``routers/customers.py`` already normalises on write
    # but legacy historical data varies).
    from services.dashboard_customer_category_counts import (
        count_pool_customers,
        count_landscaping_customers,
    )
    pool_customers_count = await count_pool_customers(
        db=db, tenant_id=tenant["id"],
    )
    landscaping_customers_count = await count_landscaping_customers(
        db=db, tenant_id=tenant["id"],
    )

    recent = await db.jobs.find(tenant_q, {"_id": 0, "photos.data": 0}).sort("created_at", -1).to_list(6)

    now = datetime.now(timezone.utc)
    seq = []
    yy, mm = now.year, now.month
    for i in range(5, -1, -1):
        m = mm - i
        y = yy
        while m <= 0:
            m += 12
            y -= 1
        seq.append((y, m))
    buckets = {f"{y}-{m:02d}": 0.0 for (y, m) in seq}
    for qd in paid:
        ds = qd.get("paid_at") or qd.get("created_at")
        try:
            dt = datetime.fromisoformat(ds)
            key = f"{dt.year}-{dt.month:02d}"
            if key in buckets:
                buckets[key] += qd["total"]
        except Exception:
            pass
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    revenue_series = [{"label": month_names[m - 1], "value": round(buckets[f"{y}-{m:02d}"], 2)} for (y, m) in seq]

    svc: dict = {}
    alljobs = await db.jobs.find({**tenant_q, **_nd()}, {"_id": 0, "photos.data": 0}).to_list(2000)
    for j in alljobs:
        k = j.get("service_type") or "Other"
        svc[k] = svc.get(k, 0.0) + (j.get("price") or 0.0)
    revenue_by_service = sorted(
        [{"label": k, "value": round(v, 2)} for k, v in svc.items() if v > 0], key=lambda x: -x["value"]
    )[:6]

    recurring = round(sum(q["total"] for q in paid if any(w in (q.get("title", "").lower()) for w in ["monthly", "weekly", "recurring"])), 2)
    project = round(max(0.0, revenue - recurring), 2)

    # ── Feb 2026 · Batch 2 — Pool vs Landscape revenue split ──
    # Compute pool_revenue / landscape_revenue / mixed_revenue by
    # keyword-scoring each paid invoice's title AND (when available)
    # the paying customer's ``service_type``. This mirrors what the
    # admin sees in the invoice grid — no schema change required.
    #
    # Heuristic (documented so ops can audit):
    #   * ``pool`` keyword in title/service_type  → pool bucket
    #   * ``landscape`` / ``lawn`` / ``garden`` / ``tree`` / ``yard``
    #     in title/service_type                    → landscape bucket
    #   * both signals present OR neither present  → mixed bucket
    #     (mixed catches "Commercial Service", "Monthly Service",
    #      multi-line packages, and totally unlabeled invoices)
    #
    # Customer service_type is looked up in one batch by ``$in`` on
    # ``customer_id`` — no N+1. Unknown customers fall through to the
    # title-only score, which itself falls into ``mixed`` when
    # nothing matches. Total is invariant: pool + landscape + mixed
    # == revenue (guaranteed by the mutually-exclusive bucket rule).
    _POOL_KWS = ("pool",)
    _LAND_KWS = ("landscape", "lawn", "garden", "tree", "yard")
    _cust_ids = list({q.get("customer_id") for q in paid if q.get("customer_id")})
    _cust_service_type: dict = {}
    if _cust_ids:
        async for c in db.customers.find(
            {"tenant_id": tid, "id": {"$in": _cust_ids}},
            {"_id": 0, "id": 1, "service_type": 1},
        ):
            _cust_service_type[c["id"]] = (c.get("service_type") or "").lower()

    def _bucket(q):
        text = " ".join(filter(None, [
            (q.get("title") or "").lower(),
            (q.get("service_type") or "").lower(),
            _cust_service_type.get(q.get("customer_id"), ""),
        ]))
        has_pool = any(kw in text for kw in _POOL_KWS)
        has_land = any(kw in text for kw in _LAND_KWS)
        if has_pool and not has_land: return "pool"
        if has_land and not has_pool: return "landscape"
        return "mixed"

    pool_revenue = 0.0
    landscape_revenue = 0.0
    mixed_revenue = 0.0
    for q in paid:
        amount = float(q.get("total") or 0)
        b = _bucket(q)
        if b == "pool":         pool_revenue += amount
        elif b == "landscape":  landscape_revenue += amount
        else:                   mixed_revenue += amount
    pool_revenue = round(pool_revenue, 2)
    landscape_revenue = round(landscape_revenue, 2)
    mixed_revenue = round(mixed_revenue, 2)

    total_leads = await db.leads.count_documents(tenant_q)
    open_leads = await db.leads.count_documents({**tenant_q, "status": {"$in": ["new", "contacted", "quoted"]}})

    # ── Phase K41d · Feb-2026 — Bulk Operations audit summary ──
    # Small "Last 24h" tile on the admin dashboard that reports:
    #   * bulk_actions_24h        — distinct bulk_batch_id in
    #                                dashboard_drilldown_edit events
    #                                within the last 24h.
    #   * bulk_actions_undone_24h — distinct undone_from_batch_id in
    #                                dashboard_drilldown_bulk_undone
    #                                events within the last 24h
    #                                (subset of ``bulk_actions_24h``).
    #   * bulk_actions_expired_24h — bulk batches whose newest edit
    #                                is > 10 min old AND which have
    #                                no undo companion. These are the
    #                                batches admins can no longer
    #                                undo, so exposing the count is
    #                                the whole point of the tile.
    #
    # NO NEW ENDPOINTS. NO NEW INDEXES. Backed by the existing
    # audit_events indexes (event_type + timestamp + tenant_id +
    # bulk_batch_id) shipped in Phase K41c.
    _now_utc = datetime.now(timezone.utc)
    _since_24h_iso = (_now_utc - timedelta(hours=24)).isoformat()
    _cutoff_undo_iso = (_now_utc - timedelta(minutes=10)).isoformat()
    _bulk_edit_batches = await db.audit_events.distinct(
        "bulk_batch_id",
        {
            "event_type": "dashboard_drilldown_edit",
            "tenant_id": tid,
            "timestamp": {"$gte": _since_24h_iso},
            "bulk_batch_id": {"$ne": None},
        },
    )
    _bulk_undone_batches = await db.audit_events.distinct(
        "undone_from_batch_id",
        {
            "event_type": "dashboard_drilldown_bulk_undone",
            "tenant_id": tid,
            "timestamp": {"$gte": _since_24h_iso},
            "undone_from_batch_id": {"$ne": None},
        },
    )
    _undone_set = {b for b in _bulk_undone_batches if b}
    # A batch counts as "expired" when its newest edit is older than
    # the 10-minute undo window AND it has no undo companion.  Batches
    # still inside the window aren't expired *yet* (they're just
    # pending / actionable), so we omit them from the count.
    _expired_count = 0
    if _bulk_edit_batches:
        pipeline = [
            {"$match": {
                "event_type": "dashboard_drilldown_edit",
                "tenant_id": tid,
                "timestamp": {"$gte": _since_24h_iso},
                "bulk_batch_id": {"$in": [b for b in _bulk_edit_batches if b]},
            }},
            {"$group": {
                "_id": "$bulk_batch_id",
                "newest": {"$max": "$timestamp"},
            }},
        ]
        async for row in db.audit_events.aggregate(pipeline):
            bid = row.get("_id")
            newest = row.get("newest")
            if not bid or bid in _undone_set:
                continue
            if isinstance(newest, str) and newest < _cutoff_undo_iso:
                _expired_count += 1
    bulk_actions_24h = len([b for b in _bulk_edit_batches if b])
    bulk_actions_undone_24h = len(_undone_set)
    bulk_actions_expired_24h = _expired_count

    return {
        "role": user.get("role", "admin"),
        "revenue": revenue,
        "outstanding": outstanding,
        "active_jobs": active,
        "pending_jobs": pending,
        "completed_jobs": completed,
        "requested_jobs": requested,
        "total_customers": total_customers,
        # ── Feb-2026 · Active/Inactive Customers tile ──
        # Authoritative fields consumed by the KPI grid. REDEFINED
        # in the Feb-2026 second pass to reflect the customer-level
        # ``is_active`` toggle (not the recurring-service contract
        # signal used in the first pass):
        #   * ``active_customers_count`` — ``is_active != False``
        #     (matches True + missing + null) + not soft-deleted.
        #   * ``inactive_customers_count`` — ``is_active == False`` +
        #     not muted (P28 ``is_muted``) + not soft-deleted.
        # These NO LONGER sum to ``total_customers`` — muted-inactive
        # and soft-deleted rows are excluded from both buckets.
        "active_customers_count": active_customers_count,
        "inactive_customers_count": inactive_customers_count,
        # ── Feb-2026 · Pool + Landscaping customer tiles ──
        # Additive fields alongside the Active/Inactive pair
        # above. Both apply the same ``is_active != False`` +
        # not-soft-deleted gate so the three customer-count
        # tiles tell a consistent "active roster" story.
        # Union semantics (P2 #6): a ``both`` customer is counted
        # on BOTH tiles — matches the ``?service_category=pool``
        # list filter so tile totals equal deep-linked list
        # totals exactly.
        "pool_customers_count": pool_customers_count,
        "landscaping_customers_count": landscaping_customers_count,
        # deprecated 2026-02, remove 2026-05-01 — replaced by the
        # Active/Inactive Customers pair above. The Technicians KPI
        # tile was retired from the dashboard on the same date but
        # the field stays in the response for one release window so
        # legacy mobile/portal builds keep working.
        "total_technicians": total_techs,
        "total_leads": total_leads,
        "open_leads": open_leads,
        "recent_jobs": recent,
        "revenue_series": revenue_series,
        "revenue_by_service": revenue_by_service,
        "recurring_vs_project": {"recurring": recurring, "project": project},
        # Feb 2026 · Batch 2 — Pool vs Landscape revenue split
        # (additive; existing consumers keep working). Dollars,
        # not cents — matches the ``revenue`` field's unit.
        "pool_revenue": pool_revenue,
        "landscape_revenue": landscape_revenue,
        "mixed_revenue": mixed_revenue,
        # ── Phase K41d · Feb-2026 — Bulk Operations audit tile ──
        # Additive fields; existing consumers keep working. Zero
        # new endpoints — the admin dashboard already fetches this
        # response on every mount.
        "bulk_actions_24h": bulk_actions_24h,
        "bulk_actions_undone_24h": bulk_actions_undone_24h,
        "bulk_actions_expired_24h": bulk_actions_expired_24h,
    }
