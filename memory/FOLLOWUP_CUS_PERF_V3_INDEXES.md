# FOLLOWUP · CUS-perf v3 — compound indexes for muted/waitlist counts

## Discovered during
CUS-perf backend follow-on recon (surprise S4, 2026-02).

## Issue
Post-`$facet`-refactor, 4 of 5 tab-count filters hit
`IXSCAN(tenant-partition)` + in-memory `FILTER` on `{is_muted,
waitlisted}` rather than pure index-only scans. The recon's
"no non-indexed scans on hot path" goal is unreachable without
dedicated compound indexes.

## Current winning-plan matrix

| Bucket | Predicate | Best-fit index | Winning plan |
|---|---|---|---|
| `active` | `is_active=True or absent + NOT_MUTED + base` | `customers_dashboard_active_inactive_idx` (tenant_id, is_active, is_muted, deleted_at) | Straight IXSCAN — first 3 keys covered |
| `inactive` | `is_active=False + NOT_MUTED + base` | Same as active | Straight IXSCAN |
| `muted` | `is_muted=True + base` | Partial — 2nd key on the compound | IXSCAN(tenant_id partition) + FILTER(is_muted) |
| `waitlist` | `waitlisted=True + base` | **NO dedicated index** | IXSCAN(tenant_id partition) + FILTER(waitlisted) |
| `all` | base only | Partition-scoped IXSCAN on any tenant-prefixed compound | IXSCAN |

## Recommended indexes

**Option A** — Add `(tenant_id, waitlisted)` compound with a partial
filter to keep storage lean (only ~2-5% of customers are waitlisted
per tenant):

```python
await db.customers.create_index(
    [("tenant_id", 1), ("waitlisted", 1)],
    name="perf_customers_v3_tenant_waitlisted",
    partialFilterExpression={"waitlisted": True},
    background=True,
)
```

**Option B** — Extend the existing
`customers_dashboard_active_inactive_idx` with `waitlisted` as a
trailing key so a single 5-key compound serves active, inactive,
muted, AND waitlisted counts:

```python
await db.customers.create_index(
    [("tenant_id", 1), ("is_active", 1), ("is_muted", 1),
     ("waitlisted", 1), ("deleted_at", 1)],
    name="perf_customers_v3_tenant_status_composite",
    background=True,
)
```

Trade-off:
- **Option A** wins on write cost (partial filter → smaller index).
- **Option B** wins on read cost (single index serves all 4 status
  counts) but adds ~15% to write amplification on customer writes.

**Recommend Option A** — writes to `customers` are much more
frequent than tab-count reads on the hot path. Partial-filter index
is the smaller footprint.

## Priority
P2 — current partition-scoped IXSCAN + in-memory FILTER is already
faster than the pre-refactor `$facet` single-round-trip.
The perf gap is ~5-15% wall-clock on tenants with 5k+ customers;
below that scale it's noise.

## Migration pattern
Mirror `backend/services/migrations/perf_customers_indexes_v2.py`:
- New module: `services/migrations/perf_customers_indexes_v3.py`
- Migration key: `perf_customers_v3`
- Register in `server.py::_REQUIRED_MIGRATIONS` sequence.
- Sentinel-gated + must_succeed=False.

## Coordinated tests
Extend `backend/tests/test_cus_perf_v3_backend_counts.py` with
explain-plan asserts on the `waitlist` + `muted` filters showing
the new indexes are the winning plan.

## Related landing
- CUS-perf v3 backend follow-on (this session) — established the
  5-parallel-`count_documents` refactor + surfaced the index gap.
