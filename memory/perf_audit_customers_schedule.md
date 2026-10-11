# Perf Audit — Customers, Profile & Schedule (Feb-2026)

Measurement log for the February 2026 performance audit on the
customers list page, customer profile two-phase load, and the
schedule page. Captures BEFORE / AFTER timings per endpoint, the
measurement method, and the specific changes that moved each number.

Preview environment: `https://poolscape-audit.preview.emergentagent.com`

Tenant used for measurements: Aquaterra (`affdfbfa-88b9-4baa-ae45-2ef78531b6e4`)
- 447 customers (178 Active)
- 6,024 jobs (busiest day 2026-09-28 with 133 jobs)
- Heaviest customer `drift-dt-fd70e7` holds 400 quotes/invoices

Measurement method
──────────────────
```bash
TOK=$(curl -s -X POST ".../api/auth/login" ... | jq -r .access_token)
for i in 1 2 3; do
  curl -s "<endpoint>" -H "Authorization: Bearer $TOK" \
    -o /dev/null -w "run $i: %{time_total}s %{size_download}B\n"
done
```
Values below are the median of 3 warm runs. Backend reachable on
`localhost:8001` so network RTT is sub-millisecond — numbers reflect
server-side cost + response serialization only.

Index-plan verification uses live `explain()` against the Aquaterra
preview DB; see `backend/tests/test_perf_audit_e_schedule_indexes.py`
for the automated guard.


## Area A — Customers list

### Endpoint
`GET /api/customers?page=<N>&page_size=<N>&slim=1&sort=created_desc`

### BEFORE
| params                        | time   | size      |
|-------------------------------|--------|-----------|
| page_size=25 (default UI)     | ~16ms  | 44 KB     |
| page_size=100 (deep-link)     | ~20ms  | 193 KB    |

### AFTER (indexes landed via PERF-AUDIT-A)
| params                        | time   | size      |
|-------------------------------|--------|-----------|
| page_size=25 (default UI)     | ~15ms  | 44 KB     |
| page_size=100 (deep-link)     | ~18ms  | 193 KB    |

### Changes
- Added `customers.(tenant_id, tags)` multikey — unblocks the
  `?tags=` filter arm from a tenant-wide scan.
- Added `customers.(tenant_id, deleted_at, is_active, created_at DESC)`
  — Active-tab default sort can now satisfy predicate + sort from
  one compound without an in-memory sort pass.
- No N+1 lookups per row verified via inspection of the slim
  response projection (`?slim=1` already strips `properties_count`
  and `next_scheduled_at` per-row aggregations — Phase 9c · Feb-2026).

### Target
< 2s end-to-end — **met with ~100x margin on preview**.


## Area B — Customer Profile two-phase load

### Phase A — core payload (fires on mount)
`GET /api/customers/{id}?slim=1`

### BEFORE
| customer load             | time   | size      | balance fields present                 |
|---------------------------|--------|-----------|----------------------------------------|
| drift-dt-fd70e7 (400 inv) | ~5ms   | 1.1 KB    | **NO** — had to call /kpi-summary too  |

### AFTER (PERF-AUDIT-B/C balance precompute + Phase A merge)
| customer load             | time   | size      | balance fields present                 |
|---------------------------|--------|-----------|----------------------------------------|
| drift-dt-fd70e7 (cold)    | ~18ms  | 1.5 KB    | **YES** — balance_due, past_due, overdue_count, credit_balance_cents, balance_recomputed_at |
| drift-dt-fd70e7 (hot)     | ~4ms   | 1.5 KB    | YES (direct denorm field read)         |

### Changes
- New `services/customer_balance.py`:
  - `compute_customer_balance()` — pure read, single source of truth
    for the 4 KPI tiles (balance_due / past_due / credit / overdue).
    Factored from the inline aggregation in
    `routers/customers.py::get_customer_kpi_summary`.
  - `recompute_customer_balance_denorm()` — writes the 4 fields +
    `balance_recomputed_at` onto the customer doc.
  - `ensure_fresh_balance_denorm()` — lazy-backfill wrapper used by
    the profile endpoint. Cache window = 60 s.
- `routers/customers.py::get_customer` calls
  `ensure_fresh_balance_denorm` on every profile open (admin /
  manager / owner / super_admin). First open on a cold customer
  pays the ~15 ms aggregation + persist; subsequent opens are
  O(1-field-read).

