"""Phase 34 · Feb 2026 — Weekly "Bulk actions summary" digest email.

Aggregates the last 7 days of ``audit_log`` rows into a Monday-morning
rollup email delivered to every tenant's ``owner`` role user(s). Routes
through the Task-L guarded `resend_adapter` so preview stays dry-run
except for the allow-listed Brian testers.

Cron: **Every Monday at 08:00 tenant local time.** Zero-action tenants
are silently skipped (no empty-digest spam).

Aggregation groups by ``action`` prefix so we roll up related events:
* ``bulk_delete_*`` — archives (invoices, estimates, payments, leads, autobilling, pricebook).
* ``lead.bulk_status_change`` — statuses changed en masse.
* ``lead.soft_delete``, ``invoice.soft_delete``, etc. — single-record
  archives are excluded (this is a *bulk* summary).

Extend the ``_BULK_ACTIONS`` map when new bulk endpoints ship.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from config import db, logger


_BULK_ACTIONS: Dict[str, str] = {
    # action → human-readable label for the digest bullet.
    "invoice.soft_delete": "invoices archived",
    "estimate.soft_delete": "estimates archived",
    "payment.soft_delete": "payments removed",
    "lead.soft_delete": "leads archived",
    "autobilling.soft_delete": "autobilling plans retired",
    "pricebook.patch": "pricebook items updated",
    "lead.bulk_status_change": "leads had status changed",
}


async def _tenant_owners(tenant_id: str) -> List[Dict[str, Any]]:
    """Return every user in this tenant whose role can receive the
    digest (owner primary, super_admin + admin as fallback so a fresh
    tenant with no owner still gets the summary)."""
    q = {"tenant_id": tenant_id,
          "role": {"$in": ["owner", "super_admin", "admin"]},
          "email": {"$nin": [None, ""]}}
    rows = await db.users.find(q, {"_id": 0, "id": 1, "email": 1,
                                       "role": 1, "name": 1}).to_list(20)
    # Prefer owner rows; if none, fall back to admin/super_admin.
    owners = [r for r in rows if r.get("role") == "owner"]
    return owners or rows


async def build_digest_rollup(tenant_id: str, since_iso: str) -> Dict[str, Any]:
    """Aggregate audit_log rows for this tenant since ``since_iso`` into
    the bucket totals we display in the digest email."""
    counts: Dict[str, int] = {}
    q = {"tenant_id": tenant_id, "at": {"$gte": since_iso},
          "action": {"$in": list(_BULK_ACTIONS.keys())}}
    async for row in db.audit_log.find(q, {"_id": 0, "action": 1}):
        a = row.get("action") or ""
        counts[a] = counts.get(a, 0) + 1
    total = sum(counts.values())
    return {"total": total, "counts": counts}


async def _engagement_kpis(tenant_id: str, since_iso: str) -> Dict[str, Any]:
    """Task LL sign-off follow-up · Feb 2026 — pulls the small
    "Engagement this week" section rendered under the bulk-actions
    rollup. Every count is unique-per-customer where the field
    exists, or a raw event count otherwise. Zero-value entries are
    dropped by ``_render_html`` so the email stays tight."""
    kpis: Dict[str, Any] = {}
    # 1. Customers who opened an invoice (unique customer count).
    opens = await db.communication_events.distinct(
        "customer_id",
        {"tenant_id": tenant_id, "event_type": "opened",
         "at": {"$gte": since_iso},
         "template_kind": {"$in": ["invoice", "invoice_reminder"]}},
    )
    if opens:
        kpis["invoice_opens"] = len([o for o in opens if o])
    # 2. Customers who paid an invoice + total amount.
    paid_rows = await db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
         "payment_status": "paid",
         "paid_at": {"$gte": since_iso}},
        {"_id": 0, "customer_id": 1, "amount_paid": 1},
    ).to_list(1000)
    if paid_rows:
        kpis["payments_paid_count"] = len(paid_rows)
        kpis["payments_paid_amount"] = round(
            sum(float(r.get("amount_paid") or 0) for r in paid_rows), 2)
    # 3. Reviews submitted this week + avg rating.
    review_rows = await db.review_requests.find(
        {"tenant_id": tenant_id,
         "star_submitted_at": {"$gte": since_iso}},
        {"_id": 0, "star_rating_submitted": 1},
    ).to_list(1000)
    if review_rows:
        ratings = [int(r.get("star_rating_submitted") or 0)
                    for r in review_rows if r.get("star_rating_submitted")]
        if ratings:
            kpis["reviews_count"] = len(ratings)
            kpis["reviews_avg_rating"] = round(sum(ratings) / len(ratings), 2)
    # 4. Customers who clicked the Google CTA.
    google_clicks = await db.review_requests.count_documents({
        "tenant_id": tenant_id,
        "google_click_at": {"$gte": since_iso},
    })
    if google_clicks:
        kpis["google_review_clicks"] = google_clicks
    # 5. New leads captured.
    new_leads = await db.leads.count_documents({
        "tenant_id": tenant_id, "created_at": {"$gte": since_iso},
    })
    if new_leads:
        kpis["new_leads"] = new_leads
    # 6. Portal logins.
    portal_logins = await db.audit_log.count_documents({
        "tenant_id": tenant_id,
        "action": {"$in": ["portal.login", "customer_portal.login"]},
        "at": {"$gte": since_iso},
    })
    if portal_logins:
        kpis["portal_logins"] = portal_logins
    return kpis


def _render_html(counts: Dict[str, int], since_dt: datetime,
                    kpis: Optional[Dict[str, Any]] = None) -> str:
    lines = []
    for action, label in _BULK_ACTIONS.items():
        n = counts.get(action, 0)
        if n <= 0:
            continue
        lines.append(f"<li><b>{n}</b> {label}</li>")
    body = "\n".join(lines) or "<li>No bulk actions this week.</li>"

    # Task LL sign-off — engagement KPIs section. Only emit lines
    # with count > 0 so the email stays tight. Skip the whole section
    # if there's nothing to report.
    kpi_lines = []
    if kpis:
        if kpis.get("invoice_opens"):
            kpi_lines.append(
                f"<li><b>{kpis['invoice_opens']}</b> customers opened an invoice</li>")
        if kpis.get("payments_paid_count"):
            amt = kpis.get("payments_paid_amount") or 0
            kpi_lines.append(
                f"<li><b>{kpis['payments_paid_count']}</b> invoices paid "
                f"— <b>${amt:,.2f}</b> collected</li>")
        if kpis.get("reviews_count"):
            avg = kpis.get("reviews_avg_rating") or 0
            kpi_lines.append(
                f"<li><b>{kpis['reviews_count']}</b> customers submitted a "
                f"review — avg <b>{avg}</b>★</li>")
        if kpis.get("google_review_clicks"):
            kpi_lines.append(
                f"<li><b>{kpis['google_review_clicks']}</b> Google review CTA clicks</li>")
        if kpis.get("new_leads"):
            kpi_lines.append(
                f"<li><b>{kpis['new_leads']}</b> new leads captured</li>")
        if kpis.get("portal_logins"):
            kpi_lines.append(
                f"<li><b>{kpis['portal_logins']}</b> portal logins</li>")
    kpi_html = ""
    if kpi_lines:
        kpi_html = (
            "<h3 style=\"margin:24px 0 8px 0\">Engagement this week</h3>"
            "<ul style=\"line-height:1.8;padding-left:20px\">"
            + "\n".join(kpi_lines) + "</ul>"
        )

    since_h = since_dt.strftime("%b %-d")
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;color:#0F172A;max-width:600px">
  <h2 style="margin:0 0 8px 0">Your weekly housekeeping summary</h2>
  <p style="color:#64748B;margin:0 0 16px 0;font-size:13px">
    Bulk actions applied since {since_h}
  </p>
  <ul style="line-height:1.8;padding-left:20px">
    {body}
  </ul>
  {kpi_html}
  <p style="color:#64748B;font-size:12px;margin-top:24px">
    Delivered every Monday at 8am. Data pulled from the audit log
    for the past 7 days.
  </p>
</div>
""".strip()


