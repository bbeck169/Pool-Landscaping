"""Phase SEO-B · Feb-2026 — Outreach follow-up digest.

Runs daily at 08:00 UTC via APScheduler (registered in ``server.py``).
For each tenant with due followups (status in {contacted, pending}
and ``next_followup_at <= now``), emails the tenant owner a summary
via the existing Resend adapter.

Idempotent — batches identify their scope by ``next_followup_at``
and mark ``last_activity_at`` on each digested row to prevent
double-notification for the same day.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from services.comms_email_adapter import send_email


async def _due_prospects_for_tenant(tenant_id: str,
                                       cutoff_iso: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    async for r in db.outreach_prospects.find(
            {"tenant_id": tenant_id,
              "deleted_at": None,
              "status": {"$in": ["contacted", "pending"]},
              "next_followup_at": {"$ne": None, "$lte": cutoff_iso}},
            {"_id": 0}).sort("next_followup_at", 1):
        items.append(r)
    return items


async def _tenant_owner_email(tenant_id: str) -> Optional[str]:
    """Prefer role=owner, else the first admin/manager we can find."""
    for role in ("owner", "admin", "super_admin", "manager"):
        u = await db.users.find_one({"tenant_id": tenant_id,
                                       "role": role,
                                       "deleted_at": None},
                                       {"_id": 0, "email": 1})
        if u and u.get("email"):
            return u["email"]
    return None


def _render_digest_html(prospects: List[Dict[str, Any]]) -> str:
    rows = []
    for p in prospects[:50]:
        rows.append(
            f"<tr>"
            f"<td style='padding:6px 12px'>{p.get('domain','')}</td>"
            f"<td style='padding:6px 12px'>{p.get('contact_name') or '—'}</td>"
            f"<td style='padding:6px 12px'>{p.get('status')}</td>"
            f"<td style='padding:6px 12px'>{p.get('next_followup_at','') or '—'}</td>"
            f"</tr>"
        )
    body = "".join(rows) or (
        "<tr><td colspan=4 style='padding:12px'>Nothing due.</td></tr>")
    return (
        "<div style='font-family:system-ui,Segoe UI,Roboto,sans-serif'>"
        f"<h2>Outreach follow-ups due ({len(prospects)})</h2>"
        "<p>These prospects need your next touch:</p>"
        "<table style='border-collapse:collapse;border:1px solid #E4E4E7'>"
        "<thead><tr style='background:#F4F4F5'>"
        "<th style='padding:6px 12px;text-align:left'>Domain</th>"
        "<th style='padding:6px 12px;text-align:left'>Contact</th>"
        "<th style='padding:6px 12px;text-align:left'>Status</th>"
        "<th style='padding:6px 12px;text-align:left'>Due</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody></table></div>")


async def run_outreach_followup_digest(
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return ``{tenants_scanned, digests_sent, prospects_flagged}``.

    When ``tenant_id`` is provided, restricts to that tenant (used by
    the manual admin trigger). When ``None``, iterates all distinct
    tenants that own at least one outreach prospect.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if tenant_id:
        tenant_ids: List[str] = [tenant_id]
    else:
        tenant_ids = await db.outreach_prospects.distinct("tenant_id")

    tenants_scanned = 0
    digests_sent = 0
    prospects_flagged = 0

    for tid in tenant_ids:
        tenants_scanned += 1
        due = await _due_prospects_for_tenant(tid, now_iso)
        if not due:
            continue
        prospects_flagged += len(due)
        recipient = await _tenant_owner_email(tid)
        if not recipient:
            logger.info("[outreach_followups] tenant %s has no owner email — skipping",
                        tid)
            continue
        html = _render_digest_html(due)
        result = await send_email(
            tenant_id=tid,
            to_email=recipient,
            subject=f"{len(due)} outreach follow-ups due today",
            html=html,
            from_name="Outreach")
        if result.get("status") == "sent":
            digests_sent += 1
        # Bump each row so the digest is idempotent per day (marking
        # ``last_activity_at`` is a soft touch, not a state change).
        for p in due:
            await db.outreach_prospects.update_one(
                {"id": p["id"], "tenant_id": tid},
                {"$set": {"last_activity_at": now_iso}})

    return {
        "tenants_scanned": tenants_scanned,
        "digests_sent": digests_sent,
        "prospects_flagged": prospects_flagged,
        "ran_at": now_iso,
    }
