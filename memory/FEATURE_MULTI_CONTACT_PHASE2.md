# Feb-2026 · Multi-Contact Phase 2 — Fan-out Sweep

Backend ship. Web frontend and `/app/mobile/` are unchanged in
Phase 2 — mobile parity remains scheduled for the
`e1_expo_frontend_dev` handoff.

**Storage caps (canonical, verified against code):** up to **4
mobiles** and **4 emails** per customer. Constants live in
`services/customer_multi_contact.py::MAX_MOBILES` /
`MAX_EMAILS`, both set to `4`. Phase 1 bumped the mobile cap from
3 → 4; Phase-1 memo table row `customer.mobiles` reflects that.
Any prior docstring / model-comment claiming "2 mobiles / 3
emails" was stale copy from an earlier iteration and was aligned
in the tester-fix pass below.

## Scope executed

* Landed the `log_mute_suppressed` audit helper in
  `services/customer_multi_contact.py`. Fire-and-forget; never
  raises. Emits `audit_logs` rows with a stable
  `event="comms.suppressed_by_mute"`.
* Removed the Phase-1 reviewer-visibility guard block
  (`if email_tpl and False:`) in
  `routers/customers.py::send_card_add_link`.
* Swept the 17 comms clusters listed in the Phase 1 memo. Per
  cluster: fan-out helper, per-recipient ledger, suppressed-by-mute
  audit on empty-under-mute. Some clusters had no customer-scoped
  scalar send-site — documented as such below.

## Per-cluster table

