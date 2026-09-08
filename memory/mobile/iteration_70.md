# Iteration 70 — Hotfixes M3 + M4 + M5

## M3 — D2D customer gate + Zillow enrichment

### Part A — "Existing customers nearby" panel
**NO-OP confirmed.** The mobile D2D screen (`app/d2d/index.tsx`) does NOT have a `/d2d/customers-nearby` fetch or customer layer. Grep returned 0 matches for `customers-nearby`, `customersNearby`, `customer.*pin`, `customer.*marker` across all D2D files. The web hotfix's customer gate has no mobile counterpart to hide.

### Part B — Zillow property enrichment on knock rows
Added enrichment functionality to the knock edit Sheet:
- **"Pull property data"** button visible for all roles (tech + admin) — no role gate.
- When knock already has `zillow_data`, label becomes **"Refresh Zillow data"** and cached fields are pre-rendered (estimated_value, sqft, lot_size, beds, baths, year_built, image).
- On success: updates local knock state so reopening the sheet shows cached data.
- Error handling:
  - 503 → "Zillow API not configured — ask your admin."
  - 429 → "Property lookups rate-limited — try again shortly."
  - Other → generic retry alert with error message.

**Files modified:** `app/d2d/index.tsx` (+68 lines: state, `enrichZillow()`, UI, styles)

## M4 — Trainings designation visibility

**Verified NO client-side filtering.** The `tests/index.tsx` `load()` function passes the API result directly to `setItems(Array.isArray(rows) ? rows : [])` with zero `.filter()` calls. Backend `_visible_departments()` is authoritative. No code changes needed.

**Files created:** `__tests__/hotfix-m4-trainings.test.tsx` (3 tests — confirms no filtering)

## M5 — Checklist bootstrap 429 hardening

Rewrote `load()` error handling in `app/job/[id]/checklist.tsx`:
- **429 → retry once** after 1s backoff → cache fallback → "Server busy — try again in a moment."
- **401/403 → "Session expired"** with "Sign in" action button routing to `/login`.
- **5xx → "Something went wrong"** with Cancel + Retry buttons.
- **Other → "Unable to open checklist"** with response body message (not raw status code).
- **Telemetry:** All bootstrap failures logged to `POST /api/telemetry/mobile-crash` (best-effort, no retry on telemetry 429).
- **`useApiErrorHandler` extraction:** NOT done. Only 1 call site has this pattern (checklist bootstrap). The 2nd call site (schedule load) uses a different error flow (timeout + abort). Extraction not justified for 1 site — documented as a future consideration if more sites emerge.

**Files modified:** `app/job/[id]/checklist.tsx` (+80 lines: `_logBootstrapFailure`, rewritten error handler with 4 code paths)
**Files created:** `__tests__/hotfix-m5-checklist-429.test.tsx` (13 tests)

## Test results
| Suite | Tests | Status |
|---|---|---|
| hotfix-m3-d2d-zillow | 4 | ✅ |
| hotfix-m4-trainings | 3 | ✅ |
| hotfix-m5-checklist-429 | 13 | ✅ |
| k32-tech-scoped-schedule | 6 | ✅ |
| hotfix-m1-m2-schedule | 10 | ✅ |
| **Total** | **36** | **All pass** |

## Screenshots
- **D2D tech view**: "No doors yet" empty state on Doors tab. No customers-nearby panel. 43 Open Leads visible.
- **Trainings tech view**: "No modules yet" — backend has no training modules seeded. Screen renders API result without filtering.
- Both screens compile and render correctly.

## Caveats
- Zillow enrichment calls `POST /d2d/prospects/{id}/enrich-zillow` — if the backend endpoint doesn't exist yet, the button will hit a 404 (gracefully handled by the generic error path).
- The `useApiErrorHandler` hook was NOT extracted — only 1 call site justifies it. Document for future if more sites need it.
- Training fixture gap: No pool-only or landscaping-only tech variants in seed data. Cannot visually verify department-restricted module lists.
