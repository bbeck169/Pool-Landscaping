# Feature — Multi-industry · Phase A (backend enum + tenant.industries[] + `useIndustries()`)

**Phase**: Feb-2026 · Phase A of D  
**Scope**: Backend (enum, tenant field, migration, validation) +
frontend (config module + `useIndustries()` hook).  
**Explicitly deferred**: settings UI (Phase B), re-gating existing
pool/landscape branches (Phase C), mobile parity (Phase D).

## Enum + labels (25 slugs)

| slug | label |
|------|-------|
| `pools` | Pools |
| `landscaping` | Landscaping |
| `hvac` | HVAC |
| `plumbing` | Plumbing |
| `pest_control` | Pest Control |
| `notary` | Notary |
| `photography` | Photography |
| `handyman` | Handyman |
| `electrical` | Electrical |
| `pressure_washing` | Pressure Washing |
| `window_cleaning` | Window Cleaning |
| `pet_waste_removal` | Pet Waste Removal |
| `trash_can_cleaning` | Trash Can Cleaning |
| `moving` | Moving |
| `snow_removal` | Snow Removal |
| `lighting_installation` | Lighting Installation |
| `epoxy_coating` | Epoxy Coating |
| `garage_storage` | Garage Storage |
| `custom_closets` | Custom Closets |
| `pet_grooming` | Pet Grooming |
| `beauty` | Beauty |
| `garage_door` | Garage Door |
| `roofing` | Roofing |
| `flooring` | Flooring |
| `automotive` | Automotive |

Source of truth (backend): `backend/services/industries.py`.  
Source of truth (frontend): `frontend/src/config/industries.js`.  
Byte-parity is enforced by
`backend/tests/test_multi_industry_phase_a.py::TestEnumContract::test_frontend_module_parity`
— if either file drifts the test fails loud with the mismatch.

`DEFAULT_INDUSTRY = "pools"` (matches the codebase's historical
single-industry default).

## Migration semantics

**File**: `backend/services/migrations/tenant_industries_backfill.py`.  
**Wired**: `server.py` startup pipeline right after
`recurring_is_active_backfill`.

Idempotent — safe to re-run on every pod boot.

Per tenant row **without** an `industries` field:

1. Best-effort read a legacy single-industry hint from
   `industry` / `industry_type` / `primary_service` (first hit
   wins). If the value maps to a canonical enum slug, use it.
2. Otherwise seed `["pools"]`.
3. Stamp via `update_one({..., "industries": {"$exists": False}}, {"$set": {...}})`
   so concurrent boots don't double-write.

**First boot on preview**: `scanned=114 backfilled=114
inferred_from_legacy=0`.  
**Second boot** (idempotency check): `scanned=0 backfilled=0`.

Tenants whose admins later save `industries: []` explicitly are
preserved as an empty array — the boot pass only touches rows
where the field does not exist yet.

## Endpoint contract additions

**No new routes** — this is an in-place enhancement. OpenAPI paths
remain **1747**.

- `GET /api/tenants/current` → response now includes
  `industries: string[]`.
- `GET /api/tenants/mine/settings` → response now includes
  `industries: string[]`.
- `PATCH /api/tenants/mine/settings` → accepts optional
  `industries: string[]`.
  - Each entry must appear in the canonical enum.
  - Invalid slug → **422** with `detail.code = "invalid_industry: <slug>"`
    and `detail.invalid = [...]`.
  - Non-list shape → **422**
    `detail.code = "invalid_industries_shape"`.
  - Duplicates are dropped silently (kept in input order).
- Auth: admin / super_admin only (existing gate).

Spec mentioned `GET /api/tenants/me` and `PATCH /api/tenants/me` —
this codebase's canonical equivalents are `/api/tenants/current`
(GET) and `/api/tenants/mine/settings` (PATCH). Documented in this
memo so future phases don't create alias routes by mistake.

## Frontend hook API

```js
import { useIndustries } from "@/hooks/useIndustries";

const { industries, hasIndustry, labels, loaded } = useIndustries();
```

- `industries: string[]` — the tenant's active slugs. Empty on cold
  mount before the tenant fetch resolves, and empty when
  `industries` is missing / malformed on the server.
- `hasIndustry(slug: string) => boolean` — safe on cold mount (returns
  `false` before the fetch settles, which matches the
  "hide feature until confirmed on" default).
- `labels: {[slug]: string}` — the canonical label map.
- `loaded: boolean` — `true` once the tenant fetch has settled
  (success **or** error). Callers can render placeholders while
  `loaded === false`.

Module-scope cache mirrors `useTenantBrand`: the tenant document is
fetched exactly once per session across every consumer.
`invalidateIndustries()` is exported for tests + future settings
save flows.

## Server-side helper

```python
from services.industries import tenant_has_industry

if tenant_has_industry(tenant, "hvac"):
    ...
```

Safe on missing / malformed tenant docs — returns `False`. Callable
from any router / service without importing the tenant router.

## Phase B / C / D roadmap notes

- **Phase B — Settings multi-select UI**: adds a checkbox grid on
  the tenant settings page keyed off `INDUSTRIES` +
  `INDUSTRY_LABELS`. Uses the existing PATCH endpoint. Do **not**
  create a new endpoint — settings PATCH already validates.
- **Phase C — Re-gate existing pool/landscape branches**: replaces
  hard-coded `if job_type == "pool"` / `landscape` branches with
  `hasIndustry("pools")` / `hasIndustry("landscaping")` gates on
  the frontend and `tenant_has_industry(...)` gates on the
  backend. Migration: any tenant with the old `job_type == "pool"`
  keeps working because Phase A already seeded them into
  `industries=["pools"]`.
- **Phase D — Mobile parity**: `/app/mobile/` reads
  `/tenants/current` too, so the mobile Redux store gains an
  `industries` slice + a mirror hook. Delegate to
  `e1_expo_frontend_dev`.

## Test coverage

Backend (`backend/tests/test_multi_industry_phase_a.py`) —
**16 tests passing**:

- Enum contract × 6 (size, first entry, label parity, slug shape,
  no dupes, JS parity).
- Helpers × 3 (`is_valid_industry`, `normalize_industries`,
  `tenant_has_industry`).
- Migration × 1 (seeds missing, honours legacy hint, idempotent).
- Endpoint contract × 6 (current returns industries, settings read
  returns industries, PATCH persists, PATCH 422 on invalid slug,
  PATCH 422 on non-list, customer 403).

Frontend (`frontend/src/test/multi-industry-phase-a.test.jsx`) —
**10 tests passing**:

- Enum config × 5 (size, default, label parity, slug shape,
  `isValidIndustry`).
- Hook × 5 (cold-mount safe defaults, fetched-state values,
  cache reuse across mounts, error fallback, malformed field
  fallback).

Legacy suites — no regression.

## Out of scope (unchanged)

- Any A–F backlog items.
- Settings multi-select UI (Phase B, next dispatch).
- Re-gating existing pool/landscape branches (Phase C).
- Mobile parity (Phase D).
- Per-industry checklist / preset mappings.
