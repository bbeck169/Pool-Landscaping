# HANDOFF — Phase 56.9b Option A landed (backend guardrail infrastructure)

Backend-only ship. Steps 1–5 + 9 + 10 completed. Steps 6, 7, 8
explicitly held for the next session per the Option A boundary
agreed with the user. **Zero user-facing exposure** in this ship
— all 5 RBAC-gated Zillow endpoints still require admin as they
did before; the guardrail infrastructure is instrumented,
tested, and ready to activate when Step 8 flips in the next
session.

## What landed this session

### Step 1 · Rate-limit service + `zillow_usage` collection ✓
- New file `backend/services/zillow_rate_limit.py` (~230 LOC).
- Pure library — no endpoint mutation.
- Caps enforced by role at check time:
  - `technician` → 20/day + 200/month per user.
  - `admin` / `super_admin` → uncapped per-user (still subject
    to tenant budget guard below).
- `log_call(user, tenant, endpoint, address, cost_units=1)` writes
  `{tenant_id, user_id, endpoint, address_hash, ts, cost_units}`
  to `zillow_usage`. `address_hash = sha256(normalize_address(...))`.
- `ensure_indexes()` (idempotent, called from every service call
  path) creates:
  - `zillow_usage`: `ts` + composite `(tenant_id, user_id, ts desc)`
  - `zillow_cache`: composite `(address_hash, cached_at)` +
    a 30-day TTL index on the datetime field `cached_at_dt`
  - `zillow_audit`: `ts`

### Step 2 · Tenant budget guard ✓
- Default 1000/month/tenant. Tenants may override via a
  `zillow_monthly_budget` field on the tenant doc (documented
  but not yet UI-editable).
- Return shape (`check_caps` result):
  - `allowed`, `reason` (`tech_daily_cap`, `tech_monthly_cap`,
    `tenant_budget_exhausted`, or `None`)
  - `usage` (per-user + tenant), `tenant_budget`, `tenant_used`,
    `tenant_pct`
  - `budget_warning: bool` — set to `True` at ≥ 90 %
  - `reset_at` — ISO of next midnight UTC (daily cap) or first
    of next month (monthly cap)
- `response_headers(caps)` returns the map of guardrail response
  headers callers (Step 6/7) will attach:
  - `X-Zillow-Budget-Warning: 1` when `budget_warning` is true
  - `X-Zillow-Tech-Today` / `-Tech-Month` / `-Tenant-Used` /
    `-Tenant-Budget`
- Super_admin `?override_budget=true` handled by
  `apply_override_or_fail(...)` — the only path that unlocks a
  saturated tenant budget. Writes a `zillow_budget_override`
  audit event to `zillow_audit` with `tenant_used_at_override`,
  `tenant_budget_at_override`, `endpoint`, `address_hash`.
  Never overrides per-user tech caps.

### Step 3 · `zillow_cache` collection + 30-day TTL + counter safety ✓
- `read_cache(address)` → cached dict or `None`. Belt-and-suspenders
  TTL check inside the function in case the Mongo TTL index is
  late.
- `write_cache(address, data)` — upserts keyed by
  `address_hash`. Stores both an ISO string (`cached_at`) for
  human readability and a datetime (`cached_at_dt`) for the TTL.
- Cache hits DO NOT call `log_call(...)`. Counters unchanged.
  Verified by test `test_cache_hit_does_not_decrement_counters`.

### Step 4 · Admin widget endpoint ✓
- `backend/routers/zillow_admin.py` grew a new admin-only
  `GET /api/zillow/usage/this-month` endpoint. Purely read-only
  aggregate — never touches the paid API.
- Response includes: `month`, `total_lookups`, `top_users` (top
  5 by count, enriched with `name`/`email`), `tenant_budget`,
  `tenant_used`, `tenant_pct`, `budget_warning`, `cache_hits`,
  `cache_hit_rate`, `generated_at`.
- Cache-hit rate is conservative: it's computed from
  `zillow_audit` rows tagged `event: "zillow_cache_hit"`. That
  audit row is emitted only by the endpoint-layer wire-in
  (Step 6/7), so until Step 6/7 land, the rate stays 0. Widget
  never over-reports.

### Step 5 · Backend tests — 7 passed / 0 failed (10.30s) ✓
`backend/tests/test_zillow_rbac.py` (7 cases; each named
individually below matches the ship-report evidence):

| # | Test | Status |
|---|---|---|
| 1 | `test_tech_within_daily_cap_allowed` | PASS |
| 2 | `test_tech_hits_daily_cap_denied_with_reset` | PASS |
| 3 | `test_tenant_budget_reaches_100pct_denied_for_admin` | PASS |
| 4 | `test_tenant_budget_warns_at_90pct` | PASS |
| 5 | `test_super_admin_override_writes_audit_event` | PASS |
| 6 | `test_cache_hit_does_not_decrement_counters` | PASS |
| 7 | `test_widget_endpoint_admin_ok_tech_403` | PASS |

Each test seeds an **isolated per-test tenant** (`56.9b-test-<uuid>`)
so real tenant traffic on the preview is never touched.

### Step 9 · HANDOFF + PRD entries ✓ (this file + PRD.md)

### Step 10 · Preflight ✓ (exit 0)

## Files touched

