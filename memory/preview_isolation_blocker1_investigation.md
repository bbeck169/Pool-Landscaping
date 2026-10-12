# Preview Isolation · Stage 3 Finalization · Blocker 1 Investigation

**Commit:** I1 (doc-only, no code change)
**Phase:** P0a Stage 3 final-verification — Blocker 1 (`customers.geocode_address_hash` RED, 4 rows)
**Date:** Feb-2026
**Author:** preview-isolation remediation agent

---

## 1. Tester-reported symptom

`GET /api/admin/preview-isolation-status` returned:

```
overall_status: "RED"
pii_shape_audit.status: "RED"
customers_with_real_pii_shape: 4
```

All 4 offenders were on `customers.geocode_address_hash` — 40-char SHA-1 hex
strings beginning with `c…` / `8…` / `3…` / `d…`.

Audit rule triggering the RED (`routers/preview_isolation_admin.py:203-204`):

```python
{"coll": "customers", "field": "geocode_address_hash",
 "filter": {"geocode_address_hash": {"$exists": True, "$ne": None}}},
```

→ Rule flags *any* non-null `geocode_address_hash` as PII.

---

## 2. Investigation — direct DB readout + hash equivalence check

Query (preview DB, no filtering):

```python
db.customers.find({"geocode_address_hash": {"$exists": True, "$ne": None}})
```

Returned 4 rows. For each, recomputed `address_hash(…)` (the stable
hasher defined at `routers/admin_customer_geocode_backfill.py:48`,
SHA-1 of `" ".join(addr.strip().lower().split())`) over every candidate
source field (`address`, `service_address`, `street_address`,
`mailing_address`, `address_line1`). Matched the result against the
stored `geocode_address_hash`.

### Result — all 4 hashes match the SYNTHETIC `address` field

| Customer                      | Stored `geocode_address_hash`               | Source string hashed | Match |
|-------------------------------|---------------------------------------------|----------------------|-------|
| Preview Customer4163          | `ced5f8c1109f5a31bb4d014130877b4eb94554aa`  | `"4163 Preview St"`  | ✅    |
| Preview Customer7204          | `8ed060a51dab9ab5588d598aeaa52061814ac905`  | `"7204 Preview St"`  | ✅    |
| Preview Customer2952          | `31781869f33476e19840b28761ff815b8fb191e4`  | `"2952 Preview St"`  | ✅    |
| Preview Customer0085          | `d900686ed988db7896e7855ba28efe848b16b21f`  | `"85 Preview St"`    | ✅    |

Two of the four (`Preview Customer2952`, `Preview Customer0085`) are the
same bucket slugs the tester created during this verification run,
confirming the hashes were stamped by the create path — not an older
scrub-missed artifact.

---

## 3. Root-cause trace — order of operations is CORRECT

1. `PreviewMiddleware.__call__` (ASGI middleware, `middleware.py:62`)
   intercepts `POST /api/customers` with `Content-Type: application/json`
   on preview env.
2. Middleware calls `sanitize_pii_payload(parsed, kind="customer")` →
   `_sanitize_dict` → `synthesize_customer_fields` →
   `address_line1 = "<bucket> Preview St"`, `address = "<bucket> Preview St"`,
   `geocode_address_hash = None` (synthesizer explicitly nulls, line 173).
3. Rewritten body is replayed to FastAPI handler.
4. `create_customer` (`routers/customers.py:1917`) receives the already-
   sanitized body. `doc = body.dict()` → `doc["address"]` is now
   `"<bucket> Preview St"`.
5. `_resolve_addr17(doc)` returns the first non-empty field in priority
   order (`services/google_maps/geocoding.py:76`): `service_address` →
   `address` → `street_address` → `mailing_address`. For the 4 offenders
   `service_address` was empty, so it returned `address`, i.e.
   `"<bucket> Preview St"`.
6. `_addr_hash17("<bucket> Preview St")` computes `sha1(norm)` of the
   synthetic string → stamped into `customers.geocode_address_hash`.

**The hash that lands in the DB is a SHA-1 of a public, deterministic
synthetic string.** It is NOT a hash of real PII. There is no correlation
attack surface — every real customer whose anchor hashes into
`bucket 4163` will have the identical `geocode_address_hash` on preview,
which is the opposite of a correlation leak (it's a many-to-one anonymizing
collapse, consistent with the synthesizer's design intent for every other
field).

---

## 4. Decision tree evaluation

