# DIAG · P0 · `/schedule` "Failed to fetch" — Post-deploy runbook

**Status**: Diagnosis confirmed — preview is healthy, prod is broken. **No code change required.** Prod is running a stale bundle against a stale backend that predates the current schedule + haystack + pricebook rollout. This memo is the post-deploy runbook only.

---

## 1 · Root cause (one line)

Prod is running a frontend/backend pair that predates the current tip — the newer client calls routes and enrichments (`/api/crews`, MP2 job list fields, override-aware pricebook, updated `search_haystack` shape) that the prod backend either doesn't serve or serves against un-migrated data. Fix is a **fresh deploy + one-shot idempotent backfills**, not a code change.

---

## 2 · Post-deploy runbook

Run all `POST`s from a shell that can reach the prod API, as **`super_admin`** (`super@aquaterra.com`). Every endpoint below is **idempotent** — safe to re-run; the second run reports `0` writes. Order matters: index/id normalizers must land before backfills that read from them.

```bash
# --- Prep ---
API=https://<PROD-API-HOST>
SUPER=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"super@aquaterra.com","password":"<prod-super-password>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
AUTH="Authorization: Bearer $SUPER"
```

### 2.1 · User-required (in the specified order)

```bash
# (a) Rebuild customer search_haystack — required for /api/customers search
#     and any surface that filters on the tenant-scoped haystack shape.
curl -s -X POST "$API/api/admin/maintenance/rebuild-customers-haystack" -H "$AUTH"
# Expect: {"ok":true,"tenant_id":"…","scanned":N,"updated":M,"duration_seconds":…}
# Rate-limited to 1/hour per tenant — 429 with retry_after is EXPECTED if re-run inside the window.

# (b) Materialize recurring-job templates for orphan clusters. Idempotent.
curl -s -X POST "$API/api/recurring-jobs/backfill-orphans" -H "$AUTH"
# Expect: {"orphan_clusters":N,"templates_created":M,"skipped_existing":K}
```

### 2.2 · Other one-shot post-deploy migrations shipped since the last known-good prod deploy

Each of these has an idempotent `dry_run=true` default; pass `dry_run=false` to actually write. Roles are enforced server-side (super_admin gate on `/admin/migrations/*`). Order below is deliberate — normalize IDs and indexes **before** any backfill that reads them.

```bash
# Schema/index/id normalizers (must run first — schedule perf indexes + tech-id + customer-id shapes)
# K42/K44/K49b are one-shot migration scripts under backend/migrations/; expose them via the admin/migrations
# router (see admin_migrations.py) — if a matching endpoint is missing on the running pod, invoke the script
# with `python -m migrations.<name>` from the prod pod shell.
python -m migrations.k44_perf_indexes                       # schedule/dispatch covered indexes
python -m migrations.k42_normalize_job_tech_id              # jobs.technician_id: technicians.id vs users.id
python -m migrations.k49b_customer_id_backfill              # jobs.customer_id shape

# Business-data backfills exposed via /api/admin/migrations/* (super_admin, dry_run defaults to true)
curl -s -X POST "$API/api/admin/migrations/backfill-invoice-numbers?dry_run=false"          -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/invoice-line-cost-backfill?dry_run=false"        -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/revenue-line-items-uuid-category?dry_run=false"  -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/pricebook-suppliers?dry_run=false"               -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/service-category-chemicals?dry_run=false"        -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/service-reports-water-bodies?dry_run=false"      -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/chemical-usage-events-water-body?dry_run=false"  -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/notification-dispatch-log?dry_run=false"         -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/backfill-persona-avatars?dry_run=false"          -H "$AUTH"
curl -s -X POST "$API/api/admin/migrations/backfill-website-visitor-leads?dry_run=false"    -H "$AUTH"
```

Skip (**do NOT run** unless explicitly requested — non-idempotent side effects on external systems):
- `POST /api/admin/migrations/sync-stripe-customers` — hits Stripe API; already run at previous deploy per commit `b4d2e9dd`.
- `POST /api/admin/migrations/sync-stripe-billing-history` — same as above.
- `POST /api/admin/migrations/auto-merge-sweep` — customer merge; requires per-tenant dry-run review first.
- `POST /api/admin/migrations/deactivate-users` — roster cleanup; requires explicit user list.
- `POST /api/admin/migrations/audit-orphan-paid-invoices` — read-only audit but pointless during the hot deploy window.
- `POST /api/admin/lumino/backfill-payment-links` — Lumino payment links; only if the prod tenant uses Lumino.

---

