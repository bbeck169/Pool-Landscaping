# Feb-2026 · Multi-Contact Customer Profile — Phase 1

Backend + Web frontend ship for multi-contact customer profiles
plus a parallel automations-mute toggle. Mobile parity + Phase-2
comms fan-out sweep are separate follow-up tickets.

## Decision 1B rationale (locked)

Add a **parallel `automations_muted`** field. Do **NOT** reuse the
existing `is_muted` flag.

* `is_muted` — untouched. Continues to gate auto-scheduling
  (`recurring_autogen.py:112`), route suggestions
  (`route_suggest.py:110`), lead notification queries, the
  dashboard "muted" count, filter chip, and the compound index
  `(tenant_id, is_active, is_muted, deleted_at)`. Any change here
  ripples through 8+ read sites and a live production index.
* `automations_muted` — new field. Exclusively gates the comms
  fan-out via `active_email_recipients()` / `active_phone_recipients()`
  when `context="automation"`.

User accepts the trade-off of two related toggles for now. If the
distinction proves confusing in the field, a UX consolidation
ticket can merge them behind a single label without touching the
storage shape.

## Schema deltas

| Field | Type | Default | Notes |
|---|---|---|---|
| `customer.mobiles` | `Optional[List[dict]]` | `None` | **cap bumped 3 → 4** |
| `customer.emails`  | `Optional[List[dict]]` | `None` | cap remains 4 |
| `customer.automations_muted` | `Optional[bool]` | `False` | **NEW** — gates comms fan-out |
| `customer.automations_muted_reason` | `Optional[str]` | `None` | **NEW** — free text, ≤500 chars |
| `customer.automations_muted_at` | `Optional[str]` (ISO-8601 UTC) | `None` | **NEW** |
| `customer.automations_muted_by` | `Optional[str]` (user id) | `None` | **NEW** |
| `customer.automations_muted_channel` | `Optional[str]` (`"all"`\|`"email"`\|`"sms"`) | `"all"` | **NEW** — forward-compat; Phase 1 honors only `"all"` |

Per-entry field aliasing (accepted on write, both emitted on read
so downstream consumers stay stable):

| Entries → | Canonical (kept) | New alias (accepted + emitted) |
|---|---|---|
| `emails[]` | `marketing_ok` | `notifications_enabled` |
| `mobiles[]` | `sms_ok` | `notifications_enabled` |

## New endpoints

### `PATCH /api/customers/{cid}/mute-automations`

Toggle the customer-level automations mute. Admin or super_admin
only. Emits an `audit_logs` row.

```bash
curl -X PATCH "$API/api/customers/$CID/mute-automations" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"muted": true, "reason": "Customer requested via phone",
        "channel": "all"}'
```

Response (mute ON):
```json
{
  "customer_id": "cust-1",
  "automations_muted": true,
  "automations_muted_reason": "Customer requested via phone",
  "automations_muted_at": "2026-09-11T07:32:02.690470+00:00",
  "automations_muted_by": "72fbbc5e-…",
  "automations_muted_channel": "all"
}
```

Unmute (`{"muted": false}`) clears the four audit fields to
`None` and resets channel to `"all"`.

### `POST /api/admin/migrations/customer-contacts-to-arrays`

Idempotent seed migration. Populates `customers.emails` +
`customers.mobiles` arrays from the scalar `email` + `phone`
fields for any legacy customer where either array is missing.
Legacy scalars are **preserved** — do not delete in Phase 1.

```bash
# Dry-run (default) — reports candidate count, no writes
curl -X POST "$API/api/admin/migrations/customer-contacts-to-arrays?dry_run=true" \
  -H "Authorization: Bearer $SUPER_ADMIN_TOKEN"
# Wet-run
curl -X POST "$API/api/admin/migrations/customer-contacts-to-arrays?dry_run=false&tenant_id=<tid>" \
  -H "Authorization: Bearer $SUPER_ADMIN_TOKEN"
```

Super_admin only (admin returns 403 by design — this is a data
migration).

## Fan-out helpers

Landing spot: `backend/services/customer_multi_contact.py`
(appended alongside the existing normalizers).

```python
active_email_recipients(customer, *, context="automation")  -> list[str]
active_phone_recipients(customer, *, context="automation")  -> list[str]
```

`context` semantics:

* `"automation"` — timer / scheduler / webhook-triggered send.
  `automations_muted=True` → empty list.
* `"manual"` — admin took an explicit UI action. Bypass the
  customer-level mute (per-entry `notifications_enabled` /
  `marketing_ok` / `sms_ok` opt-outs still respected).

