# Geocoding — Prod Verification Runbook

**Owner:** on-call (platform/ops)
**Last updated:** Feb-2026 · TD-62
**Related ship stack:** C1 kill-switch (`2976b0668`) · C2 instrumentation (`1f590e73d`) · C2.5 telemetry gap closures (`2ef50d259`) · C3 permanent fix with sentinel + 180d TTL + `should_geocode` helper (`2c9a19ccd`)
**Monitored SKU:** Google Maps Platform — **Geocoding API** (`us-central1`)

---

## 1 · Overview

TD-62 investigated a **+3,422 % spike** in Google Geocoding API spend (`$474.01` burned Oct 1–16, concentrated on `us-central1`). Root cause: the `geocode_backfill_all_tenants_boot` lifespan sweep re-fired against every tenant × every customer on every pod boot, with only a 30-day inner cache guard. Legacy / newly-imported customers with `geocoded_at = NULL` re-geocoded on every boot.

The C-stack (C1 → C3) closed the leak and shipped end-to-end telemetry so the operator can **prove** post-deploy that the fix is holding:
- `GET /api/admin/diagnostics/geocode-usage?days=<1-90>` returns a server-side rollup of `db.geocode_call_log` with per-trigger / per-outcome / per-address counts.
- Admin-gated + tenant-scoped. Super-admins see all tenants (`tenant_scoped: false`); regular admins see their own tenant only (`tenant_scoped: true`).

This runbook is the **first 24 h post-deploy health-check** the on-call runs. Three curls, four green-flags, five red-flags, one escalation ladder.

---

## 2 · Quick usage

```bash
# 1. Set env vars (prod).
API_URL=https://<prod-host>              # e.g. app.<company>.com
# 2. Grab a super-admin token (cross-tenant visibility — recommended for first check).
ADMIN_TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
   -H "Content-Type: application/json" \
   -d '{"email":"super@<company>.com","password":"<prod-password>"}' \
   | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

```bash
# 3. 7-day rollup (default window; shows weekly trend).
curl -s -X GET "$API_URL/api/admin/diagnostics/geocode-usage?days=7" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
   | python3 -m json.tool
```

```bash
# 4. 1-day rollup (first 24 h post-deploy health-check).
curl -s -X GET "$API_URL/api/admin/diagnostics/geocode-usage?days=1" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
   | python3 -m json.tool
