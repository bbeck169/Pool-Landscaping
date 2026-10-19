# TD-80 · Active Accounts count mismatch — audit

**Date:** 2026-02-18
**Scope:** Admin dashboard `Active Accounts` tile vs the Properties list it deep-links into.
**Phase:** AUDIT ONLY (no fix code). Awaiting operator approval of the recommended option before any ship.

**Operator-reported symptom:** Dashboard tile reports 290 active accounts on preview. Tapping the tile opens `/properties?is_active=true` and only 79 rows render. Delta = 211. Reproduces on web and mobile.

---

## 1 · Count aggregator path (produces "290")

### Entry point
`GET /api/dashboard` → `backend/routers/dashboard.py:174` →
`services.dashboard_property_category_counts.compute_property_counts(db=db, tenant_id=...)`.

Response field consumed by FE: `data.active_accounts_count` (`frontend/src/pages/admin/Dashboard.jsx:650`).

### Query shape (`backend/services/dashboard_property_category_counts.py:102-139`)

**Step A — resolve active customer ids** (`_active_customer_ids`, lines 86-99):

```python
customers.find({
    "tenant_id": TID,
    "$and": [
        {"$or": [{"is_active": True}, {"is_active": None}, {"is_active": {"$exists": False}}]},
        {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]},
    ],
}, {"_id": 0, "id": 1})
```

Short-circuit at line 124 if empty → all 4 counts return 0.

**Step B — count properties scoped to the active-customer id list** (lines 136-139):

```python
properties.count_documents({
    "tenant_id": TID,
    "$and": [
        {"$or": [{"active": True}, {"active": None}, {"active": {"$exists": False}}]},
        {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]},
    ],
    "customer_id": {"$in": active_cust_ids},     # ← PRIMARY JOIN KEY in the query
})
```

The parent-customer gate is applied **inside the Mongo query** via `$in`, so the count is exact across the entire tenant.

Result on preview primary tenant: **290**.

---

## 2 · List path (produces the "79-row" Properties list)

### Entry point
`GET /api/properties?is_active=true` → `backend/routers/properties.py:345-458 list_properties`.

FE caller: `frontend/src/pages/admin/properties/PropertiesListPage.jsx:215-235 fetchRows`. No explicit `limit`/`offset` → BE defaults: `limit=500, offset=0`.

### Query shape (two-pass pattern)

**Pass 1 — prelim property-level filter + fetch** (lines 396-435):

```python
q = {
    "tenant_id": TID,
    "active": {"$ne": False},                     # ← note: != False, not ==True-or-missing
    "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
}
prelim = await db.properties.find(q, {"_id": 0}).to_list(
    limit * 4 if is_active == "true" else limit + offset,
)
```

With `limit=500`, over-fetch cap = **2000**. Full prelim set on preview tenant: **5852 rows** → prelim is silently **truncated to 2000**. The remaining 3852 rows never reach pass 2.

**Pass 2 — parent-customer gate on the already-truncated prelim** (lines 438-455):

```python
cust_ids = list({r.get("customer_id") for r in prelim if r.get("customer_id")})
# ...customers.find({"id": {"$in": cust_ids}, ...<active+non-deleted>...}, {"_id": 0, "id": 1})
allowed = {c["id"] async for c in cust_cursor}
rows = [r for r in rows if r.get("customer_id") in allowed]
```

Of the 2000 truncated prelim rows, only **79** belong to parent customers that are still active.

**Pass 3** — final slice `rows[offset:offset + limit]` → still 79, no further truncation.

Result on preview primary tenant: **79**.

---

## 3 · Delta table

| Dimension | Aggregator | List | Match? |
|---|---|---|---|
| Tenant scope | `tenant_id == TID` | `tenant_id == TID` | ✓ same |
| Property active flag | `active IN {True, None, missing}` | `active != False` | ✓ **equivalent** (both match True/null/missing) |
| Property soft-delete | `deleted_at missing or None` | `deleted_at missing or None` | ✓ same |
| Parent customer active | `is_active IN {True, None, missing}` | `is_active IN {True, None, missing}` | ✓ same |
| Parent customer soft-delete | `deleted_at missing or None` | `deleted_at missing or None` | ✓ same |
| `service_category` | not applied (Active Accounts tile) | not applied (default route) | ✓ same |
| `is_muted` carve-out | not disqualifying | not disqualifying | ✓ same |
| Role gating | admin-only (`require_admin`) | admin-only (`require_admin`) | ✓ same |
| **Join strategy** | **Single Mongo query — `customer_id: {"$in": active_cust_ids}` baked in** | **Two-pass Python join on a `.to_list(limit*4)`-truncated prelim** | ✗ **DIVERGENT — root cause** |
| Over-fetch truncation | n/a (count_documents is unbounded) | **2000 (hard cap derived from `limit=500 × 4`)** | ✗ **lossy** |