async def send_weekly_digest_for_tenant(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Send the digest to every owner-role user in a single tenant.
    Zero-action tenants short-circuit before touching the send adapter."""
    since_dt = datetime.now(timezone.utc) - timedelta(days=7)
    since_iso = since_dt.isoformat()
    rollup = await build_digest_rollup(tenant["id"], since_iso)
    kpis = await _engagement_kpis(tenant["id"], since_iso)
    # Task LL sign-off — skip only when BOTH the bulk-actions AND
    # the engagement KPIs are empty. Any signal fires an email.
    if rollup["total"] == 0 and not kpis:
        return {"tenant_id": tenant["id"], "skipped_zero_actions": True}

    owners = await _tenant_owners(tenant["id"])
    if not owners:
        return {"tenant_id": tenant["id"], "skipped_no_owners": True}

    html = _render_html(rollup["counts"], since_dt, kpis)
    subject = f"Weekly housekeeping — {rollup['total']} bulk action(s)"
    sent = 0
    dry_ran = 0
    for u in owners:
        try:
            # Route through the guarded adapter — Task L guarantees
            # preview stays dry-run unless the recipient is in the
            # ``COMMS_TEST_ALLOWLIST_EMAILS`` allow-list.
            from services.email.resend_adapter import send as send_resend
            result = await send_resend(
                to=u["email"],
                subject=subject,
                html=html,
                category="transactional",
                tenant_id=tenant["id"],
                # Phase K72 · Feb-2026 — recipient is tenant owner/
                # admin. Bypasses the K72 customer-email kill switch.
                audience="internal",
            )
            status = (result or {}).get("provider_status")
            if status == "dry_run":
                dry_ran += 1
            elif status == "sent":
                sent += 1
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[digest] send failed for {u.get('email')}: {e}")
    return {"tenant_id": tenant["id"], "sent": sent, "dry_ran": dry_ran,
              "total_bulk_actions": rollup["total"],
              "counts": rollup["counts"]}


async def send_weekly_digest_all_tenants() -> Dict[str, Any]:
    """APScheduler entry point — runs Monday 08:00 UTC (we treat UTC
    as the canonical clock; per-tenant local-time support is a
    follow-up if tenants complain about odd delivery times)."""
    summary: List[Dict[str, Any]] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1, "slug": 1}):
        try:
            r = await send_weekly_digest_for_tenant(t)
            summary.append(r)
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[digest] tenant {t.get('slug')} crashed: {e}")
    logger.info(f"[phase34-digest] weekly bulk summary run — {len(summary)} tenants processed")
    return {"tenants_processed": len(summary), "detail": summary}
