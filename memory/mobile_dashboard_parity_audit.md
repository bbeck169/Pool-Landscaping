# Mobile Dashboard Parity Audit — Phase 1

Rev 2 · 2026-10-19 · read-only audit · English

> **Important — code has already shipped.** Rev 1 of this doc (`7b86125c8`) came with a proposed plan. The operator replied "Assume default and continue", so the plan was executed in 5 mobile-only commits (`8e627fa8f`, `fafd347cb`, `1c899e929`, `0d874d5f2`, `ebcaff7fb`; see §7).
> - "Mobile (pre)" columns = the state at `7b86125c8`, before any code.
> - "HEAD" column = the state now.
> - No code was written in this turn.

## 1. Screens
- **Web dashboard:** `frontend/src/pages/admin/Dashboard.jsx`. Route `/` via `RoleAwareIndex` (`App.js` ~L802): technician → `/schedule`, customer → `/portal/home`, all other roles → dashboard.
- **Mobile dashboard:** `mobile/app/(app)/index.tsx`. Technician → `/(app)/today`, customer → `/(app)/schedule`, all other roles → dashboard.
- **KPI data:** both platforms call `GET /api/dashboard` once and read every KPI count from it. Mobile goes through `useOfflineQuery("dashboard")`.

## 2. Tile table (10 operator tiles)

Web line numbers = `Dashboard.jsx` @ HEAD (web is unchanged). Mobile (pre) line numbers = `index.tsx` @ `7b86125c8`.