| Option | Verdict | Reason |
|--------|---------|--------|
| **A** — reorder so geocode runs on synthetic | **N/A — already correct** | Order of operations is already synth-before-geocode. No code to reorder. |
| **B** — null `geocode_address_hash` on preview POSTs | **Rejected** | Would drop a legitimate preview-admin workflow (geocode idempotency check works correctly on synthetic data). Hash-of-synth is harmless. |
| **C** — exempt field from audit (with proof) | **ACCEPTED** | Hash is provably derived from the already-synthesized `address` field. Not PII. The audit rule is the false-positive, not the data. |

---

## 5. Chosen fix (Commit I2 — scope preview)

Narrow the audit rule in `routers/preview_isolation_admin.py:203-204` to
flag `geocode_address_hash` **only** when the customer's address fields
do NOT match the synthetic preview pattern. If any of
`address` / `address_line1` / `service_address` starts with
`^\d+ Preview\b`, the row is known-synthetic → the hash is of synthetic
data → do not flag.

Proposed replacement (committed in I2):

```python
{"coll": "customers", "field": "geocode_address_hash",
 "filter": {"$and": [
     {"geocode_address_hash": {"$exists": True, "$ne": None}},
     # Only RED when the customer's address itself looks REAL. If the
     # address is already synthetic, the hash is of synthetic data and
     # carries zero PII-correlation signal (see I1 investigation doc).
     {"$nor": [
         {"address":         {"$regex": r"^\d+ Preview\b", "$options": "i"}},
         {"address_line1":   {"$regex": r"^\d+ Preview\b", "$options": "i"}},
         {"service_address": {"$regex": r"^\d+ Preview\b", "$options": "i"}},
     ]},
 ]}},
```

Backing invariant: `synthesize_customer_fields` writes `address` /
`address_line1` as `"<bucket> Preview St"` for every preview POST
(`synthesizer.py:137-139`), and the `address_line1` audit rule
already enforces `^\d+ Preview\b` as the synthetic-signature check
(`preview_isolation_admin.py:190-192`). We reuse the exact same
signature.

### Why NOT just drop the rule outright
Keeping the rule in composite form preserves the detector for the real
threat case: a legacy row that still has a `geocode_address_hash`
stamped from a real address (which the Jan-2026 synthesizer did not
null). Those rows would have a non-synthetic `address` field AND a
non-null hash → the composite filter still flags them → scrubber
rescues → audit returns GREEN after cleanup.

---

## 6. Scrubber force-run

No scrubber force-run required for Blocker 1. The 4 offender hashes are
of synthetic data and remain valid preview geocode-idempotency keys.
After the audit-rule narrowing in I2, the healthcheck will return GREEN
without any DB mutation.

(The Commit G scrubber-force run from the prior session already drained
every genuine real-PII hash. Any hash remaining is by construction a
hash of the post-decorator synthetic address.)

---

## 7. pytest additions (Commit I2)

New file: `backend/tests/test_preview_isolation_i2_geocode_hash_audit.py`

1. `test_geocode_hash_of_synthetic_address_is_not_flagged`
   Seed a customer with `address = "4242 Preview St"` and
   `geocode_address_hash = address_hash("4242 Preview St")`. Run the
   audit rule's filter against the DB. Expect 0 matches.

2. `test_geocode_hash_of_real_address_IS_flagged`
   Seed a customer with `address = "123 Oakwood Dr"` and a non-null
   hash. Run the same filter. Expect 1 match (the detector still catches
   genuine real-PII hashes).

3. `test_create_preview_customer_stamps_synthetic_geocode_hash`
   End-to-end via FastAPI test client: POST a customer with a REAL
   address through the preview-middleware pipeline, then GET the row.
   Assert `geocode_address_hash` equals `address_hash("<bucket> Preview St")`
   (i.e. hash of synth, NOT hash of the submitted real address).

4. `test_audit_rule_returns_green_after_preview_create`
   After step 3's POST, hit `_run_pii_shape_audit()` and assert
   `per_field_counts["geocode_address_hash"] == 0`.

---

## 8. Deliverables summary

- [x] Investigation complete — Option **C** confirmed (hash-of-synth).
- [ ] Commit I1 — persist this doc.
- [ ] Commit I2 — narrow audit rule + 4 new pytest cases.
- [ ] Commit I3 — gate route-registration on `APP_ENV` (Blocker 2, separate scope).
- [ ] Commit I4 — document phone format in `/app/memory/preview_tenants.md` (Non-blocker 3, separate scope).