**Every filter clause is semantically equivalent between the two paths.** The divergence is purely **structural**: the aggregator applies the parent-customer gate inside Mongo; the list applies it in Python *after* an over-fetch cap that is lower than the property-level prelim size.

---

## 4 · Preview DB probe (raw numbers)

Primary tenant: `Pool & Landscaping of Vistancia` (`affdfbfa-88b9-4baa-ae45-2ef78531b6e4`).

| Metric | Value |
|---|---|
| `customers` matching active-customer filter | **250** |
| `properties` matching property-level filter (unbounded) | **5852** |
| `properties` matching property-level filter (bounded, `to_list(2000)`) | **2000** |
| Unique `customer_id` on the 2000 bounded rows | 1,988 |
| Unique `customer_id` on the 5852 unbounded rows | 5,808 |
| 2000 bounded ∩ 250 active customers | **79** |
| 5852 unbounded ∩ 250 active customers | **290** |

Properties per active customer, top 10 (unbounded):
```
('c8f8ede9-...', 19), ('2f6d9ff3-...', 5), ('8910bfde-...', 4),
('seed-optimize-route-customer', 4), ('1e781f18-...', 3),
('255dd91a-...', 3), ('29431559-...', 3), ('554ac2b7-...', 3),
('a039de59-...', 3), ('cust-old-6daa751e-...', 3)
```

→ 250 active customers × ~1.16 avg properties = 290. Matches the aggregator exactly.

Every other tenant on preview has delta == 0 (either no properties or small enough prelim to fit under the 2000 cap). The bug only manifests on tenants whose **property-level prelim exceeds the over-fetch cap**, which maps directly to the Vistancia tenant's 5852-row property table (bulk of which is historical soft-deleted-customer + legacy-inactive property rows that still pass the property-level filter).

Probe script: `/tmp/td80_probe.py` (ephemeral — not committed).

---

## 5 · Hypothesis

**Primary (~100% confidence):** the over-fetch cap `limit * 4 == 2000` in pass-1 of `list_properties` truncates the property-level prelim BEFORE pass-2's parent-customer gate runs. Because inactive-/deleted-customer properties dominate the tenant's 5852-row prelim, the 2000-row slice happens to contain only 79 rows belonging to the 250 active customers. The aggregator never truncates (it uses `count_documents` on a filter that includes `customer_id: {"$in": active_cust_ids}` natively), so it correctly returns 290.

**Why historically hidden:** the previous P2 #6 tests (`test_dashboard_property_counts_commit2.py`) seed <10 property rows, well below the cap. The bug only surfaces in prod/preview-scale datasets with >2000 property rows carrying `active != False`.

**Secondary (not contributing — ruled out by the delta table):** no filter-clause drift between the two paths.

**Latent (adjacent bugs with the same root cause):** the **Pool / Landscaping / Both Service Customers tiles** deep-link to the same endpoint with `?is_active=true&service_category=...` and share the same two-pass pattern. On the preview tenant their list counts also silently truncate — operator has not yet reported this because the deltas are smaller (category filter reduces prelim size further), but the mechanism is identical.

---

## 6 · Fix strategy proposal

### Option (a) — align AGGREGATOR to the LIST filter
**Rejected.** The LIST filter is what's broken; the AGGREGATOR already uses the correct query shape. Flipping this direction would reduce the dashboard count to 79, which under-reports actual state.

### Option (b) — align LIST to the AGGREGATOR filter
Rewrite `list_properties` pass-1 to resolve `active_customer_ids` first (same `_active_customer_ids` logic as the aggregator) and bake the gate into the Mongo query:

```python
if is_active == "true":
    active_cust_ids = await _active_customer_ids(db=db, tenant_id=TID)
    if not active_cust_ids:
        return {"items": [], "limit": limit, "offset": offset, "returned": 0}
    q["customer_id"] = {"$in": active_cust_ids}
    q["active"] = {"$ne": False}
    q["$or"] = [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]
    rows = await db.properties.find(q, {"_id": 0}).skip(offset).limit(limit).to_list(limit)
```

Drops the two-pass + over-fetch entirely. The resulting rows are 1:1 identical with the aggregator's count semantics. **~15-line surgical change**, FE untouched, deep-link URL unchanged.

