# FEATURE · Routing Traffic-Aware Optimization

**Date:** Feb-2026.
**Type:** Feature addition (Candidate A of `AUDIT_MULTI_STOP_ROUTING.md`).
**Scope:** Backend + web frontend. Mobile type-mirror only (see §7).
**Environment:** Preview only.

---

## 1 · Decisions locked in

Per user dispatch (all four confirmed):

1. **Slice: Candidate A only.** No time-window fields (B), no
   navigation-URL chained batches (C), no capacity heat-mark (F).
   Clean single-purpose slice.
2. **Billing posture: opt-in per tenant.** Default OFF for every
   tenant (existing + new). Admin must explicitly enable under
   Business Settings → Routing to pay for the higher-tier SKU.
3. **Settings surface: existing Business Settings page.** New
   "Routing" section below "Branding". No new navigation entries,
   no separate Routing settings page.
4. **Time-windows (Candidate B): not on roadmap.** No schema
   collision considerations.

---

## 2 · Field contract

| Field | Type | Default | Surface |
| ----- | ---- | ------- | ------- |
| `routing_traffic_aware` | `bool` | `false` | `db.tenants` — additive. |

**GET `/api/tenants/me/business-settings`**
- `stored.routing_traffic_aware` — the raw stored value (`None` when
  the tenant has never PATCHed the field).
- `effective.routing_traffic_aware` — coerced to explicit `false` when
  unset. Downstream consumers can rely on the value never being
  `None`.

**PATCH `/api/tenants/me/business-settings`**
- Accepts `routing_traffic_aware: Optional[bool]`. `null` / missing
  is treated as "do not touch" via the existing `exclude_unset=True`
  guard.
- Audit row `business_settings.updated` naturally captures the field
  in the `changed_fields` list. No new audit event.

**GET `/api/portal/tenant/branding`** (public magic-link)
- **Does NOT surface `routing_traffic_aware`.** Locked in
  `CUSTOMER_SAFE_KEYS`: the tuple explicitly excludes the field.
  Test case 4 hard-asserts the string is absent from any response
  body from this endpoint.

**`get_effective_business_settings(db, tenant_id)`**
- Returns `routing_traffic_aware` under the effective view alongside
  every other field. Coerced to `bool` (never `None`).

---

## 3 · Routes API integration

**File:** `backend/services/google_maps/directions.py`.

### 3.1 · Preference resolver

New helper `_resolve_routing_preference(tenant_id, db_conn)`:

```
tenant_id absent          → "TRAFFIC_UNAWARE"
lookup raises             → "TRAFFIC_UNAWARE" (with warning log)
tenant.routing_traffic_aware == True → "TRAFFIC_AWARE"
otherwise                 → "TRAFFIC_UNAWARE"
```

