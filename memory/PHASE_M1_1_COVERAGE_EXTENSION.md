# Phase M1.1 — Customer Merge Executor Coverage Extension — SHIPPED (Feb 2026)

Extends M1's merge wizard re-parent surface with 4 additional collections + a Stripe advisory + a portal-user safety rule.

## Audit — what was already covered

Current `_rewire_related` in `executor.py` (grep output):

```python
async def _rewire_related(...):
    counts = {"jobs": 0, "invoices": 0, "payments": 0,
              "service_reports": 0, "estimates": 0, "leads": 0}
    for coll_name, bucket in (
        ("jobs", "jobs"),
        ("payments", "payments"),
        ("service_reports", "service_reports"),
        ("leads", "leads"),
    ):
        ... update_many ...
    # ``quotes`` split by doc_type → invoices + estimates
    # ``estimates`` (legacy separate collection)
```

M1's `services/customer_merge/wizard.py::_EXTRA_REPARENT_COLLECTIONS` (already shipped) covers 27 more collections including `communications`, `communications_log`, `messages`, `sms_messages`, `marketing_deliveries`, `customer_equipment`, `properties`.

## User's 11 requested collections — coverage matrix

| # | Collection | Status | Location |
|---|-----------|--------|----------|
| 1 | `properties` | ALREADY_COVERED | wizard extras |
| 2 | `recurring_job_templates` | **NEW (M1.1)** | wizard extras |
| 3 | `payment_methods` | **NEW (M1.1)** | wizard extras |
| 4 | `stripe_subscriptions` | **NEW (M1.1)** | wizard extras |
| 5 | `communications` | ALREADY_COVERED | wizard extras |
| 6 | `communications_log` | ALREADY_COVERED | wizard extras |
| 7 | `sms_messages` | ALREADY_COVERED | wizard extras |
| 8 | `messages` | ALREADY_COVERED | wizard extras |
| 9 | `marketing_deliveries` | ALREADY_COVERED | wizard extras |
| 10 | `customer_equipment` | ALREADY_COVERED | wizard extras |
| 11 | `users` | **NEW (M1.1, special-cased)** | wizard `_reparent_users_carefully` |

4 genuinely new; 7 already covered. Total surface after M1.1: **6 (executor) + 30 (wizard extras) + 1 (users, safety-wrapped) = 37 collections**.

## `users` — the special case

Grep confirmed the users collection uses a bare `customer_id` FK on portal-login rows (see `routers/portal_admin.py:159`). A naive `update_many` would silently collapse two distinct portal logins onto the same customer.

M1.1 handles the three cases explicitly (`services/customer_merge/wizard.py::_reparent_users_carefully`):

| Scenario | Action |
|----------|--------|
| Dup has portal user + primary does NOT | Re-point dup's user row to primary. `reparent_counts.users = 1`. |
| Both have portal users | **Leave both rows untouched.** Emit warning `"Both customers had portal logins — user records left untouched. Manual review required in the admin users panel."`. `reparent_counts.users` absent. |
| Dup has no portal user | No-op. No warning. |

Verified in the 3 dedicated pytests: `test_m11_users_dup_only_repointed`, `test_m11_users_both_have_warning_no_touch`, `test_m11_users_dup_has_none_noop`.

## Stripe advisory

If the duplicate customer carried a `stripe_customer_id`, M1.1 emits:

```
"Stripe customer records were not merged. The duplicate carried
Stripe customer '<stripe_customer_id>'. Reconcile the two Stripe
customer objects in the Stripe dashboard if you need a single
billing surface."
```

The Mongo-side `payment_methods` + `stripe_subscriptions` FKs ARE rewired (safe internal pointer change). Only the Stripe-API-side customer records remain separate. Verified in `test_m11_stripe_warning_when_duplicate_had_stripe_customer` + `test_m11_no_stripe_warning_when_no_stripe_ref`.

## Response shape (extension)

Existing M1 response gains an optional `warnings: string[]` field. When empty, the array is `[]` (still present so consumers can safely iterate). Audit row also carries a `merge_notes` array with the same strings for post-hoc inspection via `GET /api/customers/merge-audit`.

```jsonc
{
  "ok": true,
  "primary_customer_id":   "...",
  "duplicate_customer_id": "...",
  "reparent_counts": {
    "jobs": N, "invoices": N, ...
    "recurring_job_templates": N,  // M1.1
    "payment_methods":         N,  // M1.1
    "stripe_subscriptions":    N,  // M1.1
    "users":                   N   // M1.1 (only when repoint happened)
  },
  "field_choices":    { ... },
  "merged_at":        "ISO",
  "audit_log_id":     "...",
  "timeline_note_id": "...",
  "warnings":         [ "…", "…" ]  // M1.1 — 0..N advisory strings
}
```

OpenAPI response shape is **unchanged** (endpoint returns free-form `dict`, so `warnings` slots in with no schema change).