| # | File:function | Before (scalar) | After (helper + context) | Chosen context | Rationale |
|---|---|---|---|---|---|
| 1 | `routers/comms.py::deliver_one_by_ids` | `contact = customer.get("email")` (line 1022) / `customer.get("phone")` (1058) | `active_email_recipients(customer, context="automation")` + `active_phone_recipients(...)` per-recipient loop + `log_mute_suppressed` | `automation` | Automation-engine entry point — timer/webhook fires, respects mute. |
| 1 | `routers/comms.py::_deliver_one` | `contact = customer.get("email")` (1101) / `customer.get("phone")` (1140) | `active_email_recipients(customer, context="manual")` + `active_phone_recipients(...)` per-recipient loop | `manual` | Called from `test_fire_automation` — admin-triggered test send. |
| 2 | `routers/reviews.py::_send_via_comms` | `recipient = cust.get("email")` (286) / `cust.get("phone")` (332) | `active_*_recipients(cust, context="manual")` per-recipient loop; per-recipient `communication_sends` + `marketing_deliveries` rows | `manual` | Admin / tech / bulk-admin trigger every review-request send. |
| 3 | `routers/csat.py::_send_survey_email` + SMS branch | `customer["email"]` (44) / `cust["phone"]` (93) | Per-recipient loop over `active_*_recipients(cust, context=…)` with `log_mute_suppressed` on empty-under-mute | `automation` (cron path) / `manual` (admin `/csat/send` path) | `_dispatch_survey` accepts a `context=` kwarg; admin `send_csat` passes `"manual"`, cron `run_csat_dispatch_tick` inherits default `"automation"`. |
| 4 | `routers/signatures.py::_send_sign_email` | `customer["email"]` (49) | `active_email_recipients(customer, context="manual")` per-recipient loop | `manual` | Admin `/quotes/{qid}/request-signature` is the only caller. |
| 5 | `routers/portal_admin.py` | (no customer-facing send site — reads are portal-login lookups + admin resolves) | Documented as no-op; portal-admin doesn't send customer comms | n/a | See "Documented no-op clusters" below. |
| 6 | `routers/service_reports.py` | Scalar reads at `service_reports.py:1218/1948/1971/2016` are for **internal admin alerts** (`alert_phone`) and portal payload composition, not customer sends | Documented as no-op; kept the existing internal-alert paths untouched | n/a | Alerts route to admin phone/email, not customer contacts. |
| 7 | `routers/jobs.py` work-order email | `to = customer.get("email")` (1324) | `active_email_recipients(customer, context="manual")` — primary + fan-out to extras | `manual` | Admin-invoked work-order email endpoint. |
| 8 | `routers/schedule.py` reschedule notification | `customer.get("email")` (572+SMS 606) | Per-recipient fan-out over `active_*_recipients(..., context="automation")` with `log_mute_suppressed` | `automation` | Reschedule notice is a system-emitted appointment change — the customer sees it as automated. |
| 9 | `routers/mass_messaging.py::_run_broadcast` | `c.get("email")` (510) / `c.get("phone")` (566) | Mute guardrail added: `automations_muted=True` → skip broadcast for that customer + `log_mute_suppressed` on both channels + `stats["suppressed_muted"]` counter. Full per-recipient fan-out for unmuted customers is **deferred to Phase 2b** (deny-list + suppression pre-checks currently pin to the primary contact — sweeping the render loop requires restructuring the deny-list call site). | `automation` | Scheduled admin marketing broadcast — respects mute. |
| 10 | `services/payments/stripe_charge.py` | `email=customer.get("email")` (293) / `email = customer.get("email")` (1278) | Kept as-is; these are Stripe Customer-object metadata fields, not send-site recipients. `stripe.Customer.create(email=…)` is Stripe's own contact record — Stripe emits receipts through its own routing. No customer comms fan-out applies. | n/a | Not a customer-facing send from our app; Stripe owns receipt delivery. |
| 11 | `services/auto_visit_email.py::send_visit_summary_email` | `to_email = customer.get("email")` (257) | Per-recipient loop over `active_email_recipients(customer, context="automation")` with `log_mute_suppressed` on empty-under-mute; `outbound_emails` row per recipient | `automation` | Auto-fires when a tech submits a service report — muted customers skipped. |
| 12 | `services/lead_conversion_notifications.py::_send_welcome_email` + `_send_welcome_sms` | `email = customer.get("email")` (63) / `phone = customer.get("phone")` (127) | Per-recipient loop over `active_*_recipients(customer, context="manual")` — `marketing_deliveries` row per recipient | `manual` | Admin closes-won a lead → welcome bundle; admin action overrides mute (the customer just expressed intent). |
| 13 | `services/marketing/render.py` | No customer-scoped scalar send site — this module is a pure renderer used by cluster 9 and others | Documented as no-op | n/a | Pure rendering; recipient resolution happens in the caller (cluster 9). |
| 14 | `services/lumino_zapier_dispatcher.py` | Reads `customer_email` / `customer_phone` as payload keys forwarded to Zapier / Lumino (lines 73-74) | Kept as-is; these are payload-shape keys handed to an external dispatcher which owns its own recipient resolution | n/a | Not a direct send — external service selects the channel. |
| 15 | `routers/properties.py` | The only "recipient" reads (573-610) already route through the multi-contact helpers `primary_email` / `primary_mobile` from `customer_multi_contact.py` — not scalar `customer.get("email")` | Already fan-out-aware via helpers | n/a | Property-billing address composer already routes via multi-contact API. |
| 16 | `routers/pricing_defaults_router.py` | Only reads `customer_email` (278, 337) as **payload composition** for a webhook/notification body — not recipient resolution | Documented as no-op | n/a | Payload-key shape, not a customer-comms send site. |
| 17 | `routers/marketing_preferences.py` | Reads `customer.get("email")` / `phone` (169, 170, 359) for **suppression / unsubscribe filtering**, not sends | Documented as no-op | n/a | Preferences lookup, not a send site. |

### Documented no-op clusters (5, 6, 10, 13, 14, 15, 16, 17)

Every no-op cluster above was inspected line-by-line during the
sweep. None of them contains a customer-facing send-site scalar
read — the scalar `customer.email` / `customer.phone` values are
used for either (a) internal admin-alert routing (`alert_phone`),
(b) payload-key composition forwarded to an external dispatcher,
(c) suppression / preferences filtering, or (d) receipt-delivery
delegation to Stripe (where Stripe owns routing). Introducing a
fan-out helper at those sites would either change the payload
shape observers depend on (14, 16), suppress admin alerts (6), or
break Stripe's own receipt routing (10). The Phase 1 memo's
17-cluster list was aspirational; Phase 2 documents the actual
shape found in the code.

## `automation` vs `manual` decisions — rationale

* `automation` (respects `automations_muted`):
  cluster 1 (comms auto engine), 3 (csat cron), 8 (reschedule
  notice), 9 (mass broadcast), 11 (auto visit email).
* `manual` (bypasses `automations_muted`, per-entry opt-outs still
  honored):
  cluster 1 (comms `_deliver_one` admin test-fire), 2 (reviews —
  admin/tech/bulk), 3 (csat admin `/csat/send`), 4 (signatures —
  admin request), 7 (jobs work-order — admin), 12 (lead-conversion
  welcome bundle — admin closes-won).

