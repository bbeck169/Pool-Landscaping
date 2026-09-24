"""Phase P45 · Feb-2026 — Atomic single-writer gate for
service-report submit / job completion.

Prior to P45 the customer-facing "visit summary" email and
completion SMS could double-fire.  Two paths reach the same
completion transition:

  1. ``POST /api/service-reports/{report_id}/submit`` — tech-driven
     submit flow.  Writes ``submitted_at`` on the report row and
     enqueues ``_bg_send_visit_summary_email`` + ``_bg_send_completion_sms``.
  2. ``PUT /api/jobs/{jid}`` with ``status="completed"`` — admin/dispatch
     manual completion.  Also enqueued email/SMS.

If both fire (e.g., tech submits report at the same moment an
admin flips the job to completed, or a browser double-clicks the
Submit button), the customer received two emails.  ``already_notified``
soft-checks helped but had TOCTOU races.

**Fix (P45):** funnel both writer paths through a single atomic
``findOneAndUpdate`` that stamps three markers in one write:

    submitted_at        — canonical "this submit happened at T" ts
    email_pending_at    — enqueue marker; moved to ``email_sent_at``
                          by the background task on success
    sms_pending_at      — enqueue marker; moved to ``sms_sent_at``
                          on success

The filter matches ``submitted_at ∈ {None, ""}`` OR absent so BOTH
never-submitted rows and legacy empty-string rows are captured.
The unique matched-and-modified guarantee means exactly one
caller becomes the "winner" — the winner enqueues notifications;
every other concurrent caller sees ``claim_submit_or_none`` return
``None`` and skips the enqueue path.

Tenant scoping is mandatory — every query includes ``tenant_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config import db, logger


async def claim_submit_or_none(
    *,
    tenant_id: str,
    report_id: Optional[str] = None,
    job_id: Optional[str] = None,
    tech_id: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> Optional[dict]:
    """Atomically claim the submit for a service_report row.

    Match strategy (priority order):
      * ``report_id`` — most specific; matches the single report doc.
      * ``(job_id, tech_id)`` — used by the tech-submit path when
        the caller only has the job + acting tech, not the report id.
      * ``job_id`` only — used by ``jobs.py::PUT status=completed``.
        In multi-tech scenarios this claims the FIRST unsubmitted
        row (best-effort — see follow-up ticket).

    All match strategies AND-in ``tenant_id`` and require
    ``submitted_at`` to be null / empty (unclaimed).

    Returns:
      * The **pre-update** doc if this caller won the atomic claim
        (so callers can attach report metadata to the response).
      * ``None`` if the row was already claimed (or no matching
        row exists).  In that case the caller MUST skip the
        notification enqueue path.
    """
    if not tenant_id:
        raise ValueError("claim_submit_or_none: tenant_id required")
    if not (report_id or job_id):
        raise ValueError(
            "claim_submit_or_none: one of report_id / job_id required",
        )

    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    filt: dict = {
        "tenant_id": tenant_id,
        "$or": [
            {"submitted_at": {"$in": [None, ""]}},
            {"submitted_at": {"$exists": False}},
        ],
    }
    if report_id:
        filt["id"] = report_id
    else:
        filt["job_id"] = job_id
        if tech_id:
            filt["tech_id"] = tech_id

    update = {"$set": {
        "submitted_at": now_iso,
        "email_pending_at": now_iso,
        "sms_pending_at": now_iso,
    }}

    # ``return_document=False`` semantics: Motor's ``find_one_and_update``
    # defaults to ``ReturnDocument.BEFORE`` — returns the pre-update doc
    # if a match was found, ``None`` if nothing matched.  When
    # ``submitted_at`` is already set, no doc matches the filter and
    # we get back ``None`` — the correct "already-submitted" signal.
    claimed = await db.service_reports.find_one_and_update(filt, update)
    if claimed is None:
        logger.info(
            "[p45] submit already claimed tenant=%s report=%s job=%s tech=%s"
            " — skipping notification enqueue",
            tenant_id, report_id or "-", job_id or "-", tech_id or "-",
        )
        return None
    return claimed


async def stamp_email_sent(
    *,
    tenant_id: str,
    report_id: Optional[str] = None,
    job_id: Optional[str] = None,
    tech_id: Optional[str] = None,
) -> None:
    """Move the ``email_pending_at`` marker to ``email_sent_at``.

    Called from inside ``_bg_send_visit_summary_email``'s success
    branch so the pending queue drains as sends complete.  Best-
    effort — a stamp failure MUST NOT block the caller.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    filt: dict = {"tenant_id": tenant_id}
    if report_id:
        filt["id"] = report_id
    elif job_id:
        filt["job_id"] = job_id
        if tech_id:
            filt["tech_id"] = tech_id
    else:
        return
    try:
        await db.service_reports.update_one(
            filt,
            {"$set": {"email_sent_at": now_iso},
             "$unset": {"email_pending_at": ""}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[p45] stamp_email_sent soft-fail: %s", exc)


async def stamp_sms_sent(
    *,
    tenant_id: str,
    report_id: Optional[str] = None,
    job_id: Optional[str] = None,
    tech_id: Optional[str] = None,
) -> None:
    """Sibling of :func:`stamp_email_sent` for SMS."""
    now_iso = datetime.now(timezone.utc).isoformat()
    filt: dict = {"tenant_id": tenant_id}
    if report_id:
        filt["id"] = report_id
    elif job_id:
        filt["job_id"] = job_id
        if tech_id:
            filt["tech_id"] = tech_id
    else:
        return
    try:
        await db.service_reports.update_one(
            filt,
            {"$set": {"sms_sent_at": now_iso},
             "$unset": {"sms_pending_at": ""}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[p45] stamp_sms_sent soft-fail: %s", exc)
