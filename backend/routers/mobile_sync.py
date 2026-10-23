"""Phase 32 · Feb 2026 — Mobile offline capability backend foundation.

Two public endpoints under ``/api/mobile/``:

* ``POST /api/mobile/sync``            — batch-apply operations that a
  tech recorded while offline. Idempotent per ``client_op_id`` — the
  same op replayed produces the same result and never double-applies.
  Conflict policy: mobile wins on ALL entities; the pre-mobile server
  snapshot is captured in ``sync_conflict_log`` so nothing is truly
  lost.
* ``GET  /api/mobile/offline-bundle``  — returns the data slice a tech
  needs to work offline for the next 7 days (their assigned jobs,
  the tiny customer contact fields those jobs reference, any
  in-progress service reports, and the chemistry/chemicals catalogs).
  Response size is capped so mobile can cache safely.

New Mongo collections created lazily (via ``db_indexes.py`` on
startup):

  * ``mobile_devices``          — one row per device that has synced.
  * ``sync_conflict_log``       — mobile-wins audit trail.
  * ``pending_sync_receipts``   — ``client_op_id`` → dedupe receipt,
    60-day TTL.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

OFFLINE_BUNDLE_WINDOW_DAYS = 7
BUNDLE_MAX_JOBS = 200
SYNC_RECEIPT_TTL_DAYS = 60

# Phase O4 · Feb-2026 — Offline bundle expansion caps.  Kept small
# so the mobile SQLite cache stays under 5 MB even for tenants with
# thousands of active invoices.  Ordering is ``updated_at`` DESC so
# the freshest data lands first when the cap trims.
BUNDLE_MAX_INVOICES = 500
BUNDLE_MAX_QUOTES = 200
BUNDLE_MAX_PRICEBOOK_ITEMS = 500

# op_types accepted by /mobile/sync — routed via ``_HANDLERS`` below.
# Phase O4 · Feb-2026 — added job.arrive, invoice.create,
# quote.create, customer.upsert so mobile can capture full offline
# work (arrival GPS, on-site invoice/quote, lead capture).
SUPPORTED_OP_TYPES = {
    "job.update", "job.close", "job.edit", "service_report.upsert",
    "photo.upload", "chemistry.record", "chemical.add",
    "checklist.tick", "note.add",
    # Phase O4 additions:
    "job.arrive", "invoice.create", "quote.create", "customer.upsert",
}


# ═══════════ Wire models ═══════════════════════════════════════════════
class _SyncOp(BaseModel):
    client_op_id: str
    op_type: str
    entity_id: str
    payload: Dict[str, Any] = {}
    client_ts: Optional[str] = None


class _SyncBatchIn(BaseModel):
    device_id: str
    operations: List[_SyncOp]
    os: Optional[str] = None
    app_version: Optional[str] = None


# ═══════════ Dedupe / receipt persistence ══════════════════════════════
async def _get_receipt(client_op_id: str, tenant_id: str) -> Optional[dict]:
    return await db.pending_sync_receipts.find_one(
        {"client_op_id": client_op_id, "tenant_id": tenant_id},
        {"_id": 0},
    )


async def _save_receipt(op: _SyncOp, tenant_id: str, user_id: str,
                          result: dict) -> None:
    await db.pending_sync_receipts.insert_one({
        "client_op_id": op.client_op_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "op_type": op.op_type,
        "entity_id": op.entity_id,
        "result": result,
        "created_at": datetime.now(timezone.utc),
    })


async def _log_conflict(op: _SyncOp, tenant_id: str,
                           server_snapshot_before: Any) -> None:
    await db.sync_conflict_log.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "client_op_id": op.client_op_id,
        "op_type": op.op_type,
        "entity_id": op.entity_id,
        "server_snapshot_before": server_snapshot_before,
        "mobile_payload": op.payload,
        "resolution": "mobile_wins",
        "resolved_at": now_iso(),
    })


# ═══════════ Op handlers ═══════════════════════════════════════════════
async def _handle_job_update(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise ValueError("job not found")
    if job:
        await _log_conflict(op, tenant_id, job)
    updates = {k: v for k, v in (op.payload or {}).items()
                if k not in ("id", "tenant_id", "created_at")}
    updates.update({"updated_at": now_iso(),
                      "last_synced_at": now_iso(),
                      "client_op_id": op.client_op_id})
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"$set": updates})
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_job_close(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise ValueError("job not found")
    _prev_status = (job.get("status") or "").lower()
    # Feb-2026 · Chemistry required-readings gate — applied ONLY
    # when this replay actually flips a pool job to ``completed``.
    # A 422 propagates back to the mobile client so the offline
    # replay row stays in the local SQLite queue until the tech
    # fills the missing readings and re-syncs.
    if _prev_status != "completed":
        from services.chemistry_gate import (
            assert_core_readings_present, gather_readings_for_job, is_pool_job,
        )
        if is_pool_job(job):
            rep = await db.service_reports.find_one(
                {"tenant_id": tenant_id, "job_id": op.entity_id},
                {"_id": 0},
            )
            assert_core_readings_present(
                gather_readings_for_job(job, rep),
            )
    await _log_conflict(op, tenant_id, {"status": job.get("status"),
                                            "completed_at": job.get("completed_at")})
    # Preserve the offline-captured completion timestamp — that's
    # the real-world close time the tech recorded. Only fall back
    # to ``now_iso()`` if the mobile payload didn't carry one
    # (older mobile builds; treat as best-effort).
    completed_at_val = op.payload.get("completed_at") or now_iso()
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id},
        {"$set": {"status": "completed",
                    "completed_at": completed_at_val,
                    "last_synced_at": now_iso(),
                    "client_op_id": op.client_op_id,
                    "updated_at": now_iso()}},
    )
    # 2026-10-02 · duration_seconds=0 fix — mirror the online
    # service-report submit path (``routers/service_reports.py``
    # L1131-1149) + PUT /jobs status→completed branch
    # (``routers/jobs.py`` L2786) by closing every open
    # ``job_timers`` row for this job.  Previously the offline
    # close replay stamped the job doc but left ``job_timers`` rows
    # dangling in an open state forever.  Non-fatal — a timer-close
    # failure MUST NOT block the sync replay.
    try:
        from routers.job_timers import close_open_timers_for_job
        _closed = await close_open_timers_for_job(
            job_id=op.entity_id, tenant_id=tenant_id,
            actor_user_id=user_id,
            reason="mobile_offline_close",
        )
        if _closed:
            logger.info(
                "[job_timers.auto_close] mobile_sync job=%s closed=%d",
                op.entity_id, _closed,
            )
    except Exception as _tc_exc:                                # noqa: BLE001
        logger.warning(
            "[job_timers.auto_close] mobile_sync job=%s failed: %s",
            op.entity_id, _tc_exc,
        )
    # Feb-2026 · Door-hanger auto-send on completion transition.
    # Fires only on the pending→completed transition; mobile sync
    # replays of an already-completed job (idempotent close) are
    # silently skipped by the helper too, but this guard keeps
    # semantics identical across write paths.
    if _prev_status != "completed":
        try:
            from routers.workstream_service_log import (
                schedule_auto_send_door_hanger,
            )
            schedule_auto_send_door_hanger(op.entity_id, tenant_id)
        except Exception:
            pass
        # Feb-2026 · Recurring-jobs on-complete safety net.
        # Mirrors the online submit path (routers/service_reports.py
        # ~L1156 + routers/jobs.py ~L2988): on the pending→completed
        # transition from an offline-replayed close, insert the next
        # expected recurring occurrence if the cron missed it.
        # Idempotent via (tenant, template, date) dedupe. Non-fatal
        # — a safety-net failure MUST NOT fail the sync replay.
        try:
            from services.recurring_jobs_backfill import (
                materialize_next_from_completed_job,
            )
            # Shape the job doc so the helper has scheduled_date +
            # recurring_template_id — the mobile op payload doesn't
            # carry those, so refetch the just-updated row.
            _refetched = await db.jobs.find_one(
                {"id": op.entity_id, "tenant_id": tenant_id},
                {"_id": 0},
            )
            if _refetched:
                await materialize_next_from_completed_job(
                    job=_refetched,
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                )
        except Exception as _sn_exc:                            # noqa: BLE001
            logger.warning(
                "recurring_job.on_complete_safety_net.failed "
                "tenant=%s parent_job=%s error=%s:%s",
                tenant_id, op.entity_id,
                type(_sn_exc).__name__, _sn_exc,
            )
        # Phase P25 · Feb-2026 — Workstream activity-feed event.
        # Uses the SAME emitter helper as the online path
        # (``routers/jobs.py`` PATCH handler) so the event shape
        # in ``db.workstream_events`` is identical regardless of
        # write path. Idempotency: the enclosing
        # ``if _prev_status != "completed"`` gate prevents a
        # replay of an already-completed job from double-emitting,
        # and the outer ``pending_sync_receipts.client_op_id``
        # short-circuit (see ``mobile_sync`` around line 538)
        # prevents the entire handler from running on a duplicate
        # ``client_op_id`` — so the event lands at most ONCE per
        # (job, completion-transition, client_op_id) tuple.
        # ``completed_at`` = offline-captured timestamp so the
        # event's causal timestamp reflects when the tech actually
        # closed the job, not when the sync replayed.
        try:
            fresh = await db.jobs.find_one(
                {"id": op.entity_id, "tenant_id": tenant_id},
                {"_id": 0},
            )
            if fresh:
                from routers.workstream import emit_job_completed_event
                await emit_job_completed_event(
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                    actor_role="technician",
                    job=fresh,
                    completed_at=completed_at_val,
                    source="mobile_sync_replay",
                )
        except Exception as _wf_e:                              # noqa: BLE001
            logger.warning(
                "[workstream] mobile_sync_replay job.completed "
                "emit failed for job=%s: %s",
                op.entity_id, _wf_e,
            )
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_job_edit(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Feb-2026 · Mobile offline replay of a 24h edit-window PATCH.

    Mirrors the gates + audit + side-effect suppression of the web
    ``PATCH /api/jobs/{jid}`` endpoint (see ``routers/jobs.py ::
    patch_job_edit_window``).  A 403 or 422 raised here propagates
    back to the mobile client so its local queue can either surface
    the error to the tech (edit_window_expired → local warning
    card) or hold the row for a re-sync (chemistry gate failure).
    """
    from services.edit_window import (
        EDIT_WINDOW_HOURS,
        assert_immutable_fields_untouched, diff_fields,
        hours_since_completion, is_within_edit_window,
    )
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job or job.get("deleted_at"):
        raise ValueError("job not found")
    if (job.get("status") or "").lower() != "completed":
        raise HTTPException(400, {"detail": "job_not_completed"})
    if not is_within_edit_window(job):
        raise HTTPException(
            403, {"detail": "edit_window_expired",
                   "edit_window_hours": EDIT_WINDOW_HOURS,
                   "hours_since_completion": hours_since_completion(job)},
        )

    incoming = dict(op.payload or {})
    reason = (incoming.pop("edit_reason", None) or "")[:500] or None
    incoming.pop("edit_source", None)
    assert_immutable_fields_untouched(incoming)

    # Chemistry re-check (mirrors the web PATCH gate 6).
    if "chemical_readings" in incoming:
        from services.chemistry_gate import (
            assert_core_readings_present, gather_readings_for_job, is_pool_job,
        )
        if is_pool_job(job):
            rep = await db.service_reports.find_one(
                {"tenant_id": tenant_id, "job_id": op.entity_id},
                {"_id": 0},
            ) or {}
            merged = dict(rep)
            merged["chemical_readings"] = incoming["chemical_readings"]
            assert_core_readings_present(
                gather_readings_for_job(job, merged),
            )

    changes = diff_fields(job, incoming, skip=("updated_at",))
    if not changes:
        return {"server_id": op.entity_id, "server_ts": now_iso()}

    edit_id = f"edit-{op.client_op_id}"
    await db.job_edits.insert_one({
        "id": edit_id,
        "tenant_id": tenant_id, "job_id": op.entity_id,
        "edited_by": user_id, "edited_by_role": "technician",
        "edited_at": now_iso(), "changes": changes,
        "reason": reason, "source": "mobile",
    })
    try:
        incoming["updated_at"] = now_iso()
        await db.jobs.update_one(
            {"id": op.entity_id, "tenant_id": tenant_id},
            {"$set": incoming},
        )
    except Exception:
        await db.job_edits.delete_one({"id": edit_id})
        raise
    return {"server_id": op.entity_id, "server_ts": now_iso()}



