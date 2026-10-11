# Tenant Isolation Audit · Per-Tenant Templates + Automations

Feb-2026 · Stage 1 audit (no implementation yet)

Goal of the phase: every tenant gets their OWN editable copy of every
system template and automation. Changes a tenant makes do NOT affect
other tenants. System templates/automations are read-only defaults that
tenants clone and customize. A "Restore to default" action exists. Built
BEFORE Auto-Welcome (slot 6) and Visual Email Builder (slot 15) so those
features land on tenant-scoped data from day one.

────────────────────────────────────────────────────────────────────
## 1 · Current templates architecture

Three distinct template surfaces live in parallel today. Each has its
own storage model and admin UI. Only one of them (`comms`) is in scope
for THIS phase — the other two are already tenant-scoped and documented
below for completeness so the migration doesn't blindly touch them.

### 1.1 · `comms` templates — IN SCOPE
Storage: Mongo collections.

| Collection          | tenant_id | system_key | Shape | Read path | Write path |
| ------------------- | --------- | ---------- | ----- | --------- | ---------- |
| `email_templates`   | `str? / None` | `code`     | `{code, name, subject, blocks_json, is_system, is_customer_facing, version, tenant_id, created_at, updated_at}` | `routers/comms.py::_find_email_template` | `routers/comms.py` POST/PATCH/DELETE `/api/comms/email-templates/*` |
| `sms_templates`     | `str? / None` | `code`     | `{code, name, body, tokens_referenced, mms_image_url, is_system, version, tenant_id, created_at, updated_at}` | `routers/comms.py::_find_sms_template` | `routers/comms.py` POST/PATCH/DELETE `/api/comms/sms-templates/*` |
| `automation_rules`  | `str? / None` | `code`     | `{code, name, trigger_event, trigger_conditions, channel, template_code, send_delay_minutes, active, is_system, tenant_id, fire_count, last_fired_at, created_at, updated_at}` | `routers/comms.py::_find_automation` + `services/automation_engine.py::re_index_rules` | `routers/comms.py` POST/PATCH/DELETE `/api/comms/automations/*` |

Preview DB snapshot (tenant 2191 docs, 1759 distinct tenant ids):

* `email_templates`:  34 total — **8 system** (`is_system=true, tenant_id=None`), 26 tenant rows from **1 tenant**.
* `sms_templates`:    61 total — **5 system**, 56 tenant rows from **1 tenant**.
* `automation_rules`:  5 total — **5 system**, 0 tenant rows.

System rows seeded by `comms_seed/seed_comms.py` (idempotent, called from
`server.py::_background_seed`). Data lives in `comms_seed/system_data.py`
as Python literals.

**Current read model** (routers/comms.py:172-190):

```python
# find_one by code against UNION of {tenant override} + {system row with tenant_id=None}.
return await db.email_templates.find_one({
    "code": code,
    "$or": [{"tenant_id": tenant_id}, {"tenant_id": None, "is_system": True}],
})
```

**Current write model**:

* POST `/comms/email-templates`      → inserts with `tenant_id=<caller>`, `is_system=False`.
   Code conflict check uses `{tenant_id, code}`. ``'system.'`` prefix is reserved (400).
* PATCH `/comms/email-templates/{code}` → `find_one({tenant_id, code})` — only tenant-custom rows editable; system row is NOT findable from this endpoint.
* DELETE `/comms/email-templates/{code}` → same tenant-scoped filter; system rows survive.
* POST `/comms/email-templates/{code}/duplicate` → clones to a new tenant-owned row.

The automation re-indexing cache (`_RULES_INDEX`) stores `(tenant_id, trigger_event) → [rule]` with system rules under the `(None, event)` key, so `emit()` fans out tenant rules + any system rules that happened to have `active=True`.

**Can a tenant edit a system template directly today?** No — the POST
reserves `system.` prefix, PATCH/DELETE/`find_one({tenant_id, code})`
only resolve tenant-owned rows. BUT:

