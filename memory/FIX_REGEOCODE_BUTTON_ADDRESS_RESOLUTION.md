# FIX — Re-geocode button falsely reports "no address on file"

**Severity:** Customer-facing (P0). Both preview and production ship the bug until redeploy.  
**Reported:** Customer detail page for "Rochelle Vanderpool" shows a valid street address, but clicking the "Re-geocode" button toasts **"No address on file — add a service address first."**  
**Repro:** Any customer whose only populated address field is `address` (or `street_address` / `mailing_address`) — the display renderer reads from `address` but the geocode path was hardcoded to `service_address` + the legacy structured fields.

## Root cause

Two backend read paths hardcoded the fallback chain to `service_address` → `service_street/city/state/zip` → bare `street/city/state/zip`. Neither read from the plain `address` field the display renderer uses. Result: customers whose data landed on `address` via a legacy import or the admin manual-add form always got the `no_address` branch on the diagnostic step, regardless of what the customer detail page showed.

Sampled DB confirmation:

```
customer 8910bfde-… (Jennifer Carson):
  address:         "12 Vistancia Blvd, Peoria, AZ"
  service_address: null    ← old fallback stopped here
```

## Fix

**Single shared resolver** — `backend/services/google_maps/geocoding.py::resolve_customer_address(customer)`. Reads every historical address field in a documented priority order:

```
1. service_address    (may be a dict; flattened via _flatten_addr)
2. address            (the field the display renderer reads)
3. street_address
4. mailing_address
5. structured composite (service_street/city/state/zip OR bare street/city/state/zip)
```

Returns the first non-empty trimmed string. Returns `""` only when EVERY field is empty — that's the genuine `no_address` signal callers should honor.

**Both call sites rewired:**
- `services/google_maps/geocoding.py::geocode_and_persist_customer` (nightly + on-write path) — line ~196.
- `routers/customers.py::customer_manual_geocode` diagnostic branch — line ~1830 (`no_address` reason emitter).

**Frontend mirror** — `frontend/src/components/customers/CustomerGeocodeInfo.jsx::resolveCustomerAddress(customer)` uses the identical priority order. The `handleReGeocode` click handler short-circuits BEFORE the network round-trip when the resolver returns `""`: the toast fires locally, no wasted POST. When ANY field resolves, the button posts as before and the backend now finds the address end-to-end.

## Contract note — display vs geocode

Whenever the display renderer picks up a new address field (say, a future `service_property_address`), it MUST be added to `resolve_customer_address` in BOTH:

- `backend/services/google_maps/geocoding.py::resolve_customer_address`
- `frontend/src/components/customers/CustomerGeocodeInfo.jsx::resolveCustomerAddress`

Add a pytest case in `test_regeocode_address_resolution.py` to lock the new priority position. A guardrail assertion in `test_manual_geocode_endpoint_uses_shared_helper` already catches copy-paste regressions that resurrect the old inline fallback.

## Prevention tests

### Backend — `backend/tests/test_regeocode_address_resolution.py` (**14 passed**)

- Priority order across `service_address` → `address` → `street_address` → `mailing_address` → structured composite.
- Dict-shape `service_address` flattens via P37b tolerant read.
- Whitespace-only / null fields fall through so lower-priority fields keep a chance to match.
- Empty result only when every field is empty.
- Source-scan guardrail — the manual-geocode endpoint MUST import + use `resolve_customer_address`, AND MUST NOT re-inline the old fallback chain.

### Frontend — `frontend/src/test/customer-regeocode-address-resolution.test.jsx` (**9 passed**)

- `resolveCustomerAddress` mirrors the backend priority (including dict-shape `service_address`).
- Customer with only `address` populated → click fires `POST /customers/{id}/geocode?force=true` and does NOT toast "No address on file".
- Customer with NO address anywhere → toast fires and NO POST is issued.
- Customer with only `mailing_address` populated → click DOES fire POST.

### Existing test updated — `frontend/src/test/customer-geocode-info.test.jsx`

The happy-path click test seeded a customer with no address at all — post-fix the short-circuit blocked the POST. Test now seeds `address: "5542 W Big Oak St, Phoenix, AZ 85083"` on the fixture (the exact Rochelle repro address) so the click continues to post as before.

## Out of scope (queued phases, do NOT expand)

- Auto-geocoding on customer save — queued as a separate larger phase.
- One-time backfill of all customers currently missing `latitude/longitude` — queued.
- Any A–F backlog items.

## Files touched

- `backend/services/google_maps/geocoding.py` — new `resolve_customer_address` helper + updated `geocode_and_persist_customer` call site.
- `backend/routers/customers.py` — `customer_manual_geocode` diagnostic branch uses the shared helper.
- `frontend/src/components/customers/CustomerGeocodeInfo.jsx` — `resolveCustomerAddress` export + click-handler short-circuit.
- `backend/tests/test_regeocode_address_resolution.py` (new · 14 tests).
- `frontend/src/test/customer-regeocode-address-resolution.test.jsx` (new · 9 tests).
- `frontend/src/test/customer-geocode-info.test.jsx` (happy-path fixture seeded with an address).
- `memory/FIX_REGEOCODE_BUTTON_ADDRESS_RESOLUTION.md` (this doc).

## Rollout note

Preview build carries the fix. Production at `https://app.plofv.com` still runs the pre-fix bundle — user needs to redeploy to push the address-resolution helper live.
