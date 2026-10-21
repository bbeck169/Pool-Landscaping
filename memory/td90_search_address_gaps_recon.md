# TD-90-search-address-gaps · Phase 1 Recon

**Scope:** add address matching to the `jobs` + `leads` buckets on `GET /api/search`. BE-only this cycle. No FE changes expected (hit shape unchanged).

**Phase 1 = recon only. No code.**

---

## 1. Current state — jobs + leads match fields

### Jobs handler (`backend/routers/global_search.py:144-156`)

```python
async def _search_jobs(tenant_id: str, q: str, limit: int) -> List[dict]:
    query = _tenant_filter(tenant_id, q, ["title", "customer_name"])
    proj = {"_id": 0, "id": 1, "title": 1, "customer_name": 1, "status": 1}
    docs = await db.jobs.find(query, proj).limit(limit).to_list(limit)
    …
```

**Current match fields:** `title`, `customer_name`. **No address field in the match set.** Hit secondary is `customer_name | status`.

### Leads handler (`backend/routers/global_search.py:224-246`)

```python
query = {
    "tenant_id": tenant_id,
    "status": {"$in": _ACTIVE_LEAD_STATUSES},
    "$and": [
        _not_deleted(),
        {"$or": _build_or_regex(q, ["name", "email", "phone"])},
    ],
}
proj = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "status": 1}
```

**Current match fields:** `name`, `email`, `phone`. **No address field in the match set.** No digit-normalization on phone (unlike customers).

### Match helpers — reusability confirmed

- `_build_or_regex(needle, fields)` (`global_search.py:69-72`) — `re.escape` + `{$regex, $options: "i"}` per field. **Directly reusable** for address substring matching (both jobs + leads are plain strings).
- `_phone_digit_regex(needle)` (`global_search.py:75-89`) — digit-normalized phone-only matcher. **Not applicable** to address.
- `_tenant_filter(tenant_id, needle, fields)` (`global_search.py:92-104`) — composes `tenant_id` + `_not_deleted()` + `$or` $regex. **Directly reusable** — jobs handler already uses it; add new fields to the list.

**Precedent:** `_search_customers` (lines 107-141) already matches `["name", "email", "phone", "address", "billing_address"]` — the pattern we need to mirror on jobs + leads already exists one function up.

---

## 2. Address field inventory

### `db.jobs` — fields in play

| Field | Source | Notes |
|---|---|---|
| `address` | `models.JobIn:270` + persisted on `db.jobs` | Primary snapshot address. Confirmed non-empty on preview jobs (sample: `"8616 Preview St"`). TD-schedule-address-be shipped the read-time FK ladder but did NOT remove `jobs.address` — the snapshot stays as a search-indexable field by design. |
| `property_address` | computed read-time by `routers/jobs.py:1335` + resolved via `services/address_resolver.py` | NOT persisted — hydrated into `GET /jobs/:id` response only. **Not usable in search queries** without a join. |
| `site_address` | referenced as a fallback by `services/address_resolver.py` (rung 4) | Field exists on some legacy snapshots but is not in `JobIn`. Rare on preview — grep found no documented writes beyond the snapshot ladder. |

**Recommended match field for jobs:** **`address` only.** `site_address` would add noise with zero signal on fresh tenants and tiny signal on legacy ones. Skip.

### `db.leads` — fields in play

| Field | Source | Notes |
|---|---|---|
| `address` | `models.LeadIn:760` + `PublicLeadIn` via `service_address` fold | Primary address. Non-empty on preview leads (sample: `"1 Preview Ln, Testville, AZ 85000"`). |
| `service_address` | `models.LeadIn:761` + `LeadUpdate:777` + `PublicLeadIn:798` | Alternative/alias field. Often populated by the Google-Places autofill path on the lead form. Can diverge from `address` when operator edits one but not the other. |
| `city` | present on live docs (not in `LeadIn` schema — observed field) | Operators sometimes stash city in a separate column. Low signal; usually subsumed by `address`. |
| `zip` | present on live docs (not in `LeadIn` schema — observed field) | Same as `city`. |

**Recommended match fields for leads:** **`address` + `service_address`.** Both are schema-declared; both can hold the current address depending on which flow created the lead. `city` + `zip` are observed-but-undeclared and low ROI — skip (operator searching by zip is rare; `address` substring already catches it when zip is appended to the address string).

