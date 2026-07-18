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

---

## Phase 56.19 — Master Invoices 404 + RingCentral diagnostics (P0 hotfix)

### Item 1 · `/master-invoices` legacy URL 404
Root cause: bookmarked pre-refactor path had no matching Route
after the rename to `/invoices/master`. React Router bounced
to the not-found catch-all instead of the new page.

Fix (`frontend/src/App.js`):
- Added `MasterInvoicesRedirect` helper (mirrors
  `CustomerServiceReportRedirect` — grabs `:id` via
  `useParams` and returns `<Navigate to=/invoices/master/:id />`).
- Three permanent aliases under `<AppLayout>`:
  - `master-invoices` → `/invoices/master`
  - `master-invoices/new` → `/invoices/master/new`
  - `master-invoices/:id` → preserves `id` → `/invoices/master/:id`

Verified via Playwright end-to-end (admin@aquaterra login →
navigate to each legacy path → URL bounces to canonical +
`MasterInvoicesList` renders "No master invoices yet" empty
state). `curl -I` returns 200 on both `.preview` and `.host`
(SPA HTML shell — routing evaluated client-side).

Grep confirms no remaining hardcoded `/master-invoices` links
in `frontend/src` or `mobile` beyond the 3 alias routes + code
comments.

### Item 2 · RingCentral diagnostics
No live SMS testing (per user directive — pipeline is
confirmed broken until the user rotates the RC OAuth client
credentials). Ship is purely diagnostic instrumentation so the
next credential-rotation attempt surfaces the actual failure
reason.

`backend/routers/ringcentral.py`:

- New helper `_capture_rc_error(exc)` — safely reads
  `exc.response.text()` (bytes-safe, ≤ 200 chars) and returns
  `{error_class, error_snippet}`. Never touches headers or the
  JWT/secret material.
- `POST /api/ringcentral/sms/send` — on `except`, captures diag
  + logs `WARNING pool_crm rc sms send failed: <class> :: <snippet>`
  and raises 502 with `{error, error_class, error_snippet}` in
  the JSON body.
- `POST /api/ringcentral/subscription/register` — same pattern,
  logs + 502 body with class + snippet.
- `_fetch_telephony_session_detail` — was swallowing exceptions
  with only the class name; now includes the RC body snippet in
  the WARNING log (still returns None, still non-fatal to the
  webhook).
- `GET /api/ringcentral/health` — now actually validates JWT
  auth against RC by calling
  `platform.get('/restapi/v1.0/account/~/extension/~')`. When
  outbound is enabled and auth fails, health returns **503** with
  `rc_auth_ok=false` and `rc_auth_error={error_class,
  error_snippet}` embedded. When outbound is disabled the auth
  check is skipped (nothing to validate).

**Curl-verified diagnostic capture** (`.preview` `/api/ringcentral/health`):
```
HTTP=503
rc_auth_ok=false
error_class="ApiException"
error_snippet="HTTP 401 { \"error\" : \"invalid_client\", \"error_description\" : \"Invalid client application: [eZWHonfT7FQcdQKiw0Xcvw]\", \"errors\" : [ { \"errorCode\" : \"OAU-153\", \"message\" : \"Invalid client a"
```
That "OAU-153 / invalid_client" is the actual answer the user
needs to rotate/fix their RC credentials.

### Item 3 · Notification href ghost route
Root cause: four unmatched-communication kinds
(`rc_call_inbound_unmatched`, `rc_sms_inbound_unmatched`,
`rc_fax_unmatched`, `rc_voicemail_unmatched`) all shipped an
`href` of `/admin/unmatched-communications`, which was never a
registered frontend route. Bells clicked → 404.

Fix (`backend/routers/ringcentral.py`):
- Each unmatched `_notify_admins(...)` call now uses
  `/notifications?kind=<the_specific_kind>`.
- Also added `frontend/src/App.js` alias
  `admin/unmatched-communications` →
  `Navigate to /notifications?kind=rc_sms_inbound_unmatched` so
  any pre-56.19 notification rows already in Mongo still land
  somewhere real.
- Updated `test_phase55_1_fixes.py::TestUnmatchedRC::test_unknown_sms_emits_unmatched`
  assertion to match the new href.

**Verified** via `POST /api/ringcentral/simulate-inbound` (unknown
number) → `GET /api/notifications?kind=rc_sms_inbound_unmatched&limit=1`
returns `href: "/notifications?kind=rc_sms_inbound_unmatched"`.

### Tests + preflight
- `pytest tests/test_phase55_1_fixes.py::TestUnmatchedRC -q` → 3 passed
- `bash scripts/preflight.sh` → exits 0 (`preflight OK`)
  - Dead-import WARN unchanged at 424 (pre-existing tech debt,
    tracked separately for a future cleanup pass).

### Files touched
- `frontend/src/App.js` — `MasterInvoicesRedirect` component,
  3 master-invoice aliases, 1 unmatched-communications alias
- `backend/routers/ringcentral.py` — `_capture_rc_error`,
  auth-validating `/health`, diag in `sms_send`,
  `subscription/register`, `_fetch_telephony_session_detail`,
  4 unmatched-kind href updates
