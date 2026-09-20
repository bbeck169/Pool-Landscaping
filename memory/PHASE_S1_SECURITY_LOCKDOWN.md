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