* System rows are reachable via the LIST endpoint for every tenant
  (every tenant sees the 8 email / 5 sms / 5 automations as read-only
  defaults).
* **The 24-char "Restore to default" surface does NOT exist** — a
  tenant has to delete their custom row by code; there's no audit trail
  of the previous content.
* **A tenant has no "always-present" automation row.** Enabling a
  system automation requires `POST /comms/automations` with a NEW tenant
  row carrying the same `trigger_event`+`template_code` — which is
  (a) unobvious UX and (b) seeded `active=False` in the system defaults
  anyway, so the "activated system rule" code-path in
  `automation_engine.re_index_rules` has in practice never fired on
  production tenants (0 tenant-owned automation rows across 1759 tenant
  ids on preview).
* **Automation re-index of SYSTEM rules has a cross-tenant leak risk.**
  Line 73-78 of `services/automation_engine.py` rebuilds the full index
  with `{"active": True}` across every row. If a super-admin ever
  flipped a system row to `active=True` (via a direct DB edit, there is
  no public endpoint for this), `emit()` would fire it for EVERY tenant
  under the `(None, trigger)` key. That's the single bleed vector in
  the current design.

### 1.2 · `marketing_templates` collection — OUT OF SCOPE (already per-tenant)
19,128 rows across 1,992 tenant ids on preview. 7,705 rows carry `system=true`
but each one is seeded PER tenant via `routers/marketing_templates.py::
seed_marketing_templates_for_tenant(tenant_id)`. Every CRUD route scopes
by `{"tenant_id": tenant["id"]}`. Already has `factory_defaults` snapshot
on each row and a `POST /marketing/templates/{tid}/revert` endpoint that
restores from the snapshot. **This is the pattern we want for comms.** Not
in scope for the migration because isolation is already enforced.

### 1.3 · `template_definitions` collection (Templates Library)
23 system rows, 0 tenant overrides on preview. `routers/templates_library.py`
reads with the SAME union pattern as comms (`$or: [is_system, tenant_id==x]`).
Semantics match comms. Not in scope for THIS phase but will inherit
the resolver pattern defined for comms once Stage 2 ships (grep hit noted).

### 1.4 · `services/notification_templates/{en,es,fr}/`
File-system canned-copy registry for i18n'd push/in-app notifications
(service `services/i18n_notifications.py`). Immutable. No tenant override
pattern exists or is wanted — i18n copy is a product decision, not a
tenant decision.

────────────────────────────────────────────────────────────────────
## 2 · Current automations architecture

### 2.1 · `automation_rules` collection — IN SCOPE
Shape and read/write surfaces covered in §1.1 above.

### 2.2 · In-process engine · `services/automation_engine.py`
* `emit(trigger_event, payload, tenant_id, …)` — synchronous fanout
  called from 11 domain-event sites: `routers/{quotes, service_reports,
  jobs, instaquote, instaschedule, customers, impexp, handbook}.py` +
  `services/notifications.py`.
* `_RULES_INDEX = { (tenant_id, trigger): [rule, …] }` — in-memory cache
  rebuilt on write via `re_index_rules(tenant_id=None|<tid>)`.
* Daily sweeps: `sweep_invoice_overdue`, `sweep_customer_birthday`,
  `sweep_customer_anniversary` — iterate ALL tenants' rows and call
  `emit(…, tenant_id=row.tenant_id, …)` per row. **Already tenant-
  scoped** — fine.
* `_fire_rule` dedups per `(tenant_id, rule.code, entity_kind,
  entity_id)` with a 24h TTL. The dedup key includes `tenant_id` → no
  cross-tenant collisions.
* `_fire_rule` dispatches via `routers.comms.deliver_one_by_ids(
  tenant_id=…, template_code=…)` which runs the SAME template-resolver
  union pattern as §1.1 — so delivery already picks the tenant override
  if one exists, else the system default.
* `_fire_rule` updates `last_fired_at` + `fire_count` on `{code,
  tenant_id: rule.tenant_id}` — if the fired rule is a system rule
  (`tenant_id=None`), **the counter bump lands on the shared system
  row**, which is counter-aggregation across every tenant that
  activated it. Cross-tenant metric leak (not data leak, but still
  wrong). Flagged for Stage-2 fix.