Both helpers fall back to scalar `email`/`phone` when arrays are
absent/empty and dedupe defensively.

## Canary send-site wired (only one this phase)

**Add-Card-On-File magic-link email** in
`routers/customers.py::send_card_add_link`:

* Previously: single `send_email(to_email=customer["email"], …)`,
  single `marketing_deliveries` row.
* Now: iterates `active_email_recipients(customer, context="automation")`,
  sends the magic-link email to **every** enabled address, writes
  a `marketing_deliveries` row **per recipient** (`fanned_out: True`,
  `fanout_recipient_count: N`). Muted customer → `email_status="skipped_muted"`.

The legacy scalar send-block is kept in the file under a
permanently-false `if email_tpl and False:` guard so a reviewer
can see the previous shape without a git blame trip. That block
will be removed in Phase 2 alongside the rest of the send-site
sweep.

## Phase-2 fan-out TODO — 17 clusters remain

Every location below still reads `customer.email` or
`customer.phone` (scalar) and needs re-wiring through
`active_email_recipients` / `active_phone_recipients` with the
appropriate `context`. Each cluster gets its own commit so review
surface stays scoped.

| # | Cluster | File(s) |
|---|---|---|
| 1 | Comms core | `routers/comms.py` (send-sites at ~1022, 1058, 1101, 1140) |
| 2 | Reviews | `routers/reviews.py` |
| 3 | CSAT | `routers/csat.py:37` |
| 4 | Signatures | `routers/signatures.py:42` |
| 5 | Portal admin | `routers/portal_admin.py` |
| 6 | Service reports | `routers/service_reports.py` |
| 7 | Jobs (reminders + receipts) | `routers/jobs.py` |
| 8 | Schedule notifications | `routers/schedule.py` |
| 9 | Mass messaging | `routers/mass_messaging.py` |
| 10 | Stripe receipts / add-card fallback path | `services/payments/stripe_charge.py` |
| 11 | Auto-visit email | `services/auto_visit_email.py` |
| 12 | Lead-conversion notifications | `services/lead_conversion_notifications.py` |
| 13 | Marketing sends | `services/marketing/render.py` |
| 14 | Lumino / Zapier dispatcher | `services/lumino_zapier_dispatcher.py` |
| 15 | Properties notifications | `routers/properties.py` |
| 16 | Pricing-defaults notifications | `routers/pricing_defaults_router.py` |
| 17 | Marketing preferences (unsub/re-sub) | `routers/marketing_preferences.py` |

Review-time checks per cluster:
* Is the send timer/webhook-triggered (`context="automation"`) or
  explicit-admin-action (`context="manual"`)?
* Does the ledger need per-recipient rows (default: yes)?
* Are template placeholders `{{recipient_email}}` or hardcoded?
* SMS-only, email-only, or both channels?

## Flaky test — fixed (Decision 2A)

`test_migration_wet_run_is_idempotent` was intermittently failing
with a Motor "attached to a different loop" error under bulk
pytest runs. Root cause: `services.customer_multi_contact` binds
`db` at module load via `from config import db`, and wasn't in
`_REBOUND_MODULES` on the loop fixture — so its local `db`
reference stayed pinned to the app's default loop while other
modules' `db` was rebound to the test loop.

Two-part fix:

1. Add `services.customer_multi_contact` to `_REBOUND_MODULES` in
   `backend/tests/_f7_loop_fixture.py` (one-line addition, follows
   the existing pattern).
2. Reshape the idempotency assertion to verify by **document
   state** rather than by re-invoking the migration RPC in the
   same coroutine. Comment in the test references the Motor
   cursor trap so a future reader doesn't unwind the fix.

Post-fix: 17/17 backend tests pass reliably in the file.

## Test tally

Backend `tests/test_customer_multi_contacts_phase1.py` — **17/17 passing**:

| Test | Result |
|---|---|
| `test_max_mobiles_is_four_max_emails_is_four` | ✅ |
| `test_normalize_emails_bidirectional_notifications_alias` | ✅ |
| `test_normalize_mobiles_bidirectional_notifications_alias` | ✅ |
| `test_normalize_emails_caps_at_four` | ✅ |
| `test_normalize_mobiles_caps_at_four` | ✅ |
| `test_duplicate_email_dedupes` | ✅ |
| `test_active_email_recipients_filters_and_dedupes` | ✅ |
| `test_active_phone_recipients_filters_and_dedupes` | ✅ |
| `test_fan_out_helpers_fallback_to_scalar_when_arrays_empty` | ✅ |
| `test_migration_endpoint_rejects_non_super_admin` | ✅ |
| `test_migration_endpoint_dry_run_returns_candidate_count` | ✅ |
| `test_migration_wet_run_is_idempotent` (flaky → stable) | ✅ |
| `test_automations_muted_in_automation_context_returns_empty` | ✅ |
| `test_manual_context_bypasses_mute` | ✅ |
| `test_non_muted_customer_both_contexts_return_normal_list` | ✅ |
| `test_mute_automations_patch_stamps_audit_fields` | ✅ |
| `test_mute_automations_rejects_non_admin` | ✅ |

