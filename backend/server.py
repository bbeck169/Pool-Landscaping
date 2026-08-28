from fastapi import FastAPI, APIRouter, Depends
# Phase 2 rework addendum · Feb-2026 — GPS read lockdown dep, wrapped at
# include_router() time on every GPS router except gps_ingest (POST /gps/pings
# stays open to techs).
from utils import require_gps_read as _rg
from utils import new_id as _utils_new_id, now_iso as _utils_now_iso
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
import logging

from config import client, db, logger
# Feb-2026 · D2 production boot hardening — three env-gated flags
# that let a production web worker skip demo seeds, boot-time index
# creation, and APScheduler registration.  Defaults are ON in dev /
# preview and OFF in production (see ``backend/boot_flags.py``).
from boot_flags import (
    should_seed_demo_data as _should_seed_demo_data,
    should_run_startup_indexes as _should_run_startup_indexes,
    should_enable_scheduler as _should_enable_scheduler,
    snapshot as _boot_flags_snapshot,
)
from seed import seed, seed_extras, seed_tech_today_demo, seed_landscaping_user, seed_landscape_tech_carlos, seed_pool_tech_mike, auto_heal_demo_passwords_if_needed, seed_prior_readings, seed_phase51k_finance, seed_mike_today_job, align_demo_tech_departments, seed_manager_user
from routers import (
    notifications as notifications_router,
    auth, customers, technicians, jobs, quotes, leads, team, items,
    operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin, ops, reports, legal, marketing_studio, sequences, ai_ops, google as google_router, phase11,
    weather_v2,
    realtime, csat, signatures,
    analytics, onboarding,
    lead_requests, mobile_push,
    tenants, workforce,
    business_os,
    time_off,
    schedule, social,
    service_reports,
    referrals,
    public_social,
    route_optimization,
    route_optimization_approval as _route_opt_approval,
    portal_chats, portal_appointments, portal_photos,
    employee_onboarding, assets, referral_tiers,
    seo_agentic, seo_phase17c,
    estimator, dunning, inventory,
    checks,
    dispatch,
    churn, seo_content_refresh,
    warranties,
    rbac,
    workstream,
    cfo,
    timeclock_landscaping,
    budgets,
    chemical_costs,
    recurring_jobs,
    pricebook_manual_pricing,
    zillow_admin,
    ringcentral,
    ringcentral_customer,
    config as config_router,
    job_requests as job_requests_router,
    training as training_router,
    customer_equipment_photos as customer_equipment_photos_router,
    pool_calculators,
    document_generators,
    pricing_defaults_router,
    growth_playbook,
    training_nudge,
    recommendations_queue,
    templates_library,
    handbook,
    weekly_digest,
    comms,
    media_uploads,
    portal_videos,
    reviews,
    review_sync,
    marketing_m1,
    ai_credits,
    chemical_products,
    pipelines,
    ai_estimator,
    before_after,
    objects as objects_router,
    instaquote,
    instaschedule,
    chat,
    directories,
    customer_tasks,
    properties,
    invoices_mp15,
    ai_employees,
    customer_portal,
    customer_ai,
    customer_reviews,
    marketing_templates,
    marketing_segments,
    marketing_sequences,
    marketing_review_requests,
    marketing_preferences,
    marketing_analytics,
    marketing_media,
    widget_config,
    widget_chat,
    marketing_forms,
    portal_walkthrough,
    portal_greeting,
    admin_users as _p19_admin_users,
    integrations_admin as _p19_integrations_admin,
    seo_analyzer as _p20_seo,
    reviews_ai_reply as _p20_reviews_ai,
    referrals_vesting as _p20_referrals_vesting,
    gbp_posts as _p20_gbp,
    local_seo_checklist as _p20_local_seo,
    nfc_review_card as _p20_nfc,
    job_media_line_items,
    workstream_job_detail,
    resend_webhooks,
    portal_referrals,
    invoice_viewer,
    invoice_magic_view,
    portal_auto_login,
    estimate_viewer,
    referral_rewards,
    checklists,
    workstream_service_log,
    ringcentral_jwt,
    equipment_trackers,
    promo_codes,
    referrals_phase10,
    marketing_campaigns as marketing_campaigns_router,
    mass_messaging,
    customer_tags,
    communications_log,
    customer_categories,
    dispatch_board,
    job_titles,
)
# Feb 2026 · Customer Merge Phase 1 — detect + merge + audit endpoints.
# Router mounted alongside the customer_tags / customer_categories
# family below so the ``/api/customers/*`` prefix stays cohesive.
from routers import customer_merge as _customer_merge_router
# Phase 9C · Feb 2026 — QuickBooks retirement helper (idempotent
# boot migration + ALLOW_TEST_HOOKS-gated purge endpoint).
from routers import quickbooks_cleanup
# Phase 11b · Feb 2026 — Customer self-service account deletion
# (App Store consumer-account guideline blocker item 3).
from routers import customer_account as _p11b_customer_account  # noqa: E402
# Phase 17 · Feb 2026 — Route Assignment Overrides + permanent moves.
# Registered separately from the main include loop below so the
# ``/dispatch/reassign`` and ``/dispatch/assignment-change-log``
# routes are prefixed identically to the other dispatch surfaces.
from routers import dispatch_reassign as _p17_reassign  # noqa: E402
# Feb-2026 · Item 4 — Master AI knowledge base + Copilot.
from routers import ai_brain as _p18_ai_brain  # noqa: E402
# Phase 18 · Feb-2026 — Chemical cost report + per-tech inventory
# read view + department admin. Real-time low-stock fan-out lives in
# services/inventory_alerts.py and is wired into the decrement path
# on routers/inventory.py; the scheduler cron registration happens
# lower in this file.
from routers import inventory_reports as _p18_inventory_reports  # noqa: E402

# Phase 47c-hooks · Feb-2026 — Stripe test-hook endpoints (Phase 4b
# stub install/toggle + a compact /stripe/health). Only imported +
# mounted when ALLOW_TEST_HOOKS=1 so production never exposes them
# (mirrors the ringcentral_jwt / quickbooks_cleanup pattern). The
# APP_ENV=production guard further down force-clears the flag before
# this module ever gets a chance to import — so a stale .env cannot
# leak the hooks into a prod build.
if os.environ.get("ALLOW_TEST_HOOKS") == "1":
    from routers import stripe_test_hooks as _p47c_stripe_hooks  # noqa: E402
    from routers import marketing_test_hooks as _feb2026_marketing_hooks  # noqa: E402
else:
    _p47c_stripe_hooks = None  # type: ignore[assignment]
    _feb2026_marketing_hooks = None  # type: ignore[assignment]