### 2.3 · `settings.automation_rules` on `tenants.*` document
`migrations/automation_rules_v1.py` + `routers/tenants.py` manage four
numeric thresholds (`dispatch_delay_threshold_mins`, etc.) consumed by
`services/live_dispatcher.py` and `services/maintenance_scanner.py`.
**Different namespace** — not Comms automations. Already fully per-
tenant (lives on the tenant document). Not in scope.

### 2.4 · `marketing/trigger_evaluator.py` + `routers/marketing.py`
Marketing-sequence enrolment triggers (nurture flows). Already runs on
per-tenant `marketing_sequences` + `marketing_templates`. Not in scope.

────────────────────────────────────────────────────────────────────
## 3 · Proposed design

### 3.1 · Source of truth for system defaults — `comms_seed/system_data.py` (CODE REGISTRY)
Keep the system defaults as a Python registry (status quo). Reason:

1. We already have `SYSTEM_EMAIL_TEMPLATES / SYSTEM_SMS_TEMPLATES /
   SYSTEM_AUTOMATION_RULES` in `comms_seed/system_data.py`. Promoting it
   to the canonical source of truth means system rows no longer need a
   collection — they're read directly from the registry.
2. A code registry can't be mutated by any API route by definition —
   immutability is a code-review guarantee, not a per-row check.
3. The 8+5+5 system rows change ~0 times a quarter. Mongo churn for a
   static set is unnecessary.
4. Mobile/web + any future ReadReplica/BI copy of Mongo doesn't ship a
   stale `is_system=True` row.

Trade-off: a `system_key` resolver needs code-level `IMMUTABLE_SYSTEM_
TEMPLATES` tables. Done — they already exist.

**Keyed by `system_key` — the existing `code` field.** No column rename.

### 3.2 · Per-tenant override collections — new concept
Introduce 2 new collections that live BESIDE the existing comms
collections. Status-quo tenant rows in `email_templates / sms_templates
/ automation_rules` KEEP their shape; the two new collections capture
the override vs seeded distinction cleanly:

| Collection | Row shape | Purpose |
| --- | --- | --- |
| `email_templates` (unchanged) | existing | Still stores tenant-owned EMAIL templates. All rows now have `tenant_id != None`. System rows become code-registry-only. |
| `sms_templates`   (unchanged) | existing | Same. All rows have `tenant_id != None`. |
| `automation_rules` (unchanged) | existing | Still stores PER-TENANT automation rows (both override-of-system and tenant-custom). Every row has `tenant_id != None`. |
| **`template_history`** (new) | `{id, tenant_id, system_key, kind: "email" \| "sms", snapshot: {subject, blocks_json | body, …}, action: "restore_default" \| "customize_edit" \| …, by_user_id, created_at}` | 90-day retention of prior override content when a tenant reverts to default. Enables audit log recovery per the acceptance criteria. |
| **`automation_history`** (new) | same shape as `template_history` with `kind: "automation"` and the full prior `{active, trigger_event, trigger_conditions, channel, template_code, send_delay_minutes}` snapshot | Same semantics for automations. |

**Why re-use the existing collections instead of creating `tenant_*` siblings?**

* 26 tenant-custom email rows + 56 sms rows on preview already live in
  the current collections. A migration that lifts them wholesale into
  a new collection + strips the system rows is 10x the risk of a
  migration that just DELETES the `is_system=True, tenant_id=None` rows
  (there are 18 of them — 8+5+5 — all code-registry duplicates).
* Every `emit()` + `deliver_one_by_ids()` + `re_index_rules()` consumer
  already filters by `tenant_id`. The only thing that changes is: the
  rows with `tenant_id=None` go away, and the resolver falls back to
  the code registry when no tenant override exists.

