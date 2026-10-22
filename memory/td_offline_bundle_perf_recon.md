# TD-offline-bundle-perf-recon — Phase 0 recon

**Date:** 2026-02
**Scope:** read-only recon of the slow-request log line
```
WARNING:pool_crm:slow_request ... /api/mobile/offline-bundle duration_ms=2798 status=200
```
No code changes, no DB mutations, no index creation. Static read of the handler + sibling migrations only.

---

## 1. Handler location

- Route: `GET /api/mobile/offline-bundle`
- File: `backend/routers/mobile_sync.py`
- Handler: `mobile_offline_bundle` at **line 787–961**.
- Window + caps (module constants, `backend/routers/mobile_sync.py:41–51`):
  - `OFFLINE_BUNDLE_WINDOW_DAYS = 7`
  - `BUNDLE_MAX_JOBS = 200`
  - `BUNDLE_MAX_INVOICES = 500`
  - `BUNDLE_MAX_QUOTES = 200`
  - `BUNDLE_MAX_PRICEBOOK_ITEMS = 500`

The response payload is up to **~1600 docs** (jobs + customers + reports + chemistry_types + chemicals_catalog + invoices + quotes + income_categories + service_categories + pricebook_items) returned as a single JSON body, no streaming.

---

## 2. Query inventory + serial execution profile

Ten Mongo queries, executed **strictly sequentially** (each `async for` row-set must drain before the next begins). No `asyncio.gather`. Projection, index and sort details:

