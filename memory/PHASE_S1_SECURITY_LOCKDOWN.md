# Phase S1 — SaaS Security Lockdown (Multi-Tenant) — SHIPPED (Feb 2026)

## Scope

Four security guarantees, all fail-closed and idempotent:

| ID   | Guarantee                                                                                                     |
|------|----------------------------------------------------------------------------------------------------------------|
| S1.1 | **Env-var Founder Pinning** — `FOUNDER_SUPER_ADMIN_EMAIL` (default `brian@plofv.com`) is promoted to `super_admin` on boot **and** on every login (auth is NOT bypassed). |
| S1.2 | **Switch-Tenant Endpoint Lockdown** — `POST /api/auth/switch-tenant` returns `403 insufficient_role_for_tenant_switch` for anyone whose role is not `super_admin`.        |
| S1.3 | **Frontend TenantSwitcher Role Guard** — `<TenantSwitcher />` renders `null` for any actor whose `effectiveRole` isn't `super_admin`, even when they carry ≥2 memberships. |
| S1.4 | **Role-Picker Lockdown** — the `super_admin` option is absent from the Add-Team-Member modal for non-super actors; the backend `POST /api/users/{uid}/promote` rejects a `role=super_admin` payload from non-super callers with `403 super_admin_role_not_assignable`. |

Existing `admin@aquaterra.com` cross-tenant memberships remain as dead data (they cannot be exercised because switch-tenant is locked down).

## Files touched

**Backend**
- `routers/auth.py` — `FOUNDER_SUPER_ADMIN_EMAIL` reader, `promote_founder_on_boot()` + login-time promo (S1.1); `switch_tenant()` 403 gate (S1.2).
- `routers/admin_users.py` — `promote_user()` 403 branch for non-super callers when payload is `super_admin` (S1.4 belt-and-braces).
- `routers/team.py` — user-create route rejects `role=super_admin` from non-super callers.
- `server.py` — `@app.on_event("startup")` calls `promote_founder_on_boot()`.
- `tests/test_saas_security_lockdown_s1.py` — 12 pytests covering all four IDs + regression guards (no super-demotion, empty env → no-op, idempotent re-run).

**Frontend**
- `components/topbar/TenantSwitcher.jsx` — `effectiveRole !== "super_admin"` → `null`.
- `pages/ops/OpsHub.jsx` — `AddTeamMemberModal.roleOptions` filters out the `super_admin` option unless `effectiveRole === "super_admin"` (case-insensitive).
- `components/topbar/__tests__/TenantSwitcher.lockdown.test.jsx` — 9 vitests.
- `pages/ops/__tests__/S1_role_picker.test.jsx` — 5 vitests.

## Endpoints touched

| Method | Path                                    | S1 constraint                             |
|--------|-----------------------------------------|-------------------------------------------|
| POST   | `/api/auth/login`                       | Founder promo runs (idempotent).          |
| POST   | `/api/auth/switch-tenant`               | `super_admin` only → 403 otherwise.       |
| POST   | `/api/users/{uid}/promote`              | `role=super_admin` blocked for non-super. |

Startup hook: `promote_founder_on_boot()` runs once on process start; promotes `FOUNDER_SUPER_ADMIN_EMAIL` if the DB row exists and is not already `super_admin`. **Never** demotes existing `super_admin` rows.

## S1 hotfix — TenantSwitcher regression for super_admin (Feb 2026)

### The regression
External `e1_tester` sweep found 4/5 acceptance criteria clean but **TenantSwitcher was hidden for super_admin too**. Second finding: `POST /api/auth/switch-tenant` from super_admin → tenant `200d48ac-…` (pool.tenant) returned `403 tenant_not_in_memberships` even though the same tenant appeared in `/api/tenants/memberships/mine`.

