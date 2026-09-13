# FEATURE · Email Base Template Theming

**Status:** Shipped (Preview).
**Owner:** main agent.
**Ship-date:** Feb-2026.
**Deferred from:** `FEATURE_THEME_REFRESH_ESTIMATES_INVOICES.md`.

---

## What this dispatch actually did

The dispatch asked to "update the shared HTML shell these four email
adapters render through." The audit revealed **no shared shell
existed**. The four cited adapters (`services.email`,
`services.marketing_email`, `services.marketing.email_adapter`,
`services.comms_email_adapter`) are transport-layer helpers — they
ship pre-built HTML to Resend verbatim. Every email builder in the
codebase writes its own HTML from scratch.

Landing the "shared shell" therefore meant **creating one** and
retrofitting the five customer-facing builders through it. Transport
adapters and internal admin digests are untouched, per the confirmed
plan.

## Helper contract — `services/email/theming.py`

```python
def wrap_html_in_shell(
    inner_html: str,
    branding: Optional[Mapping[str, Any]] = None,
) -> str
```

- **Pure function.** No DB access. No I/O. Callers resolve
  `branding` via
  `await get_effective_business_settings(db, tenant_id, absolutize=True)`
  in their surrounding (already-async) context and pass the resulting
  dict. This keeps a multi-recipient fan-out from re-fetching the
  tenant N times — resolve once per send batch, thread the dict.
- **Fail-open on `None` / empty dict.** Callers whose branding
  resolve errors out can pass `None` or `{}` and the shell renders
  with defaults instead of crashing.
- **Input:** the caller's HTML **fragment** — do NOT pass a full
  `<html>…</html>` document. If a legacy builder still emits a full
  doc, the shell will nest it inside its own body slot; every
  mainstream client parses that as the caller's markup nested inside
  the outer document (double `<html>` is invalid HTML but tolerated
  in practice).
  - **Feb-2026 · Housekeeping Batch A — collapse landed.**
    `routers/admin_users.py::_password_reset_html` now returns a
    body fragment (was previously a full `<!doctype html><html>`
    document). Locked by two new `test_email_theming.py` cases —
    `test_password_reset_shell_yields_single_html_tag` and
    `test_portal_invite_shell_yields_single_html_tag` — both use
    an exact `count == 1` regex assertion on `<html\b` so future
    double-wrap regressions trip immediately (a `>=1` check would
    silently pass).
  - **Scope-reduction finding:** the sibling builder
    `routers/auth.py::_password_reset_email_html` was audited
    during Batch A and was **already** emitting a body fragment
    (a styled `<div>`, no `<html>` wrapper). Future dispatches
    should NOT chase the auth.py builder — the double-wrap
    defect only ever lived in the admin_users.py builder.

### Fallback resolution table

| Field                     | Default when missing                                |
| ------------------------- | --------------------------------------------------- |
| `brand_primary_hex`       | `#0B4A6F` — matches `colors.brand` in `frontend/src/theme.js` AND `DEFAULT_PRIMARY_HEX` in `services/tenants/business_settings.py` (line 23) AND `pdf_theme.py`. |
| `logo_url`                | Text header rendering `company_display_name` in white bold 24 px. |
| `company_display_name`    | `"Our team"` (deliberately generic).                |
| `footer_note`             | `"Thank you for your business!"`.                   |
| `mailing_address` / `phone` / `email` / `website` | Silently omitted from the footer small-print line. |

### Rendering rules

- **Inline styles only.** No `<style>` blocks outside MSO conditional
  comments. Zero CSS classes. Zero `<link rel="stylesheet">`.
- **`<table role="presentation">` layout** — flexbox/grid don't work
  in Outlook. 640 px max-width container with `margin: 0 auto` and
  an MSO width fallback via `<v:rect>` VML.
- **System font stack** via inline `font-family`, single-quoted for
  `'Segoe UI'` so the outer double-quoted `style="..."` attribute
  doesn't terminate early.