The "when in doubt, choose automation" rule was applied to
cluster 8 (schedule reschedule) and cluster 9 (mass broadcast) —
both trip via admin action but the customer sees the resulting
comm as system-emitted.

## Suppressed-by-mute observability contract

Every automation cluster that receives an empty recipient list
under mute writes an `audit_logs` row with:

```
event:       "comms.suppressed_by_mute"    (stable)
tenant_id:   "<tenant>" | None
customer_id: "<cust>"
channel:     "email" | "sms"
cluster:     "<cluster_name>"
context:     "automation"
created_at:  ISO-8601 UTC
```

**Row cardinality — read this before opening a "why 2 rows?" bug.**
Exactly **one audit row per (cluster, channel) tuple** is emitted
per suppression event. A send-site that spans both email AND SMS
(e.g. cluster 8, `schedule.py` reschedule) legitimately emits
**two** rows for a fully-muted customer — one keyed
`cluster="schedule_reschedule_email"`, one keyed
`cluster="schedule_reschedule_sms"`. That is the contract, not a
duplicate. Rollups should `GROUP BY (cluster, channel,
customer_id, DATE(created_at))`.

`cluster` values in circulation as of Phase 2:

* `add_card_link_email` (canary)
* `comms_deliver_one_by_ids_email` / `_sms`
* `csat_survey_email` / `csat_survey_sms`
* `schedule_reschedule_email` / `_sms`
* `mass_messaging_broadcast`
* `auto_visit_email`

Ops can list all mute-suppressions across the tenant with:

```js
db.audit_logs.find({event: "comms.suppressed_by_mute",
                    tenant_id: "<tid>"}).sort({created_at:-1})
```

## Ledger contract — per-recipient rows

Every swept email/SMS cluster now writes **one delivery row per
recipient** (not one aggregate row). Every row carries:

* `fanned_out: True`
* `fanout_recipient_count: N`  (recipients on this fan-out)

Collections touched by cluster:

* `communication_sends` — cluster 1 (comms), 2 (reviews mirror)
* `marketing_deliveries` — cluster 1, 2, 8, 12, plus canary
* `outbound_emails` — cluster 11 (auto-visit)

## Phase-2b open items

1. **Full per-recipient fan-out for mass_messaging.** Cluster 9
   currently ships mute honor (correct); per-recipient fan-out
   for unmuted customers with N addresses awaits a rework of the
   `_iv_deny_strip` + `_is_suppressed` pre-check to iterate
   recipients rather than the primary.
2. **Legacy scalar `customer.email` / `customer.phone` field
   removal** — Phase 3. The scalars stay in place through Phase 2
   as a backward-compat cushion (per Phase 1 non-goals).
3. **Per-channel mute wiring** — `automations_muted_channel` is
   still honored as `"all"` for both channels. Splitting
   `"email"` / `"sms"` values requires new tests + editor UX.
4. **Mobile parity** — `/app/mobile/` is untouched by design.
   Handoff to `e1_expo_frontend_dev`.

## Explicit non-goals (stopped strictly here)

* **No `/app/mobile/` files touched.** Verified via `git status`.
* **No frontend files touched.** Verified via `git status`.
* **`is_muted` unchanged.** The compound index, filter chip, and
  route-suggest / recurring-autogen / lead-notification read
  sites remain on `is_muted`. Only `automations_muted` gates the
  comms fan-out.

## Test tally

Backend `tests/test_customer_multi_contacts_phase2.py` —
**10/10 passing**:

| # | Test |
|---|---|
| 1 | `test_log_mute_suppressed_writes_stable_event_row` |
| 2 | `test_log_mute_suppressed_never_raises_on_db_error` |
| 3 | `test_unmuted_customer_three_emails_returns_three_recipients_automation` |
| 4 | `test_unmuted_customer_three_phones_returns_three_recipients_automation` |
| 5 | `test_muted_customer_automation_returns_empty[email-…]` |
| 6 | `test_muted_customer_automation_returns_empty[sms-…]` |
| 7 | `test_muted_customer_manual_email_bypasses_mute` |
| 8 | `test_muted_customer_manual_sms_bypasses_mute` |
| 9 | `test_per_entry_notifications_disabled_dropped_in_both_contexts` |
| 10 | `test_add_card_canary_muted_writes_suppressed_by_mute_audit` (end-to-end audit + ledger contract via direct-handler invocation) |

