# Fix — Customer address update + display concat glitch

**Phase**: Feb-2026 · P0 URGENT bugfix  
**Scope**: web + backend (admin desktop). Mobile parity out of scope.

## Root-cause analysis

### Symptom A — `LorealLoreal10616 W Carlota Ln` malformed render

**Not a code bug.** The customer detail card at
`pages/customers/CustomerDetail.jsx::getPrimaryPropertyAddress`
renders `properties[0].address.line1` + `city, state zip`
verbatim, with no prefix concatenation. Direct Mongo query on
customer `d9318a69-ac8f-40c6-841a-43a4e1e3ab0f`
(name `Dheaa Toma`) showed the DB itself held:

```
customer.address           = "LorealLoreal10616 W Carlota Ln, Peoria, AZ, 85383"
customer.address_line1     = "LorealLoreal10616 W Carlota Ln"
customer.service_address   = { street: "LorealLoreal10616 W Carlota Ln", ... }
properties[0].address.line1 = "LorealLoreal10616 W Carlota Ln"
```

Only this ONE customer is affected (broad-search across all
name / address / business_name / first_name fields returned
zero other rows with the "Loreal" substring). The corruption
was almost certainly a one-off hand-edit or a legacy import
that concatenated a stale label into the street field. The
frontend rendered exactly what was in Mongo.

**Cleanup** — applied in-place to the sole affected record
(customer `d9318a69-…` + property `a5ac99a3-…`):

```python
db.customers.update_one({'id': CID}, {'$set': {
    'address': '10616 W Carlota Ln, Peoria, AZ, 85383',
    'service_address.street': '10616 W Carlota Ln',
    'address_line1': '10616 W Carlota Ln',
}})
db.properties.update_one({'id': PID}, {'$set': {
    'address.line1': '10616 W Carlota Ln',
}})
```

No bulk migration executed — the corruption is confirmed
scoped to one row.

### Symptom B — Edit form Save "doesn't persist"

**Real bug.** The customer PUT handler at
`routers/customers.py::update_customer` did
`db.customers.update_one({'id': cid}, {'$set': payload})` and
STOPPED there — but the customer detail card reads its primary
address from **`db.properties`**, not from the customer doc:

```jsx
// CustomerDetail.jsx line 493
const oneLine = getPrimaryPropertyAddress(properties);
```

Compound issue: `CustomerIn` (models.py) exposes only the FLAT
`address` string — it does NOT accept `address_line1`, `city`,
`state`, `postal_code`, or the nested `service_address` object.
Frontend `CustomerForm.submit` composes structured fields
into the free-form via `_composeAddress` and PUTs
`{ address: "222 New Ave, Peoria, AZ 85383" }`.

Downstream, `resolve_customer_address` reads the STALE nested
`service_address` dict first (still contains the old street),
so `_addr_changed` was falsely computed as `False` → the
existing auto-geocode side-effect was skipped AND nothing
touched the property row → save appeared to no-op on the
detail card.

### Symptom C — "Google Places load failed" banner

`components/AddressAutocomplete.jsx` renders a small inline
error line when the Places SDK boot fails. The underlying
`<input>` continues to accept manual entry regardless — the
save has NEVER been gated on Places loading. Only the copy
was scary.

## Fix

### Backend — primary-property address mirror

New helper in `routers/customers.py` — `_mirror_address_to_primary_property(cid, tenant_id, customer_merged)`:

- Parses the flat `address` string FIRST (matches
  frontend `_parseAddress`), because `CustomerIn` doesn't
  expose structured fields — the parsed values are the
  authoritative source-of-truth for a PUT.
- Supports both `"street, city, STATE ZIP"` and
  `"street, city, STATE, ZIP"` layouts (the FE composer has
  produced both shapes across phases).
- Structured merged fields + nested `service_address` object
  fill in any gaps the parser leaves.
- Resolves the primary property via
  `is_primary=True` → lowest `sort_order` → skips (zero-property
  customers are covered by the existing lazy backfill in
  `list_customer_properties`).
- Writes `$set` on the resolved property row for `line1`,
  `city`, `state`, `postal_code`. Non-destructive — country /
  line2 / geocode / assignments / notes stay untouched.

New trigger clause inside `update_customer`:

```python
_flat_before = (existing.get("address") or "").strip()
_flat_after = (payload.get("address") or "").strip()
_mirror_trigger = _addr_changed or _flat_before != _flat_after
if _mirror_trigger:
    await _mirror_address_to_primary_property(cid, tenant["id"],
                                                 _merged_after)
```

