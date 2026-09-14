# Feature: Customer geocoding on save + one-time backfill

**Date**: Feb-2026
**Status**: Backend + web frontend complete. Server-side geocoding
is client-agnostic — no mobile parity work needed.

Formalises the auto-geocode-on-save automation (already partially
present as "Phase 17" on create/PUT) and adds an admin-only
backfill endpoint + button for the one-time cleanup of tenants
that already have unlocated customers on file.

---

## 1. Auto-geocode triggers

### On create — `POST /api/customers`

Runs on **every** successful create (pre-existing since Phase 17).
Feb-2026 additions:

* Stamps `geocode_address_hash` on the doc immediately (before the
  Google round-trip lands) — the hash is derived from
  `resolve_customer_address(doc)` via `sha1(lowercase whitespace-
  collapsed address)`. This lets a follow-up PUT with an
  unchanged address short-circuit without a second geocode.

### On update — `PUT /api/customers/{id}`

Fires when the RESOLVED address changes OR the stored
`geocode_address_hash` differs from the resolved address's hash.
Address detection now walks the FULL `resolve_customer_address`
fallback chain (was previously limited to `service_*`/
structured pairs):

| Priority | Field |
| -------- | ----- |
| 1 | `service_address` (free-form or dict) |
| 2 | `address` |
| 3 | `street_address` |
| 4 | `mailing_address` |
| 5 | structured composite (`service_street|street` + `service_city|city` + `service_state|state` + `service_zip|zip`) |

On change:

1. `$unset` `geocoded_at` so the 30-day cache doesn't short-circuit.
2. `$set` `geocode_address_hash` to the new hash — atomic same
   update.
3. Fire-and-forget `asyncio.create_task(geocode_and_persist_customer(...))`.
4. Failure (rate limit, ZERO_RESULTS, network) → `latitude` /
   `longitude` stay null, warning logged, no 500 to the caller.

Idempotency: an update that mutates only, say, `notes` skips the
geocode entirely — the hash comparison detects "resolved address
unchanged".

---

## 2. Backfill endpoint — `POST /api/admin/customers/backfill-geocoding`

**Auth**: `admin` / `super_admin` only. Anything else → 403.

### Query & counters

Scans customers where BOTH coord pairs are missing (`latitude` /
`longitude` AND legacy `service_lat` / `service_lng`) and that
resolve to a non-empty address via the fallback chain above.
Customers matching the "missing coords" filter but with no
resolvable address are counted as `skipped_no_address` and never
sent to Google.

### Sync vs. background threshold

| Queue size | Behaviour |
| ---------- | --------- |
| 0 rows | Return zeroed inline envelope. `enqueued: false`. |
| 1..20 rows | Run inline; return counters synchronously. `enqueued: false`. |
| > 20 rows | Hand off to `BackgroundTasks`; return `{enqueued: true, queue_size, estimated_seconds, message}` immediately. |

The estimate assumes **600 ms per row** (200 ms sleep + ~400 ms
Google round-trip).

### Rate-limit drip — 200 ms

`asyncio.sleep(0.2)` between rows. Google's default geocoding
quota is 50 QPS per project; 200 ms drip = 5 QPS which sits
comfortably an order of magnitude under. Trade-off: a 500-row
backfill takes ~5 min. Acceptable for a one-time admin action.

### Response shapes

**Inline:**

```json
{
  "scanned": 5,
  "updated": 4,
  "failed": 1,
  "skipped_no_address": 2,
  "enqueued": false
}
```

**Background handoff:**

```json
{
  "enqueued": true,
  "queue_size": 47,
  "estimated_seconds": 28,
  "skipped_no_address": 3,
  "message": "Backfill running in background — refresh in a few minutes to see updates (47 rows)"
}
```

### Audit log

Every completed batch (inline OR background) writes an entry to
`db.audit_logs`:

```json
{
  "tenant_id": "...",
  "action": "customer_geocode_backfill",
  "actor_user_id": "u-42",
  "at": "2026-02-14T15:30:00Z",
  "payload": {"scanned": 47, "updated": 45, "failed": 2, "skipped_no_address": 0}
}
```

Failure to write the audit log is swallowed — the counters go
back to the client regardless.

### Idempotency

`geocode_and_persist_customer` already 30-day-caches on
`geocoded_at`. Running the backfill a second time immediately
after a successful pass → every row's hash matches, cache is
fresh, 0 fresh updates.

### Curl recipes