## 3 · Smoke check (3 curl calls) — prove `/schedule` is healthy after deploy

Run as an admin (`admin@aquaterra.com`) — this mirrors what the browser does on `/schedule` load.

```bash
ADMIN=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@aquaterra.com","password":"<prod-admin-password>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
AH="Authorization: Bearer $ADMIN"
T=$(date -u +%Y-%m-%d); S=$(date -u -d "$T -30 days" +%Y-%m-%d); E=$(date -u -d "$T +60 days" +%Y-%m-%d)

# (1) Admin schedule window — the exact call CalendarSchedule.load() fires.
curl -s -o /tmp/j.json -w "admin_jobs   %{http_code}  %{time_total}s  %{size_download}B\n" \
     "$API/api/jobs?start=$S&end=$E" -H "$AH"
# PASS if: HTTP 200, time_total < 5.000s, size_download > 0, body is a JSON array.

# (2) Tech schedule window — proves scope_jobs_query still narrows correctly on prod data.
TECH=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"carlos@aquaterra.com","password":"<prod-tech-password>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -o /tmp/t.json -w "tech_jobs    %{http_code}  %{time_total}s  %{size_download}B\n" \
     "$API/api/jobs?start=$S&end=$E" -H "Authorization: Bearer $TECH"
# PASS if: HTTP 200, time_total < 5.000s, body is a JSON array (may be smaller than admin's).

# (3) Representative single-day query — proves ``scheduled_date`` filter + MP2 enrichments are intact.
curl -s -o /tmp/d.json -w "day_jobs     %{http_code}  %{time_total}s  %{size_download}B\n" \
     "$API/api/jobs?scheduled_date=$T" -H "$AH"
# PASS if: HTTP 200 AND (jq -r '.[0] | keys' /tmp/d.json) contains "property_label", "customer_is_vip",
#         "customer_gate_code", "service_note" (Feb-2026 MP2 UI enrichment fields present as keys, null
#         when absent). Missing keys → older backend → redeploy backend before retrying.
```

Two of the three must all pass green (admin_jobs + tech_jobs), and the day_jobs response must carry MP2 keys, before declaring the prod schedule fixed. Then open `/schedule` in a browser as admin — expect no red banner and a non-zero "N of N jobs" counter.

---

## 4 · Rollback signal — what to watch after the deploy

Tail these in the prod backend pod during the first 15 min post-deploy:

```bash
tail -f /var/log/supervisor/backend.err.log /var/log/supervisor/backend.out.log \
  | grep -E '\[429_OBS\]|slow_request|ERROR|Traceback'
```

**Rollback if any of these fire:**

1. **`[429_OBS] endpoint=GET /api/jobs …`** — schedule surface hitting the app-layer rate limiter. Any hit inside the first 5 min = the deploy widened the fan-out (e.g. mobile clients + web + WebSocket reconnects hammering `/api/jobs`); pre-deploy prod did not throttle here. Rollback if rate ≥ 5 events/min.

2. **`slow_request … path=/api/jobs … duration_ms=>10000`** — `/api/jobs?start=…&end=…` breaching 10 s on prod scale. Preview p50 is 350 ms; anything above 10 s on prod means the new K44 indexes did not land or the K42/K49b normalizers left orphan documents that force a collection scan. Rollback if p95 stays > 10 s across 20 consecutive samples.

3. **`Traceback` mentioning `customers_haystack` or `search_haystack`** — the haystack rebuild left partial state. Re-run step 2.1(a) once; if it recurs, rollback.

4. **`Traceback` on `/api/technicians` or `/api/crews`** — the schedule silent-fallback `.catch → []` will hide these from the banner, so the ONLY signal is a server-side traceback. Any 500 on either endpoint = rollback (the tech + crew dropdowns will render empty and mask bulk-reassign flows).

5. **Any request that returns 502 or 504** at the ingress with no matching backend log line — pod OOM / crash-loop from a startup migration. Rollback and investigate `dmesg` + supervisor state before retrying.

**"Deploy went sideways" summary indicator**: if the 3 smoke curls in §3 don't all pass green within 90 s of the deploy completing, or if any of the 5 signals above fire in the first 5 min, **roll back the frontend + backend deploy pair** and re-open this diagnostic in a fresh session.

---

## 5 · What this memo does NOT do

- Does NOT touch prod.
- Does NOT run `Save-to-GitHub`.
- Does NOT resume Phase 3.1 (Fix legacy lines health-tile bulk tool).
- Does NOT recommend any code change — the fix is a deploy, not a patch.

**Ship this runbook and stop.**