### 3.3 · Resolver pattern (new module: `services/tenant_templates.py`)
```python
async def get_email_template(tenant_id: str, system_key: str) -> dict:
    """Resolve a tenant's email template. Order:
       1. tenant override in db.email_templates ({tenant_id, code})
       2. system default from comms_seed.system_data.SYSTEM_EMAIL_TEMPLATES
       3. None (unknown system_key)
    MUST include tenant_id — raises TenantIdMissingError if blank."""
    _assert_tenant_id(tenant_id)
    row = await db.email_templates.find_one(
        {"tenant_id": tenant_id, "code": system_key}, {"_id": 0})
    if row:
        return _mark_customized(row)
    sys = _system_email_defaults().get(system_key)
    return _mark_default(sys) if sys else None

async def get_sms_template(tenant_id: str, system_key: str) -> dict: ...
async def get_tenant_automation(tenant_id: str, system_key: str) -> dict:
    """Automations differ: EVERY tenant has an own row after seeding, so
    the lookup is just:
       1. tenant row in db.automation_rules ({tenant_id, code})
       2. seed from code registry on first access (lazy heal — same as
          seed_demo_primary_customer).
    """
```

Response shape — add two normalized flags:
`{..., "mode": "default" | "customized" | "custom", "system_key": "<code>" | null, "is_system_default": bool}`.

### 3.4 · Automation row contract after migration
EVERY tenant has one row per `SYSTEM_AUTOMATION_RULES` entry (currently
5). Fields:
```
{
  id: new_id(),
  tenant_id: <tid>,                 # NEVER None
  code: "welcome_new_customer_email",
  system_key: "welcome_new_customer_email",  # new — links to registry
  name, description,                # defaulted from registry on seed
  trigger_event, trigger_conditions,
  channel, template_code,
  send_delay_minutes,
  active: false,                     # seeded off (same as today)
  is_custom: false,                  # true for tenant-created without system_key
  overridden_fields: [],             # tracks which fields differ from registry
  fire_count, last_fired_at,
  created_at, updated_at, updated_by
}
```
A tenant-authored custom automation sets `system_key=null, is_custom=true`
and has no "Restore to default" UI affordance.

### 3.5 · Templates row contract after migration
Email/SMS rows gain:
```
{
  ...existing...,
  system_key: "system.welcome_new_customer" | null,  # points to the registry key
  is_custom: bool,                                    # true when user clicked New Template
  overridden_fields: ["subject", "blocks_json", …],   # which registry fields diverge
}
```
Row ABSENCE from `email_templates`/`sms_templates` means "using system
default". Row PRESENCE with `system_key` set means "customized override
of system default". Row PRESENCE with `system_key=null, is_custom=true`
means "tenant-custom template, no system fallback".

### 3.6 · Repository-layer guard
New helper `_assert_tenant_id(tid: str)` raises `TenantIdMissingError`
on empty/None. Every helper in `services/tenant_templates.py` + the
`services/automation_engine.py::re_index_rules` + `emit()` call site
MUST invoke it. Pytest covers the invariant.

────────────────────────────────────────────────────────────────────
## 4 · Migration plan — `migrations/tenant_isolation_seed_v1.py`

Flags: `--dry-run` (default), `--execute`, `--force` (bypass sentinel).

Steps (idempotent):

1. **Pre-flight.** Load `SYSTEM_EMAIL_TEMPLATES`, `SYSTEM_SMS_TEMPLATES`,
   `SYSTEM_AUTOMATION_RULES` from `comms_seed.system_data`. Enumerate
   distinct `tenants.id` rows (preview: 1759).
2. **Backfill `system_key` on existing tenant-custom rows.** For every
   row where `is_system=False` and `code` matches a system_key, set
   `system_key = code` and compute `overridden_fields` by diffing against
   the registry. For rows with `code` that does NOT match (custom
   templates), set `system_key = null, is_custom = true`.
3. **Seed `automation_rules` per-tenant.** For every `(tenant_id,
   system_key)` pair in `tenants.id × SYSTEM_AUTOMATION_RULES.code`
   where no row exists, insert a new row carrying the registry defaults
   (`active=False`, `is_custom=False`, counters zeroed). Use `upsert`
   on `(tenant_id, system_key)` so a second run is a no-op.
