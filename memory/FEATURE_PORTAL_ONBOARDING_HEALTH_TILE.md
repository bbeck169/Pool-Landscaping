# FEATURE — Portal onboarding health tile (admin dashboard)

**Date shipped**: Feb 10, 2026 · Preview
**Scope**: Backend endpoint + web admin tile. Mobile parity is a separate handoff to `e1_expo_frontend_dev`.
**Status**: ✅ SHIPPED to preview. Not yet in production (user redeploys.)

## What & Why

Ops asked for a single-glance view of the customer portal onboarding funnel so they can chase stalled cases without opening the customers list four times. Reuses the `first_access_at`, `has_ever_logged_in`, and existing portal-activation denorms — **no new schema**. Snapshot tile only; a historical trend graph is explicitly out of scope.

## API surface

### New — `GET /api/reports/portal-onboarding-health`
- **Auth**: admin / super_admin / owner. Manager → 403. Unauthenticated → 401.
- **Cache**: 60s per `(tenant_id, window_days)`. Mirrors the sibling `/reports/pricebook-health` pattern verbatim.
- **Query params**: `window_days` (int 1..365, default 30).
- **Response envelope**:
  ```json
  {
    "as_of": "2026-02-10T10:00:00+00:00",
    "window_days": 30,
    "cohorts": {
      "invited":         { "count": N, "delta_30d": null },
      "activated":       { "count": N, "delta_30d": N },
      "signed_in":       { "count": N, "delta_30d": N },
      "never_logged_in": { "count": N, "delta_30d": null }
    },
    "assumptions": {
      "invited_delta": "...",
      "never_logged_in_delta": "...",
      "activated_predicate": "...",
      "never_logged_in_predicate": "..."
    }
  }
  ```

## Cohort predicate table

| Cohort | Source field(s) | Predicate | `delta_30d` |
|---|---|---|---|
| `invited` | `customers.has_login: bool` | `has_login == True` | `null` — no defining timestamp exists on the customer document. `has_login` is bool-only; the invite audit lives in `audit_events.portal_invite_bulk` and is not scanned by this tile. |
| `activated` | `customers.portal_password_set_at` OR `customers.portal_first_login_at` | Either timestamp is set (matches the `?portal_activated=true` filter) | Earliest anchor timestamp within `window_days`. |
| `signed_in` | `customers.portal_first_login_at` | Timestamp is set | `portal_first_login_at` within `window_days`. |
| `never_logged_in` | `customers.portal_first_login_at` | Timestamp is **NOT** set | `null` — cohort is defined by the ABSENCE of a login timestamp; trailing-window math is not meaningful. |

**Predicate alignment**: `never_logged_in` uses the **same predicate as the `?first_access=never` chip filter** so the tile CTA and the resulting list are in lockstep. This is broader than "invited AND !first_login" — a customer who was never invited also counts. Intentional: ops wants the same universe the chip shows so the number in the tile matches the number in the list header. Verified live on preview — tile shows **27**, chip shows **27**.

**Shared exclusions**: the query mirrors the customers-list defaults — soft-deleted (`deleted_at`) hidden, merged (`merged_into`) hidden, K49b-orphan rows (no top-level `id`) excluded via the shared `_valid_customer_id_predicate()` helper. Every cohort respects the same universe.

## Files touched

**Backend (1)**
- `backend/routers/profit_report.py` — appended `GET /reports/portal-onboarding-health` endpoint + `_ONBOARDING_CACHE` + `_ONBOARDING_ASSUMPTIONS` + `_iso_or_none` helper. ~180 lines. Reuses the existing `_require_admin` guard and the `_valid_customer_id_predicate` helper from `customers.py`.

**Frontend (2)**
- `frontend/src/components/customers/PortalOnboardingHealthTile.jsx` — new component (~200 lines). Renders 4 horizontal cards on desktop, stacks on mobile. Never-card is a click target that navigates to `/customers?first_access=never`. Loading skeleton + non-fatal error toast (tile hides on failure so the customers list stays usable).
- `frontend/src/pages/customers/CustomersList.jsx` — imported + mounted the tile after `PageHeader`, gated on `isAdmin`.

**Tests (2)**
- `backend/tests/test_portal_onboarding_health.py` — 7 pytest cases (envelope shape, RBAC × 2 role sets, cohort math + deltas, cache hit, null-delta cohorts, soft-deleted + K49b-orphan exclusion). All green.
- `frontend/src/test/portal-onboarding-health-tile.test.jsx` — 4 vitest cases (loading skeleton, 4-card render + delta arrows, never-card navigation, fetch failure hides tile + toasts). All green.

**Docs (2)**
- `memory/FEATURE_PORTAL_ONBOARDING_HEALTH_TILE.md` — this file.
- `memory/screenshots/portal_onboarding_tile.jpeg` — tile live on preview with counts Invited 8 · Activated 1 (↑1) · Signed in 1 (↑1) · Never 27 (—).

## Test tally

| Suite | Cases | Result |
|---|---|---|
| `backend/tests/test_portal_onboarding_health.py` | 7 | ✅ |
| `backend/tests/test_customer_temp_password_flow.py` | 9 | ✅ (no regression) |
| `backend/tests/test_auth_option_a_account_chooser_task4.py` | 10 | ✅ (no regression) |
| `backend/tests/test_jobs_list_slim_photos.py` | (existing) | ✅ (no regression) |
| `backend/tests/test_pb3_profit_report.py` | 27 / 28 | ✅ except pre-existing `test_sent_status_is_excluded` flake (per user standing order — NOT chased) |
| `frontend/src/test/portal-onboarding-health-tile.test.jsx` | 4 | ✅ |
| `frontend/src/test/customer-first-access-filter.test.jsx` | 13 | ✅ |
| `frontend/src/test/customers-list-portal-filter.test.jsx` | 7 | ✅ |
| `frontend/src/test/customers-list-active-filter.test.jsx` | 6 | ✅ |
| `frontend/src/test/customer-filter-bar.test.jsx` | (existing) | ✅ |
| `frontend/src/test/pb3-profit-report.test.jsx` | 5 | ✅ (no regression) |

## E2E smoke on preview

```
$ curl /api/reports/portal-onboarding-health?window_days=30 (admin)
  → HTTP 200
  → { invited: 8, activated: 1 (Δ1), signed_in: 1 (Δ1), never_logged_in: 27 (null) }

$ curl /api/reports/portal-onboarding-health (no token)   → HTTP 401
$ curl /api/customers?count_only=true&first_access=never  → 27  # matches tile CTA target
```

Web admin `/customers` page renders the tile above the tab bar. Never-card click deep-links to `/customers?first_access=never` and the resulting list badge stays at `(27)` — same predicate, same universe.

## Follow-ups (out-of-scope handoff)

- **Mobile parity** → `e1_expo_frontend_dev`: mirror the tile on the mobile customers screen. Same endpoint; same deep-link intent. (Main agent MUST NOT touch `/app/mobile/`.)
- **Historical trend chart** — explicitly deferred. If ops wants sparklines, capture nightly cohort snapshots into a new `portal_onboarding_snapshots` collection and add a `?range=90d` endpoint. NOT this sprint.
- **Per-tenant configurable `window_days`** — server already accepts the param; UI hardcodes 30. Wire a settings toggle when a second user asks for it.