The independent `_flat_before != _flat_after` check works
around the `CustomerIn` field-stripping issue — even when
`resolve_customer_address` picks the stale nested value on
the merged doc, a diff on the FLAT `address` still fires the
mirror.

### Frontend — Places banner copy

`components/AddressAutocomplete.jsx` — the two `setError(...)`
call sites that used to emit `"Google Places load failed"`
now emit `"Autocomplete unavailable — you can still type the
address manually."`. Same testid, same non-blocking behaviour
(the underlying input always accepts manual entry); the copy
now matches the existing `!keyAvailable` branch.

## Save flow trace (post-fix)

```
CustomerForm.submit()
  → api.put(/customers/{id}, {address: "222 New Ave, …", ...})
    → update_customer()
      → db.customers.update_one({$set: payload})
      → _addr_changed OR flat address diff detected
        → _mirror_address_to_primary_property()
          → resolve primary property (is_primary → sort_order 0)
          → db.properties.update_one({$set: {"address.line1": …,
                                                "address.city": …,
                                                "address.state": …,
                                                "address.postal_code": …}})
      → optional re-geocode fan-out (existing logic, unchanged)
    → response body includes updated customer doc
  → CustomerDetail refetches /customers/{id}/properties
  → detail card shows the NEW address
```

## Cleanup recipe (per-record, no bulk)

Admin can run this from any Python shell with Mongo access:

```python
from pymongo import MongoClient
from dotenv import dotenv_values
env = dotenv_values('/app/backend/.env')
db = MongoClient(env['MONGO_URL'])[env['DB_NAME']]

CID = '<affected-customer-id>'
CLEAN_STREET = '<the correct street>'
CLEAN_ADDR = f'{CLEAN_STREET}, <city>, <STATE>, <zip>'

db.customers.update_one({'id': CID}, {'$set': {
    'address':          CLEAN_ADDR,
    'address_line1':    CLEAN_STREET,
    'service_address.street': CLEAN_STREET,
}})

pid = db.properties.find_one(
    {'customer_id': CID, 'is_primary': True}
)['id']
db.properties.update_one({'id': pid}, {'$set': {
    'address.line1': CLEAN_STREET,
}})
```

Do NOT run a bulk sweep — corrupted addresses are diagnosed
per-record before mutation.

## Places load-failed handling

- Autocomplete component was **already** non-blocking — the
  `<input>` accepts manual typing regardless of SDK boot
  outcome. Save flow never depended on Places.
- Copy softened so a hiccup doesn't look like a save failure.
- No env var changes; existing runtime-fetch chain
  (`GET /api/config/maps` → `REACT_APP_GOOGLE_MAPS_API_KEY`
  fallback) untouched.

## Test coverage added

Backend — `tests/test_customer_address_property_mirror.py`:

- `test_put_customer_address_mirrors_to_primary_property` —
  end-to-end PUT with the standard 3-part composed address
  updates the primary property row.
- `test_put_with_freeform_address_only` — bare
  `address = "333 Freeform Rd, Peoria, AZ 85383"` (no
  structured fields) still triggers the mirror via the
  free-form parser.
- `test_put_without_address_change_leaves_property_alone` —
  notes-only edit doesn't touch the property row (no
  needless churn / re-geocode).
- `test_repeat_prefix_address_does_not_get_doubled` —
  regression guard for the `LorealLoreal` shape — a
  literal `"Loreal10616 W Carlota Ln"` written once must
  NOT get doubled anywhere in the save/mirror path.

**All 4 pass.** Adjacent regression suites
(`test_customer_detail_tabs.py`,
`test_customer_equipment_library.py`) green — no
new regressions from the mirror helper. Two pre-existing
failures (`test_customer_detail_additions.py::test_third_mobile_rejected_with_400`,
`test_customer_delete_ux.py::test_hard_delete_does_not_cascade_and_orphan_jobs_still_read_ok`)
are unrelated baseline drift — neither touches address /
property mirror code.

## API surface

**No new endpoints.** OpenAPI paths stable at **1749**. The
mirror helper is a side-effect on the existing
`PUT /customers/{cid}` handler.

## Out of scope

- Mobile parity (admin desktop only).
- Bulk address-corruption sweep (per-record only).
- Legacy nested `service_address` deprecation — a bigger
  refactor tracked separately.
- `CustomerIn` model expansion to include
  `address_line1`/`city`/`state`/`postal_code` — not needed
  for this fix; the free-form flat `address` remains the
  API contract.
