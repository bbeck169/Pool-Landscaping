"""Phase 50.G · Auto-Friday Pool Service Report email.

Runs every Friday 17:00 UTC via APScheduler cron. For every tenant that
has at least one admin/super_admin user, we:

1. Compute this week's Pool Service Report (same math as
   `GET /api/reports/pool-service`).
2. Compose a lightweight HTML digest.
3. Send via Resend if RESEND_API_KEY is set; otherwise log to
   `email_delivery_log` with `mocked:true, reason:"resend_key_missing"`.
4. Record every attempt (real or mocked) in `email_delivery_log`
   under `kind: "pool_service_report"` so the admin history panel can
   surface the last 10 runs.

This module is import-safe: the scheduler wire-up in server.py just
calls `run_weekly_pool_service_email()`. The Friday cadence, timezone,
and retry policy are configured at scheduler-registration time — we
just want to hit the "email each admin" iteration correctly.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from config import db, logger, RESEND_API_KEY, EMAIL_FROM, APP_PUBLIC_URL
from utils import now_iso, new_id


def _compose_html(tenant_name: str, report: Dict[str, Any]) -> str:
    """Compose the weekly pool-service admin digest email.

    POOL-B · Feb-2026 — renders two sections side-by-side:
      * **Maintenance Visits** — techs with ``pools_serviced > 0``
        (``work_class == "service"``).
      * **Repairs Completed** — techs with ``repairs_completed > 0``
        (``work_class == "repair"``).
    Bottom-of-email summary: ``Maintenance: N · Repairs: M · Total: N+M``.
    Landscape jobs are filtered at the aggregation query (see
    ``compute_pool_service``), not in the template.
    """
    summary = report.get("summary") or {}
    total_service = int(summary.get("maintenance_visits") or 0)
    total_repair  = int(summary.get("repair_visits") or 0)
    total_other   = int(summary.get("other_visits") or 0)
    total_skipped = int(report.get("total_skipped") or 0)

    def _tech_rows_html(rows, count_key, count_label, empty_text):
        rows = rows or []
        if not rows:
            return (
                "<tr><td colspan='3' style='padding:16px;text-align:center;"
                f"color:#64748B;'>{empty_text}</td></tr>"
            )
        html = ""
        for r in rows:
            html += (
                "<tr>"
                "<td style='padding:6px 12px;border-bottom:1px solid #E2E8F0'>"
                f"{r.get('technician_name', '—')}</td>"
                "<td style='padding:6px 12px;border-bottom:1px solid #E2E8F0;"
                f"text-align:right;font-weight:600'>{int(r.get(count_key) or 0)}</td>"
                "<td style='padding:6px 12px;border-bottom:1px solid #E2E8F0;"
                f"text-align:right;color:#B45309'>{int(r.get('skipped') or 0)}</td>"
                "</tr>"
            )
        return html

    maintenance_html = _tech_rows_html(
        report.get("maintenance"), "pools_serviced",
        "Pools Serviced",
        "No maintenance visits this week.",
    )
    repairs_html = _tech_rows_html(
        report.get("repairs"), "repairs_completed",
        "Repairs Completed",
        "No repairs completed this week.",
    )
    other_html = ""
    if total_other > 0:
        other_html = f"""
        <div style="margin-top:20px;font-size:12px;color:#B45309;
                    background:#FEF3C7;padding:10px 14px;border-radius:8px;">
          <b>{total_other}</b> completed pool visit(s) with unknown
          <code>work_class</code> — please check the raw job records.
        </div>
        """
    return f"""
    <div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;color:#0F172A;">
      <div style="background:#0EA5E9;padding:20px;border-radius:10px 10px 0 0;color:#fff;">
        <h1 style="margin:0;font-size:20px;">{tenant_name} · Weekly Pool Service Report</h1>
        <div style="font-size:12px;opacity:0.9;margin-top:4px;">
          Week {report.get('week_start')} → {report.get('week_end')}
        </div>
      </div>
      <div style="border:1px solid #E2E8F0;border-top:none;border-radius:0 0 10px 10px;padding:16px;background:#fff;">

        <h2 style="margin:4px 0 8px;font-size:15px;color:#0F172A;">Maintenance Visits</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:24px;">
          <thead>
            <tr style="background:#F1F5F9;">
              <th style="padding:8px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748B;">Technician</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;text-transform:uppercase;color:#64748B;">Pools Serviced</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;text-transform:uppercase;color:#64748B;">Skipped</th>
            </tr>
          </thead>
          <tbody>{maintenance_html}</tbody>
        </table>

        <h2 style="margin:4px 0 8px;font-size:15px;color:#0F172A;">Repairs Completed</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#F1F5F9;">
              <th style="padding:8px 12px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748B;">Technician</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;text-transform:uppercase;color:#64748B;">Repairs</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;text-transform:uppercase;color:#64748B;">Skipped</th>
            </tr>
          </thead>
          <tbody>{repairs_html}</tbody>
        </table>

        {other_html}

        <div style="margin-top:20px;font-size:13px;color:#334155;
                    padding-top:14px;border-top:1px solid #E2E8F0;">
          <b>Maintenance: {total_service}</b>
          &nbsp;·&nbsp;
          <b>Repairs: {total_repair}</b>
          &nbsp;·&nbsp;
          <b>Total: {total_service + total_repair}</b>
          &nbsp;·&nbsp;
          <span style="color:#B45309;">Skipped: {total_skipped}</span>
        </div>

        <div style="margin-top:16px;font-size:12px;color:#64748B;">
          <a href="{APP_PUBLIC_URL or ''}/admin/reports/pool-service" style="color:#0EA5E9;text-decoration:underline;">
            View full report in the app →
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
            seen.add(e)
            out.append(e)
    return out


