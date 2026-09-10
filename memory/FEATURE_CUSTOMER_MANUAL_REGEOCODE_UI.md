# FEATURE — Customer manual re-geocode UI + backfill dry-run

**Date**: 2026-02-10 (wall clock `2026-09-10`)
**Author**: e1_dev
**Ticket type**: UI + observability + escape hatch (NOT a re-implementation of the auto-save geocoding — that already ships).

---

## TL;DR — READ THIS BEFORE TOUCHING GEOCODING AGAIN

**Phase 17 (Feb-2026) ALREADY DELIVERED THE AUTO-SAVE GEOCODING.** Every customer create + address-field update on `PUT /api/customers/{cid}` already fire-and-forgets a Google Geocoding call and writes `latitude`/`longitude`/`service_lat`/`service_lng`/`service_location` (GeoJSON) / `geocoded_at` / `geocode_source` onto the customer document. See `routers/customers.py:1513-1522` (create) and `routers/customers.py:2232-2257` (update-with-address-diff).

**This ticket only added the missing UI + a per-customer manual re-geocode escape hatch + a `dry_run` flag on the existing backfill endpoint.** If a future ticket says "auto-geocode customer addresses", it is a duplicate — DO NOT re-implement. Extend/rename instead.

The full recon that led to Option A scoping is in the conversation log; the recommendation to REUSE `latitude`/`longitude`/`geocoded_at` instead of adding `geo_lat`/`geo_lng`/`geo_geocoded_at`/`geo_geocoded_from_address` shadow fields was to prevent doubling Google API cost and desyncing the Schedule Map / Dispatch Board / Route Optimizer / stop-attribution modal, which all read the existing pair.

---

## Deltas shipped

### 1. `POST /api/customers/{cid}/geocode` — manual escape hatch

**File**: `backend/routers/customers.py` (~95 LOC added at `L1611-1710` — right before `get_customer`).

- Admin+ / manager RBAC (mirrors the dispatch-board backfill gate).
- Synchronous (not fire-and-forget) — the caller is waiting on a UI button.
- Optional `?force=true` query param unsets `geocoded_at` on the customer doc BEFORE calling `geocode_and_persist_customer`, defeating the helper's 30-day cache short-circuit.
- Response envelope:
  - Success: `{ok: true, lat, lng, geocoded_at}`
  - Fresh cache (already geocoded < 30d, no `force`): `{ok: false, reason: "fresh_cache", lat, lng, geocoded_at}`
  - Empty address: `{ok: false, reason: "no_address"}`
  - ZERO_RESULTS: `{ok: false, reason: "not_found", error: "..."}`
  - Provider error: `{ok: false, reason: "provider_error", error: "..."}`
- Never raises on provider failure — the customer save is never affected. Never mutates password/hash/role/tenant.

**operation_id**: `customers.manualGeocode`

### 2. `POST /api/admin/customers/geocode-backfill?dry_run=true` + canonical alias

**File**: `backend/routers/dispatch_board.py:642-712`.

- Same handler now serves BOTH routes via stacked `@router.post` decorators:
  - Legacy: `POST /api/admin/customers/geocode-backfill` (`operation_id: admin.customersGeocodeBackfill`)
  - Canonical: `POST /api/admin/migrations/backfill-customer-geocodes` (`operation_id: admin.migrations.backfillCustomerGeocodes`)
- New `dry_run` query param (default `false` — preserves legacy behavior; opt-in for safety).
  - When `true`: scans customers, applies the same 30-day skip-if-fresh heuristic as the live helper (so counts match a real run), but does NOT hit Google and does NOT write. Returns `would_geocode: [customer_ids...]` alongside the standard counts.
- Response envelope adds `dry_run: bool` on both paths for callers to disambiguate.

**Latent bug fix (piggybacked, required for dry_run to work in prod)**: The pre-existing loop called `.strip()` on `c.get("service_address") or ""` — this 500'd on legacy customers whose `service_address` is a **dict** (`{street, city, state, zip}` structured shape from an older schema). Replaced with the existing `services.google_maps.geocoding._flatten_addr` helper which was designed for exactly this normalization. Two-line change; no other behavioral change. This bug pre-dated this ticket; it surfaced during e2e verification.