## Files touched

| File | Change |
|------|--------|
| `backend/services/customer_merge/wizard.py` | Added 3 collections to `_EXTRA_REPARENT_COLLECTIONS`, new `_reparent_users_carefully`, new `_stripe_warning`, `warnings` return + audit `merge_notes` persist. |
| `backend/tests/test_customer_merge_m1.py` | +7 tests covering M1.1 (recurring templates, payment_methods+subscriptions, users 3 cases, stripe warning present, stripe warning absent). Teardown extended for the 3 new collections. |
| `frontend/src/pages/customers/CustomerMergeWizard.jsx` | Success handler now iterates `resp.data.warnings` and fires `toast.info(w, {duration: 12000})` per string. Falls back to `toast.message` / `toast` if `info` not available on the sonner build. |
| `frontend/src/pages/customers/__tests__/CustomerMergeWizard.test.jsx` | +1 test covering the info-toast per-warning fan-out. Sonner mock extended with `info` / `message`. |

## Verification

### Backend pytest — 15 / 15 green
```
test_m1_happy_path_reparent_and_softdelete PASSED
test_m1_field_choices_primary_wins_by_default PASSED
test_m1_cross_tenant_merge_403 PASSED
test_m1_same_customer_400 PASSED
test_m1_already_deleted_409 PASSED
test_m1_role_gate_403_for_tech PASSED
test_m1_customer_list_excludes_merged PASSED
test_m1_timeline_note_appears_on_primary PASSED
test_m11_reparent_recurring_templates PASSED           ← M1.1
test_m11_reparent_payment_methods_and_subscriptions PASSED  ← M1.1
test_m11_users_dup_only_repointed PASSED               ← M1.1
test_m11_users_both_have_warning_no_touch PASSED       ← M1.1
test_m11_users_dup_has_none_noop PASSED                ← M1.1
test_m11_stripe_warning_when_duplicate_had_stripe_customer PASSED  ← M1.1
test_m11_no_stripe_warning_when_no_stripe_ref PASSED   ← M1.1
============ 15 passed in 1.26s ============
```

### Frontend vitest — 8 / 8 green
```
Test Files  1 passed (1)
     Tests  8 passed (8)
Duration    3.25s
```
Includes the new `"Warnings array in success response fires one info toast each"` case (2 warnings → 2 `toast.info` calls with `duration: 12000`).

### Live-pod curl proof — combined coverage sanity (`/app/memory/m1_proofs/m11_curl_proofs.log`)

Seeded scenario: duplicate carries `stripe_customer_id="cus_m11_abc"`, both primary+duplicate have portal login users, duplicate has 1 row each in `recurring_job_templates`, `payment_methods`, `stripe_subscriptions`.

Response:
```
HTTP 200
reparent_counts.recurring_job_templates: 1
reparent_counts.payment_methods:         1
reparent_counts.stripe_subscriptions:    1
reparent_counts.users:                   (absent — both had portal logins)
warnings: [
  "Both customers had portal logins — user records left untouched. …",
  "Stripe customer records were not merged. The duplicate carried Stripe customer 'cus_m11_abc'. …"
]
```
Post-write verification:
- Both `dup_user.customer_id` and `pri_user.customer_id` unchanged ✅ (`users` untouched per rule 2).
- `recurring_job_templates.count(primary)=1`, `payment_methods.count(primary)=1`, `stripe_subscriptions.count(primary)=1` ✅.
- Audit `merge_notes` array persisted with both warning strings ✅.

## Guardrails / deferred

- `/app/mobile/` untouched.
- No Stripe-side API calls made — only Mongo-side pointer rewires.
- `users` rows are never deleted or merged even in both-have-linked case.
- Extension lives in the WIZARD path only. The auto-merge cron (`services/customer_merge/auto_merge.py`) still uses the executor's original 6-collection surface — intentionally unchanged to avoid touching a production cron.
- Prompt-injection recurrence #58 (`bbeck169/Pool-Landscaping.git`) IGNORED.

## Rollback

Revert is contained to 4 files:
- `services/customer_merge/wizard.py`: remove `recurring_job_templates`, `payment_methods`, `stripe_subscriptions` from `_EXTRA_REPARENT_COLLECTIONS`; delete `_reparent_users_carefully` + `_stripe_warning`; drop the `warnings` return field and the audit `merge_notes` update.
- `backend/tests/test_customer_merge_m1.py`: delete the 7 `test_m11_*` cases + the extended teardown coll list.
- `frontend/src/pages/customers/CustomerMergeWizard.jsx`: drop the `warnings.forEach(...)` block from `_submit`.
- `frontend/src/pages/customers/__tests__/CustomerMergeWizard.test.jsx`: drop the warnings-fan-out case + the `info`/`message` sonner mocks.

No DB migration.