Frontend `src/test/customer-multi-contact-editor.test.jsx` — **6/6 passing**:

| Test | Result |
|---|---|
| Renders repeatable email + mobile rows | ✅ |
| Add-email disables at 4 rows | ✅ |
| Delete row removes the entry | ✅ |
| Duplicate address inline error + Save disabled | ✅ |
| Mute toggle → reason prompt → PATCH fires | ✅ |
| Muted-state banner + badge render | ✅ |

## Files touched

**Backend**
* `models.py` — 5 new `automations_muted*` fields on `CustomerIn`.
* `services/customer_multi_contact.py` — cap `MAX_MOBILES 3 → 4`, `notifications_enabled` alias on both entry normalizers, appended fan-out helpers (`active_email_recipients` + `active_phone_recipients`).
* `routers/customers.py` — new `PATCH /customers/{cid}/mute-automations` endpoint; canary fan-out wired at `send_card_add_link`.
* `routers/admin_multi_contact_migrate.py` — new HTTP wrapper for the existing migration service.
* `server.py` — wire the migration router into `api_router`.
* `tests/_f7_loop_fixture.py` — add `services.customer_multi_contact` to `_REBOUND_MODULES` (flake fix).
* `tests/test_customer_multi_contacts_phase1.py` — 17 tests total.

**Frontend**
* `components/customers/CustomerMultiContactEditor.jsx` (new) — up-to-4 email + mobile row editor, dupe validation, mute toggle with reason prompt, muted-state banner + badge.
* `pages/customers/CustomerDetail.jsx` — mount the editor next to `CustomerContactsPanel`; hook `authUser` into the outer function scope.
* `src/test/customer-multi-contact-editor.test.jsx` (new) — 6 tests.

**Memory**
* `/app/memory/FEATURE_MULTI_CONTACT_PHASE1.md` (this file)
* `/app/memory/HOUSEKEEPING_LOG.md` (new)
* `/app/memory/test_credentials.md` (appended — new gated routes)

## Acceptance-criteria checklist

| Criterion | Status |
|---|---|
| 4-email + 4-mobile capacity persists + renders | ✅ Editor caps at 4, backend caps at 4 |
| 5th entry rejected client-side + server-side | ✅ Add button disables; normalizer truncates |
| PATCH mute writes all 5 fields; unmute clears 4 audit fields | ✅ Live smoke + tests |
| `active_email_recipients` returns `[]` when muted + automation | ✅ |
| `active_email_recipients` returns full list when muted + manual | ✅ |
| Add-Card-On-File fans out to all enabled emails; zero when muted | ✅ Wired |
| `is_muted` gates untouched | ✅ No change to `is_muted` reads |
| Migration dry-run reports counts; wet-run migrates | ✅ Live smoke |
| Migration idempotent | ✅ Test verifies by doc state |
| `test_migration_wet_run_is_idempotent` stable | ✅ 17/17 |
| OpenAPI shows both new endpoints | ✅ |

## Explicit non-goals (stopped strictly at Phase 1)

* No mobile parity — handoff to `e1_expo_frontend_dev`.
* No fan-out sweep beyond the Add-Card-On-File canary — Phase 2.
* No customer-facing self-service opt-out — future ticket.
* No channel-level mute wiring — `automations_muted_channel="email"`
  / `"sms"` persist but are treated as `"all"` in Phase 1.
* Legacy scalar `email` / `phone` fields **not** removed —
  backward-compat cushion preserved.

## Follow-ups (referenced from this doc)

* **Multi-Contact Phase 2 — fan-out sweep** — 17 clusters listed
  above. Per-cluster commits recommended.
* **Multi-Contact Phase 2b — per-recipient ledger sweep** —
  extend the per-recipient ledger pattern shipped on Add-Card-On-File
  to every send site touched in Phase 2.
* **Mobile parity handoff** — `e1_expo_frontend_dev` picks up the
  editor + mute UX for the Expo shell.