4. **Retire shared system rows.** Delete the 8+5+5 `{is_system=True,
   tenant_id=None}` rows from `email_templates`, `sms_templates`,
   `automation_rules`. Only runs after Steps 2 + 3 succeed. (Behind an
   additional `--retire-shared-system-rows` flag so Stage-2 implementers
   can land the resolver first, let it bake for one deploy, then flip
   the retire step on.)
5. **Compound indexes.** Create unique `(tenant_id, system_key)` and
   `(tenant_id, code)` indexes on all three collections. Existing
   `(tenant_id, code)` unique indexes already exist (see
   `comms_seed/seed_comms.py::_ensure_indexes`) — adding `system_key`
   needs a sparse variant.
6. **Marker.** Stamp `migration_status[key="tenant_isolation_seed_v1"]`
   on success.

**Reports from dry-run:**
```
tenants_scanned
tenant_automations_to_seed  (expected: 1759 × 5 = 8,795 new rows)
tenant_automations_already_seeded
email_system_keys_to_backfill
sms_system_keys_to_backfill
automation_system_keys_to_backfill
shared_system_rows_to_retire   (expected: 18 → 0 if --retire-shared-system-rows)
new_indexes_to_create
```

**Idempotence proof plan:** pytest seeds a dry-run against a seeded
fake Mongo, then re-runs — second run must report zeros for every
`*_to_*` counter.

**Admin trigger endpoint** (super-admin only, per guardrails):
`POST /api/admin/migrations/tenant-isolation-seed?dry_run=true|false&retire=true|false` → returns the dry-run/execute report. Lives alongside the other
`admin/migrations/*` routes.

────────────────────────────────────────────────────────────────────
## 5 · Breaking changes · consumer-code sweep

### 5.1 · Direct queries that need resolver conversion
Everywhere today reads via the `$or` union pattern. After migration, the
system half of the `$or` is gone (no system rows live in Mongo). Every
site must switch to the resolver OR drop the `$or` clause and accept
"not found" for callers that didn't yet seed a tenant row.

| Site | Current query | Fix |
| --- | --- | --- |
| `routers/comms.py::_find_email_template` | `$or: [{tenant_id}, {tenant_id=None, is_system=True}]` | Call `services.tenant_templates.get_email_template(tenant_id, code)`. Returns a resolved doc with `mode` + `system_key`. |
| `routers/comms.py::_find_sms_template` | same | Call `get_sms_template(tenant_id, code)`. |
| `routers/comms.py::_find_automation` | same | Call `get_tenant_automation(tenant_id, code)` (automations are tenant-owned post-migration — the function is a thin wrapper over `db.automation_rules.find_one({tenant_id, code})`). |
| `routers/comms.py::list_email_templates` | `find({$or: …}).to_list(500)` | `find({"tenant_id": tenant_id})` + merge-in registry defaults for missing system_keys — resolver returns `{overrides: […tenant rows…], defaults: […registry rows no override exists for…]}`. Preserves wire shape (same JSON list, each row now carries `mode`). |
| `routers/comms.py::list_sms_templates` | same | same |
| `routers/comms.py::list_automations` | same | same |
| `services/automation_engine.py::re_index_rules` | `find({"active": True})` (lines 73-78) full-rebuild — walks ALL rows regardless of `tenant_id` | After migration there are no `tenant_id=None` rows left, so this becomes safe — but the guard `_assert_tenant_id(row.get('tenant_id'))` MUST raise on any accidentally-shared row. |
| `services/automation_engine.py::_fire_rule` | `update_one({"code": rule.code, "tenant_id": rule.tenant_id})` | After migration `rule.tenant_id` is NEVER None, so the counter lands on the correct tenant row. Fix the metric-leak issue flagged in §2.2. |
| `routers/comms.py::patch_email_template` | `find_one({tenant_id, code})` — 404 if no row | New semantics: PATCH performs copy-on-write — if no override row exists, insert one from the registry + apply the patch. Returns the new row. |
| `routers/comms.py::delete_email_template` | `delete_one({tenant_id, code})` | Repurpose as "Restore to default" — `delete_one({tenant_id, system_key})` + append a `template_history` snapshot. Returns 204 and a `{restored: true, system_key, archived_as}` body. |
| `routers/comms.py::create_email_template` | insert with `is_system=False`, reject `system.` prefix | Keep for tenant-CUSTOM templates (no `system_key`); explicit `system_key: null` path. |