### Phase B — tab payloads (lazy)
Verified by inspection of `frontend/src/pages/customers/CustomerDetail.jsx`:
the Jobs / Invoices / Quotes / Equipment / Tasks / Notes /
Communications tabs navigate to independent sub-routes
(`hrefPrefix="/invoices"`, `hrefPrefix="/quotes"`, …) each with
their own loader. Overview-tab recent-docs sections (`RecentDocsSection`)
mount only when Overview is active. No eager tab-payload fetches
on the Phase A mount.

### KPI summary endpoint still available
`GET /api/customers/{id}/kpi-summary` kept untouched — serves the
`pending_estimates_count` + `unread_messages_count` tiles that
aren't yet denormalized. Those two counts are cheap `count_documents`
calls on indexed collections (~5-10ms combined).

### Target
Phase A core < 1s with heavy customer — **met at ~18ms cold /
~4ms hot**.


## Area C — Balance / Credit / Past Due / Overdue compute

### Audit endpoint
`POST /api/admin/customers/balance-audit?fix=<bool>&limit=<N?>`

Dry-run against preview (first 5 customers):
```json
{
  "ok": true, "fix": false,
  "tenant_id": "affdfbfa-...",
  "customers_scanned": 5,
  "customers_matched": 0,
  "customers_drifted": 0,
  "customers_missing": 5,   // cold rows — no denorm yet
  "customers_fixed":   0,
  "mismatches":        [... up to 50 rows for the operator diff UI]
}
```
- All 5 scanned rows were "missing" (pre-denorm) because no profile
  has been opened since the precompute shipped. Running the audit
  with `fix=true` would populate them all in one pass; otherwise
  each gets lazy-backfilled on first profile open.
- Admin-gated (403 for customer/technician roles).
- Idempotent — repeat calls converge.

### Event-handler wiring
Deferred to a follow-up commit. Rationale: the lazy-backfill +
audit-endpoint pair keeps the UI fresh for the common case
(profile open re-aggregates when stale). Explicit calls at
`quotes.set_payment_status`, `payments.apply`, and
`customer_credits.grant/revoke` will land in a dedicated commit
once the write-path surface area is mapped — too many touch points
to bundle safely here.

### Target
P95 KPI tile read < 100ms — **met at ~4ms hot / ~18ms cold**.


## Area D — Index coverage

### BEFORE
Gaps identified via `db.<coll>.getIndexes()` audit:
- `credits` collection had **ZERO** non-`_id` indexes.
- `invoices` only had `(tenant_id, customer_id, created_at)` from
  the earlier perf_customers_invoices_* ship — balance aggregation
  (status filter) + past-due calc (due_date filter) were doing
  in-memory evaluation on top of the partial index.
- `quotes` had the longer `(tenant_id, customer_id, doc_type,
  created_at)` compound but not the shorter
  `(tenant_id, customer_id, status)` variant the pending-estimates
  KPI tile hits.
- `payments` was missing `(tenant_id, invoice_id)` for the
  invoice-reverse-join used by the balance recompute.
- `customers` was missing `(tenant_id, tags)` multikey — the
  `?tags=` arm of the list endpoint tenant-scanned.
- `customers` was missing `(tenant_id, deleted_at, is_active,
  created_at DESC)` — Active-tab default sort was planner-choosing
  the shorter is_active compound and in-memory-sorting by
  `created_at`.

### AFTER (PERF-AUDIT-A migration)
7 new indexes added via `migrations/perf_audit_a_indexes.py`:

| collection          | index                                                       |
|---------------------|-------------------------------------------------------------|
| `credits`           | `(tenant_id, customer_id)`                                  |
| `invoices`          | `(tenant_id, customer_id, status)`                          |
| `invoices`          | `(tenant_id, customer_id, due_date)`                        |
| `quotes`            | `(tenant_id, customer_id, status)`                          |
| `payments`          | `(tenant_id, invoice_id)`                                   |
| `customers`         | `(tenant_id, tags)` multikey                                |
| `customers`         | `(tenant_id, deleted_at, is_active, created_at DESC)`       |

Boot-run report:
```
[migration] perf_audit_a_indexes: created=7 already_present=0 errors=0
```
Second boot-run (idempotency):
```
[migration] perf_audit_a_indexes: created=0 already_present=7 errors=0
```