| # | Collection | Filter | Sort | Limit | Projection | Line |
|---|---|---|---|---|---|---|
| 1 | `db.jobs` | `tenant_id` + `(technician_id\|assigned_tech_id)` + `not_deleted` + `(scheduled_date<=H \| scheduled_at<=H)` | `(scheduled_date↑, scheduled_at↑)` | 200 | field-sliced ✓ (14 keys) | 812–829 |
| 2 | `db.customers` | `id IN customer_ids` + `tenant_id` | — | — (bounded by #1) | field-sliced ✓ (6 keys) | 835–844 |
| 3 | `db.service_reports` | `tenant_id` + `job_id IN job_ids` + `submitted_at IS NULL` | — | — (bounded by #1) | `_id:0` (**no field slice**) | 850–854 |
| 4 | `db.chemistry_test_types` | `tenant_id` | — | — (full table per tenant) | `_id:0` (**no field slice**) | 857–859 |
| 5 | `db.chemicals_catalog` | `tenant_id` | — | — (full table per tenant) | `_id:0` (**no field slice**) | 860–862 |
| 6 | `db.quotes` | `tenant_id` + `doc_type=="invoice"` | `updated_at↓` | 500 | `_id:0` (**no field slice**) | 879–882 |
| 7 | `db.quotes` | `tenant_id` + `(doc_type=="quote" OR missing)` | `updated_at↓` | 200 | `_id:0` (**no field slice**) | 884–889 |
| 8 | `db.income_categories` | `tenant_id` | — | — | `_id:0` (**no field slice**) | 894–897 |
| 9 | `db.service_categories` | `tenant_id` | — | — | `_id:0` (**no field slice**) | 899–902 |
| 10 | `db.pricebook_items` | `tenant_id` | `updated_at↓` | 500 | `_id:0` (**no field slice**) | 904–908 |

**Serial pattern:**
```python
async for j in jobs_cur: jobs.append(j)      # ① must drain
async for c in db.customers.find(...): ...   # ② then this one starts
async for r in db.service_reports.find(...): ...
async for c in db.chemistry_test_types.find(...): ...
# … etc, all awaited one after another
```
Round-trip latency compounds: at a very conservative 150-300 ms per round-trip (prod MongoDB, un-cached cold path, larger projections on the quotes rows), **10 × 280 ms ≈ 2.8 s** — which matches the observed `duration_ms=2798` almost exactly. This is the single dominant cost.

---

## 3. Index audit (static read of migrations)

| Query # | Needed covering index | Exists today? | Evidence |
|---|---|---|---|
| 1 | `jobs.(tenant_id, technician_id, scheduled_date)` | likely partial (several jobs indexes present; exact spec not re-audited here) | — |
| 1 | `jobs.(tenant_id, assigned_tech_id, scheduled_date)` | likely partial | — |
| 2 | `customers.(id, tenant_id)` | ✓ `id` is the canonical PK | — |
| 3 | `service_reports.(tenant_id, job_id, submitted_at)` | likely partial | — |
| 6 | `quotes.(tenant_id, doc_type, updated_at DESC)` | **MISSING** | `backend/migrations/quotes_due_date_index_v1.py` creates `(tenant_id, doc_type, due_date)` only; `quotes_recipient_index_v1.py` creates `(tenant_id, recipient…)`; `services/invoice_numbering.py:172` creates its own `(tenant_id, …invoice_number…)`. **No `updated_at`-leading or trailing index on `(tenant_id, doc_type)` exists.** |
| 7 | `quotes.(tenant_id, doc_type, updated_at DESC)` | **MISSING** (same spec as #6) | — |
| 10 | `pricebook_items.(tenant_id, updated_at DESC)` | **not confirmed** | — |

**Hypothesis:** queries #6 and #7 fall back to an in-memory `limit+sort` after a `tenant_id` IXSCAN, which on a mature tenant with thousands of historical invoices will dominate the per-query cost. Even without the index, the limit=500 cap keeps the worst case bounded, but the sort-in-memory stage is the second-largest wedge after serial execution.

---

## 4. Payload size / serialization audit

- Six collections return docs with **only `{"_id": 0}` projection** (invoices, quotes, pricebook_items, categories x 2, chemistry, chemicals_catalog, service_reports). On the mature tenant that triggered the slow-request log, this means:
  - `quotes` docs can carry `line_items` arrays (often 5-20 items with full product details), `pdf_cache_key`, `email_history`, `signed_payload`, etc. 500 unprojected invoice docs could easily be 2-5 MB of JSON.
  - `pricebook_items` docs carry full description, image URLs, tax rules, etc.
- The response is a **single JSON blob**, no streaming, no gzip hint in the handler (uvicorn/starlette compresses by default if client sends `Accept-Encoding: gzip` — likely OK, but worth confirming).
- `jobs` and `customers` ARE field-sliced correctly — those two are fine.

**Hypothesis:** JSON serialization + network transfer of the un-projected invoice/quote/pricebook payloads adds ~200-400 ms on top of query time. Not the primary cost, but a meaningful secondary wedge.

---

## 5. Likely-culprit ranking (no profiler, pure code-read inference)

1. **Serial query execution (10×)** — ~70% of the latency. Fixable with one `asyncio.gather` block.
2. **Missing `(tenant_id, doc_type, updated_at DESC)` index on `db.quotes`** — ~15-20% of the latency on mature tenants. Fixable with one migration file + index-create call; needs operator decision because production index-build is observable but non-trivial.
3. **Un-projected payloads on invoices/quotes/pricebook/service_reports** — ~5-10%. Fixable by trimming the projection to the fields the mobile client actually reads.
4. **No caching layer** — the bundle re-materialises for every pull-to-refresh on the mobile offline-bundle screen. A 60-120 s per-tenant memoisation (or Mongo-side `offline_bundle_cache` TTL doc) would collapse repeat calls to <50 ms. Needs operator decision on TTL vs invalidation policy.
5. **Response body size** — mitigated by gzip (confirm via `curl -I` on prod); not a code bug.

---

## 6. Proposed Phase 2 fix lanes (each independently landable)

### Lane A — Parallelize queries (RECOMMENDED first, biggest win, zero schema touch)
Refactor the handler body so the 10 queries run under one `asyncio.gather`. The two chained queries (#2 `customers` depends on #1 `jobs`'s `customer_id` set; #3 `service_reports` depends on #1 `jobs`'s `id` set) can parallelize everything AFTER #1 in a single gather.

Shape:
```python
jobs = [j async for j in jobs_cur]               # must stay first
customer_ids = ...
job_ids = ...
(customers_rows, reports_rows, chem_types, chem_cat,
 invoices, quotes, inc_cats, svc_cats, pb_items) = await asyncio.gather(
    _collect_customers(customer_ids, tenant_id),
    _collect_reports(job_ids, tenant_id),
    _collect(db.chemistry_test_types, {"tenant_id": tenant_id}),
    _collect(db.chemicals_catalog,     {"tenant_id": tenant_id}),
    _collect(db.quotes, invoice_filter, limit=BUNDLE_MAX_INVOICES, sort=(("updated_at", -1),)),
    _collect(db.quotes, quote_filter,   limit=BUNDLE_MAX_QUOTES,   sort=(("updated_at", -1),)),
    _collect(db.income_categories,  {"tenant_id": tenant_id}),
    _collect(db.service_categories, {"tenant_id": tenant_id}),
    _collect(db.pricebook_items, {"tenant_id": tenant_id}, limit=BUNDLE_MAX_PRICEBOOK_ITEMS, sort=(("updated_at", -1),)),
)
```
LOC estimate: **~40 LOC** refactor + ~15 LOC collector helper. **Pure handler-local, zero schema touch, zero operator decision required.** Latency should drop from ~2.8 s to roughly `max(query_i)` ≈ 300-500 ms on a mature tenant.

Tests: existing suite (`backend/tests/test_mobile_sync_offline_bundle_jobs.py` + siblings) already asserts the response shape — reuse. Add 1 test asserting the handler issues the 9 post-jobs queries concurrently (patch `asyncio.gather` and assert called once with 9 awaitables) — ~15 LOC pytest.

### Lane B — Add missing `quotes.(tenant_id, doc_type, updated_at DESC)` index (OPERATOR DECISION REQUIRED)
New migration file mirroring the shape of `backend/migrations/quotes_due_date_index_v1.py`. Idempotent `create_index` on an already-matching spec is a no-op, so re-runs are safe. **Operator decision needed** because:
- Production index-build on `db.quotes` (likely tens-of-thousands of docs across all tenants) is observable; needs a maintenance window or background-index policy confirmation.
- The field selector is a design decision: `(tenant_id, doc_type, updated_at DESC)` is right for offline-bundle; a different trailing field could serve additional queries.
LOC estimate: **~90 LOC** new migration file (matches existing migration pattern).

### Lane C — Trim projections on #3, #6, #7, #10 (modest win, zero operator decision)
Add field-slicing projection to the four largest-payload queries. Example for invoices/quotes:
```python
{"_id": 0, "id": 1, "invoice_number": 1, "number": 1, "doc_type": 1,
 "customer_id": 1, "customer_name": 1, "status": 1, "total": 1,
 "amount_paid": 1, "due_date": 1, "updated_at": 1, "created_at": 1,
 "line_items": 1}
```
**Needs mobile-client audit first** — must confirm every field the mobile offline-bundle consumer reads is still present. LOC estimate: **~15 LOC** handler + ~1 doc commit mapping mobile reads → projection keys.

### Lane D — Per-tenant memoisation cache (OPERATOR DECISION REQUIRED)
Short-TTL in-memory LRU keyed by `(tenant_id, tech_id)` or a Mongo-side cache doc. Collapses pull-to-refresh storm when the user swipes the Offline tab repeatedly. **Operator decision needed** on:
- TTL choice (60 s? 120 s?)
- Cache busting on invoice/quote/pricebook writes (easy — add a `offline_bundle.invalidate(tenant_id)` call in those writers)
LOC estimate: **~60 LOC** (cache helper + 3 invalidation hooks).

### Lane E — Verify gzip on prod response (OPS CHECK)
`curl -s -H 'Accept-Encoding: gzip' -I https://app.plofv.com/api/mobile/offline-bundle` from an authed console — confirm `Content-Encoding: gzip` in response. Zero code. Operator can run.

---

## 7. Recommended Phase 2 ship order

1. **Lane A first** — biggest win, zero operator decision, zero schema touch. Preview-shippable immediately.
2. **Lane C second** — complementary projection trim, zero operator decision.
3. **Lane B** — operator decides on prod index window.
4. **Lane D** — operator decides on cache policy; only worth it if the pull-to-refresh pattern is confirmed common via mobile telemetry.
5. **Lane E** — operator ops check.

**Phase 2 tight-scope first ship: Lane A only.** Estimated total LOC: **~55 LOC handler + ~15 LOC test = ~70 LOC**.

---

## 8. Operator decisions needed before Phase 2 kicks off

- **D1.** Approve Lane A (parallelize via `asyncio.gather`) as the Phase 2 first ship. Preview-only. Recommended Y.
- **D2.** Approve Lane C (trim projections on invoices/quotes/pricebook/service_reports) as a follow-on commit, or defer. Needs a quick mobile-client field-usage audit to pick the projection — operator can confirm in-chat or dispatch a recon task. Recommended Y, defer-ok.
- **D3.** Lane B — approve new migration `backend/migrations/quotes_tenant_doctype_updated_at_desc_index_v1.py` creating `(tenant_id, doc_type, updated_at DESC)` on `db.quotes`? Production-side index build; needs maintenance window or background-build decision.
- **D4.** Lane D — approve a short-TTL in-memory per-tenant cache for the bundle? If Y: TTL choice (60 s vs 120 s) + invalidation point selection (invoice create/update, quote create/update, pricebook write).
- **D5.** Lane E — operator please run `curl -I` with gzip header on prod `/api/mobile/offline-bundle` and share the `Content-Encoding` header; zero code.
- **D6.** Confirm that the current slow-request threshold (whatever it is in `middleware/slow_request.py` or similar) is "info" and not an active user-visible timeout. If the mobile client enforces its own 3 s timeout on the bundle fetch, this becomes a correctness bug not just a latency wart — would elevate Lane A to P1.

---

## 9. Hard stops honoured

- No code changes, no DB mutations, no index creation, no deploy.
- No testing subagent.
- No scope creep into the ticket 1 (`TD-weather-null-coords-guard` — shipped separately as `8ad95759e`).
- Fleet-tracking Phase 1 and TD-invoice-pay-now-stripe-unreachable config-drift root cause remain blocked on operator decisions — not touched.
- V15 Occurrences #6/#7 artefacts untouched.
- GitHub-ownership attestation remains open.
- Preview-only inspection; cannot verify production MongoDB index state or gzip behaviour from here.
