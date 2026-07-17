# HANDOFF — most recent shipped phase

## Phase 56.17 + P0 nav fix · Autobilling Schedule Options + Auto-Run (Feb 2026)

Two things landed in this ship, in this order:

1. **P0 bug fix — Master Invoices 404**. Root cause below.
2. **Phase 56.17 — Autobilling schedule options + daily auto-run**,
   including the `fourth_friday` amendment.

### P0 fix — Master Invoices 404

**Root cause (one-line diagnosis)**: `frontend/src/nav/adminNav.js`
line 43 pointed at `/master-invoices`, but the routes in `App.js`
(lines 250–252) are mounted at `/invoices/master`, `/invoices/master/new`,
and `/invoices/master/:id`. Clicking "Master Invoices" from the admin
nav dropped the user on `/master-invoices` → the SPA's 404
fallback. Backend endpoints and the component itself were fine; only
the nav link was stale.

**Fix** (single-line diff):

```
- { to: "/master-invoices", ... }
+ { to: "/invoices/master", ... }
```

**Files touched**: `frontend/src/nav/adminNav.js`.

**Regression scan**: grepped `/app/frontend/src` for
`/master-invoice` / `/master-billing` / `master-invoices"` — only
that one line matched. No other pages are affected. The nav link
was NOT introduced by 56.17 (it predates every ship in this
session per `git log`), so this is a latent nav/route mismatch,
not a regression from a recent phase.

**Verified**: logged in as `admin@aquaterra.com`, opened the admin
nav → "Master Invoices" — page renders the "Master Invoices"
heading + "No master invoices yet" empty state + "Create master"
CTA. Screenshot: `/tmp/56_17_master_invoices_ok.png`. Fully
resolved.

### Phase 56.17 — Autobilling schedule options + daily auto-run

Ship bundled A + B + C + D + E + partial-F + G.

**A. Schedule enum** (`backend/models.py`) — `BillingPlan` gains a
`run_schedule` field with FIVE options:
`first_friday | second_friday | third_friday | fourth_friday |
first_of_month`. Existing plans without the field default to
`first_of_month` at read time (no bulk migration).
`last_run_month` (`YYYY-MM`) is set only when a plan actually
fires — read-back safe on legacy docs.

**B. Scheduler behavior** (`backend/routers/finances.py` +
`backend/server.py`):
- `anchor_date_for_month(schedule, y, m)` — pure function.
  Fridays computed off `(4 - weekday) % 7`; `fourth_friday`
  always picks `first_friday.day + 21`, which lands 22–28 and
  never spills into a 5th-Friday month (July 2026 test proves
  Jul 24, not Jul 31).
- `next_fire_preview(schedule, today)` — rolls into next month
  (year on Dec) when today is past this month's anchor.
