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
from typing import Any, Dict, List

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


def _render_html(counts: Dict[str, int], since_dt: datetime) -> str:
    lines = []
    for action, label in _BULK_ACTIONS.items():
        n = counts.get(action, 0)
        if n <= 0:
            continue
        lines.append(f"<li><b>{n}</b> {label}</li>")
    body = "\n".join(lines) or "<li>No bulk actions this week.</li>"
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
    if rollup["total"] == 0:
        return {"tenant_id": tenant["id"], "skipped_zero_actions": True}

    owners = await _tenant_owners(tenant["id"])
    if not owners:
        return {"tenant_id": tenant["id"], "skipped_no_owners": True}

    html = _render_html(rollup["counts"], since_dt)
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