async def _handle_service_report_upsert(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    # Feb-2026 · Chemistry-gate ship — route both write branches
    # (update + insert) through the shared
    # ``apply_water_bodies_payload`` pipeline so structured
    # ``water_bodies`` patches rebuild the flat
    # ``chemical_readings`` mirror and legacy top-level patches
    # sync back into ``water_bodies[0]``. Presence-check semantics:
    # keys ABSENT from the mobile payload land as a Mongo $set only
    # on the keys present — Mongo natively preserves every un-touched
    # persisted key.
    from services.water_bodies import (
        WaterBodyValidationError,
        apply_water_bodies_payload,
    )
    existing = await db.service_reports.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        await _log_conflict(op, tenant_id, existing)
        payload = {k: v for k, v in (op.payload or {}).items()
                    if k not in ("id", "tenant_id", "created_at")}
        try:
            apply_water_bodies_payload(payload, existing)
        except WaterBodyValidationError as exc:
            raise ValueError(f"water_bodies invalid: {exc.detail}") from exc
        payload.update({"updated_at": now_iso(),
                         "last_synced_at": now_iso(),
                         "client_op_id": op.client_op_id})
        await db.service_reports.update_one(
            {"id": op.entity_id, "tenant_id": tenant_id},
            {"$set": payload},
        )
    else:
        # Insert fresh — mobile-generated id becomes canonical.
        doc = dict(op.payload or {})
        # Same pipeline for the insert branch — the mirror rebuild
        # runs from an EMPTY existing rep, so an incoming
        # ``water_bodies`` payload gets validated + gets its flat
        # mirror stamped, and a legacy-only payload spawns
        # ``water_bodies[0]`` from the incoming top-level fields.
        try:
            apply_water_bodies_payload(doc, {})
        except WaterBodyValidationError as exc:
            raise ValueError(f"water_bodies invalid: {exc.detail}") from exc
        doc.update({"id": op.entity_id, "tenant_id": tenant_id,
                     "created_at": now_iso(), "updated_at": now_iso(),
                     "last_synced_at": now_iso(),
                     "client_op_id": op.client_op_id,
                     "public_uuid": doc.get("public_uuid") or new_id()})
        await db.service_reports.insert_one(doc)
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_photo_upload(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Mobile-side photo upload is 2-step: (a) client uploads the file
    bytes via ``POST /service-reports/{id}/media`` while online-ish,
    (b) records the sync op for bookkeeping. This handler is the
    bookkeeping path — the media row is already in
    ``service_reports.photos`` when it arrives here."""
    return {"server_id": op.entity_id, "server_ts": now_iso(),
              "note": "photo bytes must be uploaded via /service-reports/{id}/media"}


# ═══════════ Phase O4 · Feb-2026 — new op_type handlers ═══════════════

async def _handle_job_arrive(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Offline replay of a GPS arrival event.  Mirrors the effect of
    ``POST /jobs/{jid}/arrive`` but skips the gates that only make
    sense at real-time (consent, radius, throttle) — the online
    endpoint is the source of truth for those, and this replay path
    is only ever entered when the tech was already offline (i.e.
    they've physically arrived; the pings just took a while to
    reach us).  The handler stamps ``timer_started_at`` +
    ``timer_start_method="mobile_offline_arrival"`` on the job doc
    and flips ``pending``/``scheduled`` → ``in_progress`` if needed,
    mirroring the web endpoint's status transition.  Idempotent: a
    replay with the same ``client_op_id`` on a row that already has
    a ``timer_started_at`` is a no-op.

    2026-10-02 · duration_seconds=0 fix — two parity gaps closed:

    (a) When the mobile payload omits ``arrived_at`` we previously
        stamped ``timer_started_at = now_iso()`` and tagged
        ``timer_start_method = "mobile_offline_arrival"`` — this
        made the sync-processing instant indistinguishable from
        a real on-site arrival, so a service-report submit landing
        in the same batch produced ``timer_duration_seconds == 0``.
        Now the fallback-to-now path tags
        ``timer_start_method = "mobile_offline_arrival_fallback_now"``
        and emits a WARN log so dashboards + audits can tell real
        offline arrivals from degraded-payload ones.

    (b) The online ``/arrive`` endpoint upserts a ``job_timers``
        collection row via ``auto_start_timer_on_arrival`` so the
        /job-timers reports see every arrival. The offline replay
        path forgot that call — the dashboards under-counted
        offline-arriving jobs.  Now mirrored, with the same
        warn-and-swallow guard the online path uses (bookkeeping
        error MUST NOT fail the sync).  Idempotency lives inside
        ``auto_start_timer_on_arrival`` (open-row probe keyed on
        ``(tenant_id, job_id, tech_id)``) — no caller-side
        precheck needed.
    """
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise ValueError("job not found")
    if job.get("timer_started_at"):
        # Already running — either the online /arrive beat us to it
        # or this is a replay of a replay.  Idempotent no-op.
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "note": "already_running"}
    if (job.get("status") or "").lower() == "completed":
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "reason": "job_completed"}
    payload = op.payload or {}
    _arrived_at = payload.get("arrived_at")
    if _arrived_at:
        _timer_started_at = _arrived_at
        _timer_start_method = "mobile_offline_arrival"
    else:
        # Soft fallback — stamp the moment of processing but tag it
        # so dashboards + audits can distinguish degraded payloads.
        _timer_started_at = now_iso()
        _timer_start_method = "mobile_offline_arrival_fallback_now"
        logger.warning(
            "[job-timers] offline arrival payload missing arrived_at"
            " — stamping now(); op=%s job=%s",
            op.client_op_id, op.entity_id,
        )
    upd = {
        "timer_started_at": _timer_started_at,
        "timer_start_method": _timer_start_method,
        "last_synced_at": now_iso(),
        "client_op_id": op.client_op_id,
        "updated_at": now_iso(),
    }
    if payload.get("lat") is not None and payload.get("lng") is not None:
        upd["arrival_lat"] = payload["lat"]
        upd["arrival_lng"] = payload["lng"]
    if (job.get("status") or "").lower() in ("", "pending", "requested", "scheduled"):
        upd["pre_arrival_status"] = job.get("status") or "scheduled"
        upd["status"] = "in_progress"
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"$set": upd})
    # 2026-10-02 · duration_seconds=0 fix (b) — mirror the online
    # /arrive endpoint by upserting a ``job_timers`` collection row.
    # Non-fatal: a bookkeeping error MUST NOT break the sync replay
    # (same posture as ``routers/jobs.py::job_arrive``).
    try:
        from routers.job_timers import auto_start_timer_on_arrival
        await auto_start_timer_on_arrival(
            job_id=op.entity_id, tenant_id=tenant_id,
            tech_id=job.get("technician_id"),
            crew_id=job.get("crew_id"),
            customer_id=job.get("customer_id"),
            started_at=_timer_started_at,
        )
    except Exception as _jt_exc:                                # noqa: BLE001
        logger.warning(
            "[job-timers] mobile_sync arrival auto-start failed job=%s: %s",
            op.entity_id, _jt_exc,
        )
    return {"server_id": op.entity_id, "server_ts": now_iso(),
              "timer_started_at": upd["timer_started_at"]}