```bash
API="$REACT_APP_BACKEND_URL/api"
T=$(curl -sX POST "$API/auth/login" \
      -H 'Content-Type: application/json' \
      -d '{"email":"super@aquaterra.com","password":"password123"}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# Kick off the backfill — response is either inline counts or
# an enqueued handoff envelope.
curl -sX POST "$API/admin/customers/backfill-geocoding" \
     -H "Authorization: Bearer $T" \
     -H 'Content-Type: application/json' -d '{}'

# Check audit log entries.
curl -s "$API/admin/audit-logs?action=customer_geocode_backfill&limit=10" \
     -H "Authorization: Bearer $T"
```

---

## 3. Frontend UX

### Admin Customers list — Backfill button

`frontend/src/pages/customers/CustomersList.jsx`. Mounted in the
`PageHeader.right` toolbar alongside Export / Import / Portal
Invite. Gated to `isAdmin` (admin + super_admin).

* Testid: `admin-customers-backfill-geocoding-btn`
* Icon: lucide `MapPinned` at 16 px
* Label: "Backfill missing GPS" (idle) / "Backfilling…" (busy)
* Disabled during the in-flight request.

Toast copy (via sonner):

| Response | Copy | Variant |
| -------- | ---- | ------- |
| `enqueued: true` | `Backfill running in background — refresh the list in a few minutes to see updates` | Neutral |
| `enqueued: false` | `Backfill complete: {updated} customers updated, {failed} failed, {skipped_no_address} skipped (no address)` | `toast.success` |
| Error | `Backfill failed: {message}` | `toast.error` |

All toasts render with `duration: 6000 ms` (long-form summary
gets a generous read time).

### Customer detail — location display line

`frontend/src/components/customers/CustomerGeocodeInfo.jsx`
(pre-existing component). Adds a hidden sibling `<span>` with
the spec testid `customer-location-display` alongside the
existing `customer-geocode-coords` handle — same **dual-testid
convention** as `/job-timers` filters. The visible copy is
unchanged: `Location: {lat.toFixed(4)}, {lng.toFixed(4)}`.

---

## 4. Files touched

| File | Change |
| ---- | ------ |
| `backend/routers/admin_customer_geocode_backfill.py` | **NEW** — router with `POST /api/admin/customers/backfill-geocoding` + `_unlocated_customers_query` + `_run_backfill` + `address_hash` helper. |
| `backend/server.py` | Wired `_admin_geo_backfill.router` into `api_router`. +1 OpenAPI path. |
| `backend/routers/customers.py` | `create_customer` stamps `geocode_address_hash` on insert; `update_customer` now walks the FULL `resolve_customer_address` fallback chain via hash comparison instead of a hard-coded key list — an unchanged address short-circuits without a second Google round-trip. |
| `frontend/src/components/customers/CustomerGeocodeInfo.jsx` | Added `customer-location-display` testid alongside the pre-existing `customer-geocode-coords` (dual-testid convention). |
| `frontend/src/pages/customers/CustomersList.jsx` | Mounted `BackfillGeocodingButton` in the admin toolbar; toast copy branches on `enqueued` flag. |
| `backend/tests/test_customer_geocode_backfill.py` | **NEW** — 6 tests: address-hash stability, auth 403, envelope contract, background-mode threshold, no-address counter, create-stamps-hash. |
| `frontend/src/test/customer-geocode-backfill.test.jsx` | **NEW** — 3 Vitest cases: dual-testid smoke, inline-toast copy, enqueued-toast copy. |
| `memory/FEATURE_CUSTOMER_AUTO_GEOCODE_AND_BACKFILL.md` | This memo. |

---

## 5. Test status

* **Backend** (`pytest tests/test_customer_geocode_backfill.py`)
  → **6 passed** (address_hash × 1, auth 403 × 1, envelope × 1,
  background threshold × 1, no-address counter × 1, create-stamps
  × 1).
* **Frontend** (`yarn test:unit`) → **582 files passed | 1 skipped
  · 4358 passed | 34 skipped** (was 4355 → **+3** matching the
  new file).
* **OpenAPI paths**: **1741** (was 1740 → **+1** for the new
  backfill endpoint — matches spec).

---

## 6. Out of scope

* Mobile parity — server-side geocoding is client-agnostic;
  mobile just reads `customer.latitude` / `longitude` from the
  API response.
* Any Google Maps API integration change — reuses existing
  `geocode_and_persist_customer` helper.
* Re-geocode button UI — already shipped in a prior phase
  (`FEATURE_CUSTOMER_MANUAL_REGEOCODE_UI.md`); this phase does
  NOT touch it.
* A–F backlog items.