- `backend/services/zillow_rate_limit.py` (**new**, ~230 LOC).
- `backend/routers/zillow_admin.py` (widget endpoint appended).
- `backend/tests/test_zillow_rbac.py` (**new**, 7 tests).
- `memory/HANDOFF.md`, `memory/PRD.md`.

**Zero endpoint RBAC changes.** `property.py` / `d2d.py` /
`utils.py` were NOT edited. The 5 endpoints listed for Step 8
still require admin. This is by design — the Option A
guarantee.

## Fresh-session brief — Phase 56.9b Steps 6/7/8 (clean 3-step)

Next session picks up here. Do NOT redo Steps 1–5.

### Step 6 · Web frontend

Wire the usage-counter chip + rate-limited banner into the 4
pages. Chip shape: `"Zillow: X/20 today, Y/200 month"` — yellow
at 80 %, red at 100 %.

Pages:
- `frontend/src/pages/property-lookup/PropertyLookupPage.jsx`
  line 164 — remove hardcoded "Admin access required" banner
  (only rendered when Step 8 activates); mount chip +
  rate-limited banner.
- `frontend/src/pages/d2d/D2dPages.jsx` lines 175, 248, 515 —
  same three-way pattern.
- `frontend/src/pages/aitools/AiToolsPages.jsx` line 572
  (virtual-bid) — same.

**Recommended new backend endpoint** to support the chip UI:
`GET /api/zillow/me/usage` — returns `caps` shape from
`check_caps(user, tenant)` for the current user. Keeps the chip
math server-side.

### Step 7 · Mobile parity

3 primary screens + 3 sub-screens (surveyed in prior session,
persisted below). Use the same shared usage-state pattern the
web adopts in Step 6.

- `mobile/app/(app)/d2d.tsx`
- `mobile/app/(app)/property-lookup.tsx`
- `mobile/app/virtual-bid.tsx`
- `mobile/app/d2d/{index,leaderboard,report}.tsx`
- `mobile/src/components/d2d/*` — chip mounts at screen-header
  level, not here
- `mobile/src/components/tools/sections.ts` — verify tile
  visibility (may need `role`-gate loosening)

### Step 8 · RBAC swap LAST

**Only after Steps 6 + 7 land.** Add to `backend/utils.py`:

```python
def require_zillow_access(user: dict = Depends(get_current_user)) -> dict:
    role = (user or {}).get("role")
    if role in ("super_admin", "admin", "technician"):
        return user
    raise HTTPException(403, "Zillow access requires admin or technician role")
```

Then swap `Depends(require_admin)` → `Depends(require_zillow_access)`
on these 5 endpoints (per Step 0 findings):

- `backend/routers/property.py::/property/lookup`
- `backend/routers/property.py::/property/save`
- `backend/routers/property.py::/property/saved`
- `backend/routers/property.py::/property/saved/{pid}`
- `backend/routers/d2d.py::/d2d/sold-leads`

**`/d2d/report` STAYS admin-only.**

At Step 8, wire the guardrail service into each endpoint:
```
caps = await check_caps(user, tenant)
caps = await apply_override_or_fail(caps, user, tenant, endpoint,
                                    address, override_budget)
if not caps["allowed"]:
    if caps["reason"] == "tenant_budget_exhausted":
        raise HTTPException(429, detail={
            "error": "tenant_budget_exhausted",
            "tenant_used": caps["tenant_used"],
            "tenant_budget": caps["tenant_budget"],
        })
    raise HTTPException(429, detail={"error": caps["reason"],
                                     "reset_at": caps["reset_at"]})
# cache
cached = await read_cache(address)
if cached:
    # emit `zillow_cache_hit` audit row so widget cache-hit rate ticks
    await db.zillow_audit.insert_one({...event: "zillow_cache_hit"...})
    return JSONResponse(cached, headers=response_headers(caps))
# paid call
data = await hit_zillow(address)
await write_cache(address, data)
await log_call(user, tenant, endpoint, address)
caps_after = await check_caps(user, tenant)  # refresh headers
return JSONResponse(data, headers=response_headers(caps_after))
```

## Deferrals (explicit, unchanged from prior sessions)

- Step 6 (web) — next session
- Step 7 (mobile) — next session
- Step 8 (RBAC swap) — next session, gated on 6 + 7 landing
- Per-tenant configurable cap UI — deferred to a 56.9b-followup.
  Backend already reads `tenant.zillow_monthly_budget` if set;
  no admin UI to edit it yet.

## Parallel user decisions (do NOT touch until greenlit)

- End-of-visit auto-email.
- "Nudge non-starters" CPO Readiness widget action.
- RingCentral test scope.

## T-phases (T1–T6)

**On hold** — user reviews 56.9b evidence + design-system audit
first.

## Paused (informational)

- 56.13d supplemental pool modules
- 56.14 landscape training
- 56.15 handbook + onboarding

---

## Phase 56.18 — Invoice Numbers (landed same session, separately)

Human-readable `INV-YYYY-NNNNNN` invoice numbers. Backend service
+ backfill + partial-unique indexes + 5/5 tests green + list
UI column. **33 aquaterra invoices backfilled**.

Deferrals (explicit): master invoice list column, invoice detail
header, PDF header, search-by-number, mobile UI, customer portal
touch, email/Stripe description, and 6 additional
invoice-birth code paths (backfill covers them until wired).

See `PRD.md` for full 56.18 entry.