```

> **Tenant-scoped variant:** log in as a regular admin instead of super-admin. The response gains `tenant_scoped: true` and the rollup filters to the admin's own `tenant_id` only.

---

## 3 · Expected response shape

The endpoint returns a JSON object with **exactly 10 top-level keys**:

| Key | Type | Meaning |
|---|---|---|
| `window_days` | `int` (1–90) | Rolling window size (matches `?days=` query). |
| `window_start` | `str` (ISO UTC) | Inclusive lower bound of the aggregation window. |
| `window_end` | `str` (ISO UTC) | Exclusive upper bound. |
| `generated_at` | `str` (ISO UTC) | When this response was computed. |
| `total_calls` | `int` | Total `geocode_call_log` rows in the window across every outcome. |
| `unique_addresses` | `int` | Count of distinct non-null `address_hash` values. |
| `by_trigger_reason` | `dict[str,int]` | Per-trigger count. Known triggers: `property_create`, `customer_create`, `customer_patch_addr_change`, `boot_sweep`, `admin_backfill`, `lead_create_public`, `tenant_hq_patch`, `ai_measure_resolve`, `unknown`. |
| `by_outcome` | `dict[str,int]` | Per-outcome count: `hit`, `skipped_cached`, `skipped_unchanged`, `no_addr`, `error`. |
| `top_10_addresses_by_count` | `list[{address, address_hash, count, top_trigger_reason}]` | Hottest 10 addresses in the window; useful for spotting a stuck retry loop or per-tenant hot address. |
| `backend_vs_user_percent_split` | `{backend_pct, user_pct, backend_n, user_n}` | Backend-triggered (`{boot_sweep, admin_backfill, csv_import, manual_regeocode}`) vs user-triggered split. |
| `tenant_scoped` | `bool` | `true` when the caller is a regular admin (own tenant only); `false` for super-admin (cross-tenant). |

Missing any key → **BE deploy regressed `routers/admin_geocode_diagnostics.py`** — roll back immediately.

---

## 4 · 🟢 Green-flag thresholds (expected post-C3)

- `total_calls` in `?days=1` **< ~50 / tenant** on the busiest tenant.
  *What it means:* steady-state user-initiated geocoding only; the C3 180-day TTL + `should_geocode` short-circuit are suppressing repeat resolves.

- `by_outcome.skipped_cached + skipped_unchanged` **combined > 60 % of `total_calls`**.
  *What it means:* the C3 cache + hash guard is firing on cosmetic PATCHes and repeat addresses before any Google call.

- `by_outcome.hit` **dominated by `property_create` / `customer_create` / `customer_patch_addr_change`** (real user-initiated address resolves).
  *What it means:* the only paid Google calls are new/changed addresses typed by real users.

- `backend_vs_user_percent_split.backend_pct` **< 30 %**.
  *What it means:* the C1 kill-switch (`ENABLE_BOOT_GEOCODE_BACKFILL=false`) + C3 sentinel are suppressing all backend-side backfill churn. Admin-initiated backfills remain the only backend-flavored path and should be rare.

- `by_trigger_reason.boot_sweep` **== 0**.
  *What it means:* the C1 kill-switch is OFF **or** the C3 `migration_status` sentinel skipped every tenant on this pod boot. Both are safe states.

---

## 5 · 🔴 Red-flag thresholds (page the on-call)

- **`by_trigger_reason.boot_sweep > 0`** → the kill-switch flipped on without the C3 sentinel kicking in.
  *Action (in order):*
  1. Verify `ENABLE_BOOT_GEOCODE_BACKFILL` env var in the pod spec. If set to a truthy value and the operator did not intentionally enable it, unset it + roll the deployment.
  2. If the env is `false` but `boot_sweep` rows still appear, inspect `db.migration_status.find({"key":"geocode_backfill_v2"})`. There should be ONE row per tenant that completed a clean sweep. If rows are missing, the sentinel write path regressed.
  3. If both guards look correct, grep pod logs for `[phase17] sentinel written for tenant=` on recent boots — the write should fire once per tenant per pod.

- **`by_outcome.hit` dominated by `admin_backfill`** → somebody kicked `POST /admin/customers/geocode-backfill` manually and is burning budget.
  *Action:* `by_trigger_reason.admin_backfill` + `top_10_addresses_by_count` identify the responsible tenant/addresses; message them and confirm they intended the manual backfill.

- **Any address in `top_10_addresses_by_count` with `count > 5/day`** → either a stuck retry loop or a per-tenant hot address.
  *Action:* identify the row(s) via `db.geocode_call_log.find({"address_hash": "<hash>"}).sort({"called_at":-1}).limit(20)` and look at `entity_id` + `error` fields. If `error` is populated on repeated calls (e.g. `status_REQUEST_DENIED`, `http_5xx`), investigate the Google API key quota + billing status; if `outcome=="hit"` on every row, the `should_geocode` short-circuit is being bypassed and we have a C3 regression.

- **`backend_vs_user_percent_split.backend_pct > 70 %`** → spike regression.
  *Action:* compare `by_trigger_reason` dominance to narrow it down:
  - `boot_sweep` dominance → see red-flag #1.
  - `admin_backfill` dominance → see red-flag #2.
  - If neither, grep source for a new backend code-path that imports `geocode_address` / `geocode_and_persist_*` without passing a `trigger_reason` kwarg; the default is `UNKNOWN` so a new `unknown` surge is diagnostic.

- **Response schema missing any key / HTTP 500 / HTTP 403 for super-admin** → BE deploy regressed `routers/admin_geocode_diagnostics.py` or the admin RBAC guard.
  *Action:* roll back the latest BE deploy and open an incident.

---

## 6 · Known observation-hygiene note (NOT a red-flag)

`services/stop_geo.py` route-optimizer lazy-property backfill continues to log under `by_trigger_reason: "unknown"`. This is a **logged-but-unattributed** call — the geocode IS captured in `geocode_call_log`, only the attribution label is a placeholder.

- **It is NOT a telemetry gap.** `total_calls` + `by_outcome` still account for these rows correctly.
- **Future enum addition:** add `ROUTE_OPTIMIZER_LAZY_BACKFILL` to `services/google_maps/geocode_trigger.py::GeocodeTrigger` and update the `stop_geo.py` call-site. Deferred until post-deploy observation shows non-trivial volume (operator ruling: closed in C3 scope, re-opened in C4 only if `unknown` > 10 % of `total_calls` for 7 consecutive days).

---

## 7 · Related runbooks / TD references

- **Parent ticket:** TD-62 in `/app/memory/TECH_DEBT.md` (Google Geocoding API spend spike — closed).
- **C-stack commits:** C1 (`2976b0668`) · C2 (`1f590e73d`) · C2.5 (`2ef50d259`) · C3 (`2c9a19ccd`).
- **Test coverage:** `backend/tests/test_geocode_permanent_fix_c3.py` (17 cases) · `backend/tests/test_boot_geocode_gate.py` · `backend/tests/test_geocode_call_log.py` · `backend/tests/test_geocode_telemetry_gaps.py`.
- **Mapbox parallel-leak audit (Feb-2026):** mirror of this runbook deferred — operator decision Q2=B. Preview BE has a live `MAPBOX_ACCESS_TOKEN` and `services/gps_stops_batch.py` reverse-geocode fan-out on every unique new GPS stop. Phase 2 Mapbox instrumentation would mirror the exact pattern in this runbook (new `db.mapbox_call_log` + `MapboxTrigger` enum + `/admin/diagnostics/mapbox-usage` endpoint). Blast radius ~3–4 h of focused work. Re-visit when operator confirms whether prod Mapbox cost actually moved.
- **Mobile Mapbox env cleanup (Feb-2026):** `mobile/.env:EXPO_PUBLIC_MAPBOX_TOKEN` is residual post-K46 (`react-native-maps` migration). Cleanup dispatch going to `e1_expo_frontend_dev` separately — not covered by this runbook.
