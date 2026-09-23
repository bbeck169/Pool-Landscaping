"""One-shot idempotent index creation script — production deploy hook.

Feb-2026 · D2 production boot hardening.

**Ops runbook**

    cd /app/backend
    python -m scripts.ensure_indexes

Run once per deploy, AFTER the code lands and BEFORE the web workers
receive traffic (or at any time — every ``create_index`` call below
is idempotent: same name + same keys is a no-op, and each call is
wrapped in an isolated ``try/except`` so one collection's failure
never blocks the rest).

The script mirrors the ``ensure_indexes()`` blocks that server.py
runs at boot in dev/preview.  In production those startup blocks are
skipped (``RUN_STARTUP_INDEXES=false`` — see ``boot_flags.py``); ops
runs this script explicitly instead so a web worker's cold start
doesn't pay the index-audit cost.

The script does NOT create demo data, run migrations, or start the
scheduler.  Those are separate concerns owned by
``backend/server.py`` startup (migrations) and
``backend/scripts/run_scheduler.py`` (scheduler worker).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow ``python -m scripts.ensure_indexes`` from /app/backend.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from config import db, logger  # noqa: E402


async def _step(name: str, coro) -> tuple[str, str, str]:
    """Run one index-creation coroutine, isolated + logged.
    Returns ``(name, status, detail)`` for the final summary."""
    try:
        await coro
        return (name, "ok", "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ensure_indexes] {name} skipped: {e}")
        return (name, "skipped", str(e))


async def _job_edits_indexes() -> None:
    """Inline job_edits indexes (originally in server.py background_seed)."""
    await db.job_edits.create_index(
        [("tenant_id", 1), ("job_id", 1), ("edited_at", -1)],
        name="job_edits_by_job",
    )
    await db.job_edits.create_index(
        [("tenant_id", 1), ("edited_by", 1), ("edited_at", -1)],
        name="job_edits_by_user",
    )


async def _jobs_tenant_scheduled_start_index() -> None:
    """Phase P34 · Feb-2026 — background compound index on
    ``jobs(tenant_id, scheduled_start)``.

    Enables the dashboard schedule-window scan + the recurring-job
    materializer's per-tenant scheduled-start range queries to
    tenant-scan a single b-tree branch rather than the full
    ``tenant_id``-only compound. The index is created with
    ``background=True`` so provisioning against a live prod cluster
    doesn't block writes on ``jobs`` while the build catches up.

    Named ``jobs_tenant_id_scheduled_start_bg`` so it's greppable /
    droppable independently of any legacy indexes we've left in place.
    Idempotent: MongoDB's ``create_index`` returns the existing name
    when the (keys, name) pair matches, so re-running is a no-op.
    """
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.jobs.create_indexes([
            IndexModel(
                [("tenant_id", 1), ("scheduled_start", 1)],
                name="jobs_tenant_id_scheduled_start_bg",
                background=True,
            ),
        ])
    except OperationFailure as e:
        # An older deploy may have left a differently-named index
        # over the same key set. In that case Mongo raises 85
        # (IndexOptionsConflict) — treat as a no-op so ensure_indexes
        # stays green. We intentionally do NOT drop the legacy index
        # here (that lives in a separate migration).
        if getattr(e, "code", None) == 85:
            return
        raise


async def _resend_webhook_events_dedup_index() -> None:
    """Phase P36.1 · Feb-2026 — unique partial index on
    ``resend_webhook_events.svix_id``.

    Idempotency guard for the Resend webhook: Resend retries a
    signed event with the same ``svix-id`` on network hiccups /
    5xx responses / at-least-once delivery, so an unindexed insert
    would create duplicate rows and (worse) double-apply the
    ``email_outbox.latest_status`` update. This partial index only
    covers rows that carry a non-null ``svix_id`` so the pre-P36.1
    backfill window doesn't blow up: legacy rows written before the
    handler started capturing the header have no ``svix_id`` and the
    partial filter skips them.

    Background build so a live prod rollout doesn't block writes.
    Named ``resend_webhook_events_dedup_bg`` for grep-ability.
    """
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.resend_webhook_events.create_indexes([
            IndexModel(
                [("svix_id", 1)],
                name="resend_webhook_events_dedup_bg",
                unique=True,
                background=True,
                partialFilterExpression={
                    "svix_id": {"$type": "string"},
                },
            ),
        ])
    except OperationFailure as e:
        if getattr(e, "code", None) == 85:
            return
        raise


async def _telematics_vehicle_links_dedup_index() -> None:
    """Phase P39 · Feb-2026 — unique compound index on
    ``telematics_vehicle_links(tenant_id, external_vehicle_id)`` so
    a tenant can never double-map the same vehicle to two techs.

    Background build; idempotent via the OperationFailure(85) swallow
    used by every P34+ index helper in this file.
    """
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.telematics_vehicle_links.create_indexes([
            IndexModel(
                [("tenant_id", 1), ("external_vehicle_id", 1)],
                name="telematics_vehicle_links_dedup_bg",
                unique=True,
                background=True,
            ),
        ])
    except OperationFailure as e:
        if getattr(e, "code", None) == 85:
            return
        raise


async def _gps_pings_telematics_dedup_index() -> None:
    """Phase P39 · Feb-2026 — unique partial compound index on
    ``gps_pings(tenant_id, external_vehicle_id, captured_at)`` so:

      * MyGeotab poller ticks return the same ``dateTime`` for a
        stationary vehicle → second insert raises ``DuplicateKeyError``
        and the receiver returns ``status="duplicate"`` instead of
        stacking rows.
      * Mojio webhook re-deliveries of the same event become no-ops.

    Partial filter ``external_vehicle_id: {$type: "string"}`` keeps the
    pre-P39 gps_pings rows (mobile / foreground ingest) out of the
    unique constraint — they have no ``external_vehicle_id`` at all.
    """
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.gps_pings.create_indexes([
            IndexModel(
                [
                    ("tenant_id", 1),
                    ("external_vehicle_id", 1),
                    ("captured_at", 1),
                ],
                name="gps_pings_dedup_bg",
                unique=True,
                background=True,
                partialFilterExpression={
                    "external_vehicle_id": {"$type": "string"},
                },
            ),
        ])
    except OperationFailure as e:
        if getattr(e, "code", None) == 85:
            return
        raise



async def _invitations_indexes() -> None:
    """Phase P32.1 · Feb-2026 — ``invitations`` collection indexes.

    Two indexes:
      1. ``invitations_dedup_bg`` — unique compound
         ``(tenant_id, customer_id, status)`` partial index scoped
         to ``status = "sent"`` so at most ONE live invite exists
         per customer per tenant. Once a row flips to
         ``accepted``/``revoked``/``expired`` the constraint no
         longer applies to it, letting the admin re-invite.
      2. ``invitations_token_hash_bg`` — non-unique index on the
         SHA-256 hash used by the auto-login handler to look the
         invitation row up on redemption. Non-unique because the
         same hash may re-appear after a revoked → re-issued
         cycle (rare but legal).

    Idempotent via the OperationFailure(85) swallow used by every
    P34+ index helper in this file.
    """
    from pymongo import IndexModel
    from pymongo.errors import OperationFailure
    try:
        await db.invitations.create_indexes([
            IndexModel(
                [("tenant_id", 1), ("customer_id", 1), ("status", 1)],
                name="invitations_dedup_bg",
                unique=True,
                background=True,
                partialFilterExpression={"status": "sent"},
            ),
            IndexModel(
                [("token_hash", 1)],
                name="invitations_token_hash_bg",
                background=True,
            ),
        ])
    except OperationFailure as e:
        if getattr(e, "code", None) == 85:
            return
        raise


async def _customers_2dsphere() -> None:
    """Inline customers.service_location 2dsphere (originally in
    server.py sync-boot startup)."""
    from pymongo import GEOSPHERE
    await db.customers.create_index(
        [("service_location", GEOSPHERE)],
        name="cust_service_location_2dsphere",
        sparse=True,
    )


async def _call_logs_and_ringcentral_indexes() -> None:
    """Inline call_logs / voicemails / rc-subscriptions indexes
    (originally in server.py sync-boot startup)."""
    from pymongo import ASCENDING as _A
    await db.call_logs.create_index(
        [("tenant_id", _A), ("started_at", _A)], name="call_logs_by_tenant_time",
    )
    await db.call_logs.create_index(
        [("tenant_id", _A), ("from_number", _A), ("started_at", _A)],
        name="call_logs_by_from_number",
    )
    await db.call_logs.create_index(
        [("tenant_id", _A), ("to_number", _A), ("started_at", _A)],
        name="call_logs_by_to_number",
    )
    await db.voicemails.create_index(
        [("tenant_id", _A), ("message_id", _A)],
        name="voicemails_by_message_id",
    )
    await db.ringcentral_subscriptions.create_index(
        [("subscription_id", _A)], name="rc_subs_by_id", unique=True,
    )


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    logger.info("[ensure_indexes] starting …")

    results: list[tuple[str, str, str]] = []

    # ── Deployment-audit indexes (Phase 58.a — the canonical
    # "must exist for production" list).  Idempotent.
    try:
        from db_indexes import ensure_deployment_indexes
        results.append(await _step(
            "deployment_indexes", ensure_deployment_indexes(),
        ))
    except Exception as e:  # noqa: BLE001
        results.append(("deployment_indexes", "import_failed", str(e)))

    # ── Router-owned ensure_indexes() functions.  Each entry is
    # ``(name, callable-or-import-path)`` — imports are lazy so a
    # missing module doesn't block the rest.
    ROUTER_ENSURE_INDEXES: list[tuple[str, str, str]] = [
        # (label, module_path, attr_name)
        ("session",                "scripts.create_session_indexes",       "ensure_on_boot"),
        ("walkie_channels",        "services.walkie.channels",             "ensure_indexes"),
        ("walkie_live_session",    "routers.walkie_signaling",             "ensure_live_session_indexes"),
        ("recurring_jobs",         "routers.recurring_jobs",               "_ensure_indexes"),
        ("public_checkins",        "routers.public_checkins",              "ensure_public_checkins_indexes"),
        ("mcp_oauth",              "services.mcp_oauth_client",            "ensure_indexes"),
        ("media_gen",              "routers.media_gen",                    "ensure_indexes"),
        ("weekly_digest",          "services.weekly_digest",               "ensure_indexes"),
        ("equipment_trackers",     "routers.equipment_trackers",           "ensure_indexes"),
        ("promo_codes",            "routers.promo_codes",                  "ensure_indexes"),
        ("job_titles",             "routers.job_titles",                   "ensure_indexes"),
        ("referral_watcher",      "services.referral_watcher",             "ensure_indexes"),
        ("widget_denied",          "routers.widget_config",                "_ensure_denied_indexes"),
        ("tos_multi",              "services.tos_service",                 "ensure_indexes"),
        # Feb 2026 · Task B — schedule window compound index.
        ("jobs_schedule",          "routers.jobs",                         "ensure_indexes"),
        # Feb 2026 · Phase F2 — data-repair audit-log unique index +
        # scans confirm-token unique index + expires_at TTL. The
        # module's ensure_indexes() also registers a TTL index on
        # data_integrity_scans.expires_at.
        ("data_repair",            "routers.data_repair",                  "ensure_indexes"),
        # Feb 2026 · Notification Bundle — unique index on
        # notifications_sent_log so a concurrent PATCH race cannot
        # double-write the same transition + TTL is separate op.
        ("notifications_pipeline", "services.notifications_pipeline.service_notifications", "ensure_indexes"),
        # Phase A1 · Feb-2026 · Proactive Intelligence — alert store.
        ("intelligence_alerts", "services.intelligence.alerts", "ensure_indexes"),
    ]
    for label, module_path, attr_name in ROUTER_ENSURE_INDEXES:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn = getattr(mod, attr_name)
            # Some ensure_indexes() functions take ``db`` explicitly
            # (walkie / tos_multi), most don't.
            import inspect
            sig = inspect.signature(fn)
            if "db" in sig.parameters:
                coro = fn(db)
            else:
                coro = fn()
            results.append(await _step(label, coro))
        except Exception as e:  # noqa: BLE001
            results.append((label, "import_failed", str(e)))

    # ── Inline index blocks that live in server.py boot (not in a
    # named ensure_indexes function).  Mirror them here so ops has
    # ONE command to run.
    results.append(await _step("job_edits",             _job_edits_indexes()))
    results.append(await _step(
        "jobs_tenant_id_scheduled_start_bg",
        _jobs_tenant_scheduled_start_index(),
    ))
    results.append(await _step(
        "resend_webhook_events_dedup_bg",
        _resend_webhook_events_dedup_index(),
    ))
    results.append(await _step(
        "telematics_vehicle_links_dedup_bg",
        _telematics_vehicle_links_dedup_index(),
    ))
    results.append(await _step(
        "gps_pings_dedup_bg",
        _gps_pings_telematics_dedup_index(),
    ))
    # Phase P32.1 · Feb-2026 — invitations collection indexes.
    results.append(await _step(
        "invitations_indexes",
        _invitations_indexes(),
    ))
    results.append(await _step("customers_2dsphere",    _customers_2dsphere()))
    results.append(await _step(
        "call_logs_and_ringcentral", _call_logs_and_ringcentral_indexes(),
    ))

    # ── K44 · Feb-2026 — belt-and-suspenders perf-index seed. The
    # boot-wired variant lives in ``migrations.k44_perf_indexes``
    # and runs on every startup; running it here as well keeps the
    # ops runbook (``python -m scripts.ensure_indexes``) authoritative
    # for the K15 + K21 + F3.5 perf-index set. Idempotent.
    try:
        from migrations.k44_perf_indexes import run as _k44_run
        _k44_summary = await _k44_run()
        _s = _k44_summary.get("summary") or {}
        detail = (
            f"created={_s.get('created')} "
            f"already={_s.get('already_present')} "
            f"errors={len(_s.get('errors') or [])}"
        )
        status = "ok" if not (_s.get("errors") or []) else "partial"
        results.append(("k44_perf_indexes", status, detail))
    except Exception as e:  # noqa: BLE001
        results.append(("k44_perf_indexes", "skipped", str(e)))

    # ── Report ────────────────────────────────────────────────
    ok = sum(1 for _, s, _ in results if s == "ok")
    skipped = sum(1 for _, s, _ in results if s != "ok")
    print("─" * 60)
    print(f"[ensure_indexes] {ok} ok · {skipped} skipped (details below)")
    for name, status, detail in results:
        line = f"  {status.upper():<14} {name}"
        if detail and status != "ok":
            line += f"  ({detail[:120]})"
        print(line)
    print("─" * 60)
    # Non-zero exit only if EVERYTHING failed — a partial skip is
    # normal (e.g. deployment_indexes may be already present, or a
    # non-critical router hasn't been deployed yet).
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