### 5.2 · Grep targets for Stage 2 code review (`tenant_id` missing)
Must-fix:
* `services/automation_engine.py` lines 65, 73-78 — `find({"active": True})`
  with no `tenant_id` filter. Already crosses tenants by design (full
  index rebuild on startup) → acceptable after migration purges the
  shared `tenant_id=None` rows. Add the guard assertion anyway so a
  regression that reintroduces a shared row throws instead of leaking.
* `routers/comms.py` lines 203, 347, 473 — `find({"$or": …})` LIST paths.
  Convert to resolver-list helper that is tenant-scoped by construction.

Nice-to-have / defensive:
* Repository guard `_assert_tenant_id` in `services/tenant_templates.py`
  — raises if `tenant_id` is empty, `None`, or missing. Pytest proves
  the raise.
* `routers/comms.py::deliver_one_by_ids` already carries `tenant_id` as
  a required kwarg — fine; just assert.

### 5.3 · Public API surface changes

| Route | Before | After |
| --- | --- | --- |
| `GET  /api/comms/email-templates` | returns union (tenant + system) | returns union (tenant override OR registry default — same wire shape); each row carries `mode: "default" \| "customized" \| "custom"` |
| `GET  /api/comms/email-templates/{code}` | 404 if neither tenant nor system has it | 404 only if `system_key` unknown AND no tenant row with `code` |
| `PATCH /api/comms/email-templates/{code}` | 404 if no tenant row | copy-on-write — on first PATCH, creates override from registry |
| `DELETE /api/comms/email-templates/{code}` | 204 on tenant row | 204 + archive to `template_history` → **"Restore to default"** |
| **NEW** `POST /api/comms/email-templates/{code}/restore-default` | — | explicit alias for the "Restore" button — same semantics as DELETE but returns the restored (registry) doc |
| Same for `sms-templates` and `automations` |

### 5.4 · Frontend
`frontend/src/pages/comms/CommsPages.jsx` — the Templates library +
Automations tables need:
* "Default / Customized / Custom" badge column (reads `mode` on each row).
* "Restore to default" row action (hidden for `mode=custom` or
  `system_key=null`).
* On first EDIT of a `mode=default` row: an inline banner reading
  "Starting from system default — your changes will be saved as a tenant
  override."
* Confirm dialog: "Revert to system default? Your current customization
  will be archived and can be recovered from the audit log within 90
  days."

`frontend/src/api/comms.js` — thin wrappers for the new POST
`/restore-default` routes.

────────────────────────────────────────────────────────────────────
## 6 · Test plan

### 6.1 · Backend (pytest)
1. `test_tenant_templates_cross_tenant_isolation.py`:
   - Seed tenants A + B. Tenant A customizes `system.welcome_new_customer`
     via PATCH. B's GET returns the registry default. A's GET returns
     the customization.
   - Tenant A deletes (= restore). B unaffected; A's next GET returns
     registry; `template_history` has an archived row for A.
2. `test_tenant_automations_cross_tenant_isolation.py`:
   - Seed tenants A + B via migration. Tenant A disables
     `welcome_new_customer_email` (active=false). `emit("customer.created",
     …, tenant_id=A)` fires 0 rules. Same emit with `tenant_id=B` fires 1.
3. `test_tenant_automations_restore_default.py`:
   - Tenant A edits `send_delay_minutes` on its welcome automation.
     Clicks Restore. Row fields reset to registry defaults, `overridden_
     fields=[]`, `automation_history` has an archived snapshot. Row is
     NOT deleted (per the brief — automations always keep a row).