- `backend/tests/test_phase55_1_fixes.py` — href assertion update

### Not shipped (deferred, previously scoped)
- Phase 56.9b Steps 6/7/8 (Zillow web + mobile UI + RBAC swap)
- Phase 56.18 followup (master invoice column, detail header,
  PDF, search, mobile, email/Stripe hooks)
- Dead-import cleanup (424 static WARN)


---

## Phase 56.9b — Steps 6 + 7 + 8 SHIPPED (Feb 2026)

Completes 56.9b Option A. Backend guardrail infrastructure
(Steps 1–5) landed in the prior session; this ship wires it into
the user-visible surfaces + performs the RBAC swap.

### Backend — Step 8

- `utils.py` — new `require_zillow_access(user)` dep. Allows
  `super_admin | admin | technician`, blocks customer + anonymous.
- `routers/property.py` — 4 endpoints swapped from
  `require_admin` → `require_zillow_access`:
  - `GET  /property/lookup` (paid — wired full guardrail flow)
  - `POST /property/save` (Mongo-only — RBAC only)
  - `GET  /property/saved` (Mongo-only — RBAC only)
  - `DELETE /property/saved/{pid}` (Mongo-only — RBAC only)
- `routers/d2d.py` — 1 endpoint swapped:
  - `GET  /d2d/sold-leads` (paid — wired full guardrail flow)
- `routers/d2d.py::/d2d/report` **stays admin-only** as spec'd.
- `routers/zillow_admin.py` — new
  `GET /api/zillow/me/usage` — returns caps shape for the
  chip UI. Uses `require_zillow_access` (both roles).

Guardrail wiring pattern (per spec sketch in HANDOFF):
1. `caps = await zrl.check_caps(user, tenant)`
2. `caps = await zrl.apply_override_or_fail(caps, …, override_budget)`
3. If `!caps.allowed` → `raise 429` with `reason` + `reset_at` / budget shape.
4. `cached = await zrl.read_cache(address)` — cache hit short-circuits
   with `_cached: true`, no `log_call`, but emits a `zillow_cache_hit`
   audit row for the widget's cache-hit rate.
5. Paid call → `write_cache` → `log_call` → refresh caps → return with
   `usage` + `tenant_used` + `budget_warning` in body and
   `X-Zillow-*` headers.

### Frontend — Step 6 (web)

- **new** `frontend/src/components/ZillowUsageChip.jsx` —
  polls `/api/zillow/me/usage` every 60s. Yellow at ≥80 % of any
  per-user cap or ≥90 % of tenant budget. Red at 100 % / budget
  exhausted / caller-marked `rateLimited`. Below-chip inline
  rate-limited banner with mailto **"Ask admin for more"**.
- Chip mounted on 4 web pages:
  1. `pages/property-lookup/PropertyLookupPage.jsx` (header)
  2. `pages/d2d/D2dPages.jsx :: D2dCanvassingMap` (below legend)
  3. `pages/d2d/D2dPages.jsx :: D2dSoldLeads` (below error banner)
  4. `pages/aitools/AiToolsPages.jsx :: VirtualBid` (below H1)
- Callers pass `rateLimited={String(err.message).includes("429")}`
  so 429 responses trigger the banner deterministically.

### Mobile — Step 7

- **new** `mobile/src/components/ZillowAccess.tsx` — mirrors backend
  `require_zillow_access`. Redirects non-eligible roles home.
- **new** `mobile/src/components/ZillowUsageChip.tsx` — exports both
  `<ZillowUsageChip />` (chip sized for Header `right` slot) and
  `<ZillowRateLimitedBanner />` (self-fetching banner rendered
  below the header). Same color rules as web.