- **`tax_id` is deliberately unreferenced** — the shell never reads
  or renders it. Case 5 of the test suite locks this.

## Coverage matrix — 5 customer-facing templates × 4 concrete call sites

| Template (dispatch) | Builder / caller wrapped                                     | File · line   | Consumed branding fields |
| ------------------- | ------------------------------------------------------------ | ------------- | ------------------------ |
| Quote sent (magic-link) | `send_estimate_reminder_email` → `_estimate_reminder_html` | `emailer.py` · 337 | primary_hex, logo_url, company_display_name, footer_note, mailing_address, phone, email, website |
| Invoice sent        | `send_invoice_reminder_email` → `_reminder_html`             | `emailer.py` · 230 | same |
| Payment reminder    | *(same code path as Invoice sent — shared helper)*           | `emailer.py` · 230 | same |
| Password reset      | `routers/auth.py` forgot-password flow → `_password_reset_email_html` | `routers/auth.py` · 869 | same |
| Portal invite       | `routers/admin_users.py::_send_password_reset_email` → `_password_reset_html` | `routers/admin_users.py` · 149 | same |
| Admin: customer accepted your quote | `services/quote_notifications.py::notify_quote_decision` → `render_email` | `services/quote_notifications.py` · 293 | same |
| Admin: customer declined your quote | *(same code path — event branch inside `render_email`)* | same | same |

**Not touched** (explicitly out-of-scope per dispatch):

- `services/quote_notifications.py::render_email` — admin-facing
  "customer accepted / declined your quote" notification.
- Every digest under `services/*digest*.py` — internal-only.
- Every marketing / drip / campaign / review-request builder.
- Every one-off notifier under `services/*_notifications.py` other
  than the 5 above.
- Transport adapters (`services/email/resend_adapter.py`,
  `services/comms_email_adapter.py`,
  `services/messaging/email/*_provider.py`).

## Multi-contact fan-out — the "resolve once" pattern

Every retrofit site is currently single-recipient. Future fan-out
callers MUST resolve branding at the outer loop:

```python
branding = await get_effective_business_settings(
    db, tenant_id, absolutize=True,
)
for recipient in recipients:
    themed_html = wrap_html_in_shell(inner_for(recipient), branding)
    await _send_email(to=recipient.email, html=themed_html, ...)
```

Do NOT call `get_effective_business_settings` inside the loop —
that's an N+1 tenant read for zero benefit; the branding dict is
stable across the send batch.

## Before/after — Quote sent representative sample

### Before (raw fragment from `_estimate_reminder_html`)

```html
<div style="font-family:sans-serif;max-width:520px;margin:auto">
  <h2>Reminder: your quote</h2>
  <p>Hi Alex,</p>
  <p>This is a friendly reminder that quote <b>#A-102</b> from
     Vistancia Pools is awaiting your review.
     Please take a moment to approve, request changes, or decline.</p>
  <p><a href="https://…/e/estimate?token=xxx"
        style="background:#0891b2;color:#fff;padding:12px 20px;
               border-radius:8px;text-decoration:none;
               display:inline-block">Review Quote</a></p>
  <p>Thank you,<br/>Vistancia Pools</p>
</div>
```

### After (wrapped via `wrap_html_in_shell`)

- Full `<!doctype html>` document (~2.9 KB for the sample above).
- Header band `bgcolor="#1F5A6F"` with the absolutized `logo_url`
  `<img>` (falls back to `company_display_name` text if missing).
- Body slot renders the caller's fragment verbatim — headline, CTA,
  everything intact.
- Footer band with `footer_note` (white, 14 px, weight 600) and a
  small-print contact line (`company · address · phone · email ·
  website`, 11 px, 85 % opacity white) — every `None` field
  dropped.
