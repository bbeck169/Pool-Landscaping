# Phase T1 — Tenant Split (Non-Destructive) + Multi-Tenant Users + Top-Nav Switcher

Status: **SHIPPED (Feb 2026)**

## Scope
- Add two pilot tenants alongside the live data-owning tenants — completely non-destructive. Aquaterra and every other production tenant is untouched.
- Support multi-tenant users via a `users.tenant_memberships` list. Every legacy single-tenant user is backfilled with a 1-item membership from their existing `tenant_id`/`role`.
- Add an `active_tenant_id` JWT claim so a user can hold membership in N tenants and switch between them without re-login.
- Ship the top-nav `<TenantSwitcher />` control — auto-hidden for single-tenant users, so nothing changes for the 99% path.
- Super_admin-only admin surface to manage memberships, gated behind `insufficient_role_for_membership_mgmt`.

## Pilot tenants (both start EMPTY save for default categories)
| id                    | slug          | name                         | settings.default_industry |
| --------------------- | ------------- | ---------------------------- | ------------------------- |
| `pool.tenant`         | `pool`        | Pool Services Pilot          | `pool`                    |
| `landscaping.tenant`  | `landscaping` | Landscaping Services Pilot   | `landscape`               |

No auto-migration of records. Explicit onboarding is required to move data into either pilot.

## Files touched
### Backend — new (5)
- `backend/scripts/create_pilot_tenants.py` — idempotent creator + explicit `service_categories` + `income_categories` seeding.
- `backend/scripts/backfill_user_memberships.py` — one-time legacy backfill (`seeded=126` on first pass, `already_multi=126` on re-run → idempotent).
- `backend/services/user_tenants.py` — `_memberships_for`, `user_has_membership`, `token_active_tenant_id`, `get_user_tenants` helpers.
- `backend/routers/tenant_memberships.py` — `POST /admin/users/{uid}/memberships` + `DELETE /admin/users/{uid}/memberships/{tid}`.
- `backend/tests/test_tenant_split_t1.py` — **10 tests / 10 passing.**

### Backend — modified (4)
- `backend/routers/auth.py`:
  - `create_token(...)` now accepts `active_tenant_id` and encodes the claim.
  - `GET /auth/me` returns `available_tenants`, `active_tenant_id`, `tenant_memberships`.
  - New `POST /auth/switch-tenant` — validates membership, persists `users.active_tenant_id`, mints new JWT.
- `backend/utils.py` (`get_current_tenant`) — claim wins over user default; unknown/stale claim → 403 `stale_tenant_membership`.
- `backend/server.py` — mounts `tenant_memberships` router.
- `backend/tests/_f7_loop_fixture.py` — rebinds new routers/services.

### Frontend — new (2)
- `frontend/src/components/topbar/TenantSwitcher.jsx` — trigger + portal-rendered dropdown, hidden when `<2` memberships. Portal fixes the overflow-x-auto clipping in the wide topbar wrap.
- `frontend/src/components/topbar/__tests__/TenantSwitcher.test.jsx` — **6 tests / 6 passing** (visibility, dropdown listing, switch flow, active-tenant no-op).

### Frontend — modified (2)
- `frontend/src/auth.jsx` — exposes `setUser` on context; consumer of `available_tenants`, `active_tenant_id` on the `me` payload.
- `frontend/src/layouts/AdminTopBar.jsx` — mounts `<TenantSwitcher />` in the wide topbar right cluster (Phase T1.5 marker).

## New endpoints
- `POST /api/auth/switch-tenant` — `{tenant_id}` body. 403 `tenant_not_in_memberships` on stranger tenant. On success returns new JWT + `active_tenant` metadata.
- `POST /api/admin/users/{user_id}/memberships` — super_admin only. Idempotent — re-add is a no-op with `created=false`.
- `DELETE /api/admin/users/{user_id}/memberships/{tenant_id}` — super_admin only. Refuses default-tenant removal (400 `cannot_remove_default_tenant_membership`). Removal of default is deferred to a future PATCH transfer route.

## JWT contract
- New optional claim: `active_tenant_id`. Legacy JWTs (no claim) still work — `get_current_tenant` falls back to `user.tenant_id`.
- Stale claim (user removed from the referenced tenant while their old JWT is still in flight) → 403 `stale_tenant_membership` on any authed read.

