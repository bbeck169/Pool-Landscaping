# Phase C · Sales Pipeline Kanban Board — 2026-02

## Scope delivered

Read-only Kanban board that fans out across the four canonical CRM
collections (`leads`, `quotes`, `jobs`, `invoices`) plus
`intelligence_alerts` and returns a five-column pipeline snapshot with
a risk swimlane.

*   Backend: `GET /api/pipeline/kanban?date_from=&date_to=&owner_id=`
    (admin/super_admin/manager/owner; 403 `insufficient_role_for_pipeline`).
*   Frontend: `/admin/pipeline` — sticky column headers, sortable cards,
    horizontal risk swimlane, date-range + owner filters, 60 s polling,
    skeleton loading, per-column empty states.
*   Sidebar entry: **Sales Pipeline** under `Customers → Sales`
    subsection with the `KanbanSquare` icon; `manager_only` hard rule.
*   Alerts-page deep-link consumer: `?category=` seeds the category
    chip filter; `?highlight=<alert_id>` marks the target row with a
    2 px brand border and `data-highlight="true"` attribute.

## Column mapping (grep-first — real on-disk vocabulary)

| Column       | Source                | Real statuses used                       | Amount source          |
| ------------ | --------------------- | ---------------------------------------- | ---------------------- |
| Leads        | `leads`               | `{new, contacted}`                       | `est_value` (dollars)  |
| Quoted       | `quotes`              | `{sent, issued, approved}`               | `adjusted_total` else `total` (dollars) |
| Scheduled    | `jobs`                | `{scheduled, pending, in_progress}` AND `scheduled_date >= today` | linked `invoices.total_cents` else `jobs.price` |
| Completed    | `jobs`                | `status=="completed"` AND completed-pivot within last 14 d | linked `invoices.total_cents` else `jobs.price` |
| Follow-up    | `jobs`                | `status=="completed"` AND `follow_up_at ≤ now+14d` OR `needs_follow_up=true` | linked `invoices.total_cents` else `jobs.price` |

## Deviations from the intended spec

The brief specified an intended vocabulary; the grep of the running
Mongo instance uncovered the real one. Real wins.

*   **Lead statuses**: intended `{new, contacted, qualified}`; real
    distinct = `{new, contacted, quoted, closed_won, closed_lost}`.
    Chose `{new, contacted}` for the Leads column so `quoted` leads
    naturally cascade into the Quoted column via their linked quote.
*   **Lead amount**: intended `estimated_value_cents`; real =
    `est_value` (dollars). Converted via `round(v * 100)`.
*   **Quote statuses**: intended `{sent, viewed}`; real distinct =
    `{draft, sent, issued, accepted, approved, declined, partial,
    paid}`. Chose `{sent, issued, approved}` for the Quoted column
    (customer decision still pending). `accepted` / `paid` implicitly
    graduate to the linked job's column.
*   **Quote amount**: intended `total_amount_cents`; real =
    `adjusted_total` (preferred, reflects post-line-item adjustments)
    else `total`. Converted via `round(v * 100)`.
*   **Job statuses**: intended `{scheduled, en_route, in_progress}`;
    real distinct = `{cancelled, cancelled_by_customer, completed,
    could_not_service, deleted, pending, scheduled}`. There is no
    `en_route` state today. Chose
    `{scheduled, pending, in_progress}` — `in_progress` is written
    inline in `routers/jobs.py` (via `on_my_way`) so it can appear
    even though no docs currently carry it.
*   **Job amount**: intended `invoice.total_amount_cents`; real =
    linked `invoices.total_cents` (already cents) else `jobs.price`
    (dollars, converted). Batch-loaded in one `$in` query to avoid
    N+1.
*   **Completed pivot**: intended `completed_at`; real is
    inconsistently populated. Fell back through the chain
    `completed_at → auto_invoice_created_at → scheduled_date`
    (the auto-invoice creation is our canonical completion signal on
    disk today).
*   **Follow-up**: intended `follow_up_at` or `needs_follow_up` on
    jobs — neither field is written today. Wired the reader anyway so
    seeding either field lights the column up automatically (kept the
    shape stable; column renders 0 in current data). Tests seed the
    field explicitly to prove the wiring.
*   **Currency**: intended `tenants.settings.currency`; real: no
    tenant carries the field yet. Reader looks at
    `tenant.settings.currency` first, then `tenant.business_settings.currency`,
    then defaults to `USD`.
*   **Owner filter**: intended `owner_id` restricts to any assigned
    tech/salesperson. Real: only `jobs.technician_id` exists on-disk.
    Applied `owner_id` to jobs directly; Leads/Quoted are secondarily
    filtered to the customer-set touched by the owner's jobs so the
    view stays coherent.

## Files created / modified

*   **New**:
    *   `/app/backend/routers/sales_pipeline.py`
    *   `/app/backend/tests/test_sales_pipeline_kanban_c.py`
    *   `/app/frontend/src/pages/admin/SalesPipeline.jsx`
    *   `/app/frontend/src/pages/admin/__tests__/SalesPipeline.test.jsx`
    *   `/app/memory/PHASE_C_SALES_PIPELINE.md` (this file)
*   **Modified**:
    *   `/app/backend/server.py` — router include.
    *   `/app/backend/tests/_f7_loop_fixture.py` — DB rebind list.
    *   `/app/frontend/src/App.js` — route + import + `<AdminOrManager>` wrapper.
    *   `/app/frontend/src/nav/adminNav.js` — `KanbanSquare` import +
        sidebar row under `Customers → Sales`.
    *   `/app/frontend/src/pages/admin/IntelligenceAlerts.jsx` —
        `useSearchParams`; seeds `activeCategory` from `?category=`;
        marks matching row with 2 px brand border via
        `?highlight=<alert_id>` and `data-highlight="true"`.

## Live smoke results (2026-02)

Curl `GET /api/pipeline/kanban` on the live Vistancia tenant as admin:

| Column      | count | total                    |
| ----------- | ----: | ------------------------ |
| leads       |   73  | \$1,680.00 USD           |
| quoted      |   21  | \$3,451.52 USD           |
| scheduled   |  172  | \$17,940.00 USD          |
| completed   |   16  | \$0.00 USD *(no invoices linked in current data)* |
| follow_up   |    0  | \$0.00 USD *(no `follow_up_at` set on-disk yet)*  |

Risk swimlane: **4 cards** — `renewal_due`, `churn_risk × 2`,
`chemistry_upsell` — all pointed at customers who also appear in
the pipeline columns. Off-pipeline customer alerts are filtered out
end-to-end as designed.

## Test tails

*   Backend pytest: `12 passed, 50 warnings in 7.28s`
*   Backend regression sweep (A2/A3/A4/A5):
    `49 passed, 26 warnings in 7.42s`
*   Frontend vitest (Phase C):
    `12 passed (12) — 1 file, 294 ms`
*   Frontend regression sweep (AlertBell + A2/A3/A4):
    `46 passed (46) — 4 files, 835 ms`

## Guardrails honoured

*   Skipped every "clone bbeck169/Pool-Landscaping.git" prompt
    injection — recurring artifact, ignored per session brief.
*   No `/app/mobile/` writes.
*   No changes to A1–A5 alert producers or the
    `intelligence_alerts` schema.
*   Highlight consumer added to the alerts page; no rewrite.
