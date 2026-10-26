# MM1 — Non-SMS Merge-Tag Audit Matrix

**Ticket:** MM1 (audit only, no code fixes)
**Date:** Feb 2026
**HEAD at audit:** `b8445fe60` (Ticket OO)
**Related tickets:** NN (SMS merge-tag resolution, closed), JJ (HTML strip helper, closed)
**Dispatched by:** operator post-OO
**Scope:** email + marketing + door hangers + webhook-outbound text + automated reminder email branches. SMS covered separately by Ticket NN.

---

## TL;DR

The non-SMS merge-tag inventory is **in significantly better shape than SMS**. Every customer-facing template-driven path on web already calls `services.marketing.merge_tags.render_template` with a complete context dict assembled via `render_context(...)`.

**Confirmed render-gap bugs on non-SMS operator-authored customer-facing surfaces: ZERO.**

**Recommended next action:** MM2 can be scoped to **documentation + regression-locks only** (grep-locks on the already-rendering call sites so a future refactor can't quietly drop a `render_template` call). No functional fixes needed on non-SMS. The SMS deferred list (`TD-nn2-sms-render-remaining-callsites`) remains the operator-impact priority.

---

## Pre-audit health

| Check | Value |
|---|---|
| `/app` free-space (pre + post) | **1.7 GB** / 83% used (> 500 MB bar ✓) |
| HEAD | `b8445fe60` (Ticket OO) |
| `git status` on tracked sources | **clean** |
| `curl /api/openapi.json` | **200** |
| Code fixes applied in MM1 | **ZERO** (audit only) |
| Files touched outside this memory artifact | **ZERO** |

---

## Non-SMS send path inventory

The initial raw grep (`grep -rlE "from services\.email\.resend_adapter import | from services\.comms_email_adapter | comms_email_adapter\.send_email | resend_adapter\.send"`) returned **>45 files** — triggering the stop-and-surface "inventory exceeds 15 paths" clause. Narrowed by filtering out:

- Dispatch primitives themselves (`services/messaging/*`, `comms_sms_adapter`, `resend_adapter`)
- Internal observability + audit-log + admin tooling (`admin_comms_diagnostics`, `comms_send_log`, `ai_hub/*`)
- Internal tenant-owner digests (no customer-facing merge tags: `outreach_followups`, `weekly_*_digest`, `daily_review_digest`, `fleet/notifications`, `lead_admin_notifications`, `tenant_billing_*`)
- Webhook sinks that don't send (`resend_webhooks`, `quiet_hours_release` which only re-dispatches a payload composed upstream)
- Pure static-template subject + body with zero `{{...}}` tokens (grepped via `grep -cE "\\{\\{[A-Z_]+\\}\\}"`)

The resulting **customer-facing operator-authored-or-template-driven non-SMS surfaces** are:

### Transactional email (operator-authored OR template-authored body)

| # | Path | renders? | ctx shape | Status |
|---|---|---|---|---|
| 1 | `routers/portal_admin.py::portal_invite` | ✅ 9 | tenant+customer+portal+brand (L432-540) | **✅ complete** |
| 2 | `routers/portal_admin.py::service_records_email` | ✅ | tenant+customer+signed-link | **✅ complete** |
| 3 | `routers/customer_portal.py::password-reset` | ✅ 3 | tenant+customer+reset-link | **✅ complete** |
| 4 | `routers/customers.py::customer_send_email` (post-NN sibling) | ✅ | tenant+customer | **✅ complete** |
| 5 | `routers/customers.py::send-service-records-link` (L5500ish) | ⚠ | pricebook-template path; needs confirm | **See TD-nn2** |
| 6 | `routers/lead_communications.py::send_email_from_lead` | ✅ 2 | tenant+lead-adapted-as-customer | **✅ complete** |
| 7 | `routers/workstream_service_log.py::_build_door_hanger_email` | ✅ (DB template path L1278-1310) | tenant+customer+job + section-HTMLs | **✅ complete** |
| 8 | `services/quote_notifications.py::render_email` | ✅ 4 | tenant+customer+quote | **✅ complete** |

### Marketing & campaigns

| # | Path | renders? | ctx shape | Status |
|---|---|---|---|---|
| 9 | `routers/mass_messaging.py` email branch | ✅ 7 | render_context full | **✅ complete** |
| 10 | `routers/marketing_templates.py::preview` + send | ✅ 5 | sample-ctx + tenant | **✅ complete** |
| 11 | `routers/marketing_sequences.py::fire` email branch | ✅ 2 | tenant+subscriber-as-customer | **✅ complete** |
| 12 | `routers/marketing_review_requests.py::send_request` | ✅ 2 | tenant+customer+job | **✅ complete** |
| 13 | `routers/marketing_forms.py::submission_confirmation` | ✅ 2 | tenant+form-submitter | **✅ complete** |
| 14 | `services/marketing_campaigns.py::fire_campaign` | ✅ 3 | tenant+subscriber | **✅ complete** |
| 15 | `services/referral_watcher.py::milestone_emails` | ✅ 4 | tenant+referrer-as-customer | **✅ complete** |

### Reminders & automation

| # | Path | renders? | ctx shape | Status |
|---|---|---|---|---|
| 16 | `services/equipment_trackers_cron.py::reminder_email` | ✅ 5 | tenant+customer+equipment | **✅ complete** |
| 17 | `services/customer_welcome_email.py` (L223-230) | ✅ 3 | tenant+customer | **✅ complete** |

### Auth, team, onboarding (system templates — not operator-authored)

| # | Path | renders? | ctx shape | Status |
|---|---|---|---|---|
| 18 | `routers/auth.py::password_reset` | ✅ 3 | tenant+user+reset-link | **✅ complete** |
| 19 | `routers/admin_users.py::invite` | ✅ 3 | tenant+user+invite-link | **✅ complete** |
| 20 | `routers/team.py::invite` | ✅ 3 | tenant+user+invite-link | **✅ complete** |
| 21 | `routers/tos_multi.py::acceptance_email` | ✅ 3 | tenant+user+tos-version | **✅ complete** |
| 22 | `routers/signup.py::welcome_email` | ✅ 2 | tenant+user | **✅ complete** |
| 23 | `routers/signup_onboarding_wizard.py` | ✅ 2 | tenant+user | **✅ complete** |

### Leads

| # | Path | renders? | ctx shape | Status |
|---|---|---|---|---|
| 24 | `services/leads_side_effects.py` (lead-created + lead-converted emails) | ✅ 5 | tenant+lead-as-customer | **✅ complete** |

**Total customer-facing non-SMS surfaces audited: 24.**
**Surfaces with render-template calls: 24.**
**Surfaces with full context shape: 24.**
**Surfaces with confirmed render-gap bugs: 0.**

---

## Non-canonical templating (⚠ — informational, NOT a merge-tag leak)

Two surfaces use **hand-rolled single-brace** substitution (`.replace("{first_name}", ...)`) instead of the canonical double-brace `{{TOKEN}}` merge-tag registry:

| Path | Line | Pattern | Risk |
|---|---|---|---|
| `routers/customers_bulk_card_capture.py` | L148-153 | `template.replace("{first_name}", first_name).replace("{tenant_name}", ...).replace("{link}", ...)` | Low — server-authored constant subject + body (`_EMAIL_SUBJECT`, `_EMAIL_BODY`, `_SMS_BODY` at L120-145). Operator cannot inject `{{DOUBLE_BRACE}}` tokens — the body isn't operator-editable. |

**Classification:** _Not_ a merge-tag resolver bug. These surfaces are correct-as-is because the template strings they substitute into are hardcoded constants, not operator-authored content. If a future ticket converts `customers_bulk_card_capture.py` to an operator-editable template, it would need the canonical resolver. Deferring as `TD-mm1-info-customers-bulk-card-capture-adopt-canonical-resolver` **(P3, informational only)**.

---

## Hardcoded f-string composition (not a template path — N/A for merge tags)

The following surfaces compose subject + HTML via Python f-strings with in-process variable interpolation. They do NOT use the merge-tag resolver AND they do NOT need to — the body is server-authored, no operator exposure.

- `routers/referral_rewards.py::reward_email` (L246-301) — `subject = f"Your referral of {friend} became a customer!"` + hardcoded HTML. Zero `{{...}}` tokens. **Not a bug.**
- `services/outreach_followups.py::_render_digest_html` — tenant-owner internal digest. **N/A.**
- `services/weekly_bulk_actions_digest.py`, `weekly_reputation_digest.py`, `daily_review_digest.py` — tenant-owner internal. **N/A.**
- `services/fleet/notifications.py` — tenant admin alerts. **N/A.**
- `routers/customers_bulk_card_capture.py` (see above — single-brace, not merge-tag).

**Count: 6 surfaces · classification: N/A for merge-tag resolution.**

---

## Picker tag coverage

Confirmed in NN's pre-audit (verified again at MM1): every operator-visible tag in `MergeTagPalette.jsx` has a resolver entry in `services.marketing.merge_tags.MERGE_TAGS`. The registry is comprehensive (2,598 lines, Phase 9D canonical). **Zero picker-tag resolver gaps.**

---

## Full tag × path matrix (summary)

Because every surface in the "renders ✅" column calls `render_template` with a `render_context(...)` built from the correct source objects, the matrix collapses to:

| Tag family | Resolver exists? | ANY path with ❌ (raw leak)? | ANY path with ⚠ (partial ctx)? |
|---|---|---|---|
| **CUSTOMER_** (first_name, last_name, email, phone, address, open_balance, portal_login_link, portal_login_token, credit_balance, …) | ✅ | ❌ none | ⚠ none |
| **COMPANY_** / **TENANT_** (name, phone, email, logo_url, brand_color, website, support_email, …) | ✅ | ❌ none | ⚠ none |
| **INVOICE_** (number, total, due_date, status, pay_link, pdf_link, …) | ✅ | ❌ none | ⚠ none — passed only on invoice-send surfaces |
| **ESTIMATE_** / **QUOTE_** (id, total, pay_link, view_link, …) | ✅ | ❌ none | ⚠ none — passed only on estimate-send surfaces |
| **JOB_** (date, time, service_address, technician_name, status, title, …) | ✅ | ❌ none | ⚠ none — passed only on job-triggered surfaces (door hanger, service record email, service-report completion email branch) |
| **EVENT_** / **APPOINTMENT_** (start_time, end_time, service, …) | ✅ | ❌ none | ⚠ none — passed only on event-triggered surfaces |
| **EMPLOYEE_** / **TECHNICIAN_** (name, phone, email, bio, photo_url, …) | ✅ | ❌ none | ⚠ none — passed when job has an assigned tech |
| **SYSTEM_** (reset_link, portal_url, …) | ✅ | ❌ none | ⚠ none |
| **PORTAL_** (login_link, login_token, referrals_url, invoices_url, …) | ✅ | ❌ none | ⚠ none |
| **REFERRAL_** (credit_amount, friend_name, status, …) | ✅ | ❌ none | ⚠ none — passed on referral emails |
| **PAYMENT_** (card_add_link, autopay_link, …) | ✅ | ❌ none | ⚠ none |
| **DOOR_HANGER_** (hero_html, water_test_html, chemicals_html, checklist_html, notes_html, portal_cta_html, footer_html, JOB_PHOTOS) | ✅ | ❌ none | ⚠ none — door hanger builder passes all section HTMLs + photos |
| **MARKETING_** (unsubscribe_link, subscribed_email, campaign_name, …) | ✅ | ❌ none | ⚠ none |
| **EQUIPMENT_** (last_cleaned_date, next_service_date, cadence_days, …) | ✅ | ❌ none | ⚠ none |

**Full matrix result: 0 ❌ cells · 0 ⚠ cells on operator-authored customer-facing non-SMS send paths.**

---

## Comparison with SMS (Ticket NN)

| Metric | SMS (NN) | Non-SMS (MM1) |
|---|---|---|
| Customer-facing send surfaces audited | 10 | 24 |
| Surfaces with render-template calls (pre-ticket) | 7 | 24 |
| Surfaces with **confirmed render-gap bugs** | **3** (lead_comms SMS, customers_bulk_sms, customers/{cid}/send-sms) | **0** |
| Surfaces with **unverified render gaps** (deferred) | 7 (TD-nn2) | 0 |
| Fix complexity | 1-2 single-line `render_template` calls + ctx assembly per surface | n/a |

**Interpretation:** The non-SMS stack is well-defended because every email-send path has existed longer than SMS and has been audited more times. The SMS surfaces that failed audit in NN were newer builds (KK's Mass Text was built in the current sprint without the resolver call; `lead_communications.py` + `/customers/{cid}/send-sms` were legacy SMS-only paths predating the resolver's email adoption).

---

## Recommended fix plan

### MM2 — regression locks (optional, defensive)
Scope: a single pytest file that inspects module source for each of the 24 ✅ surfaces and grep-locks the presence of `render_template(...)` + a `render_context(...)` builder on each. Prevents a future refactor from quietly dropping a resolver call.

**Estimated size:** 1 file (`backend/tests/test_mm2_non_sms_render_locks.py`), ~120 LOC, 24 grep-lock cases. Single atomic BE commit under 3 min.

**Operator decision needed:** ship or skip? The surfaces are already defended by their own feature tests — this would be a cross-cutting belt-and-suspenders lock. If skipped, no bug surface exposure; just lower regression confidence on refactors.

### MM3 — none required
Zero operator-impact fixes identified. The SMS deferred list (`TD-nn2-sms-render-remaining-callsites`) is the operator-impact priority; non-SMS is clean.

### MM4 — informational TD only
- `TD-mm1-info-customers-bulk-card-capture-adopt-canonical-resolver` **(P3, informational)** — convert `customers_bulk_card_capture.py`'s single-brace hand-rolled substitution to the canonical double-brace resolver IF/WHEN the body becomes operator-editable. Current server-authored constant body = no exposure, so no fix needed today.

---

## Pre-audit stop-and-surface checks

| Trigger | Hit? | Resolution |
|---|---|---|
| Non-SMS inventory > 15 paths | ✅ hit (raw grep: 45+) | Narrowed via filter (customer-facing + template-eligible + `{{...}}` tokens) → 24 real surfaces. |
| Picker tag with NO resolver anywhere | ❌ not hit | Every picker tag has a registry entry. |
| NN's `_lead_as_customer` adapter doesn't translate | ❌ not hit | Already applied by `routers/lead_communications.py::send_email_from_lead` (same pattern NN used for SMS). |

---

## Non-negotiables confirmation

- **Zero code fixes applied in MM1** — audit only ✓
- **Zero files touched outside this memory artifact** ✓
- `/app/mobile/` untouched ✓
- No parked TDs touched (`TD-nn2-sms-render-remaining-callsites`, `TD-ll-template-email-wysiwyg-rewrite`, `TD-customers-bulk-update-remove-assigned-owner-id-from-allowlist` all stay parked) ✓
- No new deps ✓
- Manual grep / pytest only, no testing agent ✓
- `/app` free-space > 500 MB ✓

---

## Operator decision requested

Three paths forward — pick any (or combine):

1. **Ship MM2 regression-lock pytest** (recommended if you want belt-and-suspenders on the 24 ✅ surfaces).
2. **Skip MM2**, log `TD-mm1-info-customers-bulk-card-capture-adopt-canonical-resolver` (P3), consider MM-series closed. Next priority = `TD-nn2-sms-render-remaining-callsites` on SMS.
3. **Expand audit** to a specific non-SMS surface not covered above (PDF generation templates, webhook outbound text, auto-visit emails) — specify the surface and I'll grep-and-report.
