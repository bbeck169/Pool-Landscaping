# PP — TD-nn2-sms-render-remaining-callsites Resolution

**Ticket:** PP (resolve NN's deferred SMS paths)
**Date:** Feb 2026
**HEAD at audit:** `eb4dc43b2` → `4a517c7a3` (MM1 doc) → `b8445fe60` (OO)
**Related tickets:** NN (SMS merge-tag resolution for 3 operator-facing paths), MM1 (non-SMS audit matrix)
**Outcome:** **TD CLOSED without code changes — audit refutes the TD's premise.**

---

## TL;DR

NN logged `TD-nn2-sms-render-remaining-callsites` as a P2 follow-up to wire `services.marketing.merge_tags.render_template` into 7 deferred SMS send paths. The deferral was based on a grep-count heuristic (**0 renders + any SMS call → suspected gap**).

PP's deep-dive confirms **ZERO of the 7 paths carry operator-authored `{{...}}` merge-tag tokens in their SMS bodies**. Every path falls into one of five "no-fix-needed" categories:

- **Server-authored constant f-string composition** (zero `{{...}}` tokens, nothing to resolve)
- **Admin-authored free-text alerts** (not customer-facing, no template)
- **Hand-rolled single-brace Python `.format(...)` templates** (correct-as-is; converting to double-brace would be a breaking schema change)
- **Dev-only smoke-test endpoints** (not a production customer flow)
- **Already renders via the canonical resolver** (custom dunning stages)

**Correct resolution: CLOSE the TD without code changes.** Wiring `render_template` into these paths would be a no-op (no `{{...}}` tokens to resolve) OR a schema break (converting single-brace to double-brace in a template body callers already `.format(...)` against).

---

## Pre-audit health

| Check | Value |
|---|---|
| `/app` free-space (pre + post) | **1.7 GB** / 84% (> 500 MB bar ✓) |
| HEAD | `b8445fe60` (OO) → `4a517c7a3` (MM1) → `eb4dc43b2` (platform auto-commit, benign) |
| `git status` on tracked sources | **clean** |
| `curl /api/openapi.json` | **200** |
| Code fixes applied in PP | **ZERO** |

---

## Per-path classification

### 1. `routers/service_reports.py` — completion SMS (L1815-1840)

- **Body source:** `services.completion_sms_template.build_completion_sms_body(...)` — a dedicated helper that renders the SMS via **i18n locale catalog** OR a DB template with **single-brace Python `str.format(first_name=…, job_title=…, business_name=…, portal_link=…)`**.
- **Scope objects available:** tenant, job, customer, portal_link.
- **`{{...}}` tokens in body:** **0** (DB template is a single-brace `.format` spec).
- **Classification:** _hand-rolled single-brace templating_. The DB `marketing_templates` row for `code=job_completion_sms` is populated as `"Hi {first_name}, your {job_title} is complete! View: {portal_link}"` and the caller invokes `template.format(**canonical_kwargs)` — NOT a double-brace resolver pass.
- **Verdict: NO FIX NEEDED.** Converting the body shape to `{{CUSTOMER_FIRST_NAME}}` would break every tenant's existing `job_completion_sms` row and the i18n catalog's single-brace keys. Current behaviour is correct.

### 2. `routers/widget_chat.py` — escalation SMS (L450-466)

- **Body source:** Python f-string: `f"{tenant_row.get('name') or 'Widget'} chat lead ({cid[:8]}): {who} · {contact_str} — {body.text[:120]}"`.
- **Recipients:** `tenant.sms_escalation_recipients` — **tenant admins, not customers**.
- **`{{...}}` tokens in body:** **0**.
- **Classification:** _server-authored f-string, internal escalation alert_. No template path.
- **Verdict: NO FIX NEEDED.** Server composes the body deterministically; there is no operator-editable template; the recipient is an internal admin.

### 3. `routers/resend_webhooks.py` — SMS (L311-330)

- **Body source:** The only SMS call site is `POST /api/dev/sms-smoke-test` — a dev-only health-check endpoint accepting `{text}` from the admin caller.
- **Recipients:** admin-supplied `to` phone.
- **`{{...}}` tokens in body:** **0** (admin pastes raw text).
- **Classification:** _dev smoke-test endpoint, not a production customer flow_.
- **Verdict: NO FIX NEEDED.** Operator-pasted raw text; no template, no resolver pass applicable.

### 4. `routers/referral_rewards.py` — reward confirmation SMS (L266-307)

- **Body source:** Python f-string: `subject = f"Your referral of {friend} became a customer!"` + conditional `sms_body += f" ${reward_amount:.2f} credit applied."`.
- **Recipient:** referrer customer.
- **`{{...}}` tokens in body:** **0**.
- **Classification:** _server-authored f-string with in-process variable interpolation_. No template editing surface.
- **Verdict: NO FIX NEEDED.** The body is a hardcoded celebration SMS composed with Python f-string interpolation — no operator-editable template, no `{{...}}` tokens to resolve.

### 5. `routers/referrals.py` — invite-friend SMS (L215-222)

- **Body source:** Python f-string: `f"{user.get('name', 'A friend')} thinks you'll like {TENANT_NAME}. ..."`.
- **Recipient:** friend (prospect) invited by an existing customer.
- **`{{...}}` tokens in body:** **0**.
- **Classification:** _server-authored f-string, viral-loop invite_.
- **Verdict: NO FIX NEEDED.** Same shape as referral_rewards — f-string composition, no template.

### 6. `services/lana/reminders.py` — admin reminder SMS (L104-124)

- **Body source:** `tag + (row.get("text") or "")` where `tag = "[LANA reminder] "` and `row['text']` is the admin's own reminder note persisted at the time the reminder was created.
- **Recipient:** `row['phone']` + `audience="internal"` + `context=CommsContext.SYSTEM` → tenant admin.
- **`{{...}}` tokens in body:** **0** (admin's own free text, no templating pass).
- **Classification:** _admin-authored free-text reminder_. The `row['text']` is already the fully-composed message the admin typed when scheduling the reminder; there is no template-resolution step.
- **Verdict: NO FIX NEEDED.** Lana reminders are notes-to-self; passing them through a merge-tag resolver would be a no-op at best and risk eating stray single-brace characters at worst.

### 7. `routers/dunning.py` — stock + custom stage SMS (L270-290)

- **Body source — stock stages** (`stage_id ∈ {pre_due_3d, on_due_day, past_due_7d, past_due_14d, past_due_30d, past_due_60d}`): `t_email_body(locale, f"dunning.{stage_id}.sms", **ctx)` → the i18n catalog in `services/email_body_i18n.py` keyed by `dunning.<stage>.sms`, rendered via Python `.format(**ctx)` with single-brace keys like `{tenant_name}`, `{invoice_number}`, `{invoice_total}`, `{days_past_due}`, `{payment_link}`.
- **Body source — custom stages** (any other `stage.id`): `_render(stage.sms_template, ctx)` which calls `services.marketing.merge_tags.render_template(normalised, ctx, missing="empty")` at L274-276 **after normalising single-brace to double-brace** at L271-272. **Custom stages ALREADY render via the canonical resolver.**
- **`{{...}}` tokens in body — stock:** 0 (single-brace i18n catalog). **Custom:** operator-provided, may contain tokens — already resolved.
- **Classification:** _stock = single-brace i18n catalog (correct); custom = already renders via canonical resolver (correct)_.
- **Verdict: NO FIX NEEDED.** Both branches are correctly implemented.

---

## Why NN logged this TD

NN's grep heuristic was `renders=$(grep -cE "render_template|render_subject_and_body" "$f")`. Files with `renders=0` AND active SMS send calls were flagged as suspected render gaps.

The heuristic conflates **"doesn't call `render_template`"** with **"has merge-tag leak"**. These are different:

- **"Doesn't call `render_template`" AND "body contains `{{...}}` tokens"** → leak (NN's 3 fixed paths).
- **"Doesn't call `render_template`" AND "body contains ZERO `{{...}}` tokens"** → NOT a leak (PP's 7 paths).

PP's deeper audit (grep for `{{[A-Z_]+}}` tokens inside each file + manual inspection of the SMS body source) proved the 7 paths all fall into the second category.

---

## Alternative hypothesis checked

Could the 7 paths load a DB template (`marketing_templates` row) that contains `{{...}}` tokens the operator added?

- **`service_reports.py`** loads from `marketing_templates` keyed by `code=job_completion_sms`. The expected body shape is single-brace `{first_name}` because the caller invokes `template.format(**kwargs)`. A tenant adding `{{CUSTOMER_FIRST_NAME}}` to this row would see those tokens LEAK — but it would also crash the `.format(...)` call because `{{...}}` is Python's escape for literal `{`, so `.format(...)` would output literal `{CUSTOMER_FIRST_NAME}` (single-brace, unresolved). This is a different bug class — **template-shape mismatch**, not a resolver gap. Logging as `TD-pp-info-service-reports-sms-template-shape-mismatch` **(P3, informational)**.
- **The other 6 paths** do NOT load from DB templates at all — bodies are hardcoded in Python source. Zero exposure.

---

## Comparison with NN's 3 fixed paths

| | NN C2 paths (fixed) | PP's 7 deferred paths |
|---|---|---|
| Body source | Operator-authored free-text from compose modal | Server-authored f-string / i18n catalog / admin reminder note |
| Operator exposes `{{...}}` tokens? | ✅ yes | ❌ no |
| Resolver call needed? | ✅ yes (NN fixed) | ❌ no (nothing to resolve) |
| Recipient | Customer / lead | Customer / tenant admin / prospect / dev smoke |
| Template surface in product? | Yes (Mass Text modal, Send SMS modals) | No |

**NN's audit heuristic was sound for the paths it fixed; it over-flagged these 7 because none of them have an operator-authored template surface in the product.**

---

## Recommended resolution

**Close `TD-nn2-sms-render-remaining-callsites` as RESOLVED (no code changes needed).**

Log a replacement informational TD if operator wants to track the one real latent risk:
- **`TD-pp-info-service-reports-sms-template-shape-mismatch`** (P3, informational) — if a tenant edits the `marketing_templates` row for `code=job_completion_sms` to use `{{CUSTOMER_FIRST_NAME}}` double-brace tokens (expected by the operator-facing Marketing Templates UI), those tokens would leak as `{CUSTOMER_FIRST_NAME}` through the caller's `.format(...)` pass. Fix: convert `build_completion_sms_body` to call `render_template(body, ctx, missing="empty")` after the `.format(...)` pass. Scoped to `services/completion_sms_template.py` only.

---

## Non-negotiables confirmation

- **Zero code fixes applied in PP** — audit refuted the TD premise ✓
- **Zero files touched outside this memory artifact** ✓
- `/app/mobile/` untouched ✓
- No OTHER parked TDs touched (`TD-ll-template-email-wysiwyg-rewrite`, `TD-customers-bulk-update-remove-assigned-owner-id-from-allowlist`, `TD-mm1-info-customers-bulk-card-capture-adopt-canonical-resolver` all stay parked) ✓
- No new deps ✓
- Manual grep/pytest only, no testing agent ✓

---

## Operator decision requested

Three paths forward:

1. **Accept the audit → close `TD-nn2-sms-render-remaining-callsites` as RESOLVED (no code changes needed).** This memory artifact is the resolution record.
2. **Ship a defensive regression-lock pytest** that pins the current no-tags state of each of the 7 bodies (so a future refactor adding `{{...}}` tokens to one of these constants triggers red). ~60 LOC, single atomic BE commit.
3. **Scope PP to the one latent-risk path** (`service_reports.py` `build_completion_sms_body`) and ship a small fix that applies `render_template` AFTER the single-brace `.format(...)` pass so tenant-edited `{{...}}` tokens in the DB row resolve correctly. ~15 LOC + one pytest.
