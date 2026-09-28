"""Phase 4 · Batch C / Deliverable 7 — Weekly Digest email service.

Aggregates prior-7-day tenant activity into an HTML email and sends via
Resend. Scheduled by APScheduler at Monday 08:00 in each tenant's
timezone (fallback America/Los_Angeles).

Reuses the pattern from `monthly_pricing_digest.py` — same tri-state
logging in `db.outbound_emails` (`sent` / `failed` / `not_sent_missing_key`)
so the audit trail exists even when the Resend key is missing.

Idempotency: `(tenant_id, ISO year-week, recipient_id, kind)` unique guard.
"""
from __future__ import annotations
import logging, os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import now_iso

logger = logging.getLogger(__name__)


DEFAULT_TZ = "America/Los_Angeles"


def _iso_week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y:04d}-W{w:02d}"


async def _tenant_timezone(tenant: dict) -> str:
    """Return the tenant's IANA timezone or the module default."""
    return (tenant.get("timezone") or "").strip() or DEFAULT_TZ


async def _tenant_admin_recipients(tenant_id: str) -> List[Dict[str, Any]]:
    return await db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1},
    ).to_list(200)


async def _count(col: str, q: dict) -> int:
    try: return await db[col].count_documents(q)
    except Exception: return 0


async def _sum_field(col: str, q: dict, field: str) -> float:
    try:
        pipe = [{"$match": q}, {"$group": {"_id": None, "s": {"$sum": f"${field}"}}}]
        rows = await db[col].aggregate(pipe).to_list(1)
        return float(rows[0]["s"]) if rows else 0.0
    except Exception:
        return 0.0