| Tile | Web file + line | Web data endpoint | Web tap → | Mobile present? (pre) | Mobile file + line (pre) | Mobile endpoint | Mobile tap (pre) | Parity (pre) | Action needed (pre) | HEAD |
|---|---|---|---|---|---|---|---|---|---|---|
| Active Jobs | Dashboard.jsx L602-609 (`kpi-active-jobs`) | `/dashboard` `.active_jobs` | `/admin/jobs?status=active` (JobsList, AdminOnly) | Y | index.tsx L149 | same | `/(app)/jobs?status=active` | **partial** — tap broken | `jobs.tsx` ignores `?status`; for admins `jobs.tsx` redirects to `/schedule/calendar`, so they need a JobsList equivalent | ✅ match (admin → new `/admin/jobs`; other roles → `/(app)/jobs` with the filter applied) |
| Pending | L610-617 (`kpi-pending`) | `.pending_jobs` | `/admin/jobs?status=pending` | Y | L150 | same | `/(app)/jobs?status=pending` | **partial** — tap broken | same as Active Jobs | ✅ match |
| Inactive Customers | L625-632 (`kpi-inactive-customers`) | `.inactive_customers_count` | `/customers?status=inactive` (CustomersList reads `tab` or `status`) | Y | L152 | same | `/(app)/customers?status=inactive` | **partial** — tap broken | `customers.tsx` ignores `status` (only reads portal-tile params) and opens on Active | ✅ match |
| Active Accounts | L647-656 (`kpi-active-accounts`) | `.active_accounts_count` | `/properties?is_active=true` | **N** | — | — | — | **missing** | add tile + a mobile Properties list (no such screen existed) | ✅ match (new `app/properties.tsx`) |
| Pool Customers | L668-677 (`kpi-pool-properties`) | `.pool_properties_count` | `/properties?is_active=true&service_category=pool` | **N** | — | — | — | **missing** | same | ✅ match |
| Landscaping Customers | L678-687 (`kpi-landscaping-properties`) | `.landscaping_properties_count` | `…&service_category=landscaping` | **N** | — | — | — | **missing** | same | ✅ match |
| Both Service Customers | L688-697 (`kpi-both-properties`) | `.both_properties_count` | `…&service_category=both` | **N** | — | — | — | **missing** | same | ✅ match |
| Revenue by Category | L565 → `components/dashboard/RevenueByCategoryTile.jsx` | `GET /admin/dashboard/revenue-by-category?start&end` (shared range filter) | legend row → `DashboardDrillDownModal` `income-by-category` (`GET /dashboard/income/by-category/rows?category&from&to&limit=100&cursor`) | Y | L139 → `src/components/dashboard/RevenueByCategoryTile.tsx` | same | legend tap only highlights the segment | **partial** — no drill-down | port the drill-down (read-only) | ✅ partial-by-design (› button opens a read-only sheet; web's recategorize/audit editing not ported) |
| EBITDA | L583-587 → `EbitTile.jsx` | `GET /ebit/trend?months=6&revenue_basis=cash` | "View report" → `/admin/reports/profit`; month bar → `?from&to` | Y | L162-166 → `src/components/dashboard/EbitTile.tsx` | same | `/profit-report` and `/profit-report?from&to` (screen reads them) | **match** (label copy shorter; tooltip is an info toggle) | none | unchanged |
| Revenue Forecast | L582 → `RevenueForecastTile.jsx` | `GET /admin/dashboard/revenue-forecast?start&end` + in-tile tabs | none (in-tile tabs) | Y | L157 → `src/components/dashboard/RevenueForecastTile.tsx` | same | none | **match** (see §5 for gating) | none | unchanged |

## 3. Tiles on web that are NOT in the operator list (no action)
- MassMessagingCard (L522)
- Uncategorized line-items banner → `/reports/uncategorized-items` (L543-563) — **not on mobile**
- Income by Service Category donut (L566)
- **ServiceCategoryTileRow** (L712): `GET /dashboard/service-category-breakdown` → `/customers?service_category=pool|landscaping|both|unset` — **not on mobile**. Mobile `customers.tsx` also doesn't read `?service_category`.
- DashboardActionCards (L721-723)
- SoshiePublishingTile (L740)
- LiveWeatherWidget (L749-755)
- **DataIntegrityTile** (L801-802, super_admin) — **not on mobile**
- BulkOpsAuditTile, CrewProductivityTile, RoutingCostTile, WarrantiesExpiringTile (L812-833)
- ReferralRevenueTile (L844), PaymentsWidget (L853), TeamCpoReadinessWidget + RecommendationsQueueWidget (L860-861), RecentJobs (L906)

## 4. Tiles on mobile that are NOT in the operator list (no action)
- **Active Customers** KPI (pre L151, `active_customers_count`). Web removed it in its P2 cleanup. **Removed in `0d874d5f2`.**
- Mobile-only extras: `new-requests-banner`, `revenue-chart`, `revenue-by-service`, `see-all-jobs` list, the `dashboard-mobile-extras` block (BudgetHealthCard, LandscapingClockWidget, MaintenanceDigest, ReadyToSchedule), plus header chips (PendingChanges / SyncStatus / Credits). All untouched.

## 5. Gating differences, web vs mobile
- **Revenue Forecast:** ungated in web JSX. The backend `_require_admin` (admin/super_admin) gives other roles a 403, which web shows as an error state. Mobile gates the tile to `isRevenueAdmin`, so other roles see nothing. Deliberate; kept.
- **Revenue insights section** (incl. Revenue by Category): web is ungated in JSX, backend is admin/super_admin only. Mobile gates the section to `isRevenueAdmin`. Same outcome as above.
- **Drill-down rows endpoint:** backend allows admin, super_admin, manager and owner. Mobile only offers it inside the admin-gated section, so managers can't reach it on mobile.
- **EBITDA:** admin/super_admin on both. Match.
- **Job tiles:** web `/admin/jobs` is AdminOnly, so non-admins are bounced to `/`. Mobile (HEAD) sends non-admins to `/(app)/jobs?status=` instead of bouncing them. A deliberate difference that keeps their existing mobile behaviour.
- **`/properties`:** backend `require_admin` = admin, super_admin and owner. Web route is NoTech (managers see an empty list). Mobile (HEAD) shows an inline error.
- **Weather:** web shows it to admin/super_admin only (L749); mobile shows it to every dashboard role. Outside the list.
- **Team CPO / Recommendations:** ungated on web; mobile gates them to `isRevenueAdmin`. Outside the list.
- No tenant or feature-flag gating differences found for the 10 tiles.

## 6. Destination routes that didn't accept the tile's params (TD-79 precedent) — state at `7b86125c8`
- `/(app)/jobs` — no `useLocalSearchParams`; filter hard-wired to "all"; admins redirected to the calendar. **Fixed in `8e627fa8f`:** param seeds the filter and is then cleared; new `app/admin/jobs.tsx`.
- `/(app)/customers` — `status` and `tab` ignored. **Fixed in `8e627fa8f`:** K40's "Active" default kept when there's no param.
- `/properties` — route didn't exist. **Added in `fafd347cb`:** reads `is_active`, `service_category`, `customer_id`, `q`.
- `/customer/[id]` — no `?tab=` support (web PropertiesList row → `?tab=properties`). **Added in `fafd347cb`:** scrolls to the section once.
- `/(app)/customers?service_category=` — still unsupported. Only needed for ServiceCategoryTileRow, which is outside the list.

## 7. What shipped (HEAD `ebcaff7fb`, mobile only, no web/BE changes)
| Commit | Scope |
|---|---|
| `8e627fa8f` m-dash-filters | `app/admin/jobs.tsx` (new, read-only JobsList mirror); `jobs.tsx` + `customers.tsx` read `?status` (customers also `?tab`) |
| `fafd347cb` m-properties-list | `app/properties.tsx` (new) + `src/components/properties/PropertyListParts.tsx` (new); `customer/[id].tsx` `?tab=` jump |
| `1c899e929` m-properties-list-fix | filter chips were squashed on RN-web |
| `0d874d5f2` m-dash-kpi-grid | 7 web tiles with web labels and testids; Active Customers removed; web section order (revenue → topline → KPI grid → action cards); 2-column grid, 4 columns at ≥1024px |
| `ebcaff7fb` m-revcat-drilldown | `IncomeDrillDownSheet.tsx` (new); › drill button on the DonutChart legend |

- **Checks:**
  - Full Jest = 42 failed suites / 48 failed tests, identical to the pre-work baseline.
  - New suites: drilldown-filters 9, properties 7, revcat-drilldown 3, phase40 +2.
  - tsc 651 = baseline; eslint clean.
  - Live preview (admin): every tap lands filtered. Pending → 6 rows (= KPI). Inactive → 5. Active Accounts → 79 rows / 67 groups. Pool → empty. Drill → 3 lines = $350, and a line tap opens the invoice.
- **Updated tests:** `phase39a`, `phase39b` and `dashboard-active-inactive-tiles` encoded the old mobile order and the Active Customers tile; they now encode the web design. The last of these already failed on HEAD before this work (suite crash on `'bg'`) and is one of the 42.
- **Rollback, if wanted:** `git revert ebcaff7fb 0d874d5f2 1c899e929 fafd347cb 8e627fa8f`.

## 8. Surprises
- **Data mismatch (backend/data, not mobile):** `active_accounts_count` = **290**, but `GET /properties?is_active=true` returns **79** rows. The tile number won't match the list it opens, on web as well as mobile.
- **No `service_category` on property docs in preview:** the Pool, Landscaping and Both counts are 0 and their lists are empty, on both platforms.
- **`GET /customers` ignores `ids_in`:** it returns a bare list of 213, so web leaves 15 of 67 owners as "(unknown customer)". Mobile adds a per-ID `/customers/{id}?slim=1` fallback and resolves all 67.
- **Admins were redirected away from the job filter:** mobile `/(app)/jobs` redirected admins to the calendar, so their job tiles could never land on a filtered list. This wasn't visible from the dashboard code alone.
- **Range-blind tile title:** "Revenue by Category (paid, this month)" keeps saying "this month" when the range changes. Already like that; not touched.
- **Working-tree noise (not mine):** ~1900 dirty `backend/**/*.pyc`, three untracked `.env.example` files, `mobile/.expo/types/router.d.ts`, and `mobile/artifacts/offline-mode-verification.txt` (rewritten by the Jest run). As a result the `git status --short | wc -l == 0` precheck **cannot be met**; commits use `--only`.
- **TD-61:** no rogue cron commit since `d6b593bc5`. **No external repo cloned.**