- `run_daily_autobilling()` — new APScheduler cron job
  (`hour=6, minute=0`; still UTC, but each plan's anchor is
  computed inside the tenant's own timezone). Per plan:
  fetch tenant TZ → today in tenant TZ → this month's anchor.
  Fire when `delta >= 0`, `delta <= 7` (grace window), and
  `last_run_month != current YYYY-MM`. Every attempt (fired,
  skipped, late_missed, error) writes to a new
  `autobilling_runs` collection with tenant_id, plan_id,
  schedule, anchor_date, current_month, status, message,
  invoice_id, ts.
- Old `run_monthly_chem_billing` every-24h job is untouched;
  the new autobilling job runs alongside it. Both are
  idempotent.

**C. Tenant timezone** — `Tenant` docs may carry a `timezone`
field (IANA). `_tenant_tz(tenant)` reads it and defaults to
`America/Phoenix` (Vistancia, AZ — no-DST). Unknown IANA names
gracefully fall back to UTC with a warning.
`PATCH /api/tenant/settings { timezone }` validates the IANA
name via `zoneinfo.ZoneInfo(...)` and 400s on typos.

**D. Admin UI editor** (`frontend/src/pages/finance/FinancePages.jsx`)
— the New Plan modal gains:
- A **Run Schedule** `<select>` with all 5 options (kept in the
  exact order requested: 1st/2nd/3rd/**4th**/1st of month).
  Test-ids on each `<option>`:
  `billing-plan-run-schedule-{first_friday,second_friday,third_friday,fourth_friday,first_of_month}`.
- A live **next-fire preview** below the dropdown
  (`billing-plan-next-fire-preview`) computed client-side with
  the same anchor math as the backend, using the browser's
  locale-aware `toLocaleDateString`.

**E. Manual "Run now"** — `POST /api/billing-plans/{pid}/run-now`
fires the same billing cycle immediately, marks
`last_run_month = current YYYY-MM`, and writes a `manual_run_now`
entry to `autobilling_runs`. Refuses (409) if the plan has
already run this calendar month. UI action wired through the
existing per-row `Run` button which already hit the
non-idempotent `/run` endpoint — Phase 56.17 leaves that
endpoint untouched for backwards compat.

**F. Autobilling runs audit log — endpoint only, UI deferred**:
`GET /api/autobilling-runs?plan_id=&status=&since=` (admin-only,
tenant-scoped) is live and returns the audit rows. The dedicated
`/admin/autobilling-runs` frontend page is **deferred** to a
follow-up — the current ship has a growing budget footprint and
the audit rows are already reachable via curl / dashboards.
Called out below in **Deferrals**.

**G. Backend tests** — `backend/tests/test_phase56_17_autobilling.py`
(new): **6 tests, all passing** (4.20s):
- Anchor math for all 5 schedules including Feb 2026 (4 Fridays:
  6/13/20/27), July 2026 (5 Fridays: 3/10/17/24/31 — 4th anchor
  must be 24), Oct 2025 (Wed start), May 2026 (Fri start).
- `next_fire_preview` rollover behavior + Dec→Jan year rollover.
- Timezone helper: Arizona no-DST OK, bogus IANA → UTC fallback.
- `run_schedule` field accepted + persisted; `fifth_friday`
  → HTTP 422.
- `/billing-plans/{id}/run-now` — RBAC (admin 200, tech 403);
  double-fire in same month → 409; audit row logged.
- `/autobilling-runs` — RBAC (admin 200, tech 403).
- `run_daily_autobilling` idempotency + 7-day grace window —
  same-day re-tick skips; >7-day-late logs `late_missed` and
  does NOT fire.
- `PATCH /tenant/settings { timezone }` — accepts IANA, rejects
  typos with 400.

### Files touched

- `backend/models.py` — `run_schedule` field + validator on
  `BillingPlanIn` and `BillingPlanUpdate` (5 options each);
  new `TenantSettingsUpdate` model.
- `backend/routers/finances.py` — +260 LOC for Phase 56.17
  block (helpers, daily job, run-now, next-fire, audit
  endpoint, tenant settings PATCH).
- `backend/server.py` — new `autobilling_daily` cron job
  wired in alongside the existing `chem_billing` job.
- `backend/tests/test_phase56_17_autobilling.py` (**new**) —
  6 tests.
- `frontend/src/pages/finance/FinancePages.jsx` — schedule
  dropdown + next-fire preview + `run_schedule` on the
  `newPlan` state.
- `frontend/src/nav/adminNav.js` — **P0 fix**: nav link
  `/master-invoices` → `/invoices/master`.

### Evidence

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0**
(418 pre-existing dead-import WARNs, no new WARNs).

**Backend tests**: `pytest test_phase56_17_autobilling.py -v` →
**6 passed** in 4.20s.

**Live curl (admin @preview)**:

```
POST /api/billing-plans {"run_schedule": "fourth_friday", ...}
  → 200, plan.run_schedule = "fourth_friday"

GET /api/billing-plans/{pid}/next-fire
  → 200 { next_fire_date: "2026-07-24",
          run_schedule: "fourth_friday",
          last_run_month: null,
          timezone: "America/Phoenix" }
      ↑ July 2026 has 5 Fridays; 4th anchor correctly picks Jul 24.

POST /api/billing-plans/{pid}/run-now
  → 200 { ok: true, invoice_id: "ef41527d…",
          last_run_month: "2026-07" }

POST /api/billing-plans/{pid}/run-now   (second call, same month)
  → HTTP 409  ("Plan already ran this calendar month …")

GET /api/autobilling-runs   (tech token)
  → HTTP 403
```

**Screenshots**:
- `/tmp/56_17_master_invoices_ok.png` — Master Invoices page
  renders (P0 fix verified).
- `/tmp/56_17_new_plan_modal.png` — New billing plan modal
  with the Run Schedule dropdown expanded on "4th Friday of the
  month" and the live preview reading "Next billing run:
  Friday, July 24, 2026".

### Non-goals held

- No per-customer schedule override.
- No weekly / bi-weekly / 5th-Friday options in v1 — five
  monthly anchors only (1st/2nd/3rd/4th Friday + 1st of month).
- No cross-month batching.
- No email/SMS notification of upcoming runs (customer still
  sees the invoice via the existing Stripe flow).

### Deferrals called out

- **`/admin/autobilling-runs` dedicated audit UI page** — the
  endpoint is live and tested; the frontend page is deferred
  to a Phase 56.17-followup so this ship stays inside a clean
  context budget. Admins can still read the audit rows via
  curl or a small future UI page.

### Priority order

1-12: ✅ (all previous phases + 56.16-followup, 56.10-mobile,
       56.11-mobile, 56.13b-followup).
13. ✅ Phase 56.17 + P0 nav fix — Autobilling schedule
    options + daily auto-run + Master Invoices 404 fix
    (**THIS SHIP**).
14. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d
    (supplemental pool modules), 56.14 (landscape training),
    56.15 (handbook + onboarding).
15. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" widget action, RingCentral test scope,
    Phase 56.17-followup autobilling audit UI page.