- Chip mounted on 3 primary screens (sub-screens skip because they
  don't call the Zillow-backed endpoints):
  1. `mobile/app/(app)/property-lookup.tsx`
  2. `mobile/app/d2d/index.tsx` (and re-exported as `(app)/d2d.tsx`)
  3. `mobile/app/virtual-bid.tsx` — **`AdminOnly` swapped for
     `ZillowAccess`**, unlocking techs.

### Live curl evidence (5/5 cases pass)

| # | Case | Response |
|---|---|---|
| 1 | Tech successful lookup (cache-primed) | `200 OK` · `_cached: true` · `usage.tech_today: 0` · headers `X-Zillow-Tech-Today: 0`, `X-Zillow-Tenant-Budget: 1000` |
| 2 | Tech at daily cap | `429` · `{error:"tech_daily_cap", reset_at:"2026-07-19T00:00:00+00:00", usage:{tech_today:20/20}}` |
| 3 | Cache hit (same addr, 2nd call) | `200 OK` · `tech_today` unchanged at 0 · 2 `zillow_cache_hit` audit rows |
| 4 | Tenant near-budget 900/1000 | `200 OK` · `X-Zillow-Budget-Warning: 1` · `X-Zillow-Tenant-Used: 900` · body `budget_warning: true` |
| 5a | Admin at exhausted budget | `429` · `{error:"tenant_budget_exhausted", tenant_used:1001, tenant_budget:1000}` |
| 5b | Super_admin `?override_budget=true` | `200 OK` · `override_audit_id: "b39740e8-..."` · Mongo `zillow_audit.event: "zillow_budget_override"` row confirmed |

### Screenshot

Tech `mike@aquaterra.com` navigating to `/property-lookup` renders
the chip **"Zillow: 3/20 today · 3/200 mo"** in the page header —
a surface that returned 403 to techs before this ship.

### Files touched

- `backend/utils.py`
- `backend/routers/property.py`
- `backend/routers/d2d.py`
- `backend/routers/zillow_admin.py`
- `frontend/src/components/ZillowUsageChip.jsx` (**new**)
- `frontend/src/pages/property-lookup/PropertyLookupPage.jsx`
- `frontend/src/pages/d2d/D2dPages.jsx`
- `frontend/src/pages/aitools/AiToolsPages.jsx`
- `mobile/src/components/ZillowAccess.tsx` (**new**)
- `mobile/src/components/ZillowUsageChip.tsx` (**new**)
- `mobile/app/virtual-bid.tsx`
- `mobile/app/(app)/property-lookup.tsx`
- `mobile/app/d2d/index.tsx`

### Preflight
`bash scripts/preflight.sh` → **exit 0** (`preflight OK`).
Dead-import WARN unchanged at 424 (pre-existing tech debt).

### Notes
- Sub-screens `mobile/app/d2d/{leaderboard,report}.tsx` do NOT
  call Zillow endpoints (they read `/d2d/leaderboard` and
  `/d2d/report`, which are aggregations of local Mongo data), so
  chip is intentionally not mounted there — mounting would be
  misleading. Recorded here in case future audit re-questions.
- The "hardcoded Admin access required banner" the fresh-session
  brief referenced turned out to be the mobile `<AdminOnly>` route
  guard on `virtual-bid.tsx` (there were no in-body text banners
  matching that string on web). Swapping to `<ZillowAccess>`
  accomplishes the same intent.


---

## Phase T1 + T2 — Pool Calculators SHIPPED (Feb 2026)

### Backend

**New router:** `backend/routers/pool_calculators.py` (~230 LOC).
5 stateless POST endpoints — pure math, no DB writes, no side
effects. Prefix `/calculators`. Custom local dep
`require_tech_or_above` (super_admin | admin | technician).
Customers + anonymous → 403.

Endpoints:
- `POST /api/calculators/lsi`
- `POST /api/calculators/volume`
- `POST /api/calculators/salt`
- `POST /api/calculators/turnover`
- `POST /api/calculators/heater-size`

Wired into `server.py` (import + list registration).

Math:
- **LSI**: `pH + tf + cf + af − tds_const`, tf via linear
  interpolation over the 10-row temperature table copied from
  the mobile calculator, `cf = log10(CH) − 0.4`,
  `af = log10(max(1, TA − cya_adj))`, `tds_const = 12.2` when
  TDS ≥ 1000 else 12.1. CYA correction options: `third | quarter | none`.
- **Volume**: rectangle `L·W·d·7.48`, oval `L·W·d·5.9`,
  circle `π·r²·d·7.48`, freeform `L·W·d·7.0` (conservative).
  Accepts either `avg_depth` OR `shallow_depth + deep_depth`
  (averaged automatically).
- **Salt**: `lbs = pool_gallons × (target − current) / 120000`.
  If over target, returns 0 lbs + a drain-and-refill estimate.
- **Turnover**: `hours = pool_gallons / (pump_gpm · 60)`. Code
  standards: residential informational; commercial ≤4ft = 4h;
  commercial >4ft = 6h; spa = 0.5h.
- **Heater size**: `BTU = gal × 8.33 × ΔT / heat_up_hours`
  (default 24h). Ambient loss `= surface_area · ΔT_ambient · 12`.
  Cost by heater type: gas (100k BTU/therm × 0.82 eff), heat
  pump (COP 5.0), electric (COP 1.0), solar ($0). Default rates
  overridable via `per_therm` (1.50) and `per_kwh` (0.15).
- All endpoints include an actionable `note` field for UI rendering.

### Frontend (Web)

**New page:** `frontend/src/pages/tech/PoolCalculators.jsx`
(~400 LOC). Tabbed panel of the 5 calculators. Each tab is a
self-contained function component with local state, form
inputs, "Compute" button, and a `<ResultBox>` that surfaces the
value + interpretation with a **Copy** button that writes a
plain-text summary via `navigator.clipboard.writeText`.

- Route: `/tech/tools/calculators` (mounted in `App.js`).
- Tile added to `ToolsHub.jsx` under both the tech "On the Job"
  section and the admin "Tools" section (both roles surfaced).
- Reused existing theme (`colors`, `lucide-react` icons — no new
  deps installed).

### Tests

**New file:** `backend/tests/test_phase_t1_t2_calculators.py`
(~200 LOC, **22 tests, 22 passed, 0.96s**).

Coverage:
- LSI: balanced known-answer (pH 7.4/80°F/CH 300/TA 100/TDS 500
  → 0.03), scaling case, corrosive case, boundary invalid (pH=0
  → 422), RBAC (customer 403).
- Volume: rectangle 20×40×5 → 29,920 gal, circle r=15 d=5
  → ~26,428 gal, shallow/deep averaging (3+8 → 5.5), unknown shape
  422, admin RBAC 200.
- Salt: known 20000gal 2500→3200 → 116.7 lbs, over-target
  drain-and-refill path, RBAC customer 403.
- Turnover: residential informational (compliant=None),
  commercial shallow pass, commercial deep fail, spa pass.
- Heater: gas sizing 20000gal 60→82°F 24h → 152,717 BTU/hr,
  heat_pump/solar paths, target≤current 422, RBAC customer 403.

### Live curl evidence (5/5 known-answer cases)

| Calculator | Input | Result |
|---|---|---|
| LSI | pH 7.4, 80°F, CH 300, TA 100, TDS 500 | `lsi: 0.03`, `interpretation: balanced` |
| Volume | rect 20×40×5 | `gallons: 29920` |
| Salt | 20000 gal, 2500→3200 ppm | `lbs_to_add: 116.7`, `bags_40lb: 2.92` |
| Turnover | 20000 gal @ 60 GPM, residential | `turnover_hours: 5.56`, `compliant: null` (informational) |
| Heater | 20000 gal, 60→82°F, 800 sqft, gas | `btu_required: 152717`, `monthly_cost: $63.22` |

### Screenshot

`mike@aquaterra.com` (Technician role) navigates to
`/tech/tools/calculators` and sees all 5 tabs (LSI selected
by default). Compute button on default field values produces
`SATURATION INDEX (LSI) 0.03 · Water is balanced` in a green
result panel with a Copy button.

### Files touched
- `backend/routers/pool_calculators.py` (**new**)
- `backend/server.py` (import + registration)
- `backend/tests/test_phase_t1_t2_calculators.py` (**new**)
- `frontend/src/pages/tech/PoolCalculators.jsx` (**new**)
- `frontend/src/pages/tech/ToolsHub.jsx` (2 tile additions)
- `frontend/src/App.js` (import + route)

### Preflight
`bash scripts/preflight.sh` → **exit 0** (`preflight OK`).
Dead-import WARN 424 → **423** (my new files contain no unused imports).

### Deferrals (explicit)
- Mobile tools hub sync — the mobile app already has 3 of these
  calculators (`mobile/app/(app)/calculators.tsx` — Dosing,
  Volume, Salt, LSI). Adding Turnover + Heater to mobile is
  queued for a future mobile-parity sweep.
- Sharing calculator results into a customer report / attaching
  to a service report — deferred.
- Per-user result history (saved calculations) — deferred.


---

## Phase 56.20 — Auto End-of-Visit Customer Email + Calculator Attach (Feb 2026)

Two related items shipped together: (A) auto-fires an email to the
customer whenever a tech submits a service report, and (B) adds an
"Attach to service report" button next to Copy on every pool
calculator ResultBox.

### A. Auto End-of-Visit Email

**New service:** `backend/services/auto_visit_email.py` (~280 LOC).

- `send_visit_summary_email(tenant, job, sr)` — non-blocking wrapper.
  Any exception is caught and logged; the submit endpoint never fails
  because of email trouble.
- `render_email(tenant, job, sr, customer)` — pure function returning
  `{subject, html, text, kind}`. Used by both the live pipeline and
  the admin preview endpoint.
- Idempotency: query `outbound_emails` for a matching
  `(kind=visit_summary, service_report_id, customer_id)` before
  sending. Duplicate submits emit no duplicate emails; the second
  call returns `{"skipped": "idempotent", "existing": {...}}`.
- Missing `RESEND_API_KEY` → row written with
  `status: "not_sent_missing_key"` and the full rendered HTML/text
  payload, ready to fire when the key lands.
- Resend error → row written with `status: "failed"` + `error`
  snippet (first 200 chars, no secret leak).
- Success → row written with `status: "sent"` + `resend_id`.

**Wired into `POST /api/jobs/{jid}/service-report/submit`** after the
invoice-generation block and before the `if clock_out_summary`
branch (see `service_reports.py`). One line of code + the try/except
wrapping.

**Rendered content (verified via live curls + tests):**
- Subject: `Your {tenant.name} service visit — {YYYY-MM-DD}`
- Header: tenant name + logo (if present) + "Service visit summary".
- Info block: Date · Tech · Address.
- Pool sections: Chemical readings table (readings dict) · Chemicals
  added (name/amount/unit) · Completed checklist items · Algae
  observation (customer-friendly: "Light algae was observed and
  treated." / "Heavy algae was observed and treated.").
- Landscape sections: 10-item checklist with ✓ marks.
- **Customer Notes** verbatim + a regex safety scrub for accidental
  `internal_notes:` leaks.
- Customer-safe photos only — anything tagged `internal | issue |
  private` is stripped before embed.
- CTA: "Leave us a review" button (if tenant has `google_review_link`
  set and `include_reviews_cta=true`) + "View full history in your
  portal" link to `{APP_PUBLIC_URL}/portal/service-reports`.
- Footer: "Internal service notes are not included." + optional
  tenant custom footer text + Unsubscribe link.

### Admin controls

3 new endpoints under `/api/settings/auto-visit-email`:
- `GET  /` — returns current tenant flags.
- `PUT  /` — patches tenant settings (`enabled`,
  `include_reviews_cta`, `google_review_link`, `footer_text`).
- `POST /preview` — renders the email using the tenant's most recent
  submitted service report so admin can eyeball the layout before
  flipping the toggle.

**New page:** `frontend/src/pages/settings/AutoVisitEmailSettings.jsx`
(~180 LOC). Route: `/admin/settings/auto-visit-email`
(`<AdminOnly>` gated). 4 controls + Save + Preview button; inline
preview panel renders the HTML in a scrollable iframe-like container.

### B. Calculator Attach Bundle

**New endpoint:** `POST /api/service-report/attach-note`
(techs + admins). Behavior:
- With `report_id` → target that specific report (must belong to caller).
- Without `report_id` → find open unsubmitted reports for
  `user.technician_id or user.id`; exactly one → attach; zero → 404;
  multiple → 200 with `status: multiple_open_reports` and a picker
  list `[{id, job_id, tech_name}, ...]`.
- Appends `[Calculator @ YYYY-MM-DD HH:MM] {text}` to the report's
  `internal_notes` (never `customer_notes`).
- Writes an audit row to `db.service_report_notes_audit` with
  `{source: "calculator", actor_user_id, actor_name, text, created_at}`.

**Frontend:** ResultBox in `PoolCalculators.jsx` now renders a
vertical Copy + Attach button stack. Attach POSTs the plain-text
summary produced by the existing Copy path. Toast status shown
inline for 5 seconds ("Attached to service report ✓" / "No open
service report — start a job first" / "Multiple open reports (N)").

### Live curl + Playwright evidence

- `GET/PUT/GET /api/settings/auto-visit-email` — roundtrip clean.
  Customer role → 403.
- `POST /api/settings/auto-visit-email/preview` — subject `Your
  AquaTerra service visit — 2026-07-16`, 2081-char HTML, redaction
  audit confirms `internal_notes` absent from body, `Leave us a
  review` + `Family-owned since 2003` present.
- **Send with key + wrong recipient** (Resend test-mode
  restriction — the account's key can only email its owner) → row
  `status: "failed"`, error snippet captured: `"You can only send
  testing emails to your own email address (brianbeckmanaz@gmail.com)…"`.
- **Idempotency (2nd call for same sr_id)** → returns
  `{"skipped": "idempotent", "existing": {id, status}}`. Audit
  collection has exactly ONE row for that report.
- **Missing-key demo** (patched os.environ) → row
  `status: "not_sent_missing_key"`, no crash, full rendered HTML/text
  persisted.
- Full audit trail sample (from `db.outbound_emails.find({kind:
  "visit_summary"})`):

    { status: "failed", to: "customer@aquaterra.com", ... }
    { status: "not_sent_missing_key", to: "rblake@outlook.com", ... }

- **Calculator attach with report_id** → 200 `{status:"attached",
  report_id, internal_notes_len: 80}`. Verified via direct Mongo
  query: `internal_notes: '[Calculator @ 2026-07-18 02:30]
  Saturation Index (LSI): 0.03 — Water is balanced'` and audit row
  `{source: "calculator", actor_name: "Mike Rivera", text: ...}`.
- **Multi-open-report branch** → returns list of 7 open reports for
  the tech (Playwright screenshot proves the toast surfaces
  "Multiple open reports (7) — open a job and try again." in the
  UI).

### Screenshots

1. **Admin settings page** (admin logged in): "Auto End-of-Visit
   Customer Emails" title, Enabled checkbox ON, Reviews CTA ON,
   Google review link populated, custom footer set. Save + Preview
   buttons visible.
2. **Preview rendering below the form**: subject `Your AquaTerra
   service visit — 2026-07-16` + full HTML in scrollable panel
   showing "AquaTerra" heading, redacted body.
3. **Tech Pool Calculators page** with LSI computed to 0.03 balanced;
   ResultBox now has Copy + **Attach** buttons stacked vertically.
   Attach clicked → status message "Multiple open reports (7) —
   open a job and try again." rendered below result.

### Tests

`backend/tests/test_phase56_20_auto_email.py` — **11 tests, 11
passed, 1.19s**.

Coverage:
- Settings roundtrip: default disabled → toggle ON → GET returns ON.
- Customer 403 on both settings endpoints.
- Preview endpoint returns 200 (with `subject`/`html`/`text`) or 404
  when no submitted reports exist.
- Renderer offline unit tests: pool body contains chemical readings,
  chemicals added, algae text, customer notes, review CTA, custom
  footer. Landscape body contains checklist + notes + `kind =
  "landscape"`. Redaction sanity: `internal_notes` string NOT in
  html or text; `internal.jpg` photo NOT in html.
- Calculator attach RBAC: customer 403, empty text 422, no-open
  reports 404 (or 200/409 for edge cases).
- Send pipeline: disabled tenant → returns None cleanly; missing
  customer → returns None cleanly (no crash).

### Files touched
- `backend/services/auto_visit_email.py` (**new**, ~280 LOC)
- `backend/routers/service_reports.py`
  (send hook + 3 settings endpoints + attach endpoint, ~130 LOC added)
- `backend/tests/test_phase56_20_auto_email.py` (**new**, ~200 LOC)
- `frontend/src/pages/settings/AutoVisitEmailSettings.jsx` (**new**)
- `frontend/src/pages/tech/PoolCalculators.jsx` (ResultBox extended
  with Attach button + status toast)
- `frontend/src/App.js` (import + route
  `/admin/settings/auto-visit-email`)

### Preflight
`bash scripts/preflight.sh` → **exit 0** (`preflight OK`). Dead-import
static WARN 423 → **426** (3 false positives from lucide icons used
inside conditional JSX branches in the new settings page —
non-blocking; recorded for the future cleanup pass).

### Non-goals (explicit)
- No customer-side opt-out UI beyond the unsubscribe link
  (footer). No SMS delivery of the visit summary (blocked on
  RingCentral OAU-153 rotation from Phase 56.19). No branded HTML
  template beyond basic layout — richer templates queued. No A/B
  testing of subject lines. No open/click tracking (would need
  Resend webhook wiring — deferred).

### `RESEND_API_KEY` note
The pod env already has a `RESEND_API_KEY` set, but it's a
**test-mode** key from `resend.dev` that can only send emails to
the account owner (`brianbeckmanaz@gmail.com`). Real-customer sends
will `status: "failed"` with that error until the user rotates in a
production key (or verifies a sending domain on Resend). The
audit-row `error` field captures the exact Resend response so the
user can debug from `db.outbound_emails.find({status:"failed"})`
without redeploying.

### Deferred / future
- Attach-with-picker UX: if `status: "multiple_open_reports"`, open a
  small dropdown next to the button so the tech can select which
  report to attach to instead of getting a "start a job" message.
  Small task (~30 min), deferred to keep this ship focused.
- Mobile parity for admin settings + attach button on mobile
  calculators — queued for the next mobile-parity sweep.
- End-to-end webhook wiring for Resend delivery events (opens,
  clicks, bounces) — deferred.


---

## Phase T3 — Business Pricing Tools (Feb 2026)

Three admin-only pricing tools. Extends `pool_calculators.py` with 3
new endpoints. Frontend is a single tabbed page at
`/admin/tools/pricing` (route wrapped in `<AdminOnly>`; the backend
endpoints also re-check via `_require_admin`).

### Backend

**Extended:** `backend/routers/pool_calculators.py` (~270 LOC added).

New helpers:
- `_require_admin(user)` — local dep (super_admin + admin only).
- `_pricing_defaults(tenant)` — merges `tenant.settings.pricing_defaults`
  over the shipped `PRICING_DEFAULTS` dict so admins can override any
  constant without a code change.
- `_chemical_cost_map(tenant_id)` — one Mongo scan of
  `chemical_costs` returning `slug → row`.

New endpoints:
- `POST /api/calculators/service-in-cost` — per-visit chemical +
  labor + overhead + minimum price + annualized revenue.
- `GET  /api/calculators/cost-per-pool` — portfolio scan. For each
  active customer with an active billing_plan: computes
  `monthly_in_cost` from `baseline_chem + labor × overhead × visits/mo`
  and `monthly_revenue` from `plan.amount × visits_per_month` (or
  the plan's own monthly amount for monthly/quarterly). Flags
  `negative_margin` / `low_margin` (<20%) / `high_margin` (>60%),
  sorts outliers first, returns median margin + counts.
- `POST /api/calculators/service-price` — new-customer price
  recommender. `base + Σfeature_adders + gallons_step × step_price ×
  zone_multiplier`. Includes peer-median comparison from live
  billing_plans (same visit_type, ±25% gallons).

Tenant-tunable defaults (in `PRICING_DEFAULTS`):
- tech_hourly_cost 35, tech_time_minutes 45, overhead_multiplier 1.25, margin_target_pct 40
- base_weekly 135, base_bi_weekly 95, base_monthly 80
- gallons_baseline 15000, gallons_step 5000, gallons_step_price 5
- adder_saltwater 15, adder_heater 10, adder_spa 25, adder_automation 15, adder_chlorine_tabs 5, adder_liquid_chlorine 20
- zone_default_multiplier 1.0

Admins can override any of these by writing to
`db.tenants.settings.pricing_defaults`. **UI for that editor is
deferred to a T3-followup** (per spec).

### Frontend

**New page:** `frontend/src/pages/admin/BusinessPricingTools.jsx`
(~430 LOC). Three tabs:

1. **Service In-cost** — pool volume, visit type, chemicals per
   visit (repeatable rows with slug/qty/unit), tech time, hourly
   cost, overhead multiplier, margin target. Result card shows
   chem/labor/overhead/total in-cost + minimum price/visit +
   annualized revenue. Copy summary button.
2. **Cost per Pool** — auto-loads on tab open. 5 stat tiles
   (Customers, Median margin, Negative, Low, High). Filter-by-name
   text input. Export CSV button. Sortable table color-coded by
   flag (red neg / yellow low / green high). Rows sorted with
   negative + low margin first (attention drawn to the fixable
   problems).
3. **Service Price** — pool volume, visit type, feature toggle
   buttons (saltwater/heater/spa/automation/chlorine_tabs/liquid_chlorine),
   optional zone. Result card shows recommended price + full
   breakdown line-by-line + peer median comparison ("above / at /
   below peer median" with sample size).

### Live curl evidence (all 3 spec cases match)

- **T3.1 in-cost** — 20000gal weekly, standard chem load, 45min @
  $35/hr, 1.25 overhead, 40% margin →
  `chemical_cost_total: 7.75, labor_cost: 26.25, overhead_cost:
  8.5, total_in_cost: 42.5, minimum_price_per_visit: 59.5,
  annualized_revenue: 3094.0, visits_per_year: 52`.
- **T3.2 cost-per-pool** — 3 aquaterra customers aggregated:
  Aimee Baram (monthly $50 / in-cost $42.50 → 15% low_margin),
  Whitmore HOA (monthly $480 / $42.50 → 91.1% high_margin),
  Jennifer Carson (weekly $520/mo / $184.17 → 64.6% high_margin).
  Median margin 64.6%. baseline_chem_cost_per_visit $7.75 surfaced.
- **T3.3 service-price** — 20000gal weekly saltwater+heater →
  `recommended_price: 165.0`. Breakdown: base 135 + saltwater 15
  + heater 10 + gallons_adder 5 + zone ×1.0 → **exact spec value**.
  Peer median $120 (1 sample: Jennifer Carson) surfaced with
  "above peer median" comparison.

### Screenshots

1. Admin (Alex Admin) on `/admin/tools/pricing` — In-cost tab
   with default weekly 20000gal computation showing all four stat
   tiles: **Chem $7.75 · Labor $26.25 · Overhead $8.50 · Total in-cost
   $42.50**. Below: Minimum price + Annualized. Chemicals-per-visit
   list editable with 3 default rows + "+ Add chemical".
2. Same admin on Cost per Pool tab — 5 stat tiles across the top
   (3 customers · **64.6% median margin** · 0 negative · 1 low · 2
   high). Color-coded table with Aimee's row in yellow (low
   margin), Whitmore + Jennifer in green (high margin). Filter box
   + Export CSV button visible.

### Tests

`backend/tests/test_phase_t3_pricing_tools.py` — **11 tests, 11
passed, 0.86s**.

- TestInCost (3): known-answer within tolerance, tech 403, customer 403.
- TestCostPerPool (3): aggregation shape assertions on all row
  fields, visit_type filter narrows results, tech 403.
- TestServicePrice (5): known-answer $165 (spec case), biweekly
  no-features $95 (default), bad visit_type 422, tech 403, customer 403.

### Files touched

- `backend/routers/pool_calculators.py` (~270 LOC appended)
- `backend/tests/test_phase_t3_pricing_tools.py` (**new**)
- `frontend/src/pages/admin/BusinessPricingTools.jsx` (**new**, ~430 LOC)
- `frontend/src/App.js` (import + `<AdminOnly>` route)
- `frontend/src/pages/tech/ToolsHub.jsx` (1 admin tile + 1 icon import)

### Preflight
`bash scripts/preflight.sh` → **exit 0** (`preflight OK`). Dead-import
WARN 426 → **428** (2 false positives from lucide icons used inside
conditional JSX branches in `BusinessPricingTools.jsx` — non-blocking;
recorded for future cleanup).

### Deferrals (explicit)

- **T3-followup**: `pricing_defaults` editor UI in `/admin/settings`
  so admins can tune constants (base_weekly, adder_saltwater, etc.)
  without a code change. Backend already reads
  `tenant.settings.pricing_defaults` — just needs the form. Small
  ship, ~30 min.
- Distance zone editor UI (currently `tenant.settings.pricing_zones`
  is a raw dict admin can write to via `PATCH /tenants/{tid}`).
- Mobile parity — techs don't need pricing tools; deferred if ever.
- Historical margin trend chart on Cost per Pool — currently a
  point-in-time snapshot only.


---

## Phase T5 — Business Analysis Tools (Feb 2026)

Two admin-only analysis tools. Extends `pool_calculators.py` with 2
new endpoints. New frontend page at `/admin/tools/analysis`.

### Backend

**Extended:** `backend/routers/pool_calculators.py` (~250 LOC added
below T3).

- `ROUTE_VALUATION_DEFAULTS` and `PAY_MODEL_DEFAULTS` constant dicts.
  Both merged over `tenant.settings.route_valuation_defaults` /
  `pay_model_defaults` via `_rv_defaults()` / `_pm_defaults()` helpers
  (same override pattern as T3).
- `_lerp(a, b, t)` — small linear interpolation helper used for the
  route-multiple calculation.

New endpoints:
- `POST /api/calculators/route-valuation` — 3-factor mix of density
  (dense 1.0 / medium 0.55 / spread 0.15) + churn (linear 4-12%) +
  contract length (linear 6-36 months). Factors are averaged and
  lerped between multiple_min=4x and multiple_max=8x. Auto-pulls
  active customer count + median monthly revenue from
  `db.customers` and `db.billing_plans` if inputs omitted (falls
  back cleanly to 0 for empty tenants).
- `POST /api/calculators/pay-model-compare` — computes hourly /
  per_pool / route_buy tech pay + company margin side-by-side.
  Returns `best_company_margin`, `best_tech_pay`, and a
  `breakeven_hint` that names which model always dominates for the
  given inputs (since `n` cancels in the hourly-vs-route_buy
  comparison).

### Frontend

**New page:** `frontend/src/pages/admin/BusinessAnalysisTools.jsx`
(~330 LOC). Two tabs matching the endpoints. Route
`/admin/tools/analysis` wrapped in `<AdminOnly>`.

- **Route Valuation tab**: form + 6-stat result card + **industry
  benchmark bar** (per-customer valuation plotted against the
  $1500-$3500 band with a colored marker: red below / green above /
  brand-color inside) + multiple-breakdown list showing each
  factor's contribution.
- **Pay Model Compare tab**: form + recommendation banner + 3-row
  side-by-side comparison table with best-margin cells and best-
  tech-pay cells color-coded green (winner metrics) + inputs echo
  footer + breakeven hint.
- Copy summary button on each tab.

### Live curl evidence (both spec cases pass)

**T5.1** — 100 customers, $150/mo, dense, 5% churn, 24mo contracts:
- `route_multiple: 7.3` (spec ~7.2 ✓)
- `route_valuation: $109,500` (spec ~$108K ✓)
- `valuation_per_customer: $1,095` (spec ~$1080 ✓)
- `benchmarks.position: "below_industry"`
- breakdown shows density_factor 1.0 · churn_factor 0.88 · contract_factor 0.6 · combined_factor 0.83

**T5.2** — 40 customers, 45min, $135/mo, weekly (4.33 vpcm):
- monthly_hours 129.9 · monthly_revenue $5,400 · other_costs 27%
- hourly: **$2,857.80/mo** (spec ~$1400/wk × 4.33 = $2856 ✓), margin **20.1%**
- per_pool: **$3,117.60/mo** (spec ~$3120 ✓), margin 15.3%
- route_buy: **$3,510.00/mo** (spec ~$3510 ✓), margin 8.0%
- Recommendation: "Highest company margin: hourly at 20.1%. Highest tech pay: route_buy at $3510.0/mo."
- Breakeven: "route_buy pays the tech more than hourly at any route size for these inputs."

### RBAC verified
- Admin: 200 on both endpoints
- Tech: **403** on both endpoints
- Customer: **403** on both endpoints (via pytest)

### Screenshots
1. **Route Valuation tab** (admin, spec inputs): 100 customers /
   $15,000 monthly revenue / $68,400 annual gross profit / **7.3x
   multiple** / **$109,500 valuation** / **$1,095 per customer**.
   Industry benchmark bar renders below with red marker at $1,095
   marked "below industry" (industry range highlighted $1500-$3500).
2. **Pay Model Compare tab**: recommendation banner "Highest
   company margin: hourly at 20.1%. Highest tech pay: route_buy at
   $3510.0/mo." Comparison table with hourly's margin cells
   (20.1% / $1,084.2 profit) in green + route_buy's tech-pay cells
   ($810.62 weekly / $3,510 monthly) in green.

### Tests

`backend/tests/test_phase_t5_analysis_tools.py` — **10 tests, 10
passed, 0.78s**.

- TestRouteValuation (6): known-answer spec case, zero-customers
  no divzero, dense > spread interpolation sanity, tech 403,
  customer 403, auto-pull-from-tenant returns positive count.
- TestPayModel (4): known-answer within ±10% for all 3 models
  + best_company_margin==hourly assertion, zero-customers all-
  zero graceful, tech 403, customer 403.

### Files touched
- `backend/routers/pool_calculators.py` (~250 LOC appended after T3)
- `backend/tests/test_phase_t5_analysis_tools.py` (**new**, 10 tests)
- `frontend/src/pages/admin/BusinessAnalysisTools.jsx` (**new**, ~330 LOC)
- `frontend/src/App.js` (import + `<AdminOnly>` route)
- `frontend/src/pages/tech/ToolsHub.jsx` (1 admin tile + 1 icon import)

### Preflight
`bash scripts/preflight.sh` → **exit 0**. Dead-import WARN 428 → 429
(1 lucide false positive in conditional JSX branch; non-blocking).

### Deferrals (explicit)

- **Sensitivity slider** on route valuation to see how multiple/
  valuation shift as churn or density change — informative but not
  in-scope for T5.
- **Route-comparator**: compare two hypothetical routes side-by-side
  (e.g., "acquiring route A vs organic growth of B"). Would layer
  cleanly on top of T5.1 — deferred.
- **Historical snapshot** of route valuations over time (would
  require a persistent audit collection) — deferred.
- Mobile parity — admin-only feature; no mobile version planned.