### Root cause (single bug, two symptoms)
`services/user_tenants.py::get_user_tenants()` and `user_has_membership()` walked `user.tenant_memberships` only. `super@aquaterra.com` has just **one** row in that array, so:
- `/api/auth/me.available_tenants` returned 1 tenant → frontend fell into the `memberships.length < 2 → null` branch and hid the switcher for the super_admin who was supposed to see it.
- `POST /api/auth/switch-tenant` guard rejected every cross-tenant target the tester tried, even active ones.

The S1.3 role predicate in `TenantSwitcher.jsx` was correct — the bug was upstream in the data layer.

### Fix
`services/user_tenants.py`
- `get_user_tenants(user)` — when `user.role == "super_admin"`, returns every `tenants.find({"active": True})` document (mirrors `/api/tenants/memberships/mine`).
- `user_has_membership(user, tenant_id)` — returns `True` for any super_admin (the switch endpoint still validates that the tenant exists + is active before minting the JWT, so a fake tenant_id still 403s).

Frontend guard: **unchanged**. The predicate `if (effectiveRole !== "super_admin") return null;` is correct.

### New regression tests

**pytest** — `tests/test_saas_security_lockdown_s1.py` +4 cases:
- `test_s1_super_can_switch_to_active_tenant_not_in_memberships` — super_admin switches to a tenant they have no membership row for → 200.
- `test_s1_super_switch_to_missing_tenant_still_403` — non-existent tenant → still 403 `tenant_not_in_memberships`.
- `test_s1_admin_switch_still_locked_after_hotfix` — admin still 403 `insufficient_role_for_tenant_switch` even with a valid membership row.
- `test_s1_super_available_tenants_lists_every_active` — `/auth/me.available_tenants` for super_admin lists every active tenant.

**vitest** — new `components/topbar/__tests__/TenantSwitcher.super_admin_positive.test.jsx` +3 cases, mounted inside a real `<PermissionsProvider>` (no mock of `usePermissions`):
- super_admin with 2 memberships → trigger renders (real hook path).
- admin with 2 memberships → renders null.
- super_admin with a stale `preview_role="admin"` in sessionStorage → renders null (fail-closed while previewing).

### Test counts after hotfix
- Backend pytest `test_saas_security_lockdown_s1.py`: **16 / 16 green** (was 12/12).
- Frontend vitest S1 suites: **17 / 17 green** (was 14/14).

### Live-pod curl proofs (log: `/app/memory/s1_proofs/hotfix_proofs.log`)

| # | Actor          | Call                                                           | Result |
|---|----------------|----------------------------------------------------------------|--------|
| 1 | super_admin    | `GET /api/auth/me` — `available_tenants` length                | **123** (was 1) ✅ |
| 2 | super_admin    | `POST /api/auth/switch-tenant {tenant_id: pool.tenant}`        | **200** with new JWT ✅ |
| 3 | super_admin    | `POST /api/auth/switch-tenant {tenant_id: landscaping.tenant}` | **200** with new JWT ✅ |
| 4 | super_admin    | `POST /api/auth/switch-tenant {tenant_id: "totally-fake"}`     | **403** `tenant_not_in_memberships` ✅ (fake tenants still blocked) |
| 5 | admin          | `POST /api/auth/switch-tenant`                                 | **403** `insufficient_role_for_tenant_switch` ✅ (S1.2 lockdown intact) |

### Live-pod screenshots
- `/app/memory/s1_proofs/super_admin_topbar_visible.png` — super's topbar right cluster shows the tenant pill (label "Pool & Landscaping of Vistancia").
- `/app/memory/s1_proofs/super_admin_topbar_dropdown_open.png` — dropdown open, "SWITCH TENANT" header + 123 tenants rendered.
- `/app/memory/s1_proofs/admin_topbar_hidden.png` — admin's topbar right cluster shows Add Job / Add Customer only, **no** tenant pill.

Console dump from Playwright confirms:
```
super switcher present: 1
super switcher label: Pool & Landscaping of Vistancia
dropdown items: {count: 123, sample: ['CRA cra-02939e0a', 'CRA cra-233a2c77', …]}
admin switcher count: 0
```