async def _send_via_resend(subject: str, html: str, to_emails: List[str]) -> Dict[str, Any]:
    if not RESEND_API_KEY:
        return {"sent": False, "mocked": True, "reason": "resend_key_missing"}
    if not to_emails:
        return {"sent": False, "mocked": True, "reason": "no_recipients"}
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
        resp = resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": to_emails,
            "subject": subject,
            "html": html,
        })
        return {"sent": True, "mocked": False, "resend_id": (resp or {}).get("id")}
    except Exception as e:
        logger.warning(f"pool-service email send failed: {e}")
        return {"sent": False, "mocked": True, "reason": f"resend_error: {e}"}


async def _log_delivery(tenant_id: str, report: Dict[str, Any],
                         recipients: List[str], result: Dict[str, Any]) -> None:
    # Fix 3 · Feb-2026 — Pool-service drill-down follow-up.
    #
    # Snapshot the completed jobs that WOULD have been in the
    # email body at SEND TIME. ``/email-history/{id}/contents``
    # reads this snapshot directly so jobs completed AFTER the
    # delivery can't backfill into a historic email's "included"
    # list (prior behavior re-ran the aggregator at request time
    # which caused the "contents shows 5 jobs but delivery.
    # total_completed=4" drift).
    #
    # Shape (lean on purpose — we skip the heavy per-job payload):
    #   {
    #     "job_ids":      [str, ...],                 # dedupe + sort
    #     "customer_ids": [str, ...],                 # dedupe + sort
    #     "jobs": [{job_id, title, customer_id,
    #                customer_name, scheduled_date,
    #                work_class, status}, ...],
    #   }
    #
    # ``work_class`` surfaces so the modal can label each row
    # Maintenance / Repair / Other without a second lookup.
    payload_snapshot = _build_delivery_snapshot(report)
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "kind": "pool_service_report",
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "recipients": recipients,
        "total_completed": int(report.get("total_completed") or 0),
        "total_skipped": int(report.get("total_skipped") or 0),
        "sent": bool(result.get("sent")),
        "mocked": bool(result.get("mocked")),
        "reason": result.get("reason"),
        "resend_id": result.get("resend_id"),
        "sent_at": now_iso(),
        "payload_snapshot": payload_snapshot,
    }
    try:
        await db.email_delivery_log.insert_one(doc)
    except Exception as e:
        logger.warning(f"email_delivery_log insert failed: {e}")


def _build_delivery_snapshot(report: Dict[str, Any]) -> Dict[str, Any]:
    """Build a minimal snapshot of completed jobs for the email.

    Fix 3 (Feb-2026) — ``/email-history/{id}/contents`` reads
    this instead of recomputing. The snapshot captures the LIVE
    aggregator's view at send-time: only maintenance + repairs +
    other-typed completed jobs are included (matches the email
    body). Skipped visits are tracked on the delivery row via
    ``total_skipped`` but never render in the drill-down.

    ``report`` is the dict returned by ``compute_pool_service`` —
    we read its ``_jobs_sample`` field when present, else fall
    through to the per-tech rows + customer_ids known there. The
    richer per-job snapshot is populated by the caller (see
    ``run_weekly_pool_service_email``) which has access to the
    raw jobs list via the aggregator helper.
    """
    jobs = report.get("_jobs_sample") or []
    seen_jobs: set = set()
    seen_customers: set = set()
    rows: List[Dict[str, Any]] = []
    for j in jobs:
        jid = j.get("job_id") or j.get("id")
        cid = j.get("customer_id")
        if not jid or jid in seen_jobs:
            continue
        seen_jobs.add(jid)
        if cid:
            seen_customers.add(cid)
        rows.append({
            "job_id":         jid,
            "title":          j.get("title") or "",
            "customer_id":    cid,
            "customer_name":  j.get("customer_name") or "",
            "scheduled_date": j.get("scheduled_date"),
            "work_class":     j.get("work_class"),
            "status":         j.get("status") or "completed",
        })
    return {
        "job_ids":      sorted(seen_jobs),
        "customer_ids": sorted(seen_customers),
        "jobs":         rows,
    }