async def _handle_invoice_create(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Offline replay of an on-site invoice creation.  Routes through
    the canonical ``insert_invoice`` helper so ``invoice_number``
    gets assigned atomically (see the P0 fix documented on
    service_reports.py's auto-invoice path).  Note: this CRM
    persists invoice rows on ``db.quotes`` (with ``doc_type =
    "invoice"``) — the ``invoices`` name is an alias for
    ``doc_type = "invoice"`` filtered reads.  Idempotent by
    ``op.entity_id`` — a replay on an existing row returns it
    verbatim instead of double-inserting."""
    existing = await db.quotes.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id,
          "doc_type": "invoice"}, {"_id": 0})
    if existing:
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "note": "idempotent replay"}
    doc = dict(op.payload or {})
    doc.update({"id": op.entity_id, "tenant_id": tenant_id,
                 "created_at": doc.get("created_at") or now_iso(),
                 "updated_at": now_iso(),
                 "last_synced_at": now_iso(),
                 "client_op_id": op.client_op_id,
                 "doc_type": "invoice"})
    try:
        # Route through the numbering helper so the persisted row has
        # a real ``invoice_number`` at insert time (avoids the null-
        # number regression fixed in the service-report auto-invoice
        # path).  Falls back to a plain ``db.quotes`` insert if the
        # numbering service errors — mobile-wins semantics.
        from services.invoice_numbering import insert_invoice
        tenant_doc = await db.tenants.find_one(
            {"id": tenant_id}, {"_id": 0}) or {"id": tenant_id}
        doc = await insert_invoice(doc, tenant_doc)
    except Exception as e:                                        # noqa: BLE001
        logger.warning(
            "[mobile_sync] invoice.create numbering fallback: %s", e)
        await db.quotes.insert_one(doc)
    # TD-22 · Feb-2026 — long-tail wire-in for credit auto-apply.
    # Mobile sync processes a batch of ops serially; adding a
    # synchronous credit-sweep (hundreds of ms per invoice × N
    # invoices in a batch) would noticeably increase sync time
    # for techs on flaky networks. Fire-and-forget via
    # ``asyncio.create_task`` so the mobile client gets its
    # response immediately. The sweep runs inside the request
    # loop so logs still correlate; failures are swallowed via
    # the task's inner try/except.
    async def _credit_apply_task(_tid, _cid, _iid):
        try:
            from services.credit_apply import (
                apply_credit_to_customer_open_invoices,
            )
            await apply_credit_to_customer_open_invoices(
                db, _tid, _cid, exclude_invoice_ids=[_iid],
            )
        except Exception as _ca_exc:  # noqa: BLE001
            logger.warning(
                "credit_apply.failed site=mobile_sync.invoice_create "
                "tenant=%s invoice=%s error=%r",
                _tid, _iid, _ca_exc,
            )
    try:
        import asyncio as _asyncio
        _asyncio.create_task(_credit_apply_task(
            tenant_id, doc.get("customer_id"), doc.get("id"),
        ))
    except Exception as _sched_exc:  # noqa: BLE001
        logger.warning(
            "credit_apply.schedule_failed site=mobile_sync.invoice_create "
            "tenant=%s invoice=%s error=%r",
            tenant_id, doc.get("id"), _sched_exc,
        )
    return {"server_id": op.entity_id, "server_ts": now_iso(),
              "invoice_number": doc.get("invoice_number")}


async def _handle_quote_create(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Offline replay of an on-site quote creation.  Same idempotency
    contract as invoice.create — an existing row wins."""
    existing = await db.quotes.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "note": "idempotent replay"}
    doc = dict(op.payload or {})
    doc.update({"id": op.entity_id, "tenant_id": tenant_id,
                 "created_at": doc.get("created_at") or now_iso(),
                 "updated_at": now_iso(),
                 "last_synced_at": now_iso(),
                 "client_op_id": op.client_op_id,
                 "doc_type": doc.get("doc_type") or "quote"})
    await db.quotes.insert_one(doc)
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_customer_upsert(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Offline lead capture.  Insert-or-update on ``customers`` keyed
    by ``op.entity_id``.  Downstream customer-merge machinery
    (routers.customer_merge) picks up duplicates on the next batch
    run — this handler intentionally does NOT re-run merge logic
    here so the mobile-wins contract stays cheap.  A conflict log
    entry captures the pre-mobile snapshot for the audit trail."""
    existing = await db.customers.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    payload = {k: v for k, v in (op.payload or {}).items()
                if k not in ("id", "tenant_id", "created_at")}
    if existing:
        await _log_conflict(op, tenant_id, existing)
        payload.update({"updated_at": now_iso(),
                         "last_synced_at": now_iso(),
                         "client_op_id": op.client_op_id})
        await db.customers.update_one(
            {"id": op.entity_id, "tenant_id": tenant_id},
            {"$set": payload},
        )
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "upserted": "updated"}
    # Fresh insert — mobile-generated id becomes canonical.
    doc = dict(payload)
    doc.update({"id": op.entity_id, "tenant_id": tenant_id,
                 "created_at": now_iso(), "updated_at": now_iso(),
                 "last_synced_at": now_iso(),
                 "client_op_id": op.client_op_id})
    await db.customers.insert_one(doc)
    return {"server_id": op.entity_id, "server_ts": now_iso(),
              "upserted": "inserted"}


async def _handle_generic_report_field_append(op: _SyncOp, tenant_id: str,
                                                    user_id: str, field: str) -> dict:
    """Common path for chemistry / chemical / checklist / note ops —
    each appends a row into a field on the service_report."""
    report = await db.service_reports.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0, field: 1})
    if not report:
        raise ValueError(f"service_report {op.entity_id} not found")
    # Mobile-wins snapshot log (only when the entry with the same
    # ``client_op_id`` doesn't already exist — otherwise it's just an
    # idempotent replay).
    existing_rows = list(report.get(field) or [])
    if any(isinstance(r, dict) and r.get("client_op_id") == op.client_op_id
             for r in existing_rows):
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "note": "idempotent replay"}
    row = dict(op.payload or {})
    row["client_op_id"] = op.client_op_id
    row["synced_at"] = now_iso()
    await db.service_reports.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id},
        {"$push": {field: row},
          "$set": {"last_synced_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"server_id": op.entity_id, "server_ts": now_iso()}


_HANDLERS = {
    "job.update":              _handle_job_update,
    "job.close":               _handle_job_close,
    "job.edit":                _handle_job_edit,
    "service_report.upsert":   _handle_service_report_upsert,
    "photo.upload":            _handle_photo_upload,
    "chemistry.record":        lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "chemical_readings"),
    "chemical.add":            lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "chemicals_added"),
    "checklist.tick":          lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "checklist_events"),
    "note.add":                lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "notes_log"),
    # Phase O4 · Feb-2026 — Offline sync additions.
    "job.arrive":              _handle_job_arrive,
    "invoice.create":          _handle_invoice_create,
    "quote.create":            _handle_quote_create,
    "customer.upsert":         _handle_customer_upsert,
}


# ═══════════ POST /api/mobile/sync ═════════════════════════════════════
@router.post("/mobile/sync", operation_id="mobile.sync")
async def mobile_sync(body: _SyncBatchIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)) -> dict:
    """Batch-apply mobile offline operations. Idempotent per
    ``client_op_id`` — the same op replayed produces the same result
    each time; conflicts always resolve mobile-wins with a snapshot
    persisted to ``sync_conflict_log``."""
    tenant_id = tenant["id"]
    user_id = user.get("id")

    # Upsert device record for auditing.
    await db.mobile_devices.update_one(
        {"device_id": body.device_id, "tenant_id": tenant_id},
        {"$set": {"user_id": user_id, "last_seen_at": now_iso(),
                    "last_sync_at": now_iso(),
                    "os": body.os, "app_version": body.app_version},
          "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )

    accepted: List[Dict[str, Any]] = []
    failed:   List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    for op in body.operations:
        # Idempotency short-circuit.
        prior = await _get_receipt(op.client_op_id, tenant_id)
        if prior:
            accepted.append({
                "client_op_id": op.client_op_id,
                **(prior.get("result") or {}),
                "idempotent_replay": True,
            })
            continue

        if op.op_type not in SUPPORTED_OP_TYPES:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": f"unsupported op_type {op.op_type!r}"})
            continue

        handler = _HANDLERS.get(op.op_type)
        if handler is None:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": "no handler wired"})
            continue

        try:
            result = await handler(op, tenant_id, user_id)
        except ValueError as e:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": str(e)})
            continue
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"mobile_sync op {op.client_op_id} failed: {e}")
            failed.append({"client_op_id": op.client_op_id,
                             "reason": str(e)[:200]})
            continue

        await _save_receipt(op, tenant_id, user_id, result)
        accepted.append({"client_op_id": op.client_op_id, **result})
        # Every accepted op that touched an entity is treated as
        # conflict-resolved (mobile wins). We echo the resolution back
        # so mobile can badge the timeline entry.
        # Phase O4 · Feb-2026 — added customer.upsert so lead-capture
        # duplicates also surface in the mobile timeline.
        if op.op_type in ("job.update", "job.close",
                           "service_report.upsert", "customer.upsert"):
            conflicts.append({"client_op_id": op.client_op_id,
                                 "resolution": "mobile_wins"})

    return {"accepted": accepted, "failed": failed, "conflicts": conflicts}


# ═══════════ GET /api/mobile/offline-bundle ════════════════════════════
async def _max_updated_at(cursor) -> Optional[str]:
    """Phase O4 helper — walk a Motor cursor once to find the freshest
    ``updated_at`` (or ``created_at`` fallback) across a small slice.
    Returned as an ISO string so the mobile client can compare via
    plain string ordering.  Returns ``None`` on empty."""
    latest = ""
    async for row in cursor:
        v = row.get("updated_at") or row.get("created_at") or ""
        if isinstance(v, str) and v > latest:
            latest = v
    return latest or None


# TD-offline-bundle-perf · Phase 2 Lane A · Feb-2026 — collector
# helpers used by ``mobile_offline_bundle`` to run the 9 post-jobs
# Mongo queries concurrently under a single ``asyncio.gather``.
# Each helper returns a plain ``list[dict]`` so the handler can
# unpack the gather tuple directly into its response shape without
# any additional transformation.  Behaviour matches the pre-refactor
# ``async for … append`` loops byte-for-byte.
async def _collect_bundle_customers(customer_ids: List[str],
                                    tenant_id: str) -> List[Dict[str, Any]]:
    if not customer_ids:
        return []
    out: List[Dict[str, Any]] = []
    async for c in db.customers.find(
            {"id": {"$in": customer_ids}, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "name": 1, "phone": 1,
              "address": 1, "address_line_1": 1, "updated_at": 1}):
        out.append({
            "id": c.get("id"), "name": c.get("name"),
            "phone": c.get("phone"),
            "address": c.get("address_line_1") or c.get("address") or "",
            "updated_at": c.get("updated_at"),
        })
    return out


async def _collect_bundle_reports(job_ids: List[str],
                                  tenant_id: str) -> List[Dict[str, Any]]:
    if not job_ids:
        return []
    return [r async for r in db.service_reports.find(
        {"tenant_id": tenant_id, "job_id": {"$in": job_ids},
          "submitted_at": None},
        {"_id": 0})]


async def _collect_bundle_full_table(coll: Any,
                                     tenant_id: str) -> List[Dict[str, Any]]:
    return [d async for d in coll.find({"tenant_id": tenant_id}, {"_id": 0})]


async def _collect_bundle_sorted_capped(coll: Any,
                                        filt: Dict[str, Any],
                                        limit: int) -> List[Dict[str, Any]]:
    return [d async for d in coll.find(filt, {"_id": 0})
            .sort("updated_at", -1).limit(limit)]


@router.get("/mobile/offline-bundle", operation_id="mobile.offlineBundle")
async def mobile_offline_bundle(tech_id: str = "me",
                                     user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)) -> dict:
    tenant_id = tenant["id"]
    if tech_id == "me":
        target_tech = user.get("technician_id") or user.get("id")
    else:
        target_tech = tech_id

    # TD-offline-bundle-tenant-cache · Phase 2 Lane D · Feb-2026 —
    # 120 s per-``(tenant_id, tech_id)`` TTL cache.  See
    # ``services/offline_bundle_cache.py`` for the design-decision
    # write-up (notably: the operator-dispatched ``tenant_id``-only
    # key was widened to the full ``(tenant_id, tech_id)`` tuple to
    # avoid serving one tech's jobs to another on cache hit).
    # Cache miss falls through to the full handler path; Lane A +
    # Lane B still protect the cold-path cost.
    from services import offline_bundle_cache as _obc
    _cached = _obc.get(tenant_id, target_tech)
    if _cached is not None:
        return _cached

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=OFFLINE_BUNDLE_WINDOW_DAYS)

    # Jobs assigned to this tech within the 7-day window.
    #
    # Phase 32 originally filtered + sorted on ``scheduled_at`` only,
    # which returned zero rows in this codebase because job docs
    # store their schedule on ``scheduled_date`` (date-only YYYY-MM-DD)
    # — ``scheduled_at`` was never populated on the live collection.
    # Mirror the dual-field pattern already shipped in
    # ``routers/portal_next_visits.py`` (date-only + full ISO
    # fallback) so legacy and future shapes both qualify. See
    # ``test_mobile_sync_offline_bundle_jobs.py`` for the matrix.
    from utils import not_deleted_filter as _nd
    horizon_iso = horizon.isoformat()
    horizon_date = horizon.date().isoformat()
    jobs_cur = db.jobs.find(
        {"tenant_id": tenant_id,
         "$and": [
             {"$or": [{"technician_id": target_tech},
                       {"assigned_tech_id": target_tech}]},
             _nd(),
             {"$or": [
                 {"scheduled_date": {"$lte": horizon_date}},
                 {"scheduled_at":   {"$lte": horizon_iso}},
             ]},
         ]},
        {"_id": 0, "id": 1, "customer_id": 1, "title": 1,
          "service_type": 1, "scheduled_at": 1, "scheduled_date": 1,
          "scheduled_end": 1,
          "notes": 1, "status": 1, "checklist_template": 1,
          "address": 1, "customer_name": 1, "updated_at": 1},
    ).sort([("scheduled_date", 1), ("scheduled_at", 1)]).limit(BUNDLE_MAX_JOBS)
    jobs = [j async for j in jobs_cur]

    # Contact info — name + phone + service address only, no other PII.
    customer_ids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    # In-progress service reports for those jobs.
    job_ids = [j["id"] for j in jobs]

    # TD-offline-bundle-perf · Phase 2 Lane A · Feb-2026 — parallelize
    # the 9 post-jobs queries via ``asyncio.gather``.  Before this
    # change these ran strictly sequentially via back-to-back
    # ``async for`` loops; latency compounded 10x and matched the
    # ~2.8 s slow-request warnings almost exactly (see
    # memory/td_offline_bundle_perf_recon.md section 2).
    #
    # Query-dependency audit (locked by test_offline_bundle_gather
    # _dependency_audit in test_td_offline_bundle_perf_gather.py):
    #   * db.jobs  (#1)  — stays SEQUENTIAL above; its result
    #                      produces ``customer_ids`` (for #2) and
    #                      ``job_ids`` (for #3).
    #   * db.customers (#2) — depends on #1's ``customer_ids``.
    #   * db.service_reports (#3) — depends on #1's ``job_ids``.
    #   * db.chemistry_test_types (#4) — tenant-scoped only.
    #   * db.chemicals_catalog (#5) — tenant-scoped only.
    #   * db.quotes invoice-slice (#6) — tenant-scoped only.
    #   * db.quotes quote-slice (#7) — tenant-scoped only.
    #   * db.income_categories (#8) — tenant-scoped only.
    #   * db.service_categories (#9) — tenant-scoped only.
    #   * db.pricebook_items (#10) — tenant-scoped only.
    # Response shape is BYTE-IDENTICAL — the dict insertion order
    # at the bottom is preserved; the customers mapping is still
    # applied inside ``_collect_bundle_customers``.
    #
    # Error handling: ``asyncio.gather(..., return_exceptions=False)``
    # (default) means the first exception propagates and sibling
    # tasks are cancelled — matches the pre-refactor behaviour where
    # any single ``async for`` raise would bubble up to FastAPI's
    # exception handler.  Mobile clients continue to receive proper
    # HTTP errors, not silently-degraded bundles.
    (customers, reports, chemistry_types, chemicals_catalog,
     invoices, quotes, income_categories, service_categories,
     pricebook_items) = await asyncio.gather(
        _collect_bundle_customers(customer_ids, tenant_id),
        _collect_bundle_reports(job_ids, tenant_id),
        _collect_bundle_full_table(db.chemistry_test_types, tenant_id),
        _collect_bundle_full_table(db.chemicals_catalog, tenant_id),
        _collect_bundle_sorted_capped(
            db.quotes,
            {"tenant_id": tenant_id, "doc_type": "invoice"},
            BUNDLE_MAX_INVOICES,
        ),
        _collect_bundle_sorted_capped(
            db.quotes,
            {"tenant_id": tenant_id,
              "$or": [{"doc_type": "quote"}, {"doc_type": {"$exists": False}}]},
            BUNDLE_MAX_QUOTES,
        ),
        _collect_bundle_full_table(db.income_categories, tenant_id),
        _collect_bundle_full_table(db.service_categories, tenant_id),
        _collect_bundle_sorted_capped(
            db.pricebook_items,
            {"tenant_id": tenant_id},
            BUNDLE_MAX_PRICEBOOK_ITEMS,
        ),
    )

    # ``versions`` — per-collection freshness fingerprint so the
    # mobile client can decide when to re-fetch the bundle without
    # comparing every row.  ISO strings compare lexicographically.
    def _max_iso(rows: List[Dict[str, Any]]) -> Optional[str]:
        latest = ""
        for r in rows:
            v = r.get("updated_at") or r.get("created_at") or ""
            if isinstance(v, str) and v > latest:
                latest = v
        return latest or None

    versions = {
        "jobs": _max_iso(jobs),
        "customers": _max_iso(customers),
        "service_reports_in_progress": _max_iso(reports),
        "invoices": _max_iso(invoices),
        "quotes": _max_iso(quotes),
        "income_categories": _max_iso(income_categories),
        "service_categories": _max_iso(service_categories),
        "pricebook_items": _max_iso(pricebook_items),
    }

    # ``caps`` — mirror of the module-level constants so the mobile
    # client can render a "showing N of M" hint without hard-coding
    # the caps in two places.
    caps = {
        "jobs": BUNDLE_MAX_JOBS,
        "invoices": BUNDLE_MAX_INVOICES,
        "quotes": BUNDLE_MAX_QUOTES,
        "pricebook_items": BUNDLE_MAX_PRICEBOOK_ITEMS,
        "window_days": OFFLINE_BUNDLE_WINDOW_DAYS,
    }

    # TD-offline-bundle-tenant-cache · Phase 2 Lane D · Feb-2026 —
    # stash the materialised bundle in the per-``(tenant_id, tech_id)``
    # cache so pull-to-refresh traffic within the next 120 s short-
    # circuits to a dict lookup.  Mutations on ``db.jobs`` or
    # ``db.quotes`` for this tenant drop the cache via
    # ``services.offline_bundle_cache.invalidate(tenant_id)`` from
    # the hook sweep in ``routers.jobs`` + ``routers.quotes``.
    bundle = {
        "jobs": jobs,
        "customers": customers,
        "service_reports_in_progress": reports,
        "chemistry_types": chemistry_types,
        "chemicals_catalog": chemicals_catalog,
        # Phase O4 additions:
        "invoices": invoices,
        "quotes": quotes,
        "income_categories": income_categories,
        "service_categories": service_categories,
        "pricebook_items": pricebook_items,
        "versions": versions,
        "caps": caps,
        "offline_bundle_expires_at": horizon.isoformat(),
        "generated_at": now.isoformat(),
        "job_count": len(jobs),
        "cap_reached": len(jobs) >= BUNDLE_MAX_JOBS,
    }
    _obc.put(tenant_id, target_tech, bundle)
    return bundle