async def _aggregate_tenant_week(tenant: dict, as_of: Optional[datetime] = None) -> Dict[str, Any]:
    """Build the digest payload for the prior 7 days ending `as_of`."""
    now = as_of or datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    tid = tenant["id"]
    q_win = {"tenant_id": tid, "created_at": {"$gte": start.isoformat()}}

    # Revenue & Billing
    invoices_new     = await _count("invoices", q_win)
    invoiced_total   = await _sum_field("invoices", q_win, "total")
    payments_total   = await _sum_field("payments", q_win, "amount")
    overdue          = await _count("invoices", {"tenant_id": tid, "status": {"$in": ["overdue", "past_due"]}})

    # Field Operations
    jobs_completed   = await _count("jobs", {"tenant_id": tid, "status": "complete",
                                              "updated_at": {"$gte": start.isoformat()}})
    jobs_pending     = await _count("jobs", {"tenant_id": tid, "status": {"$in": ["pending", "scheduled"]}})
    job_requests_new = await _count("job_requests", q_win)

    # Customer Activity
    customers_new    = await _count("customers", q_win)
    portal_downloads = await _count("documents", {"tenant_id": tid, "created_at": {"$gte": start.isoformat()}})

    # Team + onboarding-behind
    team_new         = await _count("users", {"tenant_id": tid, "role": {"$in": ["pool_tech", "landscape_tech"]},
                                                "created_at": {"$gte": start.isoformat()}})
    tech_top: List[Dict[str, Any]] = []
    try:
        pipe = [
            {"$match": {"tenant_id": tid, "status": "complete",
                         "updated_at": {"$gte": start.isoformat()}}},
            {"$group": {"_id": "$assigned_to", "jobs": {"$sum": 1}}},
            {"$sort": {"jobs": -1}}, {"$limit": 3},
        ]
        tech_top = await db.jobs.aggregate(pipe).to_list(3)
    except Exception:
        pass
    onboarding_behind: List[str] = []
    try:
        cutoff = (now - timedelta(days=14)).isoformat()
        users = await db.users.find(
            {"tenant_id": tid, "role": {"$in": ["pool_tech", "landscape_tech"]},
             "created_at": {"$lte": cutoff}},
            {"_id": 0, "id": 1, "email": 1}).to_list(200)
        # Count completed onboarding tasks per user
        for u in users:
            done = await db.onboarding_progress.count_documents(
                {"tenant_id": tid, "user_id": u["id"], "status": "complete"})
            total = await db.onboarding_tasks.count_documents(
                {"$or": [{"is_system": True}, {"tenant_id": tid}]})
            if total > 0 and (done / total) < 0.5:
                onboarding_behind.append(u.get("email") or u["id"])
    except Exception:
        pass

    # Training
    training_completions = 0
    try:
        training_completions = await db.training_progress.count_documents(
            {"tenant_id": tid, "status": "passed",
             "updated_at": {"$gte": start.isoformat()}})
    except Exception:
        pass

    # Templates finalized this week (top 5 by code)
    templates_top: List[Dict[str, Any]] = []
    try:
        pipe = [
            {"$match": {"tenant_id": tid, "status": "finalized",
                         "finalized_at": {"$gte": start.isoformat()}}},
            {"$group": {"_id": "$template_code", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 5},
        ]
        templates_top = await db.template_instances.aggregate(pipe).to_list(5)
    except Exception:
        pass

    # AI CFO highlights — reuse whatever the cfo service already produced
    cfo_highlights: List[Dict[str, Any]] = []
    try:
        row = await db.cfo_snapshots.find_one(
            {"tenant_id": tid}, {"_id": 0, "highlights": 1, "created_at": 1},
            sort=[("created_at", -1)])
        cfo_highlights = list((row or {}).get("highlights") or [])[:3]
    except Exception:
        pass

    # Growth playbook
    growth_summary = ""
    try:
        row = await db.growth_playbook_snapshots.find_one(
            {"tenant_id": tid}, {"_id": 0, "summary": 1, "created_at": 1},
            sort=[("created_at", -1)])
        growth_summary = (row or {}).get("summary") or ""
    except Exception:
        pass

    return {
        "tenant_id": tid,
        "tenant_name": tenant.get("name") or "Your business",
        "week_of": start.strftime("%b %d, %Y"),
        "iso_week": _iso_week(start),
        "revenue": {
            "invoices_new": invoices_new,
            "invoiced_total": round(invoiced_total, 2),
            "payments_total": round(payments_total, 2),
            "overdue": overdue,
        },
        "operations": {
            "jobs_completed": jobs_completed,
            "jobs_pending": jobs_pending,
            "job_requests_new": job_requests_new,
        },
        "customers": {
            "new": customers_new,
            "portal_downloads": portal_downloads,
        },
        "team": {
            "new_employees": team_new,
            "top_techs": tech_top,
            "onboarding_behind": onboarding_behind,
        },
        "training": {"completions": training_completions},
        "templates_finalized_top": templates_top,
        "cfo_highlights": cfo_highlights,
        "growth_summary": growth_summary,
    }


def render_html(payload: Dict[str, Any], dashboard_url: str = "#",
                  *, locale: str = "en") -> str:
    """Phase D6.2 · Feb-2026 — section headings, row labels, empty-
    state text, CTA, and footer note are resolved via the D6 i18n
    catalog. Data (dollar amounts, counts, tech names, template
    codes) passes through untranslated."""
    from services.email_body_i18n import t_email_body
    r = payload["revenue"]; ops = payload["operations"]; c = payload["customers"]
    t = payload["team"]; tr = payload["training"]
    _t_unassigned = t_email_body(
        locale, "email.weekly_digest.team.techrow_unassigned")
    tech_rows = "".join(
        f"<li>{row.get('_id') or _t_unassigned} — {row['jobs']} jobs</li>"
        for row in t.get("top_techs", []))
    behind = t.get("onboarding_behind") or []
    behind_html = ""
    if behind:
        _hd = t_email_body(locale, "email.weekly_digest.onboarding.heading")
        _bd = t_email_body(
            locale, "email.weekly_digest.onboarding.body",
            count=len(behind), names=", ".join(behind[:5]),
        )
        behind_html = (
            f"<div style='background:#FEF3C7;padding:8px;border-radius:6px;margin-top:8px'>"
            f"<b>{_hd}</b> {_bd}</div>"
        )
    tpl_rows = "".join(
        f"<li>{row.get('_id')} — {row['n']}</li>"
        for row in payload.get("templates_finalized_top", []))
    cfo_rows = "".join(
        f"<li>{h if isinstance(h, str) else (h.get('title') or h.get('text') or '')}</li>"
        for h in payload.get("cfo_highlights", []))
    _growth_empty = t_email_body(locale, "email.weekly_digest.growth.empty")
    growth = payload.get("growth_summary") or f"<i>{_growth_empty}</i>"

    # Resolve every localised label once so the giant f-string stays
    # readable — full sentences per key, no fragment concatenation.
    L = lambda key, **kw: t_email_body(locale, key, **kw)
    return f"""<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111;max-width:600px;margin:0 auto;padding:16px">
  <h1 style="font-size:22px;margin:0 0 4px 0">{payload['tenant_name']}</h1>
  <div style="color:#666;font-size:13px;margin-bottom:16px">{L("email.weekly_digest.subtitle", week_of=payload['week_of'])}</div>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.revenue")}</h2>
  <ul>
    <li>{L("email.weekly_digest.revenue.new_invoices", value=r['invoices_new'])}</li>
    <li>{L("email.weekly_digest.revenue.invoiced_total", value=f"{r['invoiced_total']:,.2f}")}</li>
    <li>{L("email.weekly_digest.revenue.payments_received", value=f"{r['payments_total']:,.2f}")}</li>
    <li>{L("email.weekly_digest.revenue.overdue", value=r['overdue'])}</li>
  </ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.operations")}</h2>
  <ul>
    <li>{L("email.weekly_digest.operations.jobs_completed", value=ops['jobs_completed'])}</li>
    <li>{L("email.weekly_digest.operations.jobs_pending", value=ops['jobs_pending'])}</li>
    <li>{L("email.weekly_digest.operations.new_requests", value=ops['job_requests_new'])}</li>
  </ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.customers")}</h2>
  <ul>
    <li>{L("email.weekly_digest.customers.new", value=c['new'])}</li>
    <li>{L("email.weekly_digest.customers.portal_downloads", value=c['portal_downloads'])}</li>
  </ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.team")}</h2>
  <ul>
    <li>{L("email.weekly_digest.team.new_employees", value=t['new_employees'])}</li>
    <li>{L("email.weekly_digest.team.top_techs_label")}<ul>{tech_rows or f"<li><i>{L('email.weekly_digest.team.no_completions')}</i></li>"}</ul></li>
  </ul>
  {behind_html}

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.training")}</h2>
  <ul><li>{L("email.weekly_digest.training.modules_completed", value=tr['completions'])}</li></ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.templates")}</h2>
  <ul>{tpl_rows or f"<li><i>{L('email.weekly_digest.templates.empty')}</i></li>"}</ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.cfo")}</h2>
  <ul>{cfo_rows or f"<li><i>{L('email.weekly_digest.cfo.empty')}</i></li>"}</ul>

  <h2 style="font-size:16px;border-bottom:1px solid #eee;padding-bottom:4px">{L("email.weekly_digest.section.growth")}</h2>
  <div>{growth}</div>

  <div style="margin-top:24px">
    <a href="{dashboard_url}" style="background:#0EA5E9;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none;font-weight:700">{L("email.weekly_digest.cta_dashboard")}</a>
  </div>
  <div style="color:#999;font-size:11px;margin-top:24px">{L("email.weekly_digest.footer_note")}</div>
</body></html>"""


async def _send_via_resend(subject: str, html: str, to_email: str) -> Dict[str, Any]:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return {"sent": False, "reason": "not_sent_missing_key"}
    try:
        import resend  # type: ignore
        resend.api_key = key
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
        resp = resend.Emails.send({
            "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
            "to": [to_email], "subject": subject, "html": html,
        })
        return {"sent": True, "resend_id": (resp or {}).get("id") if isinstance(resp, dict) else None}
    except Exception as e:
        logger.warning(f"weekly digest send failed: {e}")
        return {"sent": False, "reason": f"resend_error: {e}"}


async def _log_attempt(tenant_id: str, recipient_id: str, recipient_email: str,
                        iso_week: str, kind: str, status: str,
                        subject: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
    doc = {
        "tenant_id": tenant_id,
        "recipient_id": recipient_id,
        "recipient_email": recipient_email,
        "iso_week": iso_week,
        "kind": kind,
        "status": status,
        "subject": subject,
        "created_at": now_iso(),
    }
    if extra: doc.update(extra)
    try:
        await db.outbound_emails.insert_one(doc)
    except Exception as e:
        logger.warning(f"outbound_emails insert failed: {e}")


async def send_weekly_digest_for_tenant(tenant: dict, as_of: Optional[datetime] = None,
                                          kind: str = "weekly_digest",
                                          override_to: Optional[str] = None) -> Dict[str, Any]:
    payload = await _aggregate_tenant_week(tenant, as_of=as_of)
    # Phase D6.2 · Feb-2026 — resolve locale for subject + section
    # headings. Weekly-digest recipients are the tenant's admin
    # users; the D5 audience rule labels admin messaging as ops
    # and locks it to English, BUT we route through the tenant's
    # ``default_locale`` here so a Spanish-owned tenant's admin
    # gets a Spanish digest. The K72 ``audience="internal"`` label
    # only affects the customer-comms kill switch, not the copy
    # locale.
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=None, tenant=tenant)
    html = render_html(payload, locale=_locale)
    subject = t_email_body(
        _locale, "email.weekly_digest.subject",
        tenant_name=payload['tenant_name'], week_of=payload['week_of'],
    )
    iso_week = payload["iso_week"]

    recipients = ([{"id": "manual", "email": override_to, "name": "Manual"}]
                  if override_to else
                  await _tenant_admin_recipients(tenant["id"]))
    results = []
    for u in recipients:
        rid = u.get("id") or "unknown"
        remail = u.get("email") or ""
        if not remail:
            continue
        # Idempotency guard — skip if already logged this ISO week.
        if kind == "weekly_digest":
            existing = await db.outbound_emails.find_one({
                "tenant_id": tenant["id"], "recipient_id": rid,
                "iso_week": iso_week, "kind": kind,
                "status": {"$in": ["sent"]},
            })
            if existing:
                results.append({"email": remail, "status": "skipped_dupe"})
                continue
        res = await _send_via_resend(subject, html, remail)
        status = "sent" if res.get("sent") else (res.get("reason") or "failed")
        # Normalize the missing-key state to the tri-state pattern used in
        # auto_visit_email.py + monthly_pricing_digest.
        if status == "not_sent_missing_key":
            status = "not_sent_missing_key"
        elif not res.get("sent"):
            status = "failed"
        await _log_attempt(tenant["id"], rid, remail, iso_week, kind,
                            status, subject=subject,
                            extra={"resend_id": res.get("resend_id")})
        results.append({"email": remail, "status": status})
    return {"tenant_id": tenant["id"], "iso_week": iso_week,
             "recipients": len(results), "results": results, "payload": payload}


async def run_weekly_digest() -> Dict[str, Any]:
    """Called by the scheduler each Monday. Iterates every tenant."""
    tenants = await db.tenants.find(
        {}, {"_id": 0, "id": 1, "name": 1, "timezone": 1}).to_list(500)
    out = []
    for t in tenants:
        try:
            out.append(await send_weekly_digest_for_tenant(t))
        except Exception as e:
            logger.warning(f"weekly_digest failed for tenant {t.get('id')}: {e}")
    return {"tenants_processed": len(out), "results": out}


async def ensure_indexes():
    """Compound unique index for idempotency."""
    try:
        # Non-unique index for query speed; the guard is applied in-code
        # because legacy rows may not carry `iso_week`.
        await db.outbound_emails.create_index(
            [("tenant_id", 1), ("iso_week", 1), ("kind", 1), ("recipient_id", 1)],
            name="ob_weekly_digest_idx")
    except Exception as e:
        logger.warning(f"outbound_emails index skipped: {e}")
