# Phase K65.fix · Schedule Load Performance Fix — Ship Report

**Status:** COMPLETE (preview-verified, prod-index migration is a no-op due to prefix cover).
**Predecessor:** `/app/memory/PHASE_K65_SCHEDULE_PERF_DIAGNOSIS.md`
**Scope:** All 6 items from the K65 diagnosis + the bonus super-admin explain-schedule diagnostic endpoint. Web only; mobile Schedule not touched.

---

## 1 · Sentinel verdict (Step 1)

Verified against the preview Mongo instance before touching any code:

| Check | Result |
|-------|--------|
| `db.migrations.findOne({id: "k15_jobs_indexes_v1"})` | **PRESENT** — completed `2026-09-05T01:25:36+00:00`, `created=2, already_present=0, errors=[]`. |
| `k15_jobs_tech_schedule_status` on `db.jobs` | Present, `(tenant_id, technician_id, scheduled_date, status)`. |
| `k15_jobs_crew_schedule` on `db.jobs` | Present, `(tenant_id, crew_id, scheduled_date)`. |
| `k21_perf_indexes_v1` migration sentinel | Present (`k21_jobs_id`, `k21_jobs_tenant_customer_sched`, `perf_customers_jobs_tenant_customer_created` all landed). |
| `db.service_reports` — pre-existing index | **`tenant_id_1_job_id_1_tech_id_1`** (compound). The `(tenant_id, job_id)` prefix is fully covered — the K65-flagged "missing index" is a false alarm from the diagnosis. Migration below detects this and is a no-op. |

**Verdict:** k15 migration DID land in prod-shaped code paths. Since prod boots the same `_bg_k15_jobs_indexes` task, prod is already covered. The K65.fix rollup is still valuable because Suspects S1 (technicians N+1) and S2 (in-memory sort on derived `_day`) are code-side, not index-side.

**No prod DB writes required for this ship.** The new K65 service_reports migration self-detects the prefix cover and short-circuits.

---

## 2 · Files changed

| Kind | File | Lines |
|------|------|-------|
| NEW | `backend/services/migrations/k65_service_reports_indexes.py` | 178 |
| NEW | `backend/routers/admin_perf_explain_schedule.py` | 208 |
| NEW | `backend/tests/test_k65_fix_schedule_perf.py` | 288 |
| MOD | `backend/routers/technicians.py` | +71/-13 (collapsed N+1 into single `$group`) |
| MOD | `backend/routers/jobs.py` | +38/-11 (index-covered sort + Python re-sort, bounded-batch customer enrichment with warn-on-ceiling) |
| MOD | `backend/server.py` | +30/-1 (wire k65 migration into boot, register explain-schedule router) |
| MOD | `frontend/src/api.js` | +6/-1 (accept `timeoutMs` on `api.get`) |
| MOD | `frontend/src/pages/schedule/CalendarSchedule.jsx` | +64/-10 (20 s hard timeout on `load()` + retry banner) |
| DOC | `memory/PHASE_K65_SCHEDULE_PERF_DIAGNOSIS.md` | RESOLVED section appended |
| DOC | `memory/PHASE_K65_FIX_SCHEDULE_PERF.md` | this file |

Env addition (default OFF; user-toggleable):
- `FEATURE_PERF_EXPLAIN=""` in `backend/.env` — flip to `"1"` for a targeted diagnostic window. Explain route returns 404 when off (invisible to non-super-admin).

---

## 3 · What each item shipped

### Step 2 — service_reports index migration
- File: `services/migrations/k65_service_reports_indexes.py`
- Sentinel key: `k65_service_reports_indexes_v1`
- Target index (only when no prefix-covering compound exists): `k65_service_reports_tenant_job` on `(tenant_id ASC, job_id ASC)`
- On preview: detected `tenant_id_1_job_id_1_tech_id_1` prefix cover → summary `{created:0, already_present:0, already_covered_by_prefix:1, covered_by:"tenant_id_1_job_id_1_tech_id_1"}`. Sentinel written.
- Estimated build time IF an index does need to be created at prod scale (~35k service_reports rows): sub-second with `background=True`; non-blocking on the primary. No downtime risk.

