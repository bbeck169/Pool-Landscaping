# Mobile Dashboard Parity Audit — Phase 1 (pre-flight, read-only)

Date: 2026-10-19 · HEAD `d6b593bc5` · No code written. `/app/frontend` + `/app/backend` read only.

## Surfaces
| | Web | Mobile |
|---|---|---|
| Dashboard | `frontend/src/pages/admin/Dashboard.jsx` (root `/` via `RoleAwareIndex`; tech → /schedule, customer → portal) | `mobile/app/(app)/index.tsx` (tech → `/(app)/today`, customer → `/(app)/schedule`) |
| Data | `GET /api/dashboard` (one call, all KPI counts) | same `GET /api/dashboard` via `useOfflineQuery("dashboard")` |
| KPI grid | `grid-cols-2 lg:grid-cols-4`, `KpiCard` with explicit `testId` + tone | `styles.grid` row-wrap, `kpi` width 47.5% + flexGrow 1 (2 columns); `Kpi` derives testID from label |

## Web section order (top → bottom)
MassMessaging → Revenue insights (range filter + uncategorized banner + Revenue by Category + Income by Service Category) → **Topline** (Revenue Forecast + EBITDA) → **KPI grid (7 tiles)** → ServiceCategoryTileRow → ActionCards → …

## Mobile section order today
MassMessaging → Revenue insights (filter + 2 donuts, **no uncategorized banner**) → **ActionCards** → **KPI grid (4 tiles)** → **Topline** → …
→ Topline and KPI grid are in the wrong order, and ActionCards is placed above both.

## Tile-by-tile delta (10 operator tiles)
| # | Tile | Web source / testid | Web tap → | Web gate | Mobile today | Delta |
|---|---|---|---|---|---|---|
| 1 | Active Jobs | `/dashboard.active_jobs` · `kpi-active-jobs` | `/admin/jobs?status=active` (JobsList reads `?status`) | dashboard roles | Present, pushes `/(app)/jobs?status=active` | **BROKEN TAP**: `app/(app)/jobs.tsx` never reads `useLocalSearchParams`; filter state is hard-wired to `"all"` |
| 2 | Pending | `pending_jobs` · `kpi-pending` | `/admin/jobs?status=pending` | same | Present, `?status=pending` | **BROKEN TAP** (same cause) |
| 3 | Inactive Customers | `inactive_customers_count` · `kpi-inactive-customers` | `/customers?status=inactive` | same | Present, `?status=inactive` | **BROKEN TAP**: `customers.tsx` statusFilter defaults to `"active"`; route params only feed the portal-health `tileKey` (`portal_activated/first_access/has_payment_method`) |
| 4 | Active Accounts | `active_accounts_count` · `kpi-active-accounts` | `/properties?is_active=true` | same | **MISSING** | Tile missing **and** mobile has no Properties list screen |
| 5 | Pool Customers | `pool_properties_count` · `kpi-pool-properties` | `/properties?is_active=true&service_category=pool` | same | **MISSING** | same |
| 6 | Landscaping Customers | `landscaping_properties_count` · `kpi-landscaping-properties` | `…&service_category=landscaping` | same | **MISSING** | same |
| 7 | Both Service Customers | `both_properties_count` · `kpi-both-properties` | `…&service_category=both` | same | **MISSING** | same |
| 8 | Revenue by Category | `GET /admin/dashboard/revenue-by-category?start&end` · `revenue-by-category-tile` | legend row → `DashboardDrillDownModal variant="income-by-category"` (`GET /dashboard/income/by-category/rows?category&from&to&limit=100&cursor`) | BE `_require_admin` (admin/super_admin) | Present, admin-gated, same endpoint + testIDs | **No drill-down**: legend tap only highlights the segment (noted in file header) |
| 9 | EBITDA | `GET /ebit/trend?months=6&revenue_basis=cash` · `dashboard-ebit-tile` | "View report" → `/admin/reports/profit`; sparkline month → `?from&to` | JSX: admin/super_admin | Present, same gate/endpoint; report link → `/profit-report`; bar → `/profit-report?from&to` (screen reads them) | **Parity OK** (label copy shorter: "EBITDA · This month" vs web long-form + tooltip, which mobile shows as an info toggle) |
| 10 | Revenue Forecast | `GET /admin/dashboard/revenue-forecast?start&end` + tab quick-view · `revenue-forecast-tile` | no navigation (in-tile tabs) | JSX ungated; BE `_require_admin` → managers/dispatchers get a 403 error state on web | Present, `isRevenueAdmin` gate, same endpoint + tabs | **Parity OK** in function; mobile gate hides the tile where web shows an error (intentional, keep) |

Extra on mobile, removed on web: **"Active Customers"** tile (`active_customers_count`). The web P2 cleanup removed it on operator request.

## Destination route audit
- `/(app)/jobs` — FILTERS keys `all|requested|pending|active|completed` already match `?status=` values → small fix: seed `filter` from params.
- `/(app)/customers` — segments `active|inactive|waitlist|all` match web `?status=`/`?tab=` → seed `statusFilter` from `status` (or `tab`), keeping the K40 default "active" when the param is absent.
- `/properties` — **does not exist on mobile**. BE `GET /api/properties` is `require_admin`, params `is_active=true|false|all`, `service_category=pool|landscaping|both|unset`, `customer_id`, `search`, `limit≤2000`; returns `{items:[…]}`. Web hydrates names via `GET /customers?ids_in=…`, groups rows by customer, and a row tap goes to `/customers/<cid>?tab=properties`.
- `customer/[id].tsx` — has an anchor/section-scroll system (`SectionAnchor k="properties"`), but no route param to pre-scroll to a section.

## Gating summary
Dashboard KPI grid: every role that reaches the dashboard (non-tech, non-customer) on both platforms. `/properties` BE = admin-only (`require_admin`), so non-admins tapping the 4 property tiles would hit a 403 on both web and mobile. Web has the same behaviour, so mirror it with an inline error state.

## Live preview data (admin)
`active_jobs 0 · pending_jobs 6 · inactive 5 · active_accounts 290 · pool 0 · landscaping 0 · both 0`.
Caveats (BE/data, not mobile): `/properties?is_active=true` returns **79** items vs `active_accounts_count` **290**. Property docs have **no `service_category` field** in preview, so the pool/landscaping/both lists will be empty (counts are also 0, so the screen is consistent). Report this to the orchestrator; do not fix here.

## Out of the 10-tile scope (noted, not proposed)
- Web `ServiceCategoryTileRow` (`/dashboard/service-category-breakdown` → `/customers?service_category=`) is not on mobile.
- Web uncategorized-items banner (`/reports/uncategorized-count`) is not on mobile.
- Drill-down editing (recategorize + line-item audit POSTs) — the proposal covers read-only rows only.