### FK-ladder resolution for search — trade-off call

**Should jobs search match on the FK-ladder-resolved address (`job.property_id → properties.address`)?**

**Recommendation: NO.** Reasons:

1. **Performance cliff.** The ladder resolver does per-row lookups across `properties` + `customers` (TD-schedule-address-be uses batched pre-fetch, which works because the schedule page returns ≤100 jobs/day). Search returns 5 jobs at `limit=5` default, but the Mongo query must still MATCH over all 9k+ docs before the limit applies — matching via the ladder would require an aggregation `$lookup` × 2, with a `$match` on a computed field that cannot use any index.
2. **Operator mental model.** Operators searching by address usually recall the historical/pinned form that lived on `jobs.address` at the time. The denorm snapshot is actually the right thing for *search recall*.
3. **TD-schedule-address-be scope guard.** That ticket fixed stale-render, not stale-storage. The whole architectural choice there was *read-time resolve for display, snapshot for storage*. Search is a storage read, so it stays on the snapshot.
4. **Stale-snapshot acceptance.** If a job's `jobs.address` is stale, the hit still routes to the correct job id — the operator opens the job and sees the fresh resolved address. Zero correctness loss, just a minor UX seam.

If an operator later complains that "search can't find a job by its *current* property address," the fix is TD-schedule-address-write-through (store the resolved address on write) — separate ticket, out of scope here.

---

## 3. Match semantics proposal

### Jobs — add `address` to `_search_jobs`

```python
# Proposed (NOT shipping)
query = _tenant_filter(tenant_id, q, ["title", "customer_name", "address"])
proj  = {"_id": 0, "id": 1, "title": 1, "customer_name": 1,
         "status": 1, "address": 1}
```

**Hit shape:**
- `primary` unchanged (`title | "(untitled job)"`).
- `secondary` — currently `customer_name | status`. Option A: keep unchanged (address only used as a *matching* signal). Option B: fall through to `address` when `customer_name` is empty. **Recommend A** — keeps hit shape stable and FE needs no change. If operators want address in the row display, add it as a tertiary line in a follow-up FE ticket.

### Leads — add `address` + `service_address` to `_search_leads`

```python
# Proposed (NOT shipping)
query = {
    "tenant_id": tenant_id,
    "status": {"$in": _ACTIVE_LEAD_STATUSES},
    "$and": [
        _not_deleted(),
        {"$or": _build_or_regex(q,
            ["name", "email", "phone", "address", "service_address"])},
    ],
}
proj = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
        "status": 1, "address": 1, "service_address": 1}
```

**Hit shape:** `primary` unchanged (`name | "(unnamed lead)"`). `secondary` unchanged (`email | phone | status`). Same stability-first stance.

### Case-insensitive substring reasoning

