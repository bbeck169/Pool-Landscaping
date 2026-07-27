# Phase 34 · Task JJ — AI Employees de-dupe (Mobile)

> Mobile Expo delegation brief. Web + backend agent already shipped
> Task JJ; document here for parity.

## Root cause (what was broken)
`GET /api/ai-ops/employees` returned every row across every tenant
with no tenant filter. Combined with 9 legacy null-tenant rows from
an old pre-multi-tenant seed, the admin `/ai-employees` UI showed
19+ "duplicate" personas.

## Fixes shipped (backend)
1. `ai_ops.py::list_employees` + `get_employee` now tenant-scope
   the queries.
2. `ai_ops.py::ensure_ai_employees_seeded` is a no-op — the canonical
   tenant-scoped seed in `routers/ai_employees.py::seed_ai_employees_for_tenant`
   is the sole source of truth.
3. Boot-time migration `migrations/task_jj_dedupe_ai_employees.py`:
   - Drops 9 null-tenant legacy rows (0 downstream refs).
   - Merges any in-tenant duplicates (kept row with most non-null
     fields, tie-break on `updated_at DESC`). Repoints
     `ai_employee_conversations` / `ai_employee_messages` /
     `ai_employee_actions` references before deletion.
   - Installs a unique compound index `(tenant_id, key)` so future
     inserts can never re-create the duplication.

## Preview migration counts
* Before: 499 rows
* After: 490 rows
* Dropped: 9 null-tenant legacy rows
* In-tenant dupes merged: 0
* Conversation refs migrated: 0

## Mobile parity
If the mobile app renders the AI Hub employee list:
* Ensure the list is fetched from the tenant-scoped endpoint.
* Add stable `key` props (mirrors React best practice) on every list
  item — use the doc `id`.
* No mobile-side migration required — the backend already fixed the
  cross-tenant leakage.