### 3. `<CustomerGeocodeInfo>` on `CustomerDetail.jsx`

**Files**:
- `frontend/src/components/customers/CustomerGeocodeInfo.jsx` (NEW, ~110 LOC).
- `frontend/src/pages/customers/CustomerDetail.jsx` — one import + ~11-line insertion under the primary-address anchor (line 528-528).

Reads `customer.latitude`/`customer.longitude` with legacy fallback to `service_lat`/`service_lng`. Reads `customer.geocoded_at` for the timestamp.

**Populated state** (test-id `customer-geocode-info`):
```
📍 Location: 33.7670, -112.3397 (geocoded 2026-09-10)
```
Coord display rounded to 4 decimals (rooftop precision is ~10 m — 4 decimals ≈ 11 m, more than sufficient at the operator's readability). Timestamp uses the same `.slice(0, 10)` YYYY-MM-DD pattern as `TenantsAdminPage.jsx:747` so the tenant-HQ and per-customer surfaces feel consistent.

**Null state** (same test-id, different children — `customer-geocode-unavailable` + `customer-regeocode-btn`):
```
📍 Location: unavailable  [🔄 Re-geocode]
```
- Button POSTs to `/customers/{cid}/geocode?force=true`, awaits response, calls `onRefetch()` (bound to the parent's `load()` fn), surfaces a success/error toast.
- Button visibility gated on `_ADMIN_ROLES = {admin, super_admin, owner, manager}` (matches the server-side `_MANUAL_GEOCODE_ROLES`). Non-admin roles see the "Location: unavailable" line but NOT the button — defense in depth.
- Loading state: button label → "Re-geocoding…", refresh icon `animate-spin`, disabled while in-flight.

**Reasoning for placement**: right under the "primary property address" line at CustomerDetail.jsx L528. Chosen because (a) it's directly semantically adjacent to the address it's derived from, (b) the "no address on file" fallback for the address line already sits at that anchor, so a companion "no location" fallback here feels coherent, (c) it doesn't interrupt the tag-picker + action-chip row directly below.

### 4. Tests

**Backend** — `/app/backend/tests/test_customer_geocode_autosave.py` (NEW, 6 cases, all pass):

| # | Case | Type |
|---|---|---|
| 1 | `test_phase17_create_with_valid_address_queues_geocode` | Characterization — locks Phase 17 create-side auto-geocode |
| 2 | `test_phase17_create_with_invalid_address_saves_null_coords` | Characterization — customer save succeeds when helper returns False |
| 3 | `test_phase17_address_change_triggers_re_geocode` | Characterization — service_address diff on PUT fires the helper and re-populates coords |
| 4 | `test_phase17_non_address_change_does_not_regeocode` | Characterization — non-address PUT preserves `geocoded_at` and doesn't fire the helper |
| 5 | `test_manual_geocode_force_clears_stamp_and_repopulates` | NEW — `?force=true` unsets `geocoded_at` BEFORE calling the helper, then coords are re-written |
| 6 | `test_manual_geocode_rejects_non_admin` | NEW — technician role receives HTTPException(403) |

All 6 use `run_test(_f7_loop_fixture)` for loop-consistent Motor + `unittest.mock.patch` on `services.google_maps.geocoding.geocode_and_persist_customer` so no live Google API call is made in CI.

Run: `cd /app/backend && python3 -m pytest tests/test_customer_geocode_autosave.py -v` → **6 passed, 24 warnings, 6.16s**.

**Frontend** — `/app/frontend/src/test/customer-geocode-info.test.jsx` (NEW, 3 cases, all pass):

| # | Case |
|---|---|
| 1 | Populated state renders coords (4-decimal) + `(geocoded YYYY-MM-DD)` stamp, no button |
| 2 | Null state (admin role) renders "Location: unavailable" + `customer-regeocode-btn`; click posts `POST /customers/cust_2/geocode?force=true`, calls `onRefetch`, fires success toast |
| 3 | Null state (technician role) hides the button; `queryByTestId("customer-regeocode-btn")` is null |

Run: `cd /app/frontend && yarn vitest run src/test/customer-geocode-info.test.jsx` → **3 passed, 53 ms**.

Suite-adjacent regression check: `yarn vitest run src/test/customer-detail-top-action-stack.test.jsx` still **6 passed** — no CustomerDetail source-body invariants broken.

### 5. End-to-end verification (real Google API on preview)

Executed against `https://poolscape-audit.preview.emergentagent.com`:

```
POST /api/admin/customers/geocode-backfill?dry_run=true&limit=3
  → {"processed":3,"geocoded":0,"skipped":3,"failed":0,"dry_run":true,"would_geocode":[]}

POST /api/admin/migrations/backfill-customer-geocodes?dry_run=true&limit=3
  → {"processed":3,"geocoded":0,"skipped":3,"failed":0,"dry_run":true,"would_geocode":[]}
  (identical shape — alias confirmed)

POST /api/customers/seed-optimize-route-customer/geocode?force=true
  → {"ok":true,"lat":33.7670356,"lng":-112.3397496,"geocoded_at":"2026-09-10T21:57:54.543151+00:00"}
  (real Google hit against "1234 W Vistancia Blvd, Peoria, AZ 85383")

POST /api/customers/seed-optimize-route-customer/geocode   (no force, immediate re-run)
  → {"ok":false,"reason":"fresh_cache","lat":33.7670356,"lng":-112.3397496,"geocoded_at":"2026-09-10T21:57:54.543151+00:00"}
  (30-day cache short-circuit confirmed)

POST /api/customers/seed-optimize-route-customer/geocode   (customer role JWT)
  → HTTP 403 {"detail":"Manual geocode is admin/manager only"}
  (RBAC confirmed)
```

Screenshots (rendered on `poolscape-audit.preview.emergentagent.com`):
- Populated state: `/app/screenshots/customer-geocode-populated.png` — shows `Location: 33.7670, -112.3397 (geocoded 2026-09-10)` directly under the address line for customer `seed-optimize-route-customer`.
- Null state: `/app/screenshots/customer-geocode-null.png` — shows `Location: unavailable  🔄 Re-geocode` for customer `drift-dt-fd70e7` (has no service_address on file — the button will surface `reason: no_address` on click, which is a truthful diagnostic).

---

## Field schema (UNCHANGED — reused from Phase 17)

| Field | Type | Populated where |
|---|---|---|
| `latitude` / `longitude` | float | `services/google_maps/geocoding.py:214` (P37a canonical pair) |
| `service_lat` / `service_lng` | float | Same helper (`L210`) — legacy pair still written for Schedule Map / Dispatch Board reads |
| `service_location` | GeoJSON `{type:"Point",coordinates:[lng,lat]}` | Same helper (`L218-219`) — for 2dsphere queries |
| `geocoded_at` | ISO string | Same helper (`L216`) |
| `geocode_source` | `"google"` (or `"inherited_from_customer"` for jobs) | Same helper (`L217`) |
| `geocode_precision` | Google's `location_type` | Same helper (`L215`) |

**No new fields added.** No `geo_lat`, no `geo_lng`, no `geo_geocoded_at`, no `geo_geocoded_from_address` (Phase 17's field-diff mechanism in the update path is the equivalent-function alternative to `geo_geocoded_from_address`, and it's already in production).

---

## Backfill runbook

**Preview / staging dry-run** (no writes, no Google calls):
```bash
curl -X POST "$API_URL/api/admin/migrations/backfill-customer-geocodes?dry_run=true&limit=5000" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# → {processed, geocoded, skipped, failed, dry_run:true, would_geocode:[cust_id_1, ...]}
```

**Prod live-run** (Google API hits, writes to customer docs):
```bash
curl -X POST "$API_URL/api/admin/migrations/backfill-customer-geocodes?limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# → {processed, geocoded, skipped, failed, dry_run:false}
```

Rate control: `asyncio.sleep(0.1)` between calls in the loop ≈ 10 QPS, well under Google's per-second cap. Batch limit is 5000 max per request (safety guard). For catastrophic full-tenant backfill, prefer the CLI: `python -m migrations.task_p37_geocode_backfill --commit --tenant <id> --limit 5000`.

---

## Failure semantics

Every path FAIL-OPEN on the customer save:
- Provider timeout / REQUEST_DENIED / ZERO_RESULTS → `geocode_and_persist_customer` returns `False`, customer doc is NOT updated, no exception raised. `services/google_maps/geocoding.py:79-84` handles all four failure modes with `logger.warning`.
- Async task (Phase 17 create/update trigger) → `asyncio.create_task(...)` inside a `try/except: pass`. Any exception in the task is orphaned + logged by the event loop but doesn't affect the create/update endpoint's response.
- Manual endpoint → `try/except` around the helper call; caught exceptions surface as `{ok: false, reason: "provider_error", error: str(exc)}` in the response, no 5xx bubble.

---

## Rate-limit budget

- **Phase 17 create/update**: ~1 Google call per customer-create + 1 per address-changed-update. Amortized: negligible.
- **Manual button**: 1 Google call per click; requires admin+ role + `force=true` param. Not automated.
- **Backfill**: `sleep(0.1)` per row = ~10 QPS. Google's default Geocoding quota is 50 QPS + 50k/day per key. Backfill runs stay comfortably under.
- **Cache**: 30-day per-address cache in `db.geocode_cache` (ToS-compliant). Re-geocoding the same address within 30d is a cache hit, no Google call.

---

## Rollback

- Endpoint `POST /customers/{cid}/geocode` — new route; delete the ~95-LOC handler and its RBAC gate.
- Backfill `dry_run` + alias — revert the two-hunk diff on `dispatch_board.py:642-712`.
- `<CustomerGeocodeInfo>` — delete the component file + the two lines added to `CustomerDetail.jsx` (import + JSX insertion).
- Latent-bug fix (`_flatten_addr` on backfill) — revert the two-line change if desired, but note this reintroduces the 500 on customers with legacy dict-shape `service_address`.

No DB migrations, no field additions, no cache changes. Zero downstream schema impact.

---

## Test tally

| Suite | Passed | Time |
|---|---|---|
| `backend/tests/test_customer_geocode_autosave.py` (6 cases) | 6/6 | 6.16 s |
| `frontend/src/test/customer-geocode-info.test.jsx` (3 cases) | 3/3 | 53 ms |
| `frontend/src/test/customer-detail-top-action-stack.test.jsx` (regression) | 6/6 | 5 ms |
| **Total** | **15/15** | **~7 s** |

E2E verification against live preview backend: 4 curl assertions all pass (see §5 above).

---

## Follow-up tickets (log only — NOT built this ticket)

1. **`GEOCODE-STALE-FLAG-CLEANUP`** — Phase 17's field-diff mechanism means a customer whose `service_address` is set via a dict-shape schema-migration script may register as "unchanged" on subsequent PUTs even after a real address change. If we ever normalize `service_address` to a canonical string during migration, this trigger will fire spuriously. Consider adding `geo_geocoded_from_address` (the exact string used for the last successful geocode) as an audit-only field to catch these edge cases. Low priority — no user impact today.
2. **`GEOCODE-BACKFILL-DEFAULT-DRY-RUN`** — Consider flipping the `dry_run` default to `true` (opt-in-live). Would require updating one caller (the boot-time `geocode_backfill_all_tenants_boot` — but that one bypasses the endpoint and calls the helper directly, so no impact). Trade-off: safer default vs. one more query param on every intentional live call. Ping user before flipping.
3. **`GEOCODE-UI-VIP-SURFACE`** — Consider surfacing `geocode_precision` (`ROOFTOP` / `RANGE_INTERPOLATED` / `GEOMETRIC_CENTER` / `APPROXIMATE`) next to the coord line when precision is worse than rooftop. Helps ops identify addresses that need cleanup for tight-radius dispatch. Low priority.