**Edge case to preserve:** the `customer_id` query param already in the function (line 410-411). When both `is_active=true` AND `customer_id` are supplied, the resulting `$in` set should be `[customer_id]` IF the explicit customer passes the active gate, else `[]`. Logic to retain intersection semantics.

### Option (c) — shared predicate helper
Lift `_active_customer_ids` + `_active_property_match_base` out of `services/dashboard_property_category_counts.py` into a new `services/properties_active_predicate.py` (or similar) and consume from both call-sites. Both the AGGREGATOR (`compute_property_counts`) and the LIST (`list_properties`) import the single source of truth. Semantically a superset of (b).

**Blast radius:**
- 1 new module (`services/properties_active_predicate.py`, ~40 LOC).
- 1 refactor of `services/dashboard_property_category_counts.py` to import from the new module (back-compat preserved).
- 1 rewrite of `routers/properties.py::list_properties` pass-1 (same as option b).
- Pytest coverage: new unit tests for the shared predicate + a parity test asserting `count_documents(agg_query) == len(list_query_rows)` on a fixture tenant.

Can ship as 2 atomic commits:
- `td80-be-a · shared active-property/active-customer predicate helper`
- `td80-be-b · align /api/properties list to shared predicate (fixes Active Accounts delta)`

OR 1 commit if operator prefers tight batching.

### 🟢 RECOMMENDATION: Option (c)

Rationale:
1. The AGGREGATOR already has the correct logic; extracting it to a shared helper eliminates copy-paste drift risk permanently.
2. The 3 category tiles (Pool / Landscaping / Both Services) share the same two-pass pattern via `?is_active=true&service_category=...` — option (c) fixes those too in the same ship.
3. Blast radius is small (~60 LOC net across 2-3 files), locked by new unit tests + parity test.
4. Follow-up ship is well-defined (1-2 commits) — operator can scope accordingly.

If operator wants minimum change, option (b) is also valid — it fixes the Active Accounts bug exclusively but leaves the Pool/Landscaping/Both tiles silently truncating under the same mechanism. Not recommended given the latent-bug surface.

---

## 7 · Downstream touch map

| Call-site | Collection | Reads active-property predicate? | Impact of fix |
|---|---|---|---|
| `backend/routers/dashboard.py:174` → `compute_property_counts` | `properties`, `customers` | ✓ **primary consumer** of the aggregator | None — aggregator is already correct. Option (c) refactors imports only; counts unchanged. |
| `backend/routers/properties.py:345 list_properties` | `properties`, `customers` | ✗ **primary bug site** | Counts rise to match aggregator (Active Accounts: 79 → 290 on preview). Pool / Landscaping / Both category counts also rise where their truncated subset was lossy. |
| `backend/tests/test_dashboard_property_counts_commit2.py` | n/a (unit) | Covers aggregator | Must stay green post-refactor. Add parity test asserting agg == list on a 5000-row property fixture. |
| `frontend/src/pages/admin/Dashboard.jsx:650` | n/a (consumer) | Reads `data.active_accounts_count` | None. |
| `frontend/src/pages/admin/properties/PropertiesListPage.jsx:215` | n/a (consumer) | Issues `GET /api/properties?is_active=true` | None (same URL, same response shape — more rows). |
| `backend/routers/estimates.py:192 active_props = ...` | `properties` | Appears to filter by active, but context-specific (estimate-eligible) | **Out of scope.** Separate call-site for the New Estimate wizard. No tile deep-link. |
| `backend/routers/jobs.py:1605 active_props = ...` | `properties` | Same — recurring-job scheduler active-property lookup | **Out of scope.** No tile deep-link. |

No report / export / email surface currently consumes the raw list rows for a count — all count surfaces route through the aggregator. **The fix is contained to the one list endpoint.**

---

## 8 · Fix sizing summary (for operator scoping)

- **Option (c) recommended:** ~60 LOC net, 2 commits (`td80-be-a shared predicate helper`, `td80-be-b align list_properties to predicate`), low risk, locks parity via new tests.
- **Option (b) minimum:** ~20 LOC, 1 commit, fixes Active Accounts bug only — Pool/Landscaping/Both tiles remain latently lossy.
- No FE change required for either option.
- No `/app/mobile/` touch required for either option (the mobile client issues the same `GET /api/properties?is_active=true` URL — fixing the BE fixes mobile transparently).

**Awaiting operator greenlight on option + commit cadence.**