async def run_weekly_pool_service_email() -> Dict[str, Any]:
    """Iterate every tenant, compute the weekly pool-service report,
    email admins (or MOCK) and log.

    Backlog #iv · Feb-2026 — Two-layer duplicate-fire defense:

    1. **Scheduler lease** at the top of the tick — only one process
       runs the body per (job_id, minute-of-fire).  Contested calls
       no-op cleanly.  Combined with the fact that we call
       ``try_acquire_lease`` before entering the tenant loop, N
       replicas of the scheduler produce exactly one full sweep.
    2. **Dispatch-log guard** per (tenant, iso_week) — even if the
       lease races (fail-open on Mongo error), the compound unique
       index on ``notification_dispatch_log`` catches the survivor
       and returns ``already_dispatched``.  ``result="skipped_dedupe"``
       falls through in ``results`` so ops can see the guard firing.
    """
    from services.comms_hardening.scheduler_lease import (
        try_acquire_lease, release_lease,
    )
    from services.comms_hardening.dispatch_guard import (
        guard_and_log, mark_dispatch_result, hash_email,
    )

    lease = await try_acquire_lease(job_id="pool_service_weekly_email")
    if not lease.get("acquired"):
        logger.info(
            "[pool-service-email] lease not acquired · reason=%s tick=%s",
            lease.get("reason"), lease.get("tick_iso"),
        )
        return {"tenants_processed": 0, "results": [],
                "lease": "not_acquired", "tick_iso": lease.get("tick_iso")}

    # Lazy import to avoid circular jobs.py → this module.
    from routers.jobs import (
        compute_pool_service,
        collect_completed_pool_jobs_for_window,
    )
    results: List[Dict[str, Any]] = []
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    for t in tenants:
        tid = t["id"]
        tenant_name = t.get("name") or "Your business"
        try:
            report = await compute_pool_service(tid)
        except Exception as e:
            logger.warning(f"pool-service compute skipped for tenant {tid}: {e}")
            continue
        # Fix 3 · Feb-2026 — snapshot the completed jobs for this
        # tenant/week BEFORE sending so ``_log_delivery`` can
        # persist them on the delivery row (``payload_snapshot``).
        # ``/email-history/{id}/contents`` reads this snapshot
        # instead of recomputing at request time, which keeps the
        # historic email contents stable even if more jobs are
        # completed after the delivery.
        try:
            _snap_jobs = await collect_completed_pool_jobs_for_window(
                tid, report.get("week_start"), report.get("week_end"),
            )
            report["_jobs_sample"] = _snap_jobs
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "pool-service snapshot collection failed for %s: %s",
                tid, e,
            )
            report["_jobs_sample"] = []
        recipients = await _get_tenant_admin_emails(tid)
        html = _compose_html(tenant_name, report)
        subject = f"{tenant_name} · Pool Service Report · {report.get('week_start')} → {report.get('week_end')}"

        # Backlog #iv · dispatch-log guard.  One row per
        # (tenant, iso_week) — this is admin-facing, so we don't
        # apply the deny-list here (admins ARE the audience).
        dedupe_key = (
            f"pool_service_report:{tid}:{report.get('week_start')}"
        )
        # Aggregate all admin emails into a single "digest" recipient
        # id.  A stable hash of the sorted list means adding/removing
        # an admin creates a new dedupe row (new admins get the email
        # even if a sibling admin already got it this week — that's
        # the desired failure mode).
        agg_recipient = hash_email(",".join(sorted(recipients))) or "no_admins"
        guard = await guard_and_log(
            tenant_id=tid,
            notification_type="pool_service_report",
            recipient_id=agg_recipient,
            dedupe_key=dedupe_key,
            channel="email",
            resolved_address=", ".join(recipients),
            subject=subject,
            metadata={
                "week_start": report.get("week_start"),
                "week_end": report.get("week_end"),
                "recipient_count": len(recipients),
            },
        )
        if not guard["allowed"]:
            logger.info(
                "[pool-service-email] dedupe skip · tenant=%s week=%s "
                "reason=%s",
                tid, report.get("week_start"), guard["reason"],
            )
            results.append({"tenant_id": tid, "tenant_name": tenant_name,
                              "sent": False, "mocked": False,
                              "reason": "skipped_dedupe",
                              "recipients": len(recipients)})
            continue

        result = await _send_via_resend(subject, html, recipients)
        # Belt-and-suspenders: legacy delivery log (audit history).
        await _log_delivery(tid, report, recipients, result)
        # Backlog #iv: stamp the outcome on the dispatch-log row.
        await mark_dispatch_result(
            guard["dispatch_id"],
            status=("sent" if result.get("sent")
                     else ("mocked" if result.get("mocked") else "failed")),
            provider_id=result.get("resend_id"),
            error=result.get("reason") if not result.get("sent") else None,
        )
        results.append({"tenant_id": tid, "tenant_name": tenant_name, **result,
                          "recipients": len(recipients)})

    # Optional: release the lease so a Mon 09:00 UTC re-tick can run
    # (won't happen — cron is Fri 17:00 UTC weekly — but keeps the
    # collection tidy).  Safe no-op when Mongo is down.
    await release_lease(lease.get("lease_id"))
    return {"tenants_processed": len(results), "results": results,
             "lease": "acquired", "tick_iso": lease.get("tick_iso")}