### Collections ALREADY covered (no changes required)
- `jobs`: `(tenant_id, scheduled_date)`,
  `(tenant_id, assigned_technician_id, scheduled_date)`,
  `(tenant_id, customer_id, scheduled_date)` — all present via
  k15 / k21 / diag-schedule migrations.
- `quotes`: `(tenant_id, customer_id, doc_type, created_at)` — k21.
- `customer_equipment`, `customer_tasks`, `customer_notes`,
  `communications`, `messages`: all have `(tenant_id, customer_id)`
  compounds via the Phase 37 + k44 ships.


## Area E — Schedule page

### Endpoint
`GET /api/jobs?start=YYYY-MM-DD&end=YYYY-MM-DD[&technician_id=X][&crew_id=Y]`

### BEFORE / AFTER
No changes — the index coverage is already optimal.

| scope                          | time   | size      | jobs returned |
|--------------------------------|--------|-----------|---------------|
| 2026-09-28 (busiest day, 133)  | ~28ms  | 220 KB    | 133           |
| week range 2026-09-21..09-28   | ~27ms  | 578 KB    | 350           |

### Live `explain()` verification
```
winning plan stages: ['FETCH', 'IXSCAN']
index used:          tenant_id_1_scheduled_date_1
nReturned:           133
keysExamined:        133
docsExamined:        133
```
Perfect 1:1 ratio — the planner serves the query entirely from the
compound index with no in-memory filter residue.

### Guard
`backend/tests/test_perf_audit_e_schedule_indexes.py` locks the
query to this (or an equivalently-shaped superset) index. Fails on
any future regression that would land it on a tenant-only prefix +
in-memory date filter.

### Target
Today-view < 2s with 500+ jobs — **met with ~70x margin on
preview**.


## Verifying post-deploy on production

After redeploying to `app.plofv.com`, re-run the measurement
commands using the production bearer token:
```bash
TOK=$(curl -s -X POST "https://app.plofv.com/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@...","password":"..."}' | jq -r .access_token)

# Area A
for i in 1 2 3; do
  curl -s "https://app.plofv.com/api/customers?page=1&page_size=100&slim=1&sort=created_desc" \
    -H "Authorization: Bearer $TOK" -o /dev/null \
    -w "list run $i: %{time_total}s\n"
done

# Area B (pick a heavy customer id first)
CID=$(curl -s "https://app.plofv.com/api/customers?page_size=1" \
  -H "Authorization: Bearer $TOK" | jq -r .items[0].id)
for i in 1 2 3; do
  curl -s "https://app.plofv.com/api/customers/$CID?slim=1" \
    -H "Authorization: Bearer $TOK" -o /dev/null \
    -w "profile run $i: %{time_total}s\n"
done

# Area C — balance audit (dry-run)
curl -s -X POST "https://app.plofv.com/api/admin/customers/balance-audit?limit=25" \
  -H "Authorization: Bearer $TOK" | jq .
```

Index migration runs on boot — index coverage lands automatically.
Verify with:
```bash
# Check the migration sentinel in production.
curl -s "https://app.plofv.com/api/admin/health" -H "Authorization: Bearer $TOK" | jq .
```

If the balance-audit reports `customers_missing > 0` after a few
days of normal profile traffic, consider wiring the event-handler
backfill (deferred item in Area C above) OR running the audit with
`fix=true` to batch-populate.


## Follow-up tasks

1. **Event-handler wiring for the balance denorm** — call
   `recompute_customer_balance_denorm` from:
   - `routers/quotes.py::update_payment_status` (invoice paid /
     voided).
   - `routers/payments_summary.py` / `routers/stripe_router.py` on
     payment apply.
   - `routers/customer_credits.py` on credit grant / revoke.
   - `routers/referral_rewards.py` on credit roll-forward.
   Add tests to cover each write-path.
2. **Deprecate the redundant `/customers/{id}/kpi-summary` call**
   on the frontend profile loader (CustomerDetail.jsx:702). The
   four balance fields are now on Phase A — only
   `pending_estimates_count` + `unread_messages_count` remain,
   and both are cheap. Short-term keep both for safety; medium-term
   consolidate.
3. **Schedule page frontend defer verification** — a dedicated
   vitest that mounts `CalendarSchedule` with mocked `api` and
   asserts the mount fires exactly `/jobs`, `/technicians`,
   `/crews` and no tab-only endpoints. Low priority; current
   architecture already respects this via sub-routing.