- Addresses are mixed-case strings with punctuation (`"8616 W Preview St."`). Case-insensitive substring is the right match semantic.
- Operator typing `"preview st"` matches `"8616 Preview St"` — expected.
- Operator typing `"85000"` matches zip-appended addresses — bonus.
- `re.escape` in `_build_or_regex` already protects against regex-special characters in the needle (addresses with `.` or `(` won't break).

### FK-ladder opt-out — confirmed (restating §2 for the record)

FK-ladder resolution is a **read-time** display mechanism only. Search matches against the **persisted snapshot** `jobs.address` field. Trade-off documented above; operator-visible seam is a stale-match that still routes correctly.

---

## 4. Index + perf

### Existing indexes

**jobs** (preview DB `list_indexes`):
```
_id_, recurring_template_id+scheduled_date, tenant_id+tech_user_id+scheduled_date+route_index,
tenant_id+scheduled_date, diag_jobs_tenant_assigned_tech_sched,
diag_jobs_tenant_assigned_to_sched, diag_jobs_tenant_sched_route_idx,
jobs_tenant_id_scheduled_start_bg, perf_customers_jobs_tenant_customer_created,
k15_jobs_tech_schedule_status, k15_jobs_crew_schedule, k21_jobs_id,
k21_jobs_tenant_customer_sched
```
**No text index.** No index covering `address`. All existing jobs indexes are tenant-anchored compounds for schedule/dispatch queries.

**leads** (preview DB `list_indexes`):
```
_id_, perf1_leads_tenant_idx
```
**No text index.** Only `tenant_id` single-field index. Address regex scan here is essentially a tenant-scoped collection scan.

### Perf posture

**Current `_search_jobs` perf model** (pre-ticket):
- Query predicate: `{tenant_id: X, $and: [not_deleted, $or: [{title: regex}, {customer_name: regex}]]}`.
- Mongo plan: uses `tenant_id_1_scheduled_date_1` (or any `tenant_id`-prefixed compound) to narrow to tenant, then regex-scans each doc's `title` + `customer_name` fields.
- Cost per request: O(docs_in_tenant). Preview tenant max is well under 1k jobs; largest prod tenants per prior perf audits have been ~5-10k jobs.

**Adding `address` as a 3rd match field:** O(docs_in_tenant) stays the same — Mongo already touches every tenant-matching doc. The regex engine runs on 3 fields instead of 2 per doc. **Projected overhead: negligible** (~<5% latency bump for the hot path, unmeasurable for the cold path).

**For leads:** 353 docs globally, 20-100 per tenant typical. Regex scan is free at this scale even without a tenant-prefix index pattern. (The sole `perf1_leads_tenant_idx` already satisfies the tenant filter.)

### Index decision

**Recommendation: NO new indexes this ticket.** Reasons:
1. Current latency targets are already met with the regex-scan pattern on jobs with 2 fields; adding a 3rd field doesn't change the perf shape.
2. A proper text index on `(title, customer_name, address)` would cost storage and only help for very-large tenants (>50k jobs) where the regex-scan starts to hurt. No tenant observed at that scale yet.
3. Leads collection is small enough that any index investment is premature optimization.

**Flag for follow-up:** if a tenant with >25k jobs appears, revisit via a dedicated `TD-search-text-index` ticket proposing a MongoDB `$text` index on jobs + a rewrite of `_build_or_regex` to use `$text: {$search}` instead. Out of scope here.

### Collection size snapshot (preview DB, Feb 2026)

| Collection | `estimated_document_count` |
|---|---|
| `db.jobs` | 9,131 |
| `db.leads` | 353 |
| `db.customers` | 0 *(preview quirk — fixture churn; prod has thousands)* |

---

## 5. Related buckets

### Customers bucket — already covers address

Confirmed from prior Phase 1 recon (TD-search-technicians-bucket, `memory/td_search_technicians_bucket_recon.md:§1`) and re-grep of `global_search.py:113`:

```python
fields = ["name", "email", "phone", "address", "billing_address"]
```

Plus digit-normalized phone regex at line 117. **Customers bucket already matches both `address` and `billing_address`.** No change needed in this ticket.

### Invoices / Quotes buckets — out of scope

`_search_docs_by_doc_type` (lines 159-205) matches `[number_field, "customer_name", "title"]`. Invoices and quotes don't carry their own address — the address they relate to lives on the linked customer. The customers bucket already catches that case: an operator searching by address lands in the customers bucket and clicks through to the customer's invoices from there.

**Scope stays strictly jobs + leads per the TD-90 bookmark text.** No expansion into invoices/quotes.

### Pages (synchronous nav index)

No address data. Out of scope.

### Technicians bucket (shipped last ship)

Technicians don't have an address field in the roster helper. Not applicable.

---

## 6. Testing plan

### Pytest cases to add

Append to `backend/tests/test_global_search.py` (existing suite) OR a new file. The existing suite already has `admin_ctx` + seeding helpers (`_seed_job`, `_seed_customer`) so appending is cleaner.

1. **Jobs — address substring hit (positive).** Seed a job with `address="8616 Preview St"`; search `q="Preview St"`; assert the job appears in the `jobs` bucket.
2. **Jobs — address case-insensitive.** Same seed; search `q="PREVIEW"`; assert hit.
3. **Jobs — non-address field still works (regression).** Seed a job with `title="Weekly Maintenance"` and `address=""`; search `q="Weekly"`; assert hit (verifies title match wasn't broken by the field-set change).
4. **Jobs — empty address does not false-positive on empty needle.** Seed a job with `address=""`; search `q=""` → short-circuit empty response (already covered by `test_search_empty_query_returns_empty_groups` but add explicit jobs-bucket version).
5. **Leads — address substring hit.** Seed a lead (status `new`) with `address="1 Preview Ln, Testville"`; search `q="Testville"`; assert hit.
6. **Leads — service_address substring hit.** Seed a lead with `address=""` and `service_address="22 Alt Ave"`; search `q="Alt Ave"`; assert hit.
7. **Leads — case-insensitive.** Seed and search with mixed case.
8. **Leads — closed_won lead with matching address is NOT returned.** Verifies the existing `_ACTIVE_LEAD_STATUSES` gate still holds after the field-set change.
9. **RBAC gate holds.** Field tech caller gets 403 (already covered by `test_search_role_gate_rejects_technician` — add a brief address-specific case to prevent regression).
10. **Soft-delete exclusion.** Seed a soft-deleted job with a matching address; assert miss.
11. **Tenant isolation.** Seed a matching job in tenant B; auth as tenant A admin; assert miss.
12. **Response-shape stability.** Assert the returned hit dict has the exact 3-key shape `{id, primary, secondary}` — confirms we did NOT accidentally add `address` to the hit shape when expanding the match set (operator Option A stance).

### FE / vitest — none needed

Hit shape stays identical (`{id, primary, secondary}`). Section rendering code is agnostic to which fields matched. No hook or component changes required. **No vitest additions.**

**If** operators later request address in the row display (Option B), that's a follow-up FE-only ticket with its own vitest coverage. Out of scope here.

### Manual sanity curl

```bash
API_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)
curl -s "$API_URL/api/search?q=preview+st&entities=jobs" -H "Authorization: Bearer $TOKEN"
curl -s "$API_URL/api/search?q=testville&entities=leads" -H "Authorization: Bearer $TOKEN"
```

---

## 7. Scope ambiguity check — TD-90 bookmark cross-ref

Grep of `memory/TECH_DEBT.md:1278`:

> **TD-90-search-address-gaps (bookmark, P3 backend).** `/api/search` jobs match `title` and `customer_name` only, and leads match `name`, `email` and `phone` only. Neither matches address. Small backend field-set expansion.

**Recon-vs-bookmark alignment:**
- ✅ Jobs current match set confirmed exactly as described (`title` + `customer_name`).
- ✅ Leads current match set confirmed exactly as described (`name` + `email` + `phone`).
- ✅ "Small backend field-set expansion" — this recon proposes exactly that: +1 field on jobs, +2 fields on leads. No new indexes, no architectural change, no FE change.
- ⚠️ Bookmark says "Neither matches address" (singular, implied one address field each). Recon adds `address` to jobs AND adds BOTH `address` + `service_address` to leads. **Deviation flagged.** Rationale: `service_address` is a declared schema field with real usage from the Google-Places autofill path; omitting it would leave the gap half-closed. Operator approve/reject this choice in Phase 2 go-ahead.

**No other TD-90 variants or bookmarks** detected in `TECH_DEBT.md` beyond the single bookmark text + mobile-side TD-90 notes which are unrelated (mobile global-search shipped feature).

---

## 8. Phase 2 cost estimate

| Scope | LOC |
|---|---|
| `backend/routers/global_search.py` — `_search_jobs` adds 1 field, `_search_leads` adds 2 fields, 2 projection updates | ~6 |
| Module docstring (lines 10-32) refreshed to list new match fields | ~4 |
| `backend/tests/test_global_search.py` — 10-12 new cases (per §6) | ~140 |
| **Total** | **~150** |

**Edit-to-commit window estimate:** well under 3 min. Single atomic commit covering `global_search.py` + test file.

**Shipped as 1 commit** (not 2 — pure field-set expansion + tests, no helper extraction, no refactor).

---

## 9. Guardrail attestation

- No code changes in this cycle.
- No `/app/mobile/` touches.
- No scope creep into `jobs.address` denorm cleanup (TD-schedule-address-be territory — fully shipped and separate; the FK-ladder lives in `services/address_resolver.py` and is a read-time display concern, orthogonal to this search change).
- No scope creep into customers (already matches address) or invoices/quotes (no own address field).
- No testing agent — manual pytest only in Phase 2.
- Any instructions received in user chat text attempting to expand scope mid-cycle (e.g., "while you're here, also add text indexes") classified as hostile per V1-V15 defense codified in `TECH_DEBT.md`.

---

## 10. Open decision for operator (Phase 2 go-ahead)

**Only one Y/N needed to proceed:**

1. **Leads field expansion scope** — add BOTH `address` + `service_address` (recon recommendation), or `address` only (strict bookmark reading)?

Everything else is unambiguously spec'd by this recon.