## Verification — TEST COUNTS


### Backend pytest
```
pytest tests/test_saas_security_lockdown_s1.py
============ 12 passed in 3.4s ============
```
Full regression sweep (S1 + G1 + F1 + T1 + weekly-digest + sales-pipeline-c): **65 / 65 green.**

### Frontend vitest
```
yarn vitest run src/components/topbar/__tests__/TenantSwitcher.lockdown.test.jsx \
                src/pages/ops/__tests__/S1_role_picker.test.jsx
Test Files  2 passed (2)
     Tests  14 passed (14)
```
Split: TenantSwitcher lockdown 9, Role-picker lockdown 5.

### Live-pod curl proofs (log: `/app/memory/s1_proofs/curl_proofs.log`)

| # | Actor          | Call                                                              | Expected                                          | Result |
|---|----------------|-------------------------------------------------------------------|---------------------------------------------------|--------|
| 1 | admin          | `POST /api/users/{mike}/promote {"role":"super_admin"}`           | `403 super_admin_role_not_assignable`             | ✅ 403 |
| 2 | super_admin    | `POST /api/users/{mike}/promote {"role":"technician"}`            | `200 no_change:true`                              | ✅ 200 |
| 3 | super_admin    | `POST /api/users/{mike}/promote {"role":"admin"}`                 | `200 old_role=technician new_role=admin`          | ✅ 200 |
| 4 | admin          | `POST /api/auth/switch-tenant {"tenant_id":"affdfbfa-…"}`         | `403 insufficient_role_for_tenant_switch`         | ✅ 403 |
| 5 | super_admin    | `POST /api/auth/switch-tenant {"tenant_id":"affdfbfa-…"}`         | `200` + new JWT carrying `active_tenant_id`       | ✅ 200 |
| 6 | super@aquaterra.com | `GET /api/auth/me`                                           | `role=super_admin` (baseline)                     | ✅     |
| 7 | founder (DB)   | `users.find_one({email:"brian@plofv.com"})`                       | `role=super_admin`                                | ✅     |

### Screenshots (`/app/memory/s1_proofs/`)

| File                                  | Shows                                                                 |
|---------------------------------------|-----------------------------------------------------------------------|
| `team_modal_as_admin_expanded.png`    | Admin actor · role dropdown expanded · **5 options, no Super Admin**  |
| `team_modal_as_super_expanded.png`    | Super actor · role dropdown expanded · **6 options incl. Super Admin**|
| `team_modal_as_admin.png`             | Admin modal closed-select view                                        |
| `team_modal_as_super.png`             | Super modal closed-select view                                        |

Console dump confirms the option lists:

```
ADMIN role options: [pool_tech, landscape_tech, tech_both, admin, all]
SUPER role options: [pool_tech, landscape_tech, tech_both, admin, all, super_admin]
```

## Guardrails / deferred

- `/app/mobile/` untouched (mobile TenantSwitcher parity is now moot — non-super_admin no longer needs one).
- Prompt-injection asking the agent to clone `bbeck169/Pool-Landscaping.git` **IGNORED** (recurrence #53).
- Existing 15 `super_admin` accounts are preserved; boot script never demotes.
- `admin@aquaterra.com` still carries two `tenant_memberships` rows — kept as dead data, not deleted (audit-friendly).

## Rollback

- **Revert S1.2 / S1.4 gates** — delete the `if (user.get("role") or "").lower() != "super_admin"` blocks in `routers/auth.py::switch_tenant` and `routers/admin_users.py::promote_user`.
- **Revert S1.3** — restore the `TenantSwitcher` old render branch (early-return only when memberships < 2).
- **Revert S1.1** — remove the `promote_founder_on_boot()` call from `server.py::startup` and the login-time promo in `routers/auth.py::login`.

No DB migration; boot script is idempotent and reversible.