async def send_pool_service_email_now(
    tenant_id: str, week_ref: str | None = None,
) -> Dict[str, Any]:
    """Mini-fix B · Feb-2026 — admin-triggered send.

    Runs the SAME pipeline as the Friday cron for a single
    tenant/week but intentionally BYPASSES the dedupe guard so
    an admin can re-send after a correction (brief rule: "allow
    repeats; each run creates its own delivery record").

    ``week_ref`` is any ISO date inside the target week; the
    aggregator derives the Mon-Sun window from it. ``None``
    defaults to this week.

    Returns the stub ``{delivery_id, sent, mocked, reason,
    recipient_count, week_start, week_end}`` so the admin
    endpoint can echo it back and tag the audit log.
    """
    # Lazy imports keep the module import-safe (same pattern as
    # the scheduler path above).
    from routers.jobs import (
        compute_pool_service,
        collect_completed_pool_jobs_for_window,
    )
    tenant_doc = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "id": 1, "name": 1},
    ) or {"id": tenant_id}
    tenant_name = tenant_doc.get("name") or "Your business"

    # ``week_ref`` is any ISO date inside the target week. We
    # pass it as ``date_from`` only (NOT both ``date_from`` and
    # ``date_to`` — doing so would clamp the window to a single
    # day). ``compute_pool_service`` runs ``_service_week`` when
    # only one endpoint is supplied and derives the Mon-Sun
    # window from the anchor. ``None`` defaults to the current
    # week via the same helper.
    report = await compute_pool_service(tenant_id, week_ref, None)
    try:
        report["_jobs_sample"] = await collect_completed_pool_jobs_for_window(
            tenant_id, report.get("week_start"), report.get("week_end"),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "pool-service manual snapshot collection failed for %s: %s",
            tenant_id, e,
        )
        report["_jobs_sample"] = []

    recipients = await _get_tenant_admin_emails(tenant_id)
    html = _compose_html(tenant_name, report)
    subject = (
        f"{tenant_name} · Pool Service Report · "
        f"{report.get('week_start')} → {report.get('week_end')}"
    )
    result = await _send_via_resend(subject, html, recipients)
    # Delivery row — this writes the ``payload_snapshot`` populated
    # above so the ``/contents`` drill-down reads a FROZEN view.
    # We capture the generated ``id`` BEFORE calling the opaque
    # ``_log_delivery`` helper by re-implementing its logic inline;
    # keeps the helper's shape stable for the scheduler path.
    delivery_id = new_id()
    doc = {
        "id": delivery_id,
        "tenant_id": tenant_id,
        "kind": "pool_service_report",
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "recipients": recipients,
        "total_completed": int(report.get("total_completed") or 0),
        "total_skipped": int(report.get("total_skipped") or 0),
        "sent": bool(result.get("sent")),
        "mocked": bool(result.get("mocked")),
        "reason": result.get("reason"),
        "resend_id": result.get("resend_id"),
        "sent_at": now_iso(),
        "payload_snapshot": _build_delivery_snapshot(report),
        # Mini-fix B · tag manual-trigger rows so admins can
        # distinguish them from the Friday-cron ones on the
        # history panel.
        "trigger": "admin_manual",
    }
    try:
        await db.email_delivery_log.insert_one(doc)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"manual pool-service delivery log failed: {e}")
    return {
        "delivery_id":     delivery_id,
        "sent":            bool(result.get("sent")),
        "mocked":          bool(result.get("mocked")),
        "reason":          result.get("reason"),
        "recipient_count": len(recipients),
        "week_start":      report.get("week_start"),
        "week_end":        report.get("week_end"),
    }
