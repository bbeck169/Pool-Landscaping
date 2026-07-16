"""Phase 52.A · Monthly pricing insights digest.

Runs on the 1st of each month at 09:00 UTC. For every tenant:
  1. Computes previous month's 3 least-profitable service types.
  2. Calls the AI CFO for per-service price-increase suggestions.
  3. Emails admin + super_admin via Resend, or MOCK-logs when the
     Resend key is missing.
  4. Records the attempt in `email_delivery_log` under
     `kind: "monthly_pricing_digest"`.

Frontend history panel reads the log via
`GET /api/reports/pricing-insights/email-history`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from config import db, logger, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL
from utils import now_iso, new_id


def _fmt_money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _compose_html(tenant_name: str, month: str, services: List[Dict[str, Any]],
                    suggestions: List[Dict[str, Any]]) -> str:
    rows_html = ""
    by_type = {s.get("service_type"): s for s in suggestions}
    for svc in services:
        sug = by_type.get(svc["service_type"]) or {}
        tps = "".join(f"<li>{p}</li>" for p in (sug.get("customer_talking_points") or []))
        rows_html += f"""
        <tr>
          <td style='padding:10px 12px;border-bottom:1px solid #E2E8F0;vertical-align:top;'>
            <div style='font-weight:600;color:#0F172A;'>{svc['service_type']}</div>
            <div style='font-size:12px;color:#64748B;'>{svc['job_count']} jobs · margin {svc['margin_pct']:.1f}%</div>
          </td>
          <td style='padding:10px 12px;border-bottom:1px solid #E2E8F0;vertical-align:top;font-size:13px;'>
            <div>Current avg: <b>{_fmt_money(sug.get('current_avg_price_cents', 0))}</b></div>
            <div style='color:#0EA5E9;'>Recommend: <b>{_fmt_money(sug.get('recommended_price_cents', 0))}</b></div>
            <div style='color:#166534;font-size:12px;'>+{sug.get('expected_margin_lift_pct', 0)}% margin lift</div>
          </td>
          <td style='padding:10px 12px;border-bottom:1px solid #E2E8F0;vertical-align:top;font-size:12px;color:#334155;'>
            {sug.get('rationale', '—')}
            <ul style='margin:6px 0 0 16px;padding:0;font-size:12px;color:#475569;'>{tps}</ul>
          </td>
        </tr>
        """
    if not rows_html:
        rows_html = ("<tr><td colspan='3' style='padding:16px;text-align:center;"
                      "color:#64748B;font-size:13px;'>No completed jobs with cost data "
                      "in this month.</td></tr>")
    return f"""
    <div style="max-width:640px;margin:0 auto;font-family:Arial,sans-serif;">
      <div style="background:#0F172A;padding:20px;border-radius:10px 10px 0 0;color:#fff;">
        <h1 style="margin:0;font-size:20px;">{tenant_name} · Monthly Pricing Insights</h1>
        <div style="font-size:12px;opacity:0.85;margin-top:4px;">
          {month} · least-profitable service types + AI-drafted price increases
        </div>
      </div>
      <div style="border:1px solid #E2E8F0;border-top:none;border-radius:0 0 10px 10px;padding:0;background:#fff;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#F1F5F9;">
              <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748B;">Service</th>
              <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748B;">Pricing</th>
              <th style="padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748B;">Rationale · Talking Points</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        <div style="padding:12px 16px;font-size:12px;color:#64748B;border-top:1px solid #E2E8F0;">
          <a href="{APP_PUBLIC_URL or ''}/admin/reports/pricing-insights"
             style="color:#0EA5E9;text-decoration:underline;">
            Open in the app →
          </a>
        </div>
      </div>
    </div>
    """


async def _get_tenant_admin_emails(tenant_id: str) -> List[str]:
    users = await db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "email": 1},
    ).to_list(200)
    seen: set[str] = set()
    out: List[str] = []
    for u in users:
        e = (u.get("email") or "").strip()
        if e and e not in seen:
            seen.add(e); out.append(e)
    return out


async def _send_via_resend(subject: str, html: str, to_emails: List[str]) -> Dict[str, Any]:
    if not RESEND_API_KEY:
        return {"sent": False, "mocked": True, "reason": "resend_key_missing"}
    if not to_emails:
        return {"sent": False, "mocked": True, "reason": "no_recipients"}
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resp = resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": to_emails, "subject": subject, "html": html,
        })
        return {"sent": True, "mocked": False, "resend_id": (resp or {}).get("id")}
    except Exception as e:
        logger.warning(f"pricing digest send failed: {e}")
        return {"sent": False, "mocked": True, "reason": f"resend_error: {e}"}


async def run_monthly_pricing_digest() -> Dict[str, Any]:
    """Iterate tenants — compute least-profitable, call LLM, email (or mock),
    log the attempt."""
    # Lazy imports to avoid circulars at module import time.
    from routers.jobs import least_profitable_services
    from routers.cfo import price_increase_suggestions, PricingSuggestionsBody

    now = datetime.now(timezone.utc)
    y = now.year if now.month > 1 else now.year - 1
    m = now.month - 1 if now.month > 1 else 12
    month_key = f"{y:04d}-{m:02d}"
    results: List[Dict[str, Any]] = []
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    for t in tenants:
        tid = t["id"]
        tenant_name = t.get("name") or "Your business"
        # Fake a super_admin user shim so the require_admin dependency in
        # the endpoints below is satisfied. We only pass through to the
        # compute helpers — no HTTP layer is involved.
        admin_shim = {"id": "cron", "role": "super_admin", "tenant_id": tid}
        tenant_shim = {"id": tid, "name": tenant_name}
        try:
            ranked = await least_profitable_services(
                month=month_key, limit=3, admin=admin_shim, tenant=tenant_shim,
            )
            services = ranked.get("services") or []
        except Exception as e:
            logger.warning(f"pricing digest rank failed for {tid}: {e}")
            services = []
        suggestions: List[Dict[str, Any]] = []
        if services:
            try:
                sug = await price_increase_suggestions(
                    PricingSuggestionsBody(month=month_key),
                    user=admin_shim, tenant=tenant_shim,
                )
                suggestions = sug.get("suggestions") or []
            except Exception as e:
                logger.warning(f"pricing digest LLM failed for {tid}: {e}")
        recipients = await _get_tenant_admin_emails(tid)
        html = _compose_html(tenant_name, month_key, services, suggestions)
        subject = f"{tenant_name} · Monthly Pricing Insights · {month_key}"
        result = await _send_via_resend(subject, html, recipients)
        doc = {
            "id": new_id(), "tenant_id": tid,
            "kind": "monthly_pricing_digest",
            "month": month_key,
            "recipients": recipients,
            "service_count": len(services),
            "suggestion_count": len(suggestions),
            "sent": bool(result.get("sent")),
            "mocked": bool(result.get("mocked")),
            "reason": result.get("reason"),
            "resend_id": result.get("resend_id"),
            "sent_at": now_iso(),
        }
        try:
            await db.email_delivery_log.insert_one(doc)
        except Exception as e:
            logger.warning(f"email_delivery_log insert failed: {e}")
        results.append({"tenant_id": tid, "tenant_name": tenant_name,
                         **result, "services": len(services),
                         "suggestions": len(suggestions)})
    return {"tenants_processed": len(results), "month": month_key, "results": results}
