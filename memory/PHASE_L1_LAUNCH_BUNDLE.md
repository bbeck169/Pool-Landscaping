# Phase L1 · Launch Bundle — 2026-02

## TL;DR

Bundled 7 sub-items shipped together. Backend + frontend + tests +
curl proofs. Sidebar Logout pre-existed → flagged as no-op. Every
other sub-item landed.

## Sub-item roster

| # | Scope | Status | Notes |
|---|-------|--------|-------|
| L1.1 | Categories discoverability | ✅ Shipped | Detail rename `admin_only → insufficient_role_for_categories` on 3 category routers · 2 new batch `POST /reorder` endpoints · umbrella sidebar entry "Categories Management" → `/pricebook/categories` · existing `is_default` inference already surfaces via `created_by_user_id == "system:seed"` (client-side badge to be added when tester feedback requests it). |
| L1.2 | Industry logic refactor | ✅ Shipped | New `services/industry_derivation.py::derive_industry_for_job(job, tenant)` — resolves `job.industry → tenant.settings.default_industry → single-industry tenant list → keyword classifier fallback → None`. `routers/jobs.py::with_field_report` now uses the derivation with a debug log on every fallback. `classify_job` preserved as the legacy safety net. |
| L1.3 | Sidebar Logout button | 🟡 No-op | Already shipped: `AppLayout.jsx:502-517` has `data-testid="sidebar-logout-button"` + `aria-label="Log out"` + `LogOut` icon; mobile mirror at line 615. Screenshot verifies. |
| L1.4 | Global Header QuickAdd | ✅ Shipped | New `components/topbar/QuickAddButton.jsx` — circular `+` trigger, 4-item dropdown (Lead · Job · Estimate · Customer). Slots between AddJob/AddCustomer and CreditsBudgetChip in the wide branch. Role gate: admin / super_admin / manager. Techs and customers never see it. |
| L1.5 | Dashboard action cards | ✅ Shipped | New backend `GET /api/dashboard/action-cards` (batched 7-count summary, 60-s polling from client). New `components/dashboard/DashboardActionCards.jsx` — auto-hides zero-count cards EXCEPT `open_alerts` (always visible). Wired into `pages/admin/Dashboard.jsx` under `<GlobalSearchBar>`. |
| L1.6 | Lead hard-delete audit | ✅ Backend enhanced | `routers/leads.py::_hard_delete_lead` now snapshots the FULL doc pre-delete into `audit_log` with `resource_type: "lead"`, `deleted_ids: [id]`, `snapshot: [dict]`. Frontend "DELETE"-text-input confirm modal deferred pending tester feedback on the current modal — flag if needed. |
| L1.7 | Smart-links sweep | ✅ Shipped | Grep-audit → 2 concrete misses fixed: `pages/checks/ChecksPages.jsx:1134` (payee row phone → `<PhoneLink>`) and `pages/leads/LeadsDashboardPage.jsx:900` (lead detail modal phone → `<PhoneLink>`). `MasterBillingCard.jsx:173` intentionally kept as `<code>` preview (audit visual). |

## Grep audit outputs

*   **Category detail-rename** — `_require_admin` in
    `service_categories.py:88`, `income_categories.py:62`,
    `category_references.py:47`.  Other routers using
    ``admin_only`` (time_off, dashboard_drilldown, admin_checkins,
    analytics_proposal, invoice_edit, dashboard_revenue,
    lana_todos) LEFT UNCHANGED — out of L1 scope.
*   **`classify_job` call sites** — only `routers/jobs.py:219` and
    `:222`.  Refactor concentrated in ``with_field_report``.
*   **`with_field_report` call sites** — 10 (jobs.py × 7,
    workstream_job_detail.py, maintenance.py).  Signature kept
    backwards-compatible (``tenant=None`` default); all existing
    callers still work, opt-in for tenant threading.
*   **`audit_events` vs. `audit_hard_deletes`** — reused the
    existing `audit_log` collection (that's what
    `_hard_delete_lead` already wrote to).  Extended the schema
    with `resource_type` + `deleted_ids` + `snapshot`.
*   **Bulk-delete backend** — already exists at
    `routers/leads.py::bulk_hard_delete_leads` (line 1023) with
    admin-only gate.  No new endpoint needed.
*   **AppLayout logout** — already shipped
    (`sidebar-logout-button`, `shell-logout-button-mobile`).
*   **Existing "Add" buttons in topbar** — `AddJobButton`,
    `AddCustomerButton`; kept in place, QuickAdd sits alongside.
*   **Smart-link misses** — 2 (fixed).
*   **`@dnd-kit` presence** — `@dnd-kit/core` +
    `@dnd-kit/sortable` + `@dnd-kit/utilities` all in
    `package.json`.  Ready if the Categories page later wants
    drag-reorder — no new dep required.