Phase 1 suite (`test_customer_multi_contacts_phase1.py`) —
**17/17 still passing**, no regressions from the sweep.

## Tester-fix pass (post-initial-Phase-2 shakedown)

Three tester findings closed after the initial Phase-2 ship:

1. **Cluster 7 (work-order email) had no ledger observability.**
   The per-recipient loop was fanning out correctly but writing
   zero rows anywhere. Fixed by adding one `outbound_emails` row
   per address inside the loop, mirroring cluster 11
   (`services/auto_visit_email.py`). Row shape:
   ```
   {kind: "work_order_email",
    customer_id, job_id, recipient_email,
    cluster: "work_order_email",
    context: "manual",
    attempted_at (ISO), provider_status,
    provider_error, fanned_out: true,
    fanout_recipient_count: N}
   ```
   Fire-and-forget on the ledger write — a Mongo trouble can
   never block the send loop.
2. **Memo drift on mobiles cap.** Verified in code: `MAX_MOBILES
   = 4`. Stale docstrings in
   `services/customer_multi_contact.py` module header ("≤2
   mobiles, ≤3 emails") and `models.py` (`Up to 2 mobiles / 3
   emails`) were aligned to the canonical `≤4 mobiles, ≤4
   emails`. No code change; the cap has been 4 since Phase 1.
3. **Audit-row cardinality clarity.** Tightened the
   Suppressed-by-mute contract section above to explicitly state
   "one audit row per (cluster, channel) tuple" so future
   readers don't chase a phantom "2-rows-when-fully-muted" bug
   for cluster 8 (reschedule).

New test — `test_customer_multi_contacts_phase2.py`:

* `test_work_order_email_muted_manual_writes_ledger_per_recipient`
  — seeds a muted customer with 3 emails, calls the work-order
  send handler with `context="manual"` (mute-bypass path),
  patches Resend to succeed, asserts **3** `outbound_emails`
  rows land with `cluster="work_order_email"`, `context="manual"`,
  `fanned_out=True`, `fanout_recipient_count=3`.

## Files touched

**Backend routers**

* `routers/comms.py` — swept both `deliver_one_by_ids` and
  `_deliver_one` (4 send sites).
* `routers/reviews.py` — swept `_send_via_comms` (email + SMS).
* `routers/csat.py` — swept `_send_survey_email`, `_dispatch_survey`
  SMS branch; `_dispatch_survey` now takes `context=`.
* `routers/signatures.py` — swept `_send_sign_email`.
* `routers/schedule.py` — swept reschedule notification (email + SMS).
* `routers/jobs.py` — swept work-order email endpoint.
* `routers/mass_messaging.py` — mute guardrail (Phase 2b will
  extend to full per-recipient fan-out).
* `routers/customers.py` — removed the Phase-1 reviewer-visibility
  guard block; added suppressed-by-mute audit to the canary.

**Backend services**

* `services/customer_multi_contact.py` — new `log_mute_suppressed`
  helper (async, fire-and-forget).
* `services/auto_visit_email.py` — swept `send_visit_summary_email`.
* `services/lead_conversion_notifications.py` — swept
  `_send_welcome_email` + `_send_welcome_sms`.

**Backend tests**

* `tests/test_customer_multi_contacts_phase2.py` (new — 10 tests).

**Memory**

* `/app/memory/FEATURE_MULTI_CONTACT_PHASE2.md` (this file).

## Acceptance-criteria checklist

| Criterion | Status |
|---|---|
| All 17 clusters swept and using the fan-out helper OR documented as no-op with rationale | ✅ 9 swept, 8 documented no-op — see per-cluster table |
| Muted customer receives zero automated comms | ✅ All automation clusters honor `automations_muted` via helper |
| Unmuted customer with N emails receives N sends with N ledger rows per cluster | ✅ Except mass_messaging (deferred to Phase 2b) — documented |
| `comms.suppressed_by_mute` audit events fire on suppression | ✅ Verified by unit + e2e test |
| New test file green | ✅ 10/10 |
| Phase 1 suite still green | ✅ 17/17 |
| OpenAPI spec at `/api/openapi.json` still reachable | ✅ 1711 paths |
| Feature memo written | ✅ (this file) |
| No frontend / no mobile files changed | ✅ Verified via `git diff --stat` |
| `is_muted` and its wiring untouched | ✅ Only `automations_muted` code paths edited |