app = FastAPI(
    title="Pool CRM API",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# Feb-2026 · P1 · Kubernetes readiness probe endpoint.
# Emergent's ingress proxies GET /health to the pod's FastAPI on
# :8001 (see /var/log/nginx / rollout logs — ``upstream:
# "http://127.0.0.1:8001/health"``).  Without this route the probe
# gets a 404 once FastAPI is up, and connection-refused (111) while
# FastAPI is still importing (cold-start ≈ 5s + Motor lifespan
# startup adds seconds more; the K8s readiness window fired before
# ``Started server process`` printed → deploy timed out on 2026-08-26).
#
# Contract:
#   * NO ``/api`` prefix — the ingress hits ``/health`` literally.
#   * NO DB call — probe must return < 5ms so the readiness window
#     never depends on Mongo latency.
#   * NO auth — probes are pod-internal / cluster-internal only;
#     leaking a static ``{"status": "ok"}`` is intentional.
#   * NO logging middleware overhead — declared BEFORE the
#     ``api_router`` include so it bypasses the tenant / user
#     dependency stack entirely.
#
# ``/api/health`` mirror below is for frontend proxy paths that
# always inject ``/api`` — cheap defensive copy of the same handler.
@app.get("/health", include_in_schema=False)
async def _k8s_health_probe():
    return {"status": "ok"}


api_router = APIRouter(prefix="/api")


@api_router.get("/health", include_in_schema=False)
async def _api_health_probe():
    # ``/api/health`` mirror — some Emergent ingress rules and the
    # frontend fetch wrappers always prefix ``/api`` regardless of
    # target. Same guarantees as ``/health``: no DB, no auth, < 5ms.
    return {"status": "ok"}

# Marketing M2 registered BEFORE the generic loop so its
# ``/marketing/campaigns/*`` routes win over the legacy
# ``marketing_studio`` handlers that share the base prefix.
api_router.include_router(marketing_campaigns_router.router)

# Phase 12B · Feb 2026 — Stripe ↔ Customers cross-reference admin
# endpoints. Retired at the router-registration level (never
# re-mounted after the Phase 47d Stripe restoration). Legacy
# stripe_* invoice fields on ``quotes`` are preserved as the live
# audit trail feeding paid_from_intents / refunded_from_intents on
# every current charge; the removed endpoint was the admin-only
# reverse-lookup UI, not the sync layer.

# Feb-2026 · BUG E — global Terms of Service gate. Registered BEFORE
# the generic router loop so that ``GET /api/legal/tos`` wins the path
# match over the legacy legal-CMS ``GET /api/legal/{slug}`` handler.
from routers import tos as _tos_router  # noqa: E402
from routers import muted_reasons as _p29_muted_reasons  # noqa: E402
from routers import quiet_hours_settings as _p34_quiet_hours  # noqa: E402
from routers import gps_auto_start as _p37_gps_auto_start  # noqa: E402
# Feb-2026 · Job Timers Phase 1 — backend + web reporting. Mobile
# GPS geofence auto-start ships in Phase 2 (dispatched separately
# to ``e1_expo_frontend_dev``). See ``routers/job_timers.py``.
from routers import job_timers as _feb2026_job_timers  # noqa: E402
from routers import gps_audit_report as _p37d_gps_audit_report  # noqa: E402
api_router.include_router(_tos_router.router)
api_router.include_router(_p29_muted_reasons.router)
api_router.include_router(_p34_quiet_hours.router)
api_router.include_router(_p37_gps_auto_start.router)
api_router.include_router(_feb2026_job_timers.router)
# Feb-2026 · Chemical Cost Report — /api/reports/chemical-costs.
from routers import chemical_cost_report as _feb2026_chem_costs  # noqa: E402
api_router.include_router(_feb2026_chem_costs.router)
api_router.include_router(_p37d_gps_audit_report.router)

# Feb-2026 · Slice 2A — Multi-ToS backend foundation (Pool +
# Landscaping split, admin CRUD, customer onboarding-state DTO).
# Registered adjacent to the legacy single-ToS router so both
# surfaces coexist during the 2A→2C rollout (2C removes the legacy
# ``TosGate`` in favour of ``OnboardingGate``).
from routers import tos_multi as _tos_multi_router  # noqa: E402
api_router.include_router(_tos_multi_router.router)

# Feb-2026 · mobile-flagged gaps — Auto Clock-In field + user self-PATCH
# + orphan-customer repair. Registered alongside the ToS router since
# they share the /users/me + /admin/users/{id} URL space.
from routers import auto_clockin as _auto_clockin_router  # noqa: E402
api_router.include_router(_auto_clockin_router.router)
from routers import citations as _citations_router  # noqa: E402
api_router.include_router(_citations_router.router)
from routers import rank_tracker as _rank_tracker_router  # noqa: E402
api_router.include_router(_rank_tracker_router.router)
from routers import repair_calculator as _repair_calc_router  # noqa: E402
api_router.include_router(_repair_calc_router.router)
# Feb-2026 · Phase 1 — Tech "On my way" SMS endpoint.
from routers import on_my_way as _on_my_way_router  # noqa: E402
api_router.include_router(_on_my_way_router.router)
# Feb-2026 · Phase 1 — Tech "Could Not Service" outcome + reasons CRUD.
from routers import could_not_service as _cns_router  # noqa: E402
api_router.include_router(_cns_router.router)
from routers import ai_visibility as _aiv_router  # noqa: E402
api_router.include_router(_aiv_router.router)
from routers import ai_media_estimator as _p25_ai_media_router  # noqa: E402
api_router.include_router(_p25_ai_media_router.router)
from routers import integrations_supercool as _p26_supercool_router  # noqa: E402
api_router.include_router(_p26_supercool_router.router)
# Phase 11b · Feb 2026 — Customer account deletion.
api_router.include_router(_p11b_customer_account.router)
# Feb-2026 · Phase 1a — Homeworks (MCP via api.home.works) OAuth
# lifecycle (DCR + authcode + PKCE). Token exchange only — MCP
# tools/list / tools/call land in Phase 1b.
from routers import integrations_homeworks_oauth as _hw_mcp_oauth  # noqa: E402
api_router.include_router(_hw_mcp_oauth.router)
# Feb-2026 · Phase 1b — inactive-customers importer (dry-run + run +
# cancel + status + history + active).
from routers import integrations_homeworks_imports as _hw_imports  # noqa: E402
api_router.include_router(_hw_imports.router)
from routers import integrations_homeworks_active_imports as _hw_active_imports  # noqa: E402
api_router.include_router(_hw_active_imports.router)
# Queue Item 5 · Feb-2026 — Delta Sync + Pricebook (income items)
# importer surfaces. Both live under super_admin.
from routers import integrations_homeworks_delta_sync as _hw_delta_sync  # noqa: E402
api_router.include_router(_hw_delta_sync.router)
from routers import integrations_homeworks_income_items as _hw_income_items  # noqa: E402
api_router.include_router(_hw_income_items.router)
# Task 5 · Feb-2026 — "Run now" dispatcher trigger (super_admin only,
# 5-second cooldown). Complements the 30-second scheduled tick.
from routers import integrations_homeworks_dispatcher as _hw_dispatcher_router  # noqa: E402
api_router.include_router(_hw_dispatcher_router.router)
# Phase 0 POC · Feb-2026 — Homeworks BYO-creds admin surface.
# Distinct from the env-var-driven ``integrations_homeworks_oauth``
# above; this one is per-tenant, super_admin gated, and scoped to a
# read-only smoke-test (Phase 0).  See /app/memory/homeworks_integration.md.
from routers import homeworks_integration as _hw_byo_router  # noqa: E402
api_router.include_router(_hw_byo_router.router)
# Feb-2026 · Item 3 — deletion audit + restore (super_admin only).
# Provides ``GET /admin/audit/deletions`` and
# ``POST /admin/audit/deletions/{id}/restore``. The writer helper
# ``write_deletion_audit_entry`` is imported by routers/quotes.py
# to persist entries on every soft-delete.
from routers import deletion_audit as _deletion_audit_router  # noqa: E402
api_router.include_router(_deletion_audit_router.router)

# Feb-2026 · Admin migrations wrapper — super_admin-only POST
# endpoints that run one-off backfills from the deployed app.
from routers import admin_migrations as _admin_migrations_router  # noqa: E402
api_router.include_router(_admin_migrations_router.router)
from routers import comms_admin as _comms_admin  # noqa: E402
api_router.include_router(_comms_admin.router)
from routers import media_gen as _phaseb_media_router  # noqa: E402
api_router.include_router(_phaseb_media_router.router)
# Phase 22 · Feb 2026 — Public Service Images portal endpoint. Mounted
# via ``api_router`` so the ``/api`` prefix is applied automatically;
# rate-limited internally (60 req/min per IP). No auth.
from routers import public_service_images as _p22_public_svc_images  # noqa: E402
api_router.include_router(_p22_public_svc_images.router)
# Phase 27 · Feb 2026 — Service Report media (photos + videos) upload
# + reorder + public streaming. Mounts under /api via api_router.
from routers import service_report_media as _p27_svc_media  # noqa: E402
api_router.include_router(_p27_svc_media.router)
# Phase 34 · Task LL Phase 2 · Feb 2026 — CRM-wide bulk endpoints
# (customers, jobs, tasks, communications, email/sms templates).
from routers import bulk_crm as _p34_bulk_crm  # noqa: E402
api_router.include_router(_p34_bulk_crm.router)
from routers import bulk_crm_p1 as _p34_bulk_crm_p1  # noqa: E402
api_router.include_router(_p34_bulk_crm_p1.router)
from routers import reflow_history as _p34_reflow_history  # noqa: E402
api_router.include_router(_p34_reflow_history.router)
from routers import lumino_webhook as _qq_lumino_webhook  # noqa: E402
api_router.include_router(_qq_lumino_webhook.router)
from routers import lumino_zapier_bridge as _qq_lumino_zapier  # noqa: E402
api_router.include_router(_qq_lumino_zapier.router)
from routers import lumino_return as _qq_lumino_return  # noqa: E402
api_router.include_router(_qq_lumino_return.router)
# Feb 2026 — inspection audits receiver (Zap-fed, shared-secret auth).
from routers import audits as _audits_receiver  # noqa: E402
api_router.include_router(_audits_receiver.router)
# LZ2 · Feb 2026 — Retroactive "request-payment-link" endpoint.
from routers import lumino_link_request as _lz2_link_request  # noqa: E402
api_router.include_router(_lz2_link_request.router)
# LZ1 · Feb 2026 — Lumino invoice-link callback receiver (Zap-fed).
from routers import lumino_invoice_link_callback as _lz1_link_callback  # noqa: E402
api_router.include_router(_lz1_link_callback.router)
# Feb 2026 — Admin invoice edit (PATCH + audit history).
from routers import invoice_edit as _invoice_edit  # noqa: E402
api_router.include_router(_invoice_edit.router)
# Feb 2026 — Portal quick-action media aggregation (photos/videos/unread).
from routers import portal_media as _portal_media  # noqa: E402
api_router.include_router(_portal_media.router)
# Feb 2026 — Admin dashboard revenue tiles (category + forecast).
from routers import dashboard_revenue as _dashboard_revenue  # noqa: E402
api_router.include_router(_dashboard_revenue.router)

# Feb 2026 · Dashboard global-search bar — quick-find across
# customers / jobs / invoices / leads. Tenant-scoped, admin/manager
# gated. New file: routers/global_search.py.
from routers import global_search as _global_search  # noqa: E402
api_router.include_router(_global_search.router)
# Feb 2026 — Income category picklist + enforcement.
from routers import income_categories as _income_categories  # noqa: E402
api_router.include_router(_income_categories.router)

# Phase 56-a · Aug-2026 — Pricebook Suppliers CRUD.
from routers import pricebook_suppliers as _pricebook_suppliers  # noqa: E402
api_router.include_router(_pricebook_suppliers.router)

# Phase 56-c · Aug-2026 — Pricebook Cost Comparison report.
from routers import pricebook_cost_comparison as _pb_cost_comparison  # noqa: E402
api_router.include_router(_pb_cost_comparison.router)

# Phase 56-d · Aug-2026 — Supplier Spend / Margin report.
from routers import pricebook_supplier_spend as _pb_spend  # noqa: E402
api_router.include_router(_pb_spend.router)

# Backlog #iii · Feb-2026 — Supplier-name autocomplete for the
# Edit-Item modal Suppliers tab.
from routers import pricebook_supplier_names as _pb_supplier_names  # noqa: E402
api_router.include_router(_pb_supplier_names.router)

# Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.
from routers import homeworks_import as _homeworks_import  # noqa: E402
api_router.include_router(_homeworks_import.router)
# Feb 2026 — Admin check-in overrides.
from routers import admin_checkins as _admin_checkins  # noqa: E402
api_router.include_router(_admin_checkins.router)
from routers import checkin_rewrite as _checkin_rewrite  # noqa: E402
api_router.include_router(_checkin_rewrite.router)
from routers import lumino_backfill as _lumino_backfill  # noqa: E402
api_router.include_router(_lumino_backfill.router)
from routers import profit_report as _profit_report  # noqa: E402
api_router.include_router(_profit_report.router)
# Phase 53a · Feb-2026 — Editable EBIT report backend.
from routers import ebit as _p53a_ebit  # noqa: E402
api_router.include_router(_p53a_ebit.router)
# Phase 47c-hooks · Feb-2026 — Stripe test hooks. Mount ONLY when the
# hooks module actually imported (ALLOW_TEST_HOOKS=1 gate above).
if _p47c_stripe_hooks is not None:
    api_router.include_router(_p47c_stripe_hooks.router)
# Feb-2026 · Phase 3 — Marketing pipeline test hooks (emit-event +
# run-sweep). Same ALLOW_TEST_HOOKS gate as the stripe hooks above.
if _feb2026_marketing_hooks is not None:
    api_router.include_router(_feb2026_marketing_hooks.router)
# Phase 54a · Feb-2026 — Wholesale supplier pricebook import (skeleton).
from routers import suppliers as _p54a_suppliers  # noqa: E402
api_router.include_router(_p54a_suppliers.router)
from routers import gps_settings as _gps_settings  # noqa: E402
api_router.include_router(_gps_settings.router, dependencies=[Depends(_rg)])
from routers import gps_ingest as _gps_ingest  # noqa: E402
api_router.include_router(_gps_ingest.router)
# Feb 2026 — Service categories (pricebook business-unit taxonomy).
from routers import service_categories as _service_categories  # noqa: E402
api_router.include_router(_service_categories.router)
# Task TT · Feb 2026 (reconciled TT.5) — OpenWebNinja-Zillow adapter
# (dry-scaffold). Ships in ``keys_missing → 503 graceful`` mode: routes
# register unconditionally so a supervisor restart after populating
# ``OPENWEB_NINJA_ZILLOW_API_KEY`` (or the fallback ``OPENWEB_NINJA_API_KEY``)
# in ``.env`` immediately flips the adapter live.
from routers import zillow_adapter_api as _tt_zillow_adapter  # noqa: E402
api_router.include_router(_tt_zillow_adapter.router)
# Phase F0 · Feb 2026 — /api/files/* (upload/download/list/delete)
# backed by Emergent Object Storage. Fail-soft: router registers even
# when EMERGENT_LLM_KEY is missing; upload/download return 503.
from routers import files as _f0_files  # noqa: E402
api_router.include_router(_f0_files.router)

# Phase 51a · Feb 2026 — Walkie-Talkie async voice-clip backend.
from routers import walkie as _p51a_walkie  # noqa: E402
api_router.include_router(_p51a_walkie.router)
# Phase 52.1a · Feb-2026 — walkie live-streaming signaling WebSocket
# + live_only-channel creation. Signaling ONLY (audio flows P2P via
# TURN in Phase 52.1d); backend just brokers SDP offer/answer + ICE
# candidates through an in-process room dict.
from routers import walkie_signaling as _p52_1a_signaling  # noqa: E402
api_router.include_router(_p52_1a_signaling.router)
# Task SS/RR Phase 2 · Feb 2026 — the admin credit issuance /
# reversal endpoints originally shipped in ``customer_credits_admin``
# collided with the already-shipped Phase 10 ``/customers/{cid}/
# credits/adjust`` endpoint (which lives in ``referrals_phase10`` and
# is wired to the CustomerCreditsPanel UI). Retired to avoid two
# writers to divergent storage backends. The Phase 10 endpoint is
# the source of truth for admin adjustments; ``credits_apply.py`` now
# reads/writes the same Phase 10 collections so autobilling +
# manual-invoice hooks see the balance the admin actually adjusted.
# Phase 32 · Feb 2026 — Mobile offline sync backend (batch op replay
# + offline-bundle prefetch). Idempotent per ``client_op_id``;
# conflicts resolve mobile-wins with an audit-logged snapshot.
from routers import mobile_sync as _p32_mobile_sync  # noqa: E402
api_router.include_router(_p32_mobile_sync.router)
api_router.include_router(_p17_reassign.router)
api_router.include_router(_p18_ai_brain.router)
# Phase 18 · Feb-2026 — Chemical cost report + tech mobile inventory.
api_router.include_router(_p18_inventory_reports.router)
api_router.include_router(_p19_admin_users.router)
api_router.include_router(_p19_integrations_admin.router)

# Feb-2026 · Client-side error ingest + admin browser.
from routers import client_errors as _client_errors_router  # noqa: E402
api_router.include_router(_client_errors_router.router)

# Feb-2026 · Phase P2 · Live GPS positions for the Dispatch Board.
from routers import gps_live_positions as _gps_live_positions_router  # noqa: E402
api_router.include_router(_gps_live_positions_router.router, dependencies=[Depends(_rg)])

# G2 · Feb-2026 — Server-side stop detection: query + admin rebuild.
from routers import gps_stops as _gps_stops_router  # noqa: E402
api_router.include_router(_gps_stops_router.router, dependencies=[Depends(_rg)])

# MR0 · Feb-2026 — Public check-in submission + moderation queue.
from routers import public_checkins as _public_checkins_router  # noqa: E402
from routers import moderation_public_checkins as _mod_public_checkins_router  # noqa: E402
api_router.include_router(_public_checkins_router.router)
api_router.include_router(_mod_public_checkins_router.router)

# MR1+MR2 · Feb-2026 — Public widget (feed + widget.js + preview).
from routers import public_widget as _public_widget_router  # noqa: E402
api_router.include_router(_public_widget_router.router)

# MR3 · Feb-2026 — Widget analytics (impressions + clicks + top-checkins).
from routers import widget_analytics as _widget_analytics_router  # noqa: E402
api_router.include_router(_widget_analytics_router.router)

# Phase 2 · Feb-2026 — Signed 24 h public share links for Route Replay.
from routers import replay_share as _replay_share_router  # noqa: E402
api_router.include_router(_replay_share_router.router, dependencies=[Depends(_rg)])

# Phase 3 · Feb-2026 — Dispatch route optimizer (nearest-neighbor).
from routers import dispatch_route_optimize as _dispatch_opt_router  # noqa: E402
api_router.include_router(_dispatch_opt_router.router, dependencies=[Depends(_rg)])

# Phase 4 · Feb-2026 — Drag-drop / auto-insert an unscheduled job.
from routers import dispatch_route_insert as _dispatch_ins_router  # noqa: E402
api_router.include_router(_dispatch_ins_router.router, dependencies=[Depends(_rg)])

# Phase 10 · sub-item F — Dispatch weekly savings KPI.
from routers import dispatch_savings as _dispatch_savings_router  # noqa: E402
api_router.include_router(_dispatch_savings_router.router, dependencies=[Depends(_rg)])

# Feb 2026 · Schedule DnD reorder + Dispatch import.
from routers import schedule_reorder as _schedule_reorder_router  # noqa: E402
api_router.include_router(_schedule_reorder_router.router)

# Phase 11 · Feb-2026 — Invoice reconciliation log (super-admin only).
from routers import invoice_reconciliation as _invoice_reconciliation_router  # noqa: E402
api_router.include_router(_invoice_reconciliation_router.router)

# Phase 5a · Feb-2026 — AEO Suite (JSON-LD generator + LLMs.txt generator).
# Auditor lives inside services/seo_scanner and rides on /api/seo/scans.
from routers import aeo as _aeo_router  # noqa: E402
api_router.include_router(_aeo_router.router)

# Phase 7 · Feb-2026 — Weekly Scorecard Digest (Slack + Resend).
from routers import scorecard as _scorecard_router  # noqa: E402
api_router.include_router(_scorecard_router.router)

# Phase 8 · Feb-2026 — Weekly AEO PDF Digest via Resend.
from routers import aeo_digest as _aeo_digest_router  # noqa: E402
api_router.include_router(_aeo_digest_router.router)

# Phase 9 · Feb-2026 — LLMs.txt Auto-Publish (Netlify / Vercel / CF Pages).
from routers import llmstxt_publish as _llmstxt_pub_router  # noqa: E402
api_router.include_router(_llmstxt_pub_router.router)

# Phase SEO-A · Feb-2026 — Free on-page SEO auditor (admin+/manager).
from routers import seo_scans as _seo_scans_router  # noqa: E402
api_router.include_router(_seo_scans_router.router)

# Phase SEO-B · Feb-2026 — Backlink outreach CRM (admin+/manager).
from routers import outreach as _outreach_router  # noqa: E402
api_router.include_router(_outreach_router.router)

# Phase SEO-C · Feb-2026 — Keyword ideation (Google Autocomplete +
# Trends via pytrends). Admin+/manager only.
from routers import keywords as _keywords_router  # noqa: E402
api_router.include_router(_keywords_router.router)

# Phase G3 · Feb-2026 — Mapbox reverse-geocoding: /gps/route +
# admin backfill endpoint. Both admin+/manager only.
from routers import gps_route as _gps_route_router  # noqa: E402
api_router.include_router(_gps_route_router.router, dependencies=[Depends(_rg)])

# Phase G4 · Feb-2026 — Per-user GPS controls + CSV exports
# (admin+/manager). Extends G0-G3 without touching mobile.
from routers import gps_user_controls as _gps_user_controls_router  # noqa: E402
api_router.include_router(_gps_user_controls_router.router, dependencies=[Depends(_rg)])

# Phase G5a · Feb-2026 — Geofences + entry/exit alerts. CRUD lives
# here; the ingest hook (POST /gps/pings) and live-positions endpoint
# call into services.geofence_engine + evaluate_ping_against_fences.
from routers import geofences as _geofences_router  # noqa: E402
api_router.include_router(_geofences_router.router, dependencies=[Depends(_rg)])

# Phase G5b · Feb-2026 — Stop → Job proximity attribution. Extends
# G2 driver_stops with attribution fields (backwards-compatible).
# Cron registered in the scheduler init block below.
from routers import stop_attribution as _stop_attr_router  # noqa: E402
api_router.include_router(_stop_attr_router.router, dependencies=[Depends(_rg)])

# Phase G5d · Feb-2026 — Driver scorecard / leaderboard (admin+).
from routers import driver_scorecard as _driver_scorecard_router  # noqa: E402
api_router.include_router(_driver_scorecard_router.router, dependencies=[Depends(_rg)])

# Feb-2026 · Payments summary tile (restored on Phase 47d Stripe
# revival — see routers/payments_summary.py docstring).
from routers import payments_summary as _payments_summary_router  # noqa: E402
api_router.include_router(_payments_summary_router.router)

# Phase 14a · Feb-2026 — Stripe re-integration (card-on-file).
# Endpoints: /api/payments/stripe/{setup-intent,attach,payment-methods/*,charge,webhook}.
# Fresh collection ``db.stripe_charges``; legacy ``db.stripe_payments_live``
# stays retired at the collection level. Test/live mode split via
# ``STRIPE_MODE``.
from routers import stripe_router as _p14a_stripe_router  # noqa: E402
api_router.include_router(_p14a_stripe_router.router)
# Feb 2026 · P1 Hotfix #3 — Legacy-URL alias so ``/api/stripe/webhook``
# (the URL Stripe Dashboard was historically configured to hit)
# resolves to the same handler as ``/api/payments/stripe/webhook``.
# See stripe_router.webhook_alias_router for full rationale.
api_router.include_router(_p14a_stripe_router.webhook_alias_router)

# Phase 14b · Feb-2026 — Invoice filters + bulk charge-card-on-file.
# Endpoints: /api/invoices/{line-item-categories, bulk-charge-card-on-file,
# bulk-charge-runs[/{id}]}. Composes on Phase 14a's ``charge_card_on_file``.
from routers import invoices_bulk_charge as _p14b_bulk_charge  # noqa: E402
api_router.include_router(_p14b_bulk_charge.router)

# Phase 17 · Feb-2026 — QuickBooks Online read-sync router.
# Endpoints under /api/qbo/*: oauth, sync, entity reads, match links.
# Zero write-back to Intuit — display-only mirror in db.qbo_*.
from routers import qbo_router as _p17_qbo_router  # noqa: E402
api_router.include_router(_p17_qbo_router.router)
_p17_qbo_router.log_boot()

for module in [notifications_router,
               # Feb 2026 · Customer Merge Phase 1 — MUST be registered
               # before ``customers`` so the static
               # ``/customers/merge-audit`` + ``/customers/merge`` +
               # ``/customers/detect-duplicates`` paths win over the
               # dynamic ``/customers/{cid}`` in customers.py.
               _customer_merge_router,
               auth, customers, technicians, jobs, quotes, leads, team, items,
               operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin, ops, reports, legal, marketing_studio, sequences, ai_ops, google_router, phase11,
               weather_v2,
               realtime, csat, signatures,
               analytics, onboarding,
               lead_requests, mobile_push,
               tenants, workforce,
               business_os,
               time_off,
               schedule, social,
               service_reports,
               referrals,
               route_optimization,
               portal_chats, portal_appointments, portal_photos,
               employee_onboarding, assets, referral_tiers,
               seo_agentic, seo_phase17c,
               estimator, dunning, inventory,
               checks, dispatch,
               churn, seo_content_refresh,
               warranties,
               rbac,
               workstream,
               cfo,
               timeclock_landscaping,
               budgets,
               chemical_costs,
               recurring_jobs,
               pricebook_manual_pricing,
               zillow_admin,
               ringcentral,
               ringcentral_customer,
               config_router,
               job_requests_router,
               training_router,
               customer_equipment_photos_router,
               pool_calculators,
               document_generators,
               pricing_defaults_router,
               growth_playbook,
               training_nudge,
               recommendations_queue,
               templates_library,
               handbook,
               weekly_digest,
               comms,
               media_uploads,
               portal_videos,
               reviews,
               review_sync,
               marketing_m1,
               ai_credits,
               chemical_products,
               pipelines,
               ai_estimator,
               before_after,
               objects_router,
               instaquote,
               instaschedule,
               chat,
               directories,
               customer_tasks,
               properties,
               invoices_mp15,
               ai_employees,
               customer_portal,
               customer_ai,
               customer_reviews,
               marketing_templates,
               marketing_segments,
               marketing_sequences,
               marketing_review_requests,
               marketing_preferences,
               marketing_analytics,
               marketing_media,
               widget_config,
               quickbooks_cleanup,
               widget_chat,
               marketing_forms,
               portal_walkthrough,
               portal_greeting,
               _p19_admin_users,
               _p19_integrations_admin,
               _p20_seo,
               _p20_reviews_ai,
               _p20_referrals_vesting,
               _p20_gbp,
               _p20_local_seo,
               _p20_nfc,
               job_media_line_items,
               workstream_job_detail,
               resend_webhooks,
               portal_referrals,
               invoice_viewer,
               invoice_magic_view,
               estimate_viewer,
               referral_rewards,
               checklists,
               workstream_service_log,
               portal_auto_login,
               ringcentral_jwt,
               equipment_trackers,
               promo_codes,
               referrals_phase10,
               mass_messaging,
               customer_tags,
               communications_log,
               customer_categories,
               dispatch_board,
               job_titles]:
        if module is reviews:
            api_router.include_router(module.router, prefix="/reviews")
            continue
        api_router.include_router(module.router)


@api_router.get("/")
async def root():
    return {"message": "Pool CRM API"}


# Public short-link redirect — Phase 18A.1.
# Register into api_router (→ /api/r/{alias}) so the URL works through the
# Kubernetes ingress (which only forwards `/api/*`). Also mount at the app
# root (/r/{alias}) so the endpoint stays reachable when hitting the backend
# directly (dev, curl, tests). Must be registered BEFORE app.include_router.
api_router.include_router(public_social.router)
# Marketing M2 public tracking endpoints — pixel/click/unsub/webhook.
# Kept separate from the admin ``marketing_campaigns_router.router`` so
# these routes are unauthenticated.
api_router.include_router(marketing_campaigns_router.public_router)

# Phase 34 · Feb 2026 — Endpoint Path Normalization compat alias.
# Mobile clients call the 5 public review-request endpoints at
# ``/api/public/r/*``; the canonical path is ``/api/reviews/public/r/*``.
# Alias router mirrors the canonical handlers with a ``Deprecation: true``
# header. See ``routers/reviews_public_alias.py`` — deletable once mobile
# builds catch up (one release cycle after this phase).
from routers import reviews_public_alias  # noqa: E402
api_router.include_router(reviews_public_alias.router)

# Feb-2026 · Optimize Route (tech→admin approval + 10 s undo).
# Distinct namespace from route_optimization (immediate apply) and
# dispatch_route_optimize (dispatch board flow); all three coexist.
api_router.include_router(_route_opt_approval.router)

app.include_router(api_router)
app.include_router(public_social.router)

# Feb-2026 · Optimize Route (tech→admin approval + 10s undo).
# Distinct namespace from route_optimization (immediate apply) and
# dispatch_route_optimize (dispatch board flow); all three coexist.

# Phase 49 · Feb-2026 — Lana todos + reminders REST surface.
from routers import lana_todos  # noqa: E402
app.include_router(lana_todos.router)

# SEC-P3-1 hotfix — no wildcard CORS with credentials. Read allowlist from
# ALLOWED_ORIGINS (comma-separated); auto-append APP_PUBLIC_URL if set.
_APP_ENV_MW = os.environ.get("APP_ENV", "preview").lower()
_allowed_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
_app_public = os.environ.get("APP_PUBLIC_URL", "").strip()
_origins = [o.strip() for o in _allowed_raw.split(",") if o.strip()]
if _app_public and _app_public not in _origins:
    _origins.append(_app_public)

# Phase 21 · Feb 2026 — always-on Vistancia rebrand origins. Appended
# (never replacing) so existing preview + emergent.host allowlists
# stay intact. Safe to keep even before DNS is set up — CORS just
# ignores an unreachable origin.
for _rebrand_origin in ("https://app.plofv.com", "https://plofv.com"):
    if _rebrand_origin not in _origins:
        _origins.append(_rebrand_origin)

if not _origins:
    if _APP_ENV_MW == "production":
        logging.getLogger("pool_crm").error(
            "ALLOWED_ORIGINS is unset in production — refusing to enable CORS.")
        _origins = []
    else:
        # Dev/preview convenience: fall back to APP_PUBLIC_URL or localhost.
        _origins = [_app_public or "http://localhost:3000"]

# ─── Phase 13 · Feb-2026 — W1 CORS tightening ────────────────────
# Honor `CORS_ORIGINS` env var (per Phase 12 audit). Behavior:
#   * unset            → keep the ALLOWED_ORIGINS-derived list unchanged.
#   * "*"              → permissive; emit a one-time WARNING; credentials
#                        are FORBIDDEN with wildcard per CORS spec.
#   * "a.com,b.com,…"  → parse (whitespace tolerated) and append to the
#                        allowlist. Wildcards inside a list are rejected
#                        with a WARNING and stripped.
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
_cors_permissive = False
if _cors_env == "*":
    _cors_permissive = True
    _origins = ["*"]
    logging.getLogger("pool_crm").warning(
        "[cors] CORS_ORIGINS is permissive (*) — tighten before "
        "production release.")
elif _cors_env:
    _extra = []
    for o in (x.strip() for x in _cors_env.split(",") if x.strip()):
        if "*" in o:
            logging.getLogger("pool_crm").warning(
                "[cors] wildcard entry %r ignored in CORS_ORIGINS list "
                "mode; use the bare '*' value for permissive mode.", o)
            continue
        _extra.append(o)
    for o in _extra:
        if o not in _origins:
            _origins.append(o)
logging.getLogger("pool_crm").info(f"CORS allow_origins = {_origins}")

# SEC-P3-2 hotfix — auto-force ALLOW_TEST_HOOKS=0 in production, regardless
# of the value in the mounted env. Existing dev/preview behavior unchanged.
if _APP_ENV_MW == "production" and os.environ.get("ALLOW_TEST_HOOKS") == "1":
    logging.getLogger("pool_crm").warning(
        "APP_ENV=production forcing ALLOW_TEST_HOOKS=0 (was 1 in env).")
    os.environ["ALLOW_TEST_HOOKS"] = "0"

app.add_middleware(
    CORSMiddleware,
    # CORS spec forbids `Access-Control-Allow-Credentials: true` alongside
    # a wildcard origin — flip credentials off when in permissive mode.
    allow_credentials=not _cors_permissive,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Slice G2 · CORS reflect-origin for /api/widget/* ────────────────
# The widget JS runs on tenant marketing sites (any allowlisted host),
# so the CORS response for widget endpoints must reflect the caller's
# Origin. Security is enforced by ``require_widget_auth`` — CORS here
# is purely so browsers don't block legitimate cross-origin XHRs.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _StResponse

_WIDGET_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Widget-Key, X-Forwarded-Origin",
    "Access-Control-Max-Age": "86400",
}


class _WidgetCorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith("/api/widget/"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if request.method == "OPTIONS":
            resp = _StResponse(status_code=204)
        else:
            resp = await call_next(request)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        for k, v in _WIDGET_CORS_HEADERS.items():
            resp.headers[k] = v
        return resp


app.add_middleware(_WidgetCorsMiddleware)


scheduler = AsyncIOScheduler(timezone="UTC")


# Feb-2026 · D2 — read the three boot-hardening flags ONCE at
# import so every guard site references a stable module-level
# constant.  The flag helpers themselves stay env-aware for tests.
_SEED_DEMO_DATA: bool = _should_seed_demo_data()
_RUN_STARTUP_INDEXES: bool = _should_run_startup_indexes()
_ENABLE_SCHEDULER: bool = _should_enable_scheduler()

# Feb-2026 · D2 — log the boot-hardening flag snapshot ONCE at
# module import so ops can grep the boot log to confirm posture.
try:
    logger.info(f"[boot_flags] snapshot={_boot_flags_snapshot()}")
except Exception:  # pragma: no cover — defensive; never block boot
    pass


# ── Cold-start optimization ───────────────────────────────────────────
# Only the demo-admin `seed()` + a Mongo ping stay on the sync boot path
# so that /api/auth/login is answerable within ~1s of process start.
# All heavier idempotent seeds and the APScheduler registration run in a
# background task fired 2s after boot. `/api/health/seeds` exposes the
# progress so the frontend / monitoring can display a "warming" hint.

SEEDS_COMPLETE: bool = False
SEEDS_PHASE: str = "pending"
SEEDS_STARTED_AT: str | None = None
SEEDS_COMPLETED_AT: str | None = None


async def _background_seed():
    """Runs every heavy, idempotent seed off the boot path.
    Every step is wrapped so one bad seed can't block the rest."""
    global SEEDS_COMPLETE, SEEDS_PHASE, SEEDS_COMPLETED_AT
    from datetime import datetime, timezone as _tz
    import asyncio
    SEEDS_PHASE = "running"
    logger.info("Background seed pipeline starting…")

    async def step(name: str, coro):
        global SEEDS_PHASE
        SEEDS_PHASE = name
        try:
            await coro
        except Exception as e:
            logger.warning(f"seed step {name} skipped: {e}")

    if _SEED_DEMO_DATA:
        await step("seed_extras", seed_extras())
    # Backfill income category — kept as a raw update, not a helper.
    try:
        SEEDS_PHASE = "income_category_backfill"
        res = await db.quotes.update_many(
            {"$or": [{"line_items.category": {"$exists": False}},
                        {"line_items.category": None}]},
            {"$set": {"line_items.$[el].category": "Pool"}},
            array_filters=[{"$or": [{"el.category": {"$exists": False}},
                                     {"el.category": None}]}],
        )
        if res.modified_count:
            logger.info(f"Backfilled income category on {res.modified_count} docs")
    except Exception as e:
        logger.warning(f"income category backfill skipped: {e}")

    await step("legal_docs", legal.ensure_seeded())
    await step("marketing_templates", marketing_studio._seed_templates())
    await step("sequences", sequences.ensure_sequences_seeded())
    await step("ai_employees", ai_ops.ensure_ai_employees_seeded())
    # ``onboarding_demo`` is demo-only — flips the aquaterra demo
    # tenant's onboarding checklist to "completed".  Skip in prod.
    if _SEED_DEMO_DATA:
        await step("onboarding_demo", onboarding._seed_completed_for_demo())
    await step("lead_request_form", lead_requests._seed_lead_request_form())
    await step("tenant_backfill", tenants.run_tenant_backfill())
    await step("super_admin", tenants._seed_super_admin())

    # Feb-2026 · Multi-category tech assignment · P1 follow-up —
    # normalize legacy ``users.department`` tokens (``"pool"`` /
    # ``"landscaping"``) into the modern enum accepted by
    # ``PUT /admin/users/{uid}/department``.  Idempotent — second
    # run reports 0 updates.  MUST run BEFORE
    # ``align_demo_tech_departments`` so the demo alignment sees
    # already-modern values.  Unconditional (not gated by
    # ``SEED_DEMO_DATA``) because this is a one-shot production
    # upgrade, not demo data.
    try:
        from migrations.normalize_user_department_tokens import (
            run as _normalize_dept_run,
        )
        await step("normalize_user_departments", _normalize_dept_run())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"normalize_user_departments skipped: {e}")

    # Feb-2026 · Slice GH0 post-fix — mirror the sync-boot dev-domain
    # seed after ``tenant_backfill`` so a fresh cold boot (where the
    # aquaterra tenant didn't exist yet at sync-startup) still gets
    # the dev hosts pinned. Uses the same helper as sync-boot.
    try:
        from routers.widget_config import seed_dev_widget_domains_for_aquaterra
        result = await seed_dev_widget_domains_for_aquaterra()
        logger.info(f"[gh0-seed:bg] {result}")
    except Exception as e:
        logger.warning(f"gh0 dev-domain background seed crashed: {e}")

    # Slice I — walkthrough backfill (idempotent, grandfathers existing customers).
    try:
        from routers.portal_walkthrough import run_walkthrough_backfill
        result = await run_walkthrough_backfill()
        logger.info(f"[slice-i] walkthrough backfill: {result}")
    except Exception as e:
        logger.warning(f"walkthrough backfill crashed: {e}")

    # Feb-2026 · BUG E — Terms of Service gate backfill (idempotent).
    # Grandfathers existing non-super_admin users to CURRENT_TOS_VERSION
    # so this fix does not wall out the preview accounts. Super admins
    # get gate fields explicitly cleared (they are exempt).
    try:
        from routers.tos import run_tos_backfill as _tos_backfill
        tos_res = await _tos_backfill()
        logger.info(f"[bug-e] tos backfill: {tos_res}")
    except Exception as e:
        logger.warning(f"tos backfill crashed: {e}")

    # Feb-2026 · Slice 2A — Multi-ToS foundation. Ensure indexes on
    # the two new collections + seed a v1 published Pool ToS from
    # the legacy ``TOS_MARKDOWN`` for every tenant that doesn't
    # already have a pool row. Idempotent — repeat runs are cheap.
    try:
        from services.tos_service import (
            ensure_indexes as _tos_multi_indexes,
            seed_pool_tos_from_legacy as _tos_multi_seed,
        )
        await _tos_multi_indexes(db)
        seeded = 0
        async for _t in db.tenants.find({}, {"_id": 0, "id": 1}):
            try:
                r = await _tos_multi_seed(db, _t["id"])
                if r:
                    seeded += 1
            except Exception as _seed_exc:
                logger.warning(
                    f"[slice-2a] pool ToS seed failed for tenant "
                    f"{_t.get('id')}: {_seed_exc}"
                )
        logger.info(f"[slice-2a] multi-tos seed: {seeded} tenant(s) seeded")
    except Exception as e:
        logger.warning(f"[slice-2a] multi-tos boot init crashed: {e}")

    # Feb-2026 · Phase 21 — Rebrand AquaTerra → Pool & Landscaping of
    # Vistancia. Idempotent one-shot migration that updates the tenant
    # name + adds `plofv` slug alias + fills in business_card /
    # email_sender / primary_app_domain settings. Second run is a
    # no-op. Never crashes boot on failure.
    try:
        from migrations import rebrand_aquaterra_to_plofv as _rebrand_p21
        rb_res = await _rebrand_p21.run()
        logger.info(f"[phase21] rebrand migration: {rb_res}")
    except Exception as e:
        logger.warning(f"[phase21] rebrand migration crashed: {e}")

    # Feb-2026 · Crew Phase A — seed 2 demo crews for AquaTerra so the
    # Schedule "New Job" + Edit-modal crew pickers always have
    # something to select. Idempotent by name; skips other tenants.
    # Runs on boot so a preview DB reset can't leave testers with an
    # empty crew list.
    try:
        from scripts.seed_aquaterra_crews import seed_aquaterra_crews
        _crews_res = await seed_aquaterra_crews()
        logger.info(f"[crew-seed] {_crews_res}")
    except Exception as e:
        logger.warning(f"crew seed crashed: {e}")

    # Feb-2026 · mobile-flagged gap — Auto Clock-In field backfill
    # (idempotent). Stamps role-appropriate defaults on existing users
    # without the field so mobile / web can key off a single flag.
    try:
        from routers.auto_clockin import run_auto_clockin_backfill
        ac_res = await run_auto_clockin_backfill()
        logger.info(f"[auto-clockin] backfill: {ac_res}")
    except Exception as e:
        logger.warning(f"[auto-clockin] backfill crashed: {e}")

    # Feb-2026 · Item 11 — Referral vesting backfill (idempotent).
    try:
        from routers.referrals_vesting import run_backfill as _vest_backfill
        vest_res = await _vest_backfill()
        logger.info(f"[vesting-backfill] {vest_res}")
    except Exception as e:
        logger.warning(f"vesting backfill crashed: {e}")

    # Feb-2026 · Phase 22 — Citation Builder seed + NAP drift sweep.
    # Idempotent: upserts the master directory list by slug, then
    # recomputes ``nap_drift_detected`` for every tenant's citations.
    try:
        from routers.citations import run_citations_seed_and_drift
        _c_res = await run_citations_seed_and_drift()
        logger.info(f"[citations-seed] {_c_res}")
    except Exception as e:
        logger.warning(f"citations seed crashed: {e}")

    # Feb-2026 · Phase 23-A — DataForSEO auth log line. Weekly rank
    # tracker cron is INTENTIONALLY not scheduled here; boot only
    # verifies credentials. Flip RANK_TRACKER_CRON_ENABLED=true and
    # invoke ``run_weekly_rank_tracker`` from a scheduler to activate.
    try:
        from services import dataforseo_client as _dfs
        _dfs.log_auth_config()
    except Exception as e:
        logger.warning(f"[dataforseo] boot log skipped: {e}")

    # Feb-2026 · Phase 24 — seed the 7 default AI visibility prompts
    # for any tenant with an empty prompt list. Idempotent.
    try:
        from routers.ai_visibility import run_ai_visibility_seed
        _s = await run_ai_visibility_seed()
        logger.info(f"[aiv-seed] {_s}")
    except Exception as e:
        logger.warning(f"aiv seed crashed: {e}")

    # Feb-2026 · Phase 26 — MCP OAuth 2.1 client indexes (Supercool).
    # Creates the state TTL index + unique connection/tool_catalog keys.
    # Feb-2026 · D2 — skipped in prod.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from services import mcp_oauth_client as _mcp
        await _mcp.ensure_indexes()
    except Exception as e:
        logger.warning(f"mcp_oauth ensure_indexes crashed: {e}")

    # Feb-2026 · Phase B — image generation indexes.
    # Feb-2026 · D2 — skipped in prod.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from routers import media_gen as _phaseb_media
        await _phaseb_media.ensure_indexes()
    except Exception as e:
        logger.warning(f"media_gen ensure_indexes crashed: {e}")

    # Feb-2026 · 24h post-completion edit-window audit indexes.
    # Feb-2026 · D2 — skipped in prod.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        await db.job_edits.create_index([
            ("tenant_id", 1), ("job_id", 1), ("edited_at", -1),
        ], name="job_edits_by_job")
        await db.job_edits.create_index([
            ("tenant_id", 1), ("edited_by", 1), ("edited_at", -1),
        ], name="job_edits_by_user")
    except Exception as e:
        logger.warning(f"job_edits ensure_indexes crashed: {e}")

    # Feb-2026 — one-shot idempotent Brian integration ownership
    # transfer. Runs every boot but only mutates on the first pass.
    try:
        from migrations.transfer_integrations_to_brian import run as _brian_run
        brian_result = await _brian_run()
        logger.info(f"[migration:brian] result={{'ok': {brian_result.get('ok')}, "
                     f"'created': {brian_result.get('brian_user_created')}, "
                     f"'diff_keys': {sorted(list((brian_result.get('diff') or {}).keys()))}}}")
        if brian_result.get("temp_password"):
            # Print once on cold-start — we do NOT persist this anywhere.
            logger.warning(
                "[migration:brian] BRIAN TEMP PASSWORD (first-boot only) = %s",
                brian_result["temp_password"],
            )
    except Exception as e:
        logger.warning(f"brian integrations transfer crashed: {e}")

    # Feb-2026 · D2 — the following demo tech users + demo-only
    # data seeds skip in production (APP_ENV=production or
    # SEED_DEMO_DATA=false).  Each ``seed_*_user`` also individually
    # gates on SEED_DEMO_USERS=1 inside seed.py; the outer
    # SEED_DEMO_DATA guard here is the belt-and-braces defense for
    # a prod pod that gets misconfigured.
    if _SEED_DEMO_DATA:
        await step("landscaping_user", seed_landscaping_user())
        await step("landscape_tech_carlos", seed_landscape_tech_carlos())
        # Phase 41.1b · Feb 2026 — idempotent backfill of mike@aquaterra.com
        # (pool tech). Historically he lived only inside the one-shot
        # ``seed()`` bulk seed, which early-returns when users exist —
        # any deployment where another user was created first never got
        # Mike, leaving `test_ai_employees_ae1.py` + `test_phase50.py`
        # with a 401-on-login fixture failure. Now backfilled on every boot.
        await step("pool_tech_mike", seed_pool_tech_mike())
        # Phase 5A follow-up · Feb 2026 — realign Mike (pool) / Carlos
        # (landscape) + seed the manager role-gate test account. Both are
        # idempotent and safe to run on every boot.
        await step("align_demo_tech_departments", align_demo_tech_departments())
        await step("seed_manager_user", seed_manager_user())
        # Phase 53c · Feb-2026 — heal any drift where the demo manager
        # got promoted to admin by an unrelated migration. Idempotent.
        from seed import seed_demo_manager as _seed_demo_manager
        await step("seed_demo_manager", _seed_demo_manager())
    # ``auto_heal_demo_passwords`` already self-gates on APP_ENV=production
    # inside seed.py — left unconditional here so the log line still
    # prints (helps ops confirm the safe-in-prod posture).
    await step("auto_heal_demo_passwords", auto_heal_demo_passwords_if_needed())
    try:
        from comms_seed.seed_comms import seed_comms as _seed_comms
        await step("comms_system_rows", _seed_comms())
    except Exception as _e:
        logger.warning(f"seed_comms failed: {_e}")

    try:
        from reviews_seed.seed_reviews import seed_reviews as _seed_reviews
        await step("reviews_phase1_seed", _seed_reviews())
    except Exception as _e:
        logger.warning(f"seed_reviews failed: {_e}")
    # Feb-2026 · D2 — the following are demo/sample data.  Skip in prod.
    if _SEED_DEMO_DATA:
        await step("business_os", business_os.seed_business_os())
        await step("tech_today_demo", seed_tech_today_demo())
        await step("prior_readings", seed_prior_readings())
        await step("phase51k_finance", seed_phase51k_finance())
        await step("mike_today_job", seed_mike_today_job())
        # Feb-2026 · D2 — AMBIGUOUS.  ``chemical_costs`` +
        # ``inventory_alerts_seed`` + ``pricebook_suppliers`` seed
        # per-tenant rows that could either be reference data (real
        # tenants would want them) or demo-only.  Per the user's
        # instruction we default to gating them off in prod so a
        # fresh production tenant does not get demo pool chemicals
        # / suppliers.  Revisit if a production tenant needs the
        # reference catalogue — most likely we'd promote these to
        # unconditional migrations at that point.
        await step("chemical_costs", chemical_costs.seed_chemical_costs())
        # Phase 18 · Feb-2026 — Auto-seed the 8 core pool chemicals into
        # every tenant's inventory_items. Idempotent by ``sku=P18-<slug>``;
        # existing rows keep their tuned reorder_point (per user decision).
        try:
            from services.inventory_alerts import seed_chemicals_all_tenants
            await step("inventory_alerts_seed", seed_chemicals_all_tenants())
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"inventory_alerts seed skipped: {_e}")
    # Directories subsystem · Phase D1 (Feb 2026) — global catalogue.
    # Unconditional: this is reference data (the master list of
    # third-party AI directories) that real production tenants use.
    try:
        from services.directory_seed import ensure_seeded as _dir_seed
        await step("directory_catalogue", _dir_seed())
    except Exception as _e:
        logger.warning(f"directory_seed skipped: {_e}")

    # Phase 56-a · Aug-2026 — Pricebook Suppliers per-tenant seed.
    # Idempotent: inserts the 13 default rows only if tenant has zero
    # docs. Respects user-side deletes (no re-seed once populated).
    # Feb-2026 · D2 — AMBIGUOUS (see chemical_costs note above).
    # Gated off in prod as a safety default.
    if _SEED_DEMO_DATA:
        try:
            from services.pricebook_suppliers_seed import (
                seed_all_tenants as _seed_pb_suppliers,
            )
            await step("pricebook_suppliers", _seed_pb_suppliers())
        except Exception as _e:                                       # noqa: BLE001
            logger.warning(f"pricebook_suppliers seed skipped: {_e}")

    # Scheduler registration (needs the DB but not auth).
    try:
        SEEDS_PHASE = "scheduler"
        # Feb-2026 · D2 — gate the entire APScheduler registration +
        # ``.start()`` behind ``ENABLE_SCHEDULER``.  Raising here
        # short-circuits into the same ``except`` handler below, which
        # logs at WARN and moves on.  In production a dedicated
        # worker process runs ``python -m scripts.run_scheduler``
        # (which sets ``ENABLE_SCHEDULER=true`` for its own env)
        # while web workers keep the flag off so they don't compete
        # on job execution.
        if not _ENABLE_SCHEDULER:
            raise RuntimeError(
                "scheduler disabled by ENABLE_SCHEDULER=false — "
                "run scripts.run_scheduler in a dedicated process"
            )
        scheduler.add_job(seo.run_due_publishes, "interval", minutes=10,
                            id="seo_drip", replace_existing=True)
        scheduler.add_job(finances.run_monthly_chem_billing, "interval",
                            hours=24, id="chem_billing", replace_existing=True)
        # Phase 56.17 — daily autobilling schedule dispatcher.
        # Runs every day at 06:00 UTC; each plan's anchor date is
        # computed in the tenant's own timezone inside the job.
        scheduler.add_job(finances.run_daily_autobilling, "cron",
                            hour=6, minute=0, id="autobilling_daily",
                            replace_existing=True)
        scheduler.add_job(coverage.revert_expired_coverage, "interval",
                            hours=12, id="coverage_revert",
                            replace_existing=True)
        # Phase 54e · Feb-2026 — wholesale supplier sync cron (hourly
        # + daily at 03:00 UTC). Gated by SUPPLIER_SYNC_LIVE=1 —
        # default OFF everywhere, so the cron ticks fire but log-only.
        try:
            from services.suppliers.cron import register_supplier_cron_jobs
            register_supplier_cron_jobs(scheduler)
        except Exception as _sce:
            logger.warning(f"supplier.cron.register_skipped: {_sce}")
        scheduler.add_job(finances.run_late_fee_assessment, "cron",
                            hour=2, minute=0, id="late_fees",
                            replace_existing=True)
        scheduler.add_job(marketing_studio.run_marketing_autopost,
                            "interval", minutes=10,
                            id="marketing_autopost", replace_existing=True)
        scheduler.add_job(sequences.run_sequences_tick, "interval",
                            minutes=15, id="sequences_tick",
                            replace_existing=True)
        scheduler.add_job(csat.run_csat_dispatch_tick, "interval",
                            minutes=5, id="csat_dispatch",
                            replace_existing=True)
        scheduler.add_job(dunning.run_dunning_scan, "interval",
                            minutes=60, id="dunning_scan",
                            replace_existing=True)
        # Feb 2026 · Customer Merge Phase 3 — daily auto-merge sweep
        # of HIGH-confidence duplicate clusters (exact email OR exact
        # phone). Runs at 09:15 UTC, 10 minutes after the marketing
        # 09:05 sweep to avoid Motor pool contention. Feature-flagged
        # via ``AUTO_MERGE_ENABLED`` (default true).
        try:
            from services.customer_merge.auto_merge import (
                cron_daily_auto_merge as _cm_cron,
            )
            scheduler.add_job(
                _cm_cron, "cron",
                hour=9, minute=15,
                id="customer_merge_auto_sweep",
                replace_existing=True,
            )
            logger.info(
                "scheduler: customer_merge_auto_sweep registered @ 09:15 UTC",
            )
        except Exception as _e_cm:  # noqa: BLE001
            logger.warning("[customer-merge] scheduler wiring failed: %s", _e_cm)
        # Feb-2026 · P34 — Automation quiet-hours release worker.
        # Runs every 5 minutes; picks up any deferred SMS / email
        # rows whose ``scheduled_for`` has passed and dispatches them.
        try:
            from services.quiet_hours_release import run_release_tick as _p34_tick
            scheduler.add_job(_p34_tick, "interval",
                                minutes=5, id="p34_quiet_hours_release",
                                replace_existing=True)
            logger.info("scheduler: p34 quiet-hours release tick registered "
                            "(every 5 min)")
        except Exception as _e34:  # noqa: BLE001
            logger.warning("[p34] scheduler wiring failed: %s", _e34)
        # Phase 17 · Feb-2026 — QBO daily inbound read-sync.
        try:
            import os as _os
            from services.qbo import sync as _qbo_sync  # noqa: WPS433
            _hr = int(_os.environ.get("QBO_SYNC_CRON_HOUR_UTC") or 3)
            scheduler.add_job(_qbo_sync.qbo_daily_sync, "cron",
                                hour=_hr, minute=0, id="qbo_daily_sync",
                                replace_existing=True)
        except Exception as _e:  # noqa: BLE001
            logger.warning("[qbo] scheduler wiring failed: %s", _e)
        # Phase 18 · Feb-2026 — Daily low-stock inventory scan. Hour
        # offset from Phase 5b 07:00, Phase 5c 08:00, Phase 7 :05,
        # Phase 8 :10, Phase 17 03:00 per the operator's cron-load
        # brief.
        try:
            import os as _os
            from services import inventory_alerts as _p18_inv_alerts  # noqa: WPS433
            _inv_hr = int(_os.environ.get("INVENTORY_CRON_HOUR_UTC") or 6)
            scheduler.add_job(
                _p18_inv_alerts.run_daily_low_stock_scan, "cron",
                hour=_inv_hr, minute=0, id="inventory_low_stock_daily",
                replace_existing=True,
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("[inventory_alerts] scheduler wiring failed: %s", _e)
        # Phase 34 · Feb 2026 — Weekly Bulk Actions Digest.
        # Monday 08:00 UTC. See services/weekly_bulk_actions_digest.py
        # for the rollup logic. Tenants with zero bulk actions in the
        # past 7 days are silently skipped. Delivery routes through
        # the Task-L guarded resend adapter so preview stays dry-run.
        try:
            from services.weekly_bulk_actions_digest import send_weekly_digest_all_tenants
            scheduler.add_job(
                send_weekly_digest_all_tenants, "cron",
                day_of_week="mon", hour=8, minute=0,
                id="weekly_bulk_digest", replace_existing=True,
            )
        except Exception as e:
            logger.warning(f"[phase34-digest] cron install failed: {e}")
        # Phase 26.2 — daily weather scan across every tenant (05:00 UTC).
        scheduler.add_job(dispatch.scheduled_weather_scan_all, "cron",
                            hour=5, minute=0, id="weather_scan",
                            replace_existing=True)
        # Phase 5b · AEO — daily AI visibility scan across enabled tenants.
        # Hour configurable via AEO_VISIBILITY_CRON_HOUR_UTC (default 7).
        try:
            from services.aeo_visibility import (
                daily_visibility_scan, CRON_HOUR_UTC,
            )
            scheduler.add_job(daily_visibility_scan, "cron",
                                hour=CRON_HOUR_UTC, minute=0,
                                id="aeo_visibility_scan",
                                replace_existing=True)
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[aeo] cron install failed: {_e}")
        # Phase 5c · AEO — daily brand-mention crawl (default 08:00 UTC).
        try:
            from services.brand_mentions import (
                daily_mentions_scan, CRON_HOUR_UTC as _MENTIONS_HR,
            )
            scheduler.add_job(daily_mentions_scan, "cron",
                                hour=_MENTIONS_HR, minute=0,
                                id="aeo_mentions_scan",
                                replace_existing=True)
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[aeo] mentions cron install failed: {_e}")
        # Phase 7 · Weekly scorecard digest — runs hourly; per-tenant
        # settings decide when to actually fire.
        try:
            from services.scorecard_digest import weekly_digest_cron
            scheduler.add_job(weekly_digest_cron, "cron",
                                minute=5, id="scorecard_weekly_digest",
                                replace_existing=True)
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[scorecard] cron install failed: {_e}")
        # Phase 8 · Weekly AEO PDF digest — hourly, per-tenant hour gate.
        try:
            from services.aeo_digest import weekly_digest_cron as _aeo_digest_cron
            scheduler.add_job(_aeo_digest_cron, "cron", minute=10,
                                id="aeo_weekly_digest", replace_existing=True)
        except Exception as _e:  # noqa: BLE001
            logger.warning(f"[aeo_digest] cron install failed: {_e}")
        # Phase 27.1 — weekly churn rescore (Mondays 06:00 UTC).
        scheduler.add_job(churn.scheduled_churn_scan_all, "cron",
                            day_of_week="mon", hour=6, minute=0,
                            id="churn_scan", replace_existing=True)
        # Phase 28.1 — daily warranty expiration reminders (08:00 UTC).
        scheduler.add_job(
            warranties.scheduled_warranty_expiration_scan_all,
            "cron", hour=8, minute=0,
            id="warranty_expiration_scan", replace_existing=True)
        # Phase 50.G — Auto-Friday Pool Service Report email (17:00 UTC).
        from services.pool_service_email import run_weekly_pool_service_email
        scheduler.add_job(
            run_weekly_pool_service_email,
            "cron", day_of_week="fri", hour=17, minute=0,
            id="pool_service_weekly_email", replace_existing=True)
        # Phase 51.I — nightly recurring-job generator (02:00 UTC).
        from routers.recurring_jobs import run_recurring_job_generator
        scheduler.add_job(
            run_recurring_job_generator,
            "cron", hour=2, minute=0,
            id="recurring_job_generator", replace_existing=True)

        # Phase 4B follow-up — Stripe live-key health cron slot,
        # intentionally left empty. The live probe now runs on
        # demand via ``GET /api/settings/integrations/health/stripe``
        # (see routers/google.py); a cron isn't needed while there
        # is only one Stripe account per tenant.
        # Phase 54 — nightly RingCentral contact pull-sync (03:00 UTC).
        async def _rc_nightly_pull():
            try:
                from services.ringcentral_client import is_outbound_enabled, get_rc_platform
                if not await is_outbound_enabled(): return
                platform = get_rc_platform()
                resp = platform.get("/restapi/v1.0/account/~/extension/~/address-book/contact",
                                     {"perPage": 500})
                data = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
                for r in (data or {}).get("records") or []:
                    phone = r.get("businessPhone") or r.get("homePhone") or r.get("mobilePhone")
                    if not phone: continue
                    exists = await db.leads.find_one({"phone": phone, "source": "rc-contact-sync"})
                    if exists: continue
                    await db.leads.insert_one({
                        "id": _utils_new_id(),
                        "source": "rc-contact-sync",
                        "phone": phone,
                        "name": f"{r.get('firstName','')} {r.get('lastName','')}".strip() or "Unknown",
                        "email": r.get("email"),
                        "created_at": _utils_now_iso(),
                        "status": "new",
                    })
            except Exception:
                pass
        scheduler.add_job(
            _rc_nightly_pull,
            "cron", hour=3, minute=0,
            id="rc_contact_pull_sync", replace_existing=True)

        # G2 · Feb-2026 — Server-side stop detection batch cron.
        # Runs every 3 minutes; each run is a no-op when
        # gps_settings.enabled=false for the tenant.
        try:
            from services.gps_stops_batch import run_gps_stops_batch
            scheduler.add_job(
                run_gps_stops_batch,
                "interval", minutes=3,
                id="gps_stops_batch_processor", replace_existing=True,
                max_instances=1, coalesce=True,
            )
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[gps_stops] cron install failed: {e}")

        # G5b · Feb-2026 — Attribution batch: link pending stops to
        # closest same-day scheduled job (within tenant-configurable
        # threshold). Runs every 5 minutes; no-op when gps_settings
        # is disabled or the tenant has zero pending stops.
        try:
            from services.stop_attributor import (
                run_attribution_batch_all_tenants)
            scheduler.add_job(
                run_attribution_batch_all_tenants,
                "interval", minutes=5,
                id="stop_attribution_batch",
                replace_existing=True,
                max_instances=1, coalesce=True,
            )
            logger.info("scheduler: stop_attribution_batch "
                         "registered (every 5 min)")
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[stop_attribute] cron install failed: {e}")

        # Phase SEO-B · Feb-2026 — Outreach follow-up daily digest
        # at 08:00 UTC. Emails each tenant owner a summary of due
        # follow-ups. Idempotent by day.
        try:
            from services.outreach_followups import (
                run_outreach_followup_digest)
            scheduler.add_job(
                run_outreach_followup_digest,
                "cron", hour=8, minute=0,
                id="outreach_daily_followup_digest",
                replace_existing=True,
                max_instances=1, coalesce=True,
            )
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[outreach] cron install failed: {e}")

        # Phase G3 · Feb-2026 — Reverse-geocode cache purge (05:00 UTC).
        # Drops rows in ``reverse_geocode_cache`` where ``expires_at``
        # is in the past. Safe against empty collections.
        try:
            from services.reverse_geocoder import (
                purge_expired_geocode_cache)
            scheduler.add_job(
                purge_expired_geocode_cache,
                "cron", hour=5, minute=0,
                id="reverse_geocode_cache_purge",
                replace_existing=True,
                max_instances=1, coalesce=True,
            )
        except Exception as e:                                        # noqa: BLE001
            logger.warning(f"[reverse_geocoder] cron install failed: {e}")
        # Task QQ Phase 2 · Feb 2026 — nightly Lumino reconciler
        # (03:00 UTC). Polls pending payments/subscriptions to close
        # any gap left by the return-URL / Zapier bridge paths.
        # Safe in preview: the provider returns a mock for
        # ``mock_``/``prev_`` session ids and dry-runs everything
        # else, so the cron is a no-op unless real Lumino creds are
        # populated in production.
        try:
            from services.lumino_reconciler import register_lumino_reconciler_job
            register_lumino_reconciler_job(scheduler)
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[task-qq] lumino reconciler cron install failed: {e}")
        # Queue Item 5c · Feb-2026 — Homeworks Import Dispatcher.
        # Replaces the operator-driven nohup workflow: polls every 30s
        # for ``status=queued`` docs on ``homeworks_import_runs`` and
        # drives the correct importer's ``run_full`` inline. Manual
        # ``scripts/homeworks_run_*.py`` launchers stay in-tree as
        # debugging escape hatches.
        try:
            from services.homeworks_mcp.import_dispatcher import register_dispatcher
            register_dispatcher(scheduler)
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[queue-item-5c] homeworks import dispatcher install failed: {e}")
        # Phase 52.A — monthly pricing insights digest (1st @ 09:00 UTC).
        from services.monthly_pricing_digest import run_monthly_pricing_digest
        scheduler.add_job(
            run_monthly_pricing_digest,
            "cron", day=1, hour=9, minute=0,
            id="monthly_pricing_digest", replace_existing=True)
        # Phase 4 · Batch C — Weekly digest email (Mondays 08:00 UTC).
        # Per-tenant timezone is honored inside the service; the cron
        # trigger fires globally at a reasonable US business hour.
        from services.weekly_digest import run_weekly_digest, ensure_indexes as _wd_indexes
        await _wd_indexes()
        scheduler.add_job(
            run_weekly_digest,
            "cron", day_of_week="mon", hour=8, minute=0,
            id="weekly_digest", replace_existing=True)
        logger.info("scheduler: weekly_digest registered (Mondays 08:00 UTC)")

        # Phase 11 · Feb 2026 — Equipment Service Trackers (Filter &
        # Salt Cell). Hourly scan performs per-tenant local-time dispatch:
        # for each tenant, if their local weekday is Monday and local
        # hour is 08, fire the admin digest + optional customer
        # reminders (the reminder path is OFF by default; tenants opt
        # in via ``equipment_service_customer_reminders_enabled``).
        try:
            from routers.equipment_trackers import ensure_indexes as _est_indexes
            from services.equipment_trackers_cron import hourly_scan as _est_hourly
            await _est_indexes()
            scheduler.add_job(
                _est_hourly, "cron", minute=0,
                id="equipment_service_hourly", replace_existing=True,
            )
            logger.info(
                "scheduler: equipment_service_hourly registered "
                "(per-tenant Mon 08:00 local dispatch)"
            )
        except Exception as _ee:
            logger.warning(f"equipment_service cron registration crashed: {_ee}")

        # Phase 10 · Feb 2026 — Referral credit watcher (30-day paid
        # window). Hourly cron; each tenant's dispatch is gated by its
        # local hour (default 03:00). Also seeds the two credit-earned
        # templates + runs the legacy immediate-credit back-migration.
        try:
            from routers.promo_codes import ensure_indexes as _promo_indexes
            from services.referral_watcher import (
                hourly_scan as _ref_hourly,
                ensure_indexes as _ref_indexes,
                seed_referral_credit_templates as _seed_tpls,
                backmigrate_legacy_referral_credits as _backmigrate,
            )
            await _promo_indexes()
            await _ref_indexes()
            await _seed_tpls()
            bm_res = await _backmigrate()
            logger.info(f"[phase10] back-migration: {bm_res}")
            scheduler.add_job(
                _ref_hourly, "cron", minute=0,
                id="referral_watcher_hourly", replace_existing=True,
            )
            logger.info(
                "scheduler: referral_watcher_hourly registered "
                "(per-tenant local-hour dispatch, default 03:00)"
            )
        except Exception as _re:
            logger.warning(f"referral watcher registration crashed: {_re}")

        # Phase 12B — weekly Stripe ↔ customers reverse-sync cron
        # slot. Intentionally left empty. Customer creation happens
        # inline in the /payments/stripe/attach path (see
        # routers/customer_portal.py + routers/customers.py), so
        # there is no separate sweep to run. Kept as a signpost.

        # G0 · Feb-2026 — GPS driver-activity retention purge cron.
        # Daily 04:00 UTC. Safe against empty collections. G1/G2 will
        # feed real pings; today this job runs against zero rows.
        try:
            from routers.gps_settings import purge_expired_pings
            scheduler.add_job(
                purge_expired_pings, "cron",
                hour=4, minute=0,
                id="gps_pings_retention_purge",
                replace_existing=True,
            )
            logger.info("scheduler: gps_pings_retention_purge registered (04:00 UTC daily)")
        except Exception as _g0e:                                     # noqa: BLE001
            logger.warning(f"gps purge cron registration crashed: {_g0e}")

        # Comms Phase 3 · Feb 2026 — automation-engine daily sweeps.
        # invoice.overdue (09:00 UTC), customer.birthday (08:00),
        # customer.anniversary (08:05). Rule index is warmed up too,
        # so the very first domain event after boot does not pay the
        # cold-start read cost.
        try:
            from services import automation_engine as _auto
            await _auto.re_index_rules()
            _auto.register_daily_sweeps(scheduler)
            # Phase 49 · Feb-2026 — minute-cadence Lana reminder tick.
            try:
                from services.lana.reminder_cron import register_lana_reminders_cron
                register_lana_reminders_cron(scheduler)
            except Exception as _lana_exc:  # pragma: no cover
                logger.warning("[lana.reminders.cron] register failed: %s", _lana_exc)
            # Phase 51d · Feb-2026 — minute-cadence walkie cleanup tick.
            try:
                from services.walkie.cleanup_cron import register_walkie_cleanup_cron
                register_walkie_cleanup_cron(scheduler)
            except Exception as _walkie_exc:  # pragma: no cover
                logger.warning("[walkie.cleanup.cron] register failed: %s", _walkie_exc)
            # Phase 52.1a · Feb-2026 — 5-min live-session stale-cleanup tick.
            try:
                from services.walkie.live_cleanup_cron import register_live_cleanup_cron
                register_live_cleanup_cron(scheduler)
            except Exception as _walkie_live_exc:  # pragma: no cover
                logger.warning(
                    "[walkie.live.cleanup.cron] register failed: %s", _walkie_live_exc,
                )
        except Exception as _ae:
            logger.warning(f"automation_engine registration crashed: {_ae}")

        # Reviews Phase 3 · Feb 2026 — external platform daily syncs
        # (google 03:00, facebook 03:10, yelp 03:20 UTC). Adapters no-op
        # when their env flag / API key is missing, so this is safe to
        # register unconditionally.
        try:
            from services import review_scraper as _scraper
            _scraper.register_daily_sync(scheduler)
        except Exception as _rse:
            logger.warning(f"review_scraper registration crashed: {_rse}")

        # QuoteIQ Phase Q1 · AI Credits monthly reset (1st @ 00:05 UTC).
        try:
            from services.ai_credits import run_monthly_reset_all
            scheduler.add_job(
                run_monthly_reset_all,
                "cron", day=1, hour=0, minute=5,
                id="ai_credits_monthly_reset", replace_existing=True)
        except Exception as _ae:
            logger.warning(f"ai_credits monthly reset registration crashed: {_ae}")

        # Feb 2026 · Unified Notifications — muted-notification digest
        # (nightly 00:15 UTC). Sweeps every tenant with
        # ``notification_digest_enabled=True`` and enqueues one digest
        # email per user with muted push events in the last 24 h. Safe
        # no-op when no tenants opt in.
        try:
            from services.notifications import run_muted_digest_sweep
            scheduler.add_job(
                run_muted_digest_sweep,
                "cron", hour=0, minute=15,
                id="muted_notification_digest", replace_existing=True)
        except Exception as _de:
            logger.warning(f"muted digest registration crashed: {_de}")

        # Feb-2026 · Marketing Slice M5c — Drip / Nurture Sequences.
        # Two jobs:
        #   1. Step processor — every 5 minutes: advance every enrolment
        #      whose next_send_at is due, record mock deliveries.
        #   2. Daily sweep — 09:00 UTC: eval invoice_past_due_N_days,
        #      birthday and segment_join across every tenant.
        try:
            from services.marketing.drip_events import (
                sequences_tick_all_tenants,
                daily_marketing_trigger_sweep,
            )
            scheduler.add_job(
                sequences_tick_all_tenants,
                "cron", minute="*/5",
                id="m5_sequences_tick", replace_existing=True)
            scheduler.add_job(
                daily_marketing_trigger_sweep,
                "cron", hour=9, minute=0,
                id="m5_daily_trigger_sweep", replace_existing=True)
            logger.info("scheduler: m5 tick (*/5 min) + daily sweep (09:00 UTC) registered")
        except Exception as _m5e:
            logger.warning(f"m5c scheduler registration crashed: {_m5e}")

        # Feb 2026 · Marketing Phase 1 · Custom Trigger Builder — daily
        # schema-v2 sweep. Fires at 09:05 UTC (5 min after the legacy
        # sweep so we don't overlap the customer/tenant scans). Handles
        # invoice_overdue / customer_birthday / service_anniversary
        # plus a schema-v2 re-arm of job_scheduled_reminder_1d. Per-
        # tenant isolation lives inside daily_phase1_trigger_sweep so
        # one slow tenant doesn't block others.
        try:
            from services.marketing.phase1_sweeps import (
                daily_phase1_trigger_sweep,
            )
            scheduler.add_job(
                daily_phase1_trigger_sweep,
                "cron", hour=9, minute=5,
                id="phase1_daily_trigger_sweep",
                replace_existing=True)
            logger.info("scheduler: phase1 daily trigger sweep (09:05 UTC) registered")
        except Exception as _p1e:
            logger.warning(f"phase1 scheduler registration crashed: {_p1e}")

        # Feb-2026 · Marketing Slice M6 — Review Requests.
        # Piggy-backs on the mocked marketing_deliveries pipeline.
        # Two jobs:
        #   1. Tick — every 5 minutes: fire due queued rows.
        #   2. Expiry sweep — 03:15 UTC daily: flip expired rows.
        try:
            from routers.marketing_review_requests import (
                m6_tick_all_tenants, m6_expiry_sweep,
            )
            scheduler.add_job(
                m6_tick_all_tenants,
                "cron", minute="*/5",
                id="m6_review_request_tick", replace_existing=True)
            scheduler.add_job(
                m6_expiry_sweep,
                "cron", hour=3, minute=15,
                id="m6_review_request_expiry", replace_existing=True)
            logger.info("scheduler: m6 tick (*/5 min) + expiry sweep (03:15 UTC) registered")
        except Exception as _m6e:
            logger.warning(f"m6 scheduler registration crashed: {_m6e}")

        # Feb-2026 · GH-Fix v2 — self-healing tick that re-seeds the
        # aquaterra dev-domain allowlist every 10 min. Non-prod only
        # (helper self-gates on APP_ENV). Keeps the widget bundle
        # working through test PATCH-replace churn.
        try:
            from routers.widget_config import seed_dev_widget_domains_for_aquaterra
            async def _widget_dev_seed_tick():
                try:
                    await seed_dev_widget_domains_for_aquaterra()
                except Exception as exc:  # pragma: no cover — logged only
                    logger.warning(f"gh0 dev-domain tick crashed: {exc}")
            scheduler.add_job(
                _widget_dev_seed_tick,
                "interval", minutes=10,
                id="gh0_widget_dev_seed", replace_existing=True)
            logger.info("scheduler: gh0 dev-domain seed tick (*/10 min) registered")
        except Exception as _gh0e:
            logger.warning(f"gh0 dev-domain tick registration crashed: {_gh0e}")

        scheduler.start()
    except Exception as e:
        logger.warning(f"scheduler registration skipped: {e}")

    SEEDS_COMPLETED_AT = datetime.now(_tz.utc).isoformat()
    SEEDS_PHASE = "complete"
    SEEDS_COMPLETE = True
    logger.info("Background seed pipeline complete.")


@app.on_event("startup")
async def startup():
    global SEEDS_STARTED_AT
    import asyncio
    from datetime import datetime, timezone as _tz
    # Sync boot path — auth-critical only.
    try:
        await client.admin.command("ping")
        logger.info("MongoDB ping OK")
    except Exception as e:
        logger.error(f"MongoDB ping FAILED at startup: {e}")
    # Phase 13 · Feb-2026 — W2 · ensure session-collection compound
    # indexes at boot (self-healing safety net; the script can also be
    # run manually). Wrapped so a Mongo hiccup can't block boot.
    # Feb-2026 · D2 — skipped in prod (RUN_STARTUP_INDEXES=false);
    # ops runs ``python -m scripts.ensure_indexes`` instead.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from scripts.create_session_indexes import ensure_on_boot as _idx_boot
        await _idx_boot()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Phase13-W2] session index create failed: {e}")
    # Phase 51a · Feb 2026 — Walkie-Talkie indexes + tenant bootstrap.
    # Feb-2026 · D2 — the ``_walkie_ensure_indexes`` +
    # ``ensure_live_session_indexes`` sub-calls are skipped in prod
    # (RUN_STARTUP_INDEXES=false); the tenant channel bootstrap
    # below runs unconditionally because it's not an index.
    try:
        from services.walkie.channels import (
            ensure_indexes as _walkie_ensure_indexes,
            bootstrap_standard_channels as _walkie_bootstrap,
        )
        if _RUN_STARTUP_INDEXES:
            await _walkie_ensure_indexes(db)
            # Phase 52.1a · Feb-2026 — live-session indexes.
            try:
                from routers.walkie_signaling import ensure_live_session_indexes as _live_indexes
                await _live_indexes()
            except Exception as _live_idx_exc:  # pragma: no cover
                logger.warning(f"[Phase52.1a] live-session index bootstrap: {_live_idx_exc}")
        # Bootstrap the standard channels for every existing tenant.
        tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(length=None)
        for t in tenants:
            tid = t.get("id")
            if tid:
                await _walkie_bootstrap(db, tid)
        logger.info(f"[Phase51a] walkie indexes + channels ready across {len(tenants)} tenants")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Phase51a] walkie bootstrap failed: {e}")

    # Feb-2026 · Task A · idempotent partial-unique-index migration on
    # ``db.jobs.(recurring_template_id, scheduled_date)``. Lazy-fires
    # from any /recurring-jobs/* handler too, but running at startup
    # closes the P0 timing gap where a legacy sparse-unique index
    # could still be live on a freshly-deployed pod until the first
    # recurring-jobs call. Idempotent: no-op when the partial index
    # is already present.
    # Feb-2026 · D2 — skipped in prod (RUN_STARTUP_INDEXES=false);
    # the lazy-fire from /recurring-jobs/* still closes the gap.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from routers.recurring_jobs import _ensure_indexes as _rj_ensure_indexes
        await _rj_ensure_indexes()
        idx_info = await db.jobs.index_information()
        _rj_target = idx_info.get("recurring_template_id_1_scheduled_date_1")
        _rj_shape = (
            "partial" if _rj_target and _rj_target.get("partialFilterExpression")
            else ("legacy-sparse" if _rj_target else "missing")
        )
        logger.info(
            f"[startup._ensure_indexes] recurring_template_id_1_scheduled_date_1 "
            f"shape={_rj_shape} indexes={sorted(idx_info.keys())}"
        )
    except Exception as _rj_idx_exc:  # noqa: BLE001
        logger.warning(f"[startup._ensure_indexes] {_rj_idx_exc}")
    # Phase 34 · Task L · Feb-2026 — one-line audit banner so it's
    # unmistakable from the boot logs whether outbound comms are
    # LIVE or DRY-RUN in the current environment.
    try:
        from services.comms_env_guard import startup_banner
        logger.info(startup_banner())
    except Exception as e:  # pragma: no cover
        logger.warning(f"comms_env_guard startup_banner failed: {e}")

    # Feb-2026 · Comms whitelist SDK-level safety net (P0 directive).
    # Monkey-patches ``resend.Emails.send`` so every direct SDK call
    # in the codebase (~13 sites that bypass the adapter chokepoint)
    # is gated by ``is_comm_allowed``. Idempotent + fail-closed.
    try:
        from services.comms.sdk_intercept import install_resend_gate
        install_resend_gate()
        logger.info("[comms.gate] resend SDK monkey-patch installed")
    except Exception as e:  # pragma: no cover
        logger.warning(f"[comms.gate] SDK monkey-patch install failed: {e}")
    # Task TT · Feb 2026 — Zillow adapter armed banner. Reads env
    # freshly at boot; a supervisor restart flips ``keys_configured``
    # from False → True the moment RapidAPI env is populated.
    try:
        from services.property_data import startup_log_line as _zillow_startup_log
        logger.info(_zillow_startup_log())
    except Exception as e:  # pragma: no cover
        logger.warning(f"[ZILLOW] startup banner failed: {e}")
    # Phase F0 · Feb 2026 — File storage init. Fail-soft when
    # EMERGENT_LLM_KEY is missing; module logs its own warning.
    try:
        from services.file_storage import init_storage as _f0_init, is_storage_configured as _f0_ok
        _f0_init()
        if _f0_ok():
            logger.info("[FILE_STORAGE] initialized")
        else:
            logger.warning("[FILE_STORAGE] disabled — see prior WARN for reason")
    except Exception as e:  # pragma: no cover
        logger.warning(f"[FILE_STORAGE] init failed: {e}")
    await seed()  # idempotent, ~ms after first run; creates demo admin.
    SEEDS_STARTED_AT = datetime.now(_tz.utc).isoformat()
    # Deployment audit (Phase 58.a) — ensure the deploy-blocker indexes
    # documented in db_indexes.py exist. Idempotent.
    # Feb-2026 · D2 — skipped in prod (RUN_STARTUP_INDEXES=false);
    # ops runs ``python -m scripts.ensure_indexes`` instead.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from db_indexes import ensure_deployment_indexes
        await ensure_deployment_indexes()
    except Exception as e:
        logger.warning(f"ensure_deployment_indexes crashed: {e}")

    # MR0 · Feb-2026 — Public check-in moderation queue indexes.
    # Feb-2026 · D2 — skipped in prod.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from routers.public_checkins import ensure_public_checkins_indexes
        await ensure_public_checkins_indexes()
    except Exception as e:
        logger.warning(f"ensure_public_checkins_indexes crashed: {e}")

    # Phase 5A · Feb 2026 — seed daily service-line checklists per
    # tenant. Idempotent, non-destructive; tenants that have already
    # customised their checklist keep their edits.
    try:
        from routers.checklists import seed_service_checklists_for_all_tenants
        await seed_service_checklists_for_all_tenants()
    except Exception as e:
        logger.warning(f"[phase5a] service_checklists seed crashed: {e}")

    # Phase 17 · Feb 2026 — 2dsphere index on customer service_location
    # + kick off a fire-and-forget geocode backfill so /dispatch has
    # pins to render on first admin visit. The backfill sleeps between
    # calls so it never bursts through Google's per-second quota.
    # Feb-2026 · D2 — the create_index is skipped in prod
    # (RUN_STARTUP_INDEXES=false); ops runs scripts.ensure_indexes
    # instead. The geocode backfill kick-off below remains
    # unconditional — it's a data migration, not an index.
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from pymongo import GEOSPHERE
        await db.customers.create_index(
            [("service_location", GEOSPHERE)],
            name="cust_service_location_2dsphere",
            sparse=True,
        )
    except Exception as e:
        logger.warning(f"[phase17] service_location 2dsphere index crashed: {e}")
    try:
        from routers.dispatch_board import geocode_backfill_all_tenants_boot
        asyncio.create_task(geocode_backfill_all_tenants_boot())
        logger.info("[phase17] geocode backfill scheduled (fire-and-forget)")
    except Exception as e:
        logger.warning(f"[phase17] geocode backfill schedule crashed: {e}")

    # Feb-2026 · Item 4 — seed the aquaterra AI company profile on
    # first boot so admins have something to edit rather than an empty
    # brain. Idempotent: skips if a company_profile row already exists.
    try:
        import uuid as _uuid_p18
        from utils import now_iso as _now_iso_p18
        aq = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        if aq:
            # Phase 34 · Task AA · Feb 2026 — PLOFV referral reward.
            # Idempotent seed so PLOFV mints $55 credit for every
            # referral going forward. Historical credits are NOT
            # retroactively adjusted (they live in ``service_credits``
            # with their original ``amount_cents``). We stamp both
            # the legacy top-level field the referral_watcher reads
            # AND the new nested ``settings.referrals.reward_amount_cents``
            # location for future normalisation.
            try:
                await db.tenants.update_one(
                    {"id": aq["id"]},
                    {"$set": {
                        "referral_reward_amount_cents": 5500,
                        "settings.referrals.reward_amount_cents": 5500,
                    }},
                )
            except Exception as _e_reward:
                logger.warning(f"[phase34-task-aa] PLOFV reward seed failed: {_e_reward}")

            has_profile = await db.ai_knowledge_base.find_one(
                {"tenant_id": aq["id"], "kind": "company_profile",
                  "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
                {"_id": 0},
            )
            if not has_profile:
                await db.ai_knowledge_base.insert_one({
                    "id": str(_uuid_p18.uuid4()), "tenant_id": aq["id"],
                    "kind": "company_profile",
                    "title": "Pool & Landscaping of Vistancia — Company Profile",
                    "content_md": (
                        "# Pool & Landscaping of Vistancia\n\n"
                        "We service the greater Peoria & Vistancia, Arizona area.\n\n"
                        "**Services:** recurring pool maintenance, salt cell + filter cleaning, "
                        "one-off repairs, landscaping crews.\n\n"
                        "**Brand voice:** friendly, direct, no fluff. Never quote prices without "
                        "admin approval. Techs never see prices.\n\n"
                        "**Escalation:** for billing questions route to admin; for scheduling "
                        "changes offer earliest available."
                    ),
                    "tags": ["seed"], "is_active": True,
                    "created_by": "system", "created_at": _now_iso_p18(),
                    "updated_at": _now_iso_p18(),
                })
                logger.info("[item4] seeded aquaterra ai_knowledge_base company_profile")
    except Exception as exc:
        logger.warning(f"[item4] ai_knowledge_base seed crashed: {exc}")

    # Phase 16 · Feb 2026 — seed 3 default customer categories per
    # tenant (Pool / Landscaping / Both, all is_system=True) and
    # backfill customer.category_ids / service_days / assigned_tech_ids
    # so mass-messaging filters work on an existing dataset. Both
    # calls are idempotent — safe to run on every restart.
    try:
        from routers.customer_categories import (
            seed_default_categories_for_all_tenants,
            recompute_customer_denorm,
        )
        _p16_seeded = await seed_default_categories_for_all_tenants()
        logger.info(
            f"[phase16] customer_categories seeded {_p16_seeded} default row(s)"
        )
        async for _t in db.tenants.find({}, {"_id": 0, "id": 1}):
            try:
                _n = await recompute_customer_denorm(_t["id"])
                if _n:
                    logger.info(
                        f"[phase16] customer denorm updated {_n} for tenant={_t['id']}"
                    )
            except Exception as _e:  # pragma: no cover
                logger.warning(
                    f"[phase16] denorm crashed for tenant={_t.get('id')}: {_e}"
                )
    except Exception as e:
        logger.warning(f"[phase16] customer_categories boot crashed: {e}")

    # Phase 12 · Feb 2026 — "Require card on file" tenant default +
    # idempotent template seed for the ``add_card_request_*`` bodies.
    try:
        from services.add_card_links import (
            ensure_require_card_default_on_tenants,
            ensure_tenants_timezone_backfill,
            seed_add_card_templates_all_tenants,
        )
        _p12_n = await ensure_require_card_default_on_tenants()
        logger.info(
            f"[phase12] require_card_on_file_default set on {_p12_n} tenant(s)"
        )
        _p12_seeded = await seed_add_card_templates_all_tenants()
        logger.info(
            f"[phase12] add_card_request_* templates seed — {_p12_seeded}"
        )
        # Batch 12C · Feb 2026 — timezone audit + backfill.
        await ensure_tenants_timezone_backfill()
    except Exception as e:
        logger.warning(f"[phase12] boot migration crashed: {e}")

    # Phase 4B — Stripe live-payments boot inspection.
    # Not run at boot; the on-demand health probe at
    # ``/api/settings/integrations/health/stripe`` covers this
    # cheaply and reflects the current STRIPE_MODE + key state.

    # Phase 6 · Feb 2026 — RingCentral banner + subscription index.
    try:
        from services.ringcentral.rc_client import log_startup_banner
        log_startup_banner()
        # Phase 9C · Feb 2026 — one-shot idempotent QuickBooks cleanup.
        try:
            from routers.quickbooks_cleanup import run_migration as _qb_migrate
            await _qb_migrate()
        except Exception as _qb_exc:
            logger.warning(f"[startup] qb-cleanup migration failed: {_qb_exc}")
    except Exception as e:
        logger.warning(f"[phase6] rc boot banner/migration crashed: {e}")

    # Feb-2026 · D2 — split off the inline call_logs / voicemails /
    # rc_subscriptions indexes so they can be gated independently
    # of the banner + qb migration.  Skipped in prod (ops runs
    # scripts.ensure_indexes).
    try:
        if not _RUN_STARTUP_INDEXES:
            raise RuntimeError("startup indexes disabled — run scripts.ensure_indexes")
        from pymongo import ASCENDING as _A, DESCENDING as _D
        await db.call_logs.create_index(
            [("tenant_id", _A), ("session_id", _A)],
            unique=True,
            partialFilterExpression={"session_id": {"$exists": True, "$type": "string"}},
            name="uniq_call_log_session",
        )
        await db.call_logs.create_index([("tenant_id", _A), ("from_number", _A),
                                            ("started_at", _D)],
                                          name="calls_by_from")
        await db.call_logs.create_index([("tenant_id", _A), ("to_number", _A),
                                            ("started_at", _D)],
                                          name="calls_by_to")
        await db.voicemails.create_index([("tenant_id", _A), ("message_id", _A)],
                                            unique=True, name="uniq_vm")
        await db.ringcentral_subscriptions.create_index(
            [("tenant_id", _A), ("subscription_id", _A)],
            unique=True, name="uniq_rc_sub",
        )
    except Exception as e:
        logger.warning(f"[phase6] rc index create crashed: {e}")

    # Phase 56.3.A — idempotent one-shot: back-fill first_name / last_name
    # on any legacy customer doc that only has the combined `name` field.
    try:
        from routers.customers import migrate_customer_names_split
        migrated_n = await migrate_customer_names_split()
        logger.info(f"[phase56.3.A] customer name-split migration: {migrated_n} row(s)")
    except Exception as e:
        logger.warning(f"customer name-split migration crashed: {e}")

    # Feb 2026 · Job Titles auto-learn catalog — idempotent backfill
    # from existing ``db.jobs.title`` distincts per tenant. Guarded
    # by a ``db.migrations`` sentinel so second-and-later boots are
    # ~10ms no-ops. See ``routers/job_titles.py`` for the shape.
    try:
        from routers.job_titles import backfill_from_existing_jobs
        _jt_report = await backfill_from_existing_jobs()
        logger.info(f"[job_titles] backfill: {_jt_report}")
    except Exception as e:
        logger.warning(f"job_titles backfill crashed: {e}")

    # Feb 2026 · Technician-name backfill — stamps ``technician_name``
    # on every job that has a ``technician_id`` but no
    # ``technician_name`` (jobs stamped before the write-side denorm
    # fix landed). Idempotent — guarded by a ``db.migrations``
    # sentinel. See
    # ``services/migrations/backfill_technician_names.py``.
    try:
        from services.migrations.backfill_technician_names import (
            backfill_technician_names_on_jobs,
        )
        _tb_report = await backfill_technician_names_on_jobs()
        logger.info(f"[tech-backfill] {_tb_report}")
    except Exception as e:
        logger.warning(f"technician_name backfill crashed: {e}")

    # Feb 2026 · Marketing Phase 1 · Custom Trigger Builder — one-shot
    # (idempotent) schema-v2 trigger migration. Rewrites every legacy
    # ``trigger_type`` scalar into the v2 nested ``trigger`` doc
    # with a single AND/immediate/no-filter condition and stamps
    # ``schema_version=2``. Legacy fields are PRESERVED so the M5c
    # fanout keeps functioning during the migration window. Second-
    # and-later boots are ~O(N) reads with zero writes (per-doc
    # ``schema_version`` gate).
    try:
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        _v2_report = await migrate_marketing_sequences_to_v2()
        logger.info(f"[marketing.v2] {_v2_report}")
    except Exception as e:
        logger.warning(f"marketing_sequences v2 migration crashed: {e}")

    # Feb 2026 · Object-Storage URL migration — idempotent, sentinel-
    # guarded rewrite of any DB record still pointing at pod-local
    # ``/uploads/*`` or bare ``/objects/*`` URLs. Uploads surviving
    # pod-local files to Emergent Object Storage and rewrites the DB
    # URL to the canonical ``/api/objects/{path}`` shape served by
    # ``routers/objects.py``. See
    # ``services/migrations/object_storage_url_migration.py``.
    try:
        from services.migrations.object_storage_url_migration import (
            migrate_object_storage_urls,
        )
        _obj_report = await migrate_object_storage_urls()
        logger.info(f"[url_migration] {_obj_report}")
    except Exception as e:
        logger.warning(f"object_storage url migration crashed: {e}")

    # Feb 2026 · Persona avatar_url backfill — idempotent, sentinel-
    # guarded stamp of ``/avatars/personas/{key}.jpg`` on every
    # ai_employees doc whose ``key`` is one of the 10 canonical
    # admin personas (the "Pixar portraits" shipped as static
    # frontend assets). Ensures a fresh prod redeploy renders every
    # persona's portrait without an admin touching the database.
    # See ``services/migrations/persona_avatar_backfill.py``.
    try:
        from services.migrations.persona_avatar_backfill import (
            backfill_persona_avatar_urls,
        )
        _pa_report = await backfill_persona_avatar_urls()
        logger.info(f"[persona-avatar] {_pa_report}")
    except Exception as e:
        logger.warning(f"persona avatar backfill crashed: {e}")

    # Feb 2026 · Task B — seed 3 canonical system-template sequences
    # (invoice past-due, review request, birthday promo) on every
    # active tenant. Idempotent per tenant via ``system_template_id``;
    # sentinel-guarded at the boot level. New tenants created after
    # this fires get their templates via the ``routers/tenants.py``
    # provisioning hook. See
    # ``services/migrations/seed_system_templates.py``.
    try:
        from services.migrations.seed_system_templates import (
            seed_system_templates_all_tenants,
        )
        _stpl_report = await seed_system_templates_all_tenants()
        logger.info(f"[seed_system_templates] {_stpl_report}")
    except Exception as e:
        logger.warning(f"seed_system_templates migration crashed: {e}")

    # Feb-2026 Customer Detail Additions — idempotent one-shot back-fill
    # of the ``mobiles`` / ``emails`` arrays from the legacy scalar
    # ``phone`` / ``email`` fields. Skipped for docs that already have
    # the arrays.
    try:
        from services.customer_multi_contact import migrate_customer_multi_contact
        n = await migrate_customer_multi_contact()
        logger.info(f"[multi-contact] migration: {n} row(s)")
    except Exception as e:
        logger.warning(f"multi-contact migration crashed: {e}")

    # Feb 2026 · Customer Merge Phase 3 — one-time boot cleanup of any
    # pre-existing high-confidence duplicate clusters (exact email OR
    # exact phone). Idempotent via ``migrations`` sentinel
    # ``feb2026_customer_merge_boot_cleanup_v1``. Second boot = no-op.
    # See ``services/migrations/customer_merge_boot_cleanup.py``.
    try:
        from services.migrations.customer_merge_boot_cleanup import (
            run_customer_merge_boot_cleanup,
        )
        _cm_boot = await run_customer_merge_boot_cleanup()
        if _cm_boot.get("already_ran"):
            logger.info(
                f"[customer_merge_boot] sentinel present · ran_at="
                f"{_cm_boot.get('ran_at')} · skipping",
            )
        else:
            _s = _cm_boot.get("summary") or {}
            logger.info(
                f"[customer_merge_boot] scanned {_s.get('tenants_scanned', 0)} "
                f"tenants, auto-merged {_s.get('groups_auto_merged', 0)} "
                f"groups, affected {_s.get('records_affected', 0)} records",
            )
    except Exception as e:
        logger.warning(f"customer_merge_boot cleanup crashed: {e}")

    # Feb 2026 · Invoice/Quote line cost snapshot backfill. Rehydrates
    # ``wholesale_price_snapshot`` + ``labor_cost_snapshot`` on
    # existing line items from the tenant pricebook when they are
    # 0/null but the pricebook carries a real cost. Idempotent via
    # sentinel ``feb2026_invoice_line_cost_backfill_v1``. Also links
    # lines missing ``item_id`` by exact name match against the
    # pricebook. Fixes the Internal Margin / EBIT / Profit report
    # panels reading $0 costs on legacy invoices.
    try:
        from services.migrations.invoice_line_cost_backfill import (
            run_invoice_line_cost_backfill,
        )
        _lc_boot = await run_invoice_line_cost_backfill()
        if _lc_boot.get("already_ran"):
            logger.info(
                f"[invoice_line_cost_backfill] sentinel present · ran_at="
                f"{_lc_boot.get('ran_at')} · skipping",
            )
        else:
            _s = _lc_boot.get("summary") or {}
            logger.info(
                f"[invoice_line_cost_backfill] tenants={_s.get('tenants_scanned', 0)} "
                f"docs_scanned={_s.get('docs_scanned', 0)} "
                f"docs_updated={_s.get('docs_updated', 0)} "
                f"ws_hydrated={_s.get('lines_hydrated_ws', 0)} "
                f"lc_hydrated={_s.get('lines_hydrated_lc', 0)} "
                f"linked_by_name={_s.get('lines_linked_by_name', 0)}",
            )
    except Exception as e:
        logger.warning(f"invoice_line_cost_backfill crashed: {e}")

    # Feb-2026 · P0 fix — Invoice number backfill. Heals invoice
    # docs persisted with a null / missing / empty
    # ``invoice_number`` field so operators never see "Invoice #: -"
    # on the invoices list. Idempotent + sentinel-guarded
    # (``feb2026_invoice_number_backfill_v1``); a subsequent boot
    # is a no-op unless the sentinel is cleared. Ships alongside
    # the canonical ``insert_invoice`` helper that plugged the
    # three write paths feeding the bug.
    try:
        from services.migrations.invoice_number_backfill import (
            run_invoice_number_backfill,
        )
        _inv_num_boot = await run_invoice_number_backfill()
        if _inv_num_boot.get("status") == "skipped":
            logger.info(
                "[invoice_number_backfill] sentinel present · skipping",
            )
        else:
            _s = _inv_num_boot.get("summary") or {}
            logger.info(
                f"[invoice_number_backfill] scanned={_s.get('scanned', 0)} "
                f"updated={_s.get('updated', 0)} "
                f"skipped={_s.get('skipped', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(f"invoice_number_backfill crashed: {e}")

    # Feb-2026 · Multi-body service reports — Phase 1 migration.
    # Populates ``water_bodies[0]`` on legacy service_report docs from
    # the top-level ``chemical_readings`` / ``chemicals_added`` /
    # ``photos`` / ``notes`` fields. Idempotent + sentinel-guarded
    # (``feb2026_service_reports_water_bodies_v1``). Runs after the
    # invoice-number backfill so all service reports are body-shaped
    # before the first request lands.
    try:
        from services.migrations.service_reports_water_bodies import (
            run_water_bodies_migration,
        )
        _wb_boot = await run_water_bodies_migration()
        if _wb_boot.get("status") == "skipped":
            logger.info(
                "[service_reports.water_bodies] sentinel present · skipping",
            )
        else:
            _s = _wb_boot.get("summary") or {}
            logger.info(
                f"[service_reports.water_bodies] scanned={_s.get('scanned', 0)} "
                f"migrated={_s.get('migrated', 0)} "
                f"skipped_already_multi={_s.get('skipped_already_multi', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(f"service_reports water_bodies migration crashed: {e}")

    # Feb-2026 · Multi-body Phase 1 · Option 2 — chemical_usage_events
    # water-body backfill. Adds ``water_body_id`` (nullable) to every
    # legacy usage event. MUST run AFTER the
    # ``service_reports_water_bodies`` migration above so per-body
    # linking can consult the bodies array. Idempotent + sentinel
    # (``chemical_usage_events_water_body_v1``).
    try:
        from services.migrations.chemical_usage_events_water_body import (
            run_chemical_usage_events_water_body_migration,
        )
        _cue_boot = await run_chemical_usage_events_water_body_migration()
        if _cue_boot.get("status") == "skipped":
            logger.info(
                "[chemical_usage_events.water_body] sentinel present · skipping",
            )
        else:
            _s = _cue_boot.get("summary") or {}
            logger.info(
                f"[chemical_usage_events.water_body] scanned={_s.get('scanned', 0)} "
                f"linked_to_body={_s.get('linked_to_body', 0)} "
                f"stamped_null={_s.get('stamped_null', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(
            f"chemical_usage_events water_body migration crashed: {e}",
        )

    # Feb-2026 · Backlog #1 Part 2 — Canonical "Chemicals" service
    # category. Idempotent + sentinel (``service_category_chemicals_v1``).
    # Ensures every onboarded tenant has a "Chemicals"
    # ``service_categories`` row and backfills every chemical
    # pricebook item (``items.category ~ /^chemical/i``) whose
    # ``service_category_id`` is null → linked to the tenant's
    # Chemicals category. Auto-invoice line-items inherit
    # ``service_category_id`` from the source pricebook item so the
    # "Income by Service Category" tile can aggregate correctly.
    try:
        from services.migrations.service_category_chemicals import (
            run_service_category_chemicals_migration,
        )
        _sc_boot = await run_service_category_chemicals_migration()
        if _sc_boot.get("status") == "skipped":
            logger.info(
                "[service_category_chemicals] sentinel present · skipping",
            )
        else:
            _s = _sc_boot.get("summary") or {}
            logger.info(
                f"[service_category_chemicals] tenants={_s.get('scanned_tenants', 0)} "
                f"created={_s.get('created_categories', 0)} "
                f"linked={_s.get('linked_items', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(
            f"service_category_chemicals migration crashed: {e}",
        )

    # Feb-2026 · Backlog #1 Tightening T1 — historical invoice
    # line_items with a UUID-shaped ``category`` string get rewritten
    # in-place: resolvable id → name (+ stamp
    # ``income_category_id``); unresolvable → clear to ``""`` so the
    # tile's Uncategorized fallback picks them up. Idempotent +
    # sentinel (``revenue_line_items_uuid_category_v1``). MUST run
    # AFTER ``service_category_chemicals`` above so the income
    # categories collection is fully seeded before resolution.
    try:
        from services.migrations.revenue_line_items_uuid_category import (
            run_revenue_line_items_uuid_category_migration,
        )
        _rl_boot = await run_revenue_line_items_uuid_category_migration()
        if _rl_boot.get("status") == "skipped":
            logger.info(
                "[revenue_line_items_uuid_category] sentinel present · skipping",
            )
        else:
            _s = _rl_boot.get("summary") or {}
            logger.info(
                f"[revenue_line_items_uuid_category] scanned={_s.get('scanned', 0)} "
                f"rewritten_to_name={_s.get('rewritten_to_name', 0)} "
                f"cleared_orphan={_s.get('cleared_orphan', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(
            f"revenue_line_items_uuid_category migration crashed: {e}",
        )

    # Backlog #iii · Feb-2026 — Pricebook multi-supplier fold-up.
    # Sentinel: ``pricebook_suppliers_v1``. Folds legacy scalar
    # ``wholesale_price`` + compact ``supplier_prices[]`` +
    # ``supplier_slug``/``external_sku`` into the new rich
    # ``items.suppliers[]`` list and regenerates the two compat
    # mirrors. Runs after the two Backlog-#1 migrations so income /
    # service categories are fully seeded before the fold-up needs
    # to resolve supplier display names. Idempotent + sentinel-guarded.
    try:
        from services.migrations.pricebook_suppliers import (
            run_pricebook_suppliers_migration,
        )
        _ps_boot = await run_pricebook_suppliers_migration()
        if _ps_boot.get("status") == "skipped":
            logger.info(
                "[pricebook_suppliers] sentinel present · skipping",
            )
        else:
            _s = _ps_boot.get("summary") or {}
            logger.info(
                f"[pricebook_suppliers] tenants={_s.get('tenants_scanned', 0)} "
                f"scanned={_s.get('scanned_items', 0)} "
                f"updated={_s.get('updated_items', 0)} "
                f"skipped={_s.get('skipped_no_change', 0)} "
                f"errors={_s.get('errors_count', 0)}",
            )
    except Exception as e:
        logger.warning(f"pricebook_suppliers migration crashed: {e}")

    # Backlog #iv · Feb-2026 — Notification dispatch log + scheduler
    # leases.  Creates ``notification_dispatch_log`` with the compound
    # unique index that makes the ``guard_and_log`` insert-then-send
    # pattern race-safe, plus the ``scheduler_leases`` collection
    # with TTL index used by
    # ``services/comms_hardening/scheduler_lease.py``.
    # Sentinel: ``notification_dispatch_log_v1``.  Idempotent.
    try:
        from services.migrations.notification_dispatch_log import (
            run_notification_dispatch_log_migration,
        )
        _ndl_boot = await run_notification_dispatch_log_migration()
        if _ndl_boot.get("status") == "skipped":
            logger.info(
                "[notification_dispatch_log] sentinel present · skipping",
            )
        else:
            _s = _ndl_boot.get("summary") or {}
            logger.info(
                f"[notification_dispatch_log] indexes_created="
                f"{_s.get('indexes_created', 0)} "
                f"already_present={_s.get('already_present', 0)} "
                f"errors={len(_s.get('errors') or [])}",
            )
    except Exception as e:
        logger.warning(f"notification_dispatch_log migration crashed: {e}")

    # Backlog #iv · R1 · Feb-2026 — Allowlist-hygiene sanity check.
    # Emits a WARN log per overlap between ``COMMS_TEST_ALLOWLIST_*``
    # and live workforce / tenant / from-number addresses.  Log-only
    # — never blocks startup.  This surfaces the exact config smell
    # documented in the audit for Bug 2 (``+16028874400`` is both a
    # tenant from-number AND in the DRY-RUN allowlist).
    try:
        from services.comms_hardening.deny_list import (
            allowlist_overlap_check,
        )
        _ah_res = await allowlist_overlap_check()
        if _ah_res.get("overlaps"):
            logger.warning(
                "[notifications] allowlist_overlap_check surfaced %s "
                "overlap(s) between COMMS_TEST_ALLOWLIST_* and live "
                "workforce/tenant addresses — see WARN lines above.",
                _ah_res["overlaps"],
            )
        else:
            logger.info(
                "[notifications] allowlist_overlap_check clean · "
                "checked_phones=%s checked_emails=%s",
                _ah_res.get("checked_phones", 0),
                _ah_res.get("checked_emails", 0),
            )
    except Exception as e:
        logger.warning(f"allowlist_overlap_check crashed: {e}")

    # Feb-2026 · P0 fix — Orphan-paid invoice audit. Report-only on
    # boot so operators see the count in logs without silently
    # flipping seed / demo fixtures. Real flips happen through the
    # super_admin admin endpoint
    # (``POST /api/admin/migrations/audit-orphan-paid-invoices``)
    # after the operator reviews the dry-run diff.
    try:
        from services.migrations.invoice_status_audit import (
            run_orphan_paid_audit,
        )
        _op_boot = await run_orphan_paid_audit(force=True, dry_run=True)
        _s = _op_boot.get("summary") or {}
        if _s.get("corrected", 0) > 0:
            logger.warning(
                f"[orphan_paid_audit] boot report · "
                f"{_s.get('corrected', 0)} invoices flagged as "
                f"paid without a payment_record. Trigger "
                f"POST /api/admin/migrations/audit-orphan-paid-invoices"
                f"?dry_run=false to flip them to pending_reconciliation.",
            )
        else:
            logger.info("[orphan_paid_audit] boot report · 0 orphans")
    except Exception as e:
        logger.warning(f"orphan_paid_audit boot report crashed: {e}")

    # Feb-2026 M2 fix — idempotent single-brace → double-brace migration
    # on stored campaign templates. The render engine now accepts both
    # shapes; this migration just normalises DB snapshots so admins
    # editing an M2 template see the canonical form.
    # reading the raw doc see the canonical form.
    try:
        from services.marketing_campaigns import migrate_campaign_templates_to_double_brace
        n = await migrate_campaign_templates_to_double_brace()
        logger.info(f"[m2] template brace migration: {n} campaign(s)")
    except Exception as e:
        logger.warning(f"m2 brace migration crashed: {e}")

    # Feb-2026 MP1 — Multi-property seed. Idempotent per-customer:
    # inserts a single "Main" property for every legacy customer that
    # has an address but no property rows yet. Also backfills jobs
    # with a null ``property_id`` onto that new row when only 1 property
    # exists (safe auto-assign).
    try:
        from routers.properties import migrate_customers_to_properties
        n = await migrate_customers_to_properties()
        logger.info(f"[mp1] properties migration seeded {n} property row(s)")
    except Exception as e:
        logger.warning(f"mp1 properties migration crashed: {e}")

    # Feb-2026 MP1.5 — Multi-property invoice plumbing. Idempotent:
    # backfills ``property_id`` on legacy invoices/estimates whose
    # linked jobs already carry a property. Skipped silently when a
    # doc's jobs span multiple properties (admin can consolidate
    # manually via POST /api/invoices/consolidate).
    try:
        from routers.invoices_mp15 import migrate_invoices_estimates_property_id
        counts = await migrate_invoices_estimates_property_id()
        logger.info(
            f"[mp1.5] invoice/estimate property_id backfill — {counts}"
        )
    except Exception as e:
        logger.warning(f"mp1.5 backfill migration crashed: {e}")

    # Feb-2026 AE1 — AI Employees roster seed. Idempotent per tenant:
    # inserts the 8 default employees (Casey, Emmie, Buddy, Vizzy,
    # Dexter, Soshie, Scouty, Commet) on any tenant that doesn't have
    # them yet. Admin edits (rename, custom system prompt, disable)
    # survive re-runs.
    try:
        from routers.ai_employees import seed_ai_employees_all_tenants
        counts = await seed_ai_employees_all_tenants()
        logger.info(f"[ae1] ai_employees seed — {counts}")
    except Exception as e:
        logger.warning(f"ae1 ai_employees seed crashed: {e}")

    # Phase 34 · Task JJ · Feb 2026 — AI Employees dedupe + unique
    # index. Removes legacy null-tenant rows that leaked into every
    # tenant's admin AI Hub via ``GET /ai-ops/employees`` (see
    # ``migrations/task_jj_dedupe_ai_employees.py`` for full RCA).
    try:
        from migrations.task_jj_dedupe_ai_employees import dedupe_ai_employees
        _jj = await dedupe_ai_employees()
        logger.info(f"[phase34-task-jj] {_jj}")
    except Exception as e:
        logger.warning(f"[phase34-task-jj] dedupe migration crashed: {e}")

    # Phase 34 · Task CC · Feb 2026 — Leads status enum migration.
    # Idempotent boot-time sweep that normalises every ``leads.status``
    # value to the five canonical snake_case buckets
    # (new, contacted, quoted, closed_won, closed_lost). Unrecognised
    # legacy values are mapped to ``"new"`` and each occurrence is
    # logged so an admin can audit them from the boot log.
    try:
        from routers.leads import migrate_lead_statuses as _mig_lead_status
        _lead_status_result = await _mig_lead_status()
        logger.info(f"[phase34-task-cc] lead status migration — {_lead_status_result['per_bucket']}")
    except Exception as e:
        logger.warning(f"[phase34-task-cc] lead status migration crashed: {e}")


    # Feb-2026 · Slice L.c — ensure the widget_denied_requests TTL +
    # tenant-time indexes exist. Idempotent; failures are logged.
    try:
        from routers.widget_config import _ensure_denied_indexes
        await _ensure_denied_indexes()
        logger.info("[l.c] widget_denied_requests indexes ensured")
    except Exception as e:
        logger.warning(f"[l.c] denied indexes failed: {e}")

    # Feb-2026 · Marketing Slice M3 — seed 12 starter email + SMS
    # templates for any tenant that has zero templates today. Admin
    # edits + custom templates survive re-runs (seed only fires when
    # the tenant is empty).
    try:
        from routers.marketing_templates import seed_marketing_templates_all_tenants
        counts = await seed_marketing_templates_all_tenants()
        logger.info(f"[m3] marketing_templates seed — {counts}")
    except Exception as e:
        logger.warning(f"m3 marketing_templates seed crashed: {e}")

    # Feb-2026 · Marketing Slice M4 — seed 4 default segments per tenant.
    try:
        from routers.marketing_segments import seed_segments_all_tenants
        counts = await seed_segments_all_tenants()
        logger.info(f"[m4] marketing_segments seed — {counts}")
    except Exception as e:
        logger.warning(f"m4 marketing_segments seed crashed: {e}")

    # Feb-2026 · Marketing Slice M5a — seed system drip sequences that
    # reference the M3-seeded system templates. Idempotent per tenant.
    try:
        from routers.marketing_sequences import seed_sequences_all_tenants
        counts = await seed_sequences_all_tenants()
        logger.info(f"[m5] marketing_sequences seed — {counts}")
    except Exception as e:
        logger.warning(f"m5 marketing_sequences seed crashed: {e}")

    # Feb-2026 · Slice GH0 post-fix — seed the dev preview host onto the
    # aquaterra tenant's widget_allowed_domains so the widget bundle
    # served from poolscape-audit.preview.emergentagent.com (and the
    # ingress-rewritten cluster host) works immediately.
    # GH-Fix v2: unified in routers.widget_config.seed_dev_widget_domains_for_aquaterra
    # so the sync-boot, background-seed, and scheduler-tick hooks all
    # apply the SAME multi-host seed and can be re-run at any time.
    try:
        from routers.widget_config import seed_dev_widget_domains_for_aquaterra
        result = await seed_dev_widget_domains_for_aquaterra()
        logger.info(f"[gh0-seed] sync-boot: {result}")
    except Exception as e:
        logger.warning(f"gh0 dev-domain sync seed crashed: {e}")

    # Feb-2026 · Slice H1 — Turnstile status log (single WARN when the
    # TURNSTILE_SECRET env var is missing so ops know form submissions
    # are being accepted without verification).
    try:
        from routers.marketing_forms import log_turnstile_status_once
        log_turnstile_status_once()
    except Exception as e:
        logger.warning(f"turnstile status log crashed: {e}")

    # Phase 5A · Video Uploads (Feb 2026) — init Emergent object storage
    # session key once at startup. Never crashes the boot: on failure the
    # upload endpoints return 503 with a clear error.
    try:
        from services import object_storage as _obj_store
        _obj_store.init_storage()
        logger.info(
            f"[object_storage] init complete — ready={_obj_store.is_ready()}"
        )
    except Exception as e:
        logger.warning(f"object_storage init crashed: {e}")

    async def _defer():
        try:
            await asyncio.sleep(2)
            await _background_seed()
        except Exception as e:
            logger.warning(f"background seed task crashed: {e}")

    asyncio.create_task(_defer())
    logger.info("Boot path complete — API is now accepting requests.")


@app.get("/api/health/seeds")
async def health_seeds():
    """Cold-start progress indicator. Anyone can poll this."""
    return {
        "complete": bool(SEEDS_COMPLETE),
        "phase": SEEDS_PHASE,
        "started_at": SEEDS_STARTED_AT,
        "completed_at": SEEDS_COMPLETED_AT,
    }


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    client.close()