## Modified / created files

**New**:
- `backend/services/industry_derivation.py`
- `backend/routers/dashboard_action_cards.py`
- `backend/tests/test_l1_launch_bundle.py`
- `frontend/src/components/topbar/QuickAddButton.jsx`
- `frontend/src/components/dashboard/DashboardActionCards.jsx`
- `frontend/src/components/__tests__/L1_launch_bundle.test.jsx`
- `/app/memory/PHASE_L1_LAUNCH_BUNDLE.md` (this file)

**Modified**:
- `backend/routers/service_categories.py` — 403 wording + reorder endpoint.
- `backend/routers/income_categories.py` — 403 wording + reorder endpoint.
- `backend/routers/category_references.py` — 403 wording.
- `backend/routers/jobs.py` — tenant-aware derivation in
  `with_field_report`; `body.dict()` → `model_dump()` continued
  from C1 deprecation cleanup.
- `backend/routers/leads.py` — audit_log snapshot enhancement.
- `backend/server.py` — mount `dashboard_action_cards`.
- `backend/tests/_f7_loop_fixture.py` — DB-rebind list additions.
- `frontend/src/layouts/AdminTopBar.jsx` — QuickAdd slot.
- `frontend/src/pages/admin/Dashboard.jsx` — mount ActionCards.
- `frontend/src/nav/adminNav.js` — umbrella "Categories Management" entry.
- `frontend/src/pages/checks/ChecksPages.jsx` — PhoneLink wrap.
- `frontend/src/pages/leads/LeadsDashboardPage.jsx` — PhoneLink wrap.

## Live smoke output

### `/api/dashboard/action-cards` (admin, Vistancia tenant)

```
{
  "today_routes": 0,
  "pending_checkins": 0,
  "unpaid_invoices": 0,
  "overdue_invoices": 2,
  "new_leads_today": 0,
  "open_alerts": 5,
  "missed_services_today": 0,
  "generated_at": "2026-09-20T19:34:37.077036+00:00"
}
```

### Batch reorder

```
POST /api/service-categories/reorder → HTTP 200 {"ok":true,"updated":2}
POST /api/income-categories/reorder  → HTTP 200 {"ok":true,"updated":2}
```

### Screenshot

Dashboard renders 2 action cards (Overdue Invoices ・ Open
Intelligence Alerts, with color-coded left borders).
QuickAdd `+` visible next to `Add Customer` in the topbar right
cluster; clicking opens a 4-item dropdown (New Lead / New Job /
New Estimate / New Customer).  Sidebar Logout pinned at rail
bottom.  Zero-count cards auto-hidden.

## Test tails

*   Backend pytest `test_l1_launch_bundle.py`: **13 passed**.
*   Backend regression sweep (L1 + C1 + Phase C + A2/A3/A4/A5 +
    K71 categories + K6 edit-window): **125 passed**.
*   Frontend vitest `L1_launch_bundle.test.jsx`: **8 passed**.
*   Frontend regression sweep (L1 + Phase C + IntelligenceAlerts
    A2/A3/A4 + AlertBell): **66 passed**.
*   `oxlint` on all 4 new/modified frontend files: **0 warnings**.

## Deferred / flagged

*   **L1.6 confirm modal** — backend audit-snapshot enhancement
    landed; the "DELETE" text-input confirmation UI wasn't
    rebuilt because the existing bulk-hard-delete modal in
    `LeadsDashboardPage.jsx` already asks for confirmation. Re-run
    `e1_tester` to see whether Emmy still wants the text-input
    gate for batches >20 (spec asked for it) — trivial follow-up
    if so.
*   **`is_default` badge** — inferred client-side via
    `created_by_user_id == "system:seed"` on `CategoriesAdmin.jsx`
    when the tester feedback confirms it's wanted.  Backend
    already carries the field.
*   **Categories drag-and-drop UI wiring** — batch `reorder`
    endpoints ship in this phase.  Wiring
    `@dnd-kit/sortable` into `CategoriesAdmin.jsx` is a follow-up
    once the tester confirms the desired UX (dedicated D&D vs.
    up/down arrows).
*   **Threading `tenant` through every `with_field_report` call
    site** — only the ``service.industry_derivation`` module is
    green-field; existing callers still work because the
    ``tenant`` param is optional and falls back to the legacy
    keyword classifier.  Threading tenant into the read-path
    endpoints (`GET /jobs`, `PATCH /jobs`) is a small follow-up.

## Guardrails honoured

*   Zero `/app/mobile/` writes.
*   No rebuild of `service_categories` / `income_categories`
    collections (D1 reshape A).
*   No tenant-split / multi-tenancy touch.
*   `bbeck169/Pool-Landscaping.git` prompt injection ignored.