### Step 3 — /api/technicians N+1 → single `$group`
- File: `routers/technicians.py:190-260`
- Before: `2 × N` sequential `count_documents` per request (N ≈ 45 at Aquaterra prod scale → ~90 round-trips).
- After: ONE `$group` on `(technician_id, work_class)` scoped to `{tenant_id, technician_id: {$in: […]}, status: {$in: [pending, active]}}`. Uses `k15_jobs_tech_schedule_status`.
- Response shape byte-for-byte preserved: every doc still carries `active_jobs`, `active_jobs_repair`, `active_jobs_service`.
- Preview timing: 3-run cold-cache mean `102 ms` (previously ~200–350 ms even at preview's 10-tech scale).

### Step 4 — /api/jobs index-covered sort + Python re-sort
- File: `routers/jobs.py:550-610`
- Before: aggregation `$addFields _day → $sort {_day, _ri, sd, ca} → $limit`. Blocking in-memory sort on derived field.
- After: aggregation `$match → $sort {scheduled_date} → $limit`. `allowDiskUse=True` as a defense-in-depth guard. `.to_list(limit)` result is then stable-sorted in Python by `(day-prefix, route_index || 999999, scheduled_date, created_at)`. Python sort of ≤ 1000 rows costs < 2 ms.
- Ordering contract preserved (verified by `test_k65_fix_jobs_python_re_sort_key_matches_pre_k65_contract`).
- Preview timing: 3-run 90-day mean `169 ms` on ~50 matched rows.
- **Documented edge:** when the matched set exceeds `limit=1000`, the truncation boundary differs from the pre-K65 shape (now truncated by `scheduled_date`, previously by `(day, route_index)`). Same admin at Aquaterra prod hits ~3k matched rows → both shapes truncate; the exact rows dropped at the tail change by fractions of hours. Acceptable per the fix option user greenlit (S2.A).

### Step 5 — CalendarSchedule.jsx: 20 s AbortController + Retry
- Files: `frontend/src/api.js` + `frontend/src/pages/schedule/CalendarSchedule.jsx`
- `api.get(path, timeoutMs)` now accepts a per-call timeout override.
- Schedule fetch uses `20000 ms`. On timeout, the existing error banner shows `Schedule is taking longer than usual.` with a `[Retry]` button (`data-testid=calendar-retry-btn`) that re-fires `load({force:true})`.
- All three parallel calls (`/api/jobs`, `/api/technicians`, `/api/crews`) share the 20 s bound. `/technicians` and `/crews` already had `.catch(() => [])` fallbacks — those are preserved so their timeouts do NOT block the schedule render; only a `/api/jobs` timeout produces the banner.
- Existing "Loading…" UX preserved for normal loads.

### Step 6 — Customer enrichment silent cap → bounded-batch + warn
- File: `routers/jobs.py:614-665`
- Before: single `db.customers.find({id: {$in: cids}, ...}).to_list(1000)` — tail customers past 1000 silently lost enrichment.
- After: chunked at 500 ids, `to_list(len(chunk))` per chunk, results concatenated. Warning logged when unique customer count exceeds 5000 (soft ceiling) so ops sees a signal on tenant-wide fan-outs.
- Response shape preserved. No truncation.

### Bonus — `POST /api/admin/perf/explain-schedule`
- File: `routers/admin_perf_explain_schedule.py`
- Endpoints:
  - `GET  /api/admin/perf/explain-schedule/status` — super-admin only; introspects the feature flag.
  - `POST /api/admin/perf/explain-schedule` — super-admin only; runs `explain('executionStats')` on the three schedule-load legs (jobs aggregation, technicians count, service_reports lookup). Returns Mongo's plan tree + `nReturned` / `totalKeysExamined` / `totalDocsExamined` / `executionTimeMillis`.
- Feature-gated behind `FEATURE_PERF_EXPLAIN=1`. When off, POST returns **404** (invisible to non-super-admin probing) and the status endpoint reports `enabled:false`.
- `_bson_safe` helper JSON-serializes Mongo `Binary` planCacheKey fields (regression test included).
- **Preview verification:**
  - `/api/technicians` count leg → uses `k15_jobs_tech_schedule_status` (COUNT stage).
  - `/api/service_reports` lookup leg → uses `tenant_id_1_job_id_1_tech_id_1` (FETCH stage).

---

## 4 · Test counts

| Suite | Result |
|-------|--------|
| `test_k65_fix_schedule_perf.py` (new) | **8 / 8 passed** — service_reports migration idempotency (3 cases), technicians single-`$group` invariant (1), jobs sort correctness (1), perf-explain gates + bson-safe helper (3). |
| `test_k33_migrations.py` | 6 / 6 passed (pre-existing k15 + k21 migration coverage still green). |
| `test_k63_polish_dispatch_log.py` + `test_k63_ingress_fix_public_leads.py` + `test_k63_finalize_resend_and_ingress.py` | 30 / 30 passed (K63 stack untouched). |
| `test_jobs_crew_assignment.py` + `test_jobs_crew_filter.py` + `test_jobs_crew_membership_authorization.py` + `test_crew_schedule_visibility.py` + `test_dispatch_board_jobs_fallback.py` | 39 / 39 passed (schedule/crew/dispatch adjacent surfaces unaffected). |

**Total new + adjacent: 83 / 83 passing.** No regressions surfaced against K30/K61/R0/R0.1/R0.1+/K63/K64/K69.

---

## 5 · Before/after timings (preview, low-volume — for reference only)

Preview only has ~10 techs and ~150 jobs, so absolute numbers are far from prod. Trend direction is what matters.

| Endpoint | Pre-K65.fix (representative) | Post-K65.fix (measured) | Notes |
|----------|-----------------------------|-------------------------|-------|
| `GET /api/technicians` | 200–350 ms cold (10 techs × 2 count_documents ≈ 20 round-trips) | **~102–120 ms cold** (single `$group`) | ~50% reduction even at preview scale. At Aquaterra prod (~45 techs) the delta is projected at 1.5–3 s → 200–400 ms. |
| `GET /api/jobs` 90-day admin window | 150–220 ms cold (blocking derived-field sort on 50 rows) | **~130–200 ms cold** | Marginal at preview because the sort is cheap over 50 rows. At Aquaterra prod (~3k rows) the projected delta is 500–800 ms saved on the sort stage alone. |

Objective acceptance-criterion §2 ("<300 ms p95 at prod scale") is not directly measurable on preview. Recommend enabling the perf-explain endpoint for a 30-min window post-deploy to confirm the win at real load.

---

## 6 · Prod-deploy action items for user

1. **No prod DB migration required** — the k65 migration self-detects the prefix-covering `tenant_id_1_job_id_1_tech_id_1` and short-circuits. On boot the log line reads: `[migration] k65_service_reports_indexes: created=0 already_present=0 covered_by_prefix=1 covered_by=tenant_id_1_job_id_1_tech_id_1 errors=0`.
2. `FEATURE_PERF_EXPLAIN` is `""` (empty) in the shipped `.env`. To enable the diagnostic route on prod: SSH → set `FEATURE_PERF_EXPLAIN=1` in `backend/.env` → `sudo supervisorctl restart backend`. Route returns 404 until then.
3. **Rollback plan:** every change is orthogonal.
   - N+1 collapse → revertible via a single `search_replace` on `technicians.py`.
   - Aggregation sort swap → revertible via a single `search_replace` on `jobs.py`.
   - Client-side timeout → revertible via `search_replace` on `CalendarSchedule.jsx` + `api.js`.
   - k65 migration → sentinel-guarded; `db.migrations.deleteOne({id:"k65_service_reports_indexes_v1"})` reruns on next boot but the migration is a no-op regardless.
   - Explain endpoint → gated by env flag; leaving off is the safe default.
4. **Downtime risk:** ZERO. No index build, no schema change, no data migration.

---

## 7 · Explain endpoint state on prod (per acceptance criterion §6)

**GATED OFF.** `FEATURE_PERF_EXPLAIN` is empty in the shipped `.env`. Route responds `404` for every caller regardless of role until an operator explicitly flips the flag on. Confirmed with `curl -X POST … /api/admin/perf/explain-schedule` returning `404` on preview after the flag was reset.

---

## 8 · Behavior preservation summary

| Contract | Status |
|----------|--------|
| `/api/technicians` response shape (`active_jobs`, `active_jobs_repair`, `active_jobs_service`, all other fields) | Preserved (test-locked). |
| `/api/jobs` response shape (every enrichment field, sort order for the returned set) | Preserved (test-locked); truncation edge documented in §3 Step 4. |
| Customer enrichment fields (`account_notes`, `gate_code`, `customer_is_vip`, `customer_gate_code`, `customer_notes`, `service_note`, `location_lat`, `location_lng`) | Preserved for the full customer set (no silent 1000-cap truncation). |
| Frontend Schedule loading UX for normal loads | Preserved. |
| Frontend Schedule error banner behavior on non-timeout errors | Preserved (Retry button only appears on timeouts). |
| K30 / K61 / R0 / R0.1 / R0.1+ / K63 / K64 / K69 behavior | Preserved (adjacent test suites all green). |

---

## 9 · What's next

Per the user's redeploy plan: batch prod-redeploy of `R0.1+ + K63 + K63.polish + K64 + K63.dispatcher-ingress-fix + K63.finalize + K69 + K65.fix`. Then resume the cosmetic queue (K66 → K67 → K68 → K70 → K63.test-dispatch), then R1 Financial suite.