**Byte-for-byte back-compat:** every existing call site that omits
`tenant_id` (or where the tenant hasn't opted in) continues to hit
the `TRAFFIC_UNAWARE` SKU exactly as before.

### 3.2 · Threading through the platform HTTP call

`_platform_optimize_route_http` and
`_platform_compute_route_no_optimize_http` gained a
`routing_preference: str = "TRAFFIC_UNAWARE"` kwarg. The public
`optimize_route` and `compute_route_no_optimize` resolve the
preference once at the top of the call and pass it through.

### 3.3 · BYO Maps dispatcher

The BYO dispatcher branch (`_maybe_dispatch_route`) is
intentionally NOT touched. BYO providers (Mapbox / HERE) cannot
honour the Google-specific `routingPreference` flag, so the
preference only applies on the platform-HTTP fallback branch. This
matches the constraint noted in the audit memo §4.

---

## 4 · Log format for cost debugging

Every optimizer call now emits exactly one `INFO` line:

```
[routing] tenant=<tid> traffic_aware=<True|False> waypoint_count=<n> op=<optimize|baseline>
```

Grepping backend logs by `tenant=<tid>` and `traffic_aware=True`
gives the raw call count for the higher-tier SKU. Correlate with
the invoice line item for cost attribution.

---

## 5 · Frontend — Business Settings toggle

**File:** `frontend/src/pages/settings/BusinessSettings.jsx`.

New `<section>` with `data-testid="business-settings-routing-section"`
placed below the Branding section. Single checkbox toggle with
`data-testid="bs-routing-traffic-aware-toggle"` and helper text
`data-testid="bs-routing-traffic-aware-helper"`:

- **Label:** "Traffic-aware route optimization"
- **Helper:** "Uses Google's live traffic data to sequence stops.
  May incur additional API cost."

Save button gating identical to existing fields (dirty tracking +
validation). No live preview widget (per contract).

**Bool coercion in the PATCH builder:** the existing loop that
maps empty strings to `null` was extended with a `typeof v ===
"boolean"` guard so booleans ship through as-is. No collateral
change to string fields.

---

## 6 · Non-goals honoured

- No changes to Routes API request shape beyond `routingPreference`.
- No changes to waypoint cap (25 stops), pinned-status semantics,
  "minutes saved" telemetry, or any other routing behaviour.
- No new endpoints. OpenAPI count unchanged at **1731**.
- No `.env.production` reads/writes.
- No `/app/mobile/` UI touched — mobile has no admin edit surface
  today (see §7).
- No customer-facing routing surfaces touched.

---

## 7 · Mobile scope adjustment

The dispatch called for "Mirror the toggle in `/app/mobile/`
Business Settings screen — same field, same label, same helper
text" and a mobile test. **Finding:** no admin Business Settings
edit screen exists in `/app/mobile/` — the mobile client is
technician-facing and only ships a read-only `useBusinessSettings`
hook for branding consumption. A `BusinessSettingsScreen.tsx`
does not exist and creating one is squarely mobile-specialist
territory under the standing `/app/mobile/` guardrail.

**What was done in mobile (minimal, non-UI):**

- `mobile/src/api/businessSettings.ts` — extended the
  `BusinessSettingsStored` type to include
  `routing_traffic_aware?: boolean | null`. Documented in a
  JSDoc comment. Zero runtime impact; consumers that don't
  reference the field are unaffected.

**What was NOT done in mobile (deferred to mobile specialist):**

- No new admin edit screen.
- No new mobile test — no target UI to exercise.

When the mobile team (via `e1_expo_frontend_dev`) later builds an
admin edit surface in mobile, the type is ready and the PATCH
endpoint is shared with web, so the mirror will be a pure UI wire-up.

---

## 8 · Tests

**Backend (7 tests total across 2 files):**

- `backend/tests/test_business_settings_routing.py` — 6 cases
  (PATCH true / PATCH false / default preserves / public branding
  excludes / effective-view helper / technician 403).
- `backend/tests/test_routing_traffic_preference.py` — 3 cases
  (traffic-aware ON → outbound body contains `TRAFFIC_AWARE`;
  OFF → `TRAFFIC_UNAWARE`; no tenant → `TRAFFIC_UNAWARE`).

**Frontend (2 new cases inside existing suite):**

- `frontend/src/test/business-settings.test.jsx` — Routing section
  renders + toggle round-trips through PATCH → refetch.

**Mobile:** deferred — no target UI (see §7).

---

## 9 · Touched files

```
backend/services/tenants/business_settings.py                 |  +14 / -3
backend/routers/business_settings.py                          |  +7
backend/services/google_maps/directions.py                    |  +85 / -6
backend/tests/test_business_settings_routing.py               |  new
backend/tests/test_routing_traffic_preference.py              |  new
frontend/src/pages/settings/BusinessSettings.jsx              |  +55 / -1
frontend/src/test/business-settings.test.jsx                  |  +65 / -2
mobile/src/api/businessSettings.ts                            |  +9
memory/FEATURE_ROUTING_TRAFFIC_AWARE.md                       |  new
```

**OpenAPI count:** 1731 → **1731** (no new endpoints). Verified
post-implementation.

---

## 10 · Follow-ups (documented, not shipped)

- `TRAFFIC_AWARE_OPTIMAL` premium SKU — could be added as a
  three-state select later (Off / Live traffic / Live + historical)
  behind a per-tenant "premium routing" opt-in.
- Cost telemetry dashboard — parse the `[routing] tenant=<tid>
  traffic_aware=<bool>` log lines into a Business Metrics tile
  showing per-tenant call counts on the higher-tier SKU.
- Mobile admin edit surface — hand off to `e1_expo_frontend_dev`.