## `GET /auth/me` new fields
```json
{
  "tenant_id":         "affdfbfa-88b9-4baa-ae45-2ef78531b6e4",
  "active_tenant_id":  "pool.tenant",
  "tenant_memberships": [
    {"tenant_id": "affdfbfa-88b9-...", "role": "admin",  "joined_at": "..."},
    {"tenant_id": "pool.tenant",       "role": "admin",  "joined_at": "..."}
  ],
  "available_tenants": [
    {"id": "affdfbfa-88b9-...", "name": "Pool & Landscaping of Vistancia",
     "slug": "aquaterra", "role": "admin", "is_active_now": false},
    {"id": "pool.tenant",        "name": "Pool Services Pilot",
     "slug": "pool",       "role": "admin", "is_active_now": true}
  ]
}
```

## Test counts
- Backend pytest: **10 passed / 10** (`test_tenant_split_t1.py`) — pilot idempotency, backfill idempotency, switch-tenant happy + stranger 403, tenant-B-scoped reads post-switch, legacy-JWT fallback, role gating matrix (super/admin/tech), idempotent membership add, DELETE default-refusal, stale-membership 403.
- Frontend vitest: **6 passed / 6** (`TenantSwitcher.test.jsx`) — visibility (0/1/2+), dropdown lists tenants, switch POSTs correct id + swaps token + reloads, active-tenant no-op.
- Full backend + frontend suites: **all pre-existing tests still green (0 regressions).**

## E2E curl verification (live preview, `admin@aquaterra.com`)
```
1. `python -m scripts.create_pilot_tenants`
   → pool.tenant status=created, landscaping.tenant status=created (2nd run: already_exists)
2. `python -m scripts.backfill_user_memberships`
   → seeded=126, already_multi=126 (2nd run: seeded=0)
3. POST /api/admin/users/{admin_uid}/memberships {tenant_id: pool.tenant, role: admin}
   → 200 created=true, memberships=[aquaterra, pool.tenant]
4. GET /api/auth/me (aquaterra JWT)
   → available_tenants=[{aquaterra, active_now=true}, {pool.tenant, active_now=false}]
5. POST /api/auth/switch-tenant {tenant_id: pool.tenant}
   → 200, new JWT decoded → active_tenant_id="pool.tenant"
6. GET /api/customers?limit=5 (post-switch)
   → count=0, tenant_ids_seen=[]  ← proves pool.tenant is empty AND scope flows through
7. POST /api/auth/switch-tenant {tenant_id: affdfbfa-…} (switch back)
   → 200, active_tenant={id: affdfbfa-…, name: "Pool & Landscaping of Vistancia"}
8. GET /api/customers?limit=1 (post-switch-back)
   → count=28, sample tenant_id=affdfbfa-…, name="Drift Datetime"
```

## Frontend UX
- Wide topbar (`>=md`) shows `<TenantSwitcher />` between `<QuickAddButton />` and `<CreditsBudgetChip />`.
- Rendered as a compact pill with the `Building2` icon + current tenant name + `ChevronsUpDown` chevron.
- Click → dropdown listing every membership; active tenant carries a `Check` glyph.
- On pick: `POST /api/auth/switch-tenant` → `localStorage.setItem(TOKEN_KEY, new_token)` → `window.location.reload()` (per user brief — cleanest way to reset every mounted context, react-query caches, etc.).
- Because the wide topbar wrap uses `overflow-x-auto`, the menu is portaled via `createPortal(document.body)` and self-positioned from the trigger rect so it renders unclipped over content.
- Screenshot: `/app/memory/screenshots/t1_tenant_switcher_open.jpg` — trigger reads `Pool & Landscaping of Vist…`, dropdown shows `SWITCH TENANT | Pool & Landscaping of Vist… ✓ | Pool Services Pilot`.

## Guardrails
- Single-tenant users see nothing new — trigger auto-hides when `memberships.length < 2`. Backwards-compatible with pre-T1 UX.
- Pilot tenants MUST start empty. Do not auto-migrate any records. Onboarding is explicit.
- Removing a user's default tenant membership is refused with `cannot_remove_default_tenant_membership` — the safety net until a `PATCH default-tenant transfer` route ships.
- Every stale-JWT scenario (user removed from tenant with an old JWT in flight) fails closed with `stale_tenant_membership` — no cross-tenant reads leak.
- Mobile switcher parity is delegated to `e1_expo_frontend_dev` — nothing under `/app/mobile/` was touched.

## Deferred / follow-ups
- `PATCH /admin/users/{uid}/default-tenant` — transfer default before allowing the last-membership removal.
- Toast primitive on switch failure (currently console.error only).
- Mobile parity for `<TenantSwitcher />` (owner: `e1_expo_frontend_dev`).