4. `test_tenant_templates_repo_guard.py`:
   - `get_email_template(tenant_id="", "x")` raises `TenantIdMissingError`.
   - `get_tenant_automation(tenant_id=None, "x")` raises.
5. `test_tenant_isolation_migration.py`:
   - Dry-run against fake-Mongo seeded with the current preview-shape
     snapshot → counts match expected (8,795 automations to seed, 18
     shared system rows to retire, etc.).
   - Execute → re-run returns zeros for all `*_to_*` counters.
   - Sentinel is stamped exactly once.
6. `test_tenant_automation_custom.py`:
   - Tenant creates an automation without a `system_key`. `mode=custom`.
     `/restore-default` returns 400 ("no system default for custom
     automation").

### 6.2 · Frontend (vitest)
1. `tenant-templates-badges.test.jsx`:
   - List renders three rows: one `mode=default`, one `mode=customized`,
     one `mode=custom`. Each ships the right badge class.
2. `tenant-templates-edit-first-time.test.jsx`:
   - Edit form on a `mode=default` row shows the "Starting from default"
     banner on open. After save, banner disappears and badge flips to
     Customized.
3. `tenant-templates-restore-confirm.test.jsx`:
   - Click Restore → confirm dialog opens with the 90-day message.
     Confirm → row's badge flips back to Default; previous content lands
     in audit log.
4. `tenant-automations-list.test.jsx`:
   - Status toggle flips `active`; Mode column shows Default/Customized/
     Custom; Restore button disabled for Custom.

### 6.3 · Known-pre-existing suites to re-run (no regressions)
`tests/test_comms_backend.py`, `tests/test_automation_engine.py`,
`tests/test_automation_rules.py`, every pytest under `tests/test_batch12*`
that touches comms templates, `src/test/comms-*`.

────────────────────────────────────────────────────────────────────
## 7 · Rollout order (for Stage 2)

1. Land resolver + guard (`services/tenant_templates.py`) + unit tests —
   no behaviour change yet, both the old `$or` paths and the new
   resolver work.
2. Flip `routers/comms.py` + `services/automation_engine.py` consumers
   to the resolver (step 1 of §5.1).
3. Add copy-on-write to PATCH + Restore-to-default endpoints.
4. Ship migration script + admin endpoint (dry-run first).
5. Frontend badges + Restore UI + edit-form banner.
6. Run migration `--execute` on preview; verify no regressions via the
   isolation pytests + a 24-hour `emit()` dedup window check.
7. Run migration `--execute --retire-shared-system-rows` on preview;
   verify delete count matches dry-run (18 rows).
8. Repeat 6-7 on production once preview soak completes.

────────────────────────────────────────────────────────────────────
## 8 · Open questions for user approval

Nothing blocking — defaults picked below. Call out any you want flipped:

* **Q1.** System-defaults source of truth: **code registry
  (`comms_seed/system_data.py`)**, not a `system_templates` collection.
  Reason: §3.1. Flip to Mongo-collection if a future Visual Builder
  needs to WRITE new system templates from the UI — unlikely.
* **Q2.** Shared `tenant_id=None` system rows: **retire via a flagged
  migration step** so we can land the resolver first, soak, then flip
  the retire step on without downtime. (Alternative: retire in the same
  migration run — faster but requires the resolver to ship atomically.)
* **Q3.** Automation "custom" automations (`system_key=null`): **DELETE
  endpoint stays available** on these (full tenant ownership), unlike
  system-backed rows where DELETE becomes Restore. Confirm this split is
  the desired UX.
* **Q4.** Template-history retention: **90 days** per the brief.
  Implemented via a TTL index on `created_at`. Confirm 90d is correct
  (brief says 90 days — locked).
* **Q5.** `template_definitions` collection (§1.3) — same resolver
  pattern + same migration? **Yes, in a follow-up phase** — kept out of
  this scope so the Comms + Automations change lands cleanly first.

Reply APPROVE (with any Q1-Q5 flips) and Stage 2 begins.