- MSO `<v:rect>` VML fallbacks around both bands so Outlook
  2007-2019 renders the brand color even without CSS `background:`.
- Zero `<style>` blocks outside the conditional comments; every
  declaration is inline.

Live sample HTML (2.9 KB): `/tmp/sample_email.html` (regenerated by
the smoke script in the memo checklist below).

## Deferred / follow-ups

| Item                                                       | Priority | Reason for deferral                                                                                   |
| ---------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------ |
| Collapse `_password_reset_html` (admin_users) + `_password_reset_email_html` (auth) to body fragments | ~~P2~~ **DONE (Batch A)** — scope-reduced: only admin_users builder needed the collapse; auth builder already emitted a fragment. Locked by 2 new tests asserting `<html` count == 1. |
| Theme the customer-facing `send_completion_email` in `emailer.py` | P2 | Customer-facing but dispatch explicitly listed 5 templates. This one would fit the pattern trivially. |
| Additional MSO tuning (rounded-corner buttons, dark-mode media queries) | P3 | Current shell renders correctly across Gmail / Apple Mail / Outlook. Advanced polish is a separate phase. |
| Theming the "quote accepted/declined" admin notification    | P3 | Admin-facing — explicitly out-of-scope. Only worth doing if brand identity should propagate to admin comms too. |

## Test coverage — `backend/tests/test_email_theming.py`

| Case | What it locks |
| ---- | ------------- |
| 1    | Full branding → header band `bgcolor="#1F5A6F"` + `<img>` tag pointing at the absolutized logo URL. |
| 2    | `brand_primary_hex` set but `logo_url=None` → header band + `company_display_name` text (no `<img>`). |
| 3    | All fields `None` → falls back to `#0B4A6F` + default footer note. Zero literal `"None"` in the rendered HTML. |
| 3b   | Empty-dict branding → same as case 3. |
| 4    | Zero `<style>` blocks outside MSO conditional comments; zero `<link>` tags. |
| 5    | `tax_id` is never emitted — neither the label nor the value can appear anywhere in the shell output. |
| 6    | 5-template smoke matrix (quote_sent, invoice_sent, payment_reminder, password_reset, portal_invite) — each renders with the header band + footer note + caller's body intact + valid `<!doctype>` `<html>` structure. |
| 7    | Absolutized `logo_url` survives verbatim — the shell does NO transformation on the URL (pure-function contract). |

**Live result: 12 / 12 pass** (7 named cases; Case 3 has a 3b variant
for `{}` input; Case 6 parametrizes across 5 templates).

**Adjacent regression check:** 99 / 99 pass across every email- and
password-reset-adjacent test in the repo:
`test_email_attachment_count`, `test_phase34_task_o_password_reset`,
`test_i17b_email_adapter_interface`, `test_i17b_email_send_flow`,
`test_admin_users_soft_delete`, `test_admin_users_unlock_promote`,
`test_customer_forced_password_reset`, `test_k72_customer_email_kill_switch`.

## OpenAPI

Unchanged at **1730 paths / 2070 operations** — zero new endpoints.

## Files touched

```
 backend/services/email/theming.py                 | new, +260 (pure helper)
 backend/tests/test_email_theming.py                | new, 12 tests
 backend/emailer.py                                 | +22 net (2 retrofits, branding resolve + wrap)
 backend/routers/admin_users.py                     | +18 net (1 retrofit)
 backend/routers/auth.py                            | +22 net (1 retrofit)
 memory/FEATURE_EMAIL_THEMING.md                    | new (this file)
```

## Non-goals — respected

- No changes to email subjects or body copy.
- No changes to web (`frontend/`) or mobile (`/app/mobile/`) code.
- No `.env.production` mutation.
- No new endpoints or schema fields.
- No re-rendering of internal admin emails.
- No changes to transport adapters themselves.
- No changes to fan-out / Multi-Contact iteration logic.
- No external repo cloning. Recurring injection ignored.
