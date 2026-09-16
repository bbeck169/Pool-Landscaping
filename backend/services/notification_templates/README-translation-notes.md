# Phase D5 · notification body translation notes

**Locale scope**: `en` (authoritative), `es`, `fr`.
**Tone**: neutral formal — Spanish uses `usted`, French uses `vous`. Never `tú` or `tu`.
**Backend-only**: this file lives on the backend side so `/app/frontend/` stays untouched during D5. Web-UI localisation notes still live under `frontend/src/i18n/locales/en/README-translation-notes.md` (updated in D3/D4).

## Merge variables — DO NOT LOCALISE

Every template uses Python `str.format`-compatible `{placeholder}` tokens. These tokens are the CONTRACT between the code (backend send site) and the template (translator). Translators MUST preserve every `{placeholder}` verbatim across all three locales — do NOT translate the token names.

Examples that are safe to translate:
* `Please add a card…` → `Agregue una tarjeta…` / `Ajoutez une carte…` ✅
* `Hi {customer_first_name},` → `Hola {customer_first_name}:` / `Bonjour {customer_first_name},` ✅ (the token stays literal)

Examples that would BREAK the send:
* Renaming `{customer_first_name}` → `{nombre_del_cliente}` ❌
* Deleting a token because the sentence flows better without it ❌
* Adding a NEW token that the backend send site doesn't supply ❌

The `test_notification_templates_placeholder_parity.py` test enforces this contract automatically — a drift will fail CI.

## Punctuation preservation

* Preserve `—` (em dash) and `…` (ellipsis) — matches D3/D4 rule.
* Preserve trailing colons on French salutation lines (`Bonjour {name},` — French uses comma after salutation, not colon).
* Spanish salutations use colon (`Hola {name}:`).

## Spanish gender

Gender-neutral phrasing where it reads naturally (`Le damos la bienvenida`, `Su cuenta`). Masculine-default is acceptable when neutrality forces stilted phrasing — flag those below.

Currently-flagged strings using masculine default (v1):
* None in the initial D5 template set. All strings are addressed to a generic customer / account, not to a specific person by first name in a gendered adjective.

## Templates shipped in D5 (Feb-2026)

| template_key | Kind | Audience | Locales | Notes |
|---|---|---|---|---|
| `completion_sms` | SMS | Customer | en/es/fr | Fires when a tech submits a service report. |
| `visit_summary_email` | Email | Customer | en/es/fr | Static shell — the dynamic content sections (chemistry readings table, photos grid) are still composed in Python and are currently English-only. Follow-up work (D6) will migrate the section titles. |
| `add_card_link_email` | Email | Customer | en/es/fr | Add-card magic-link email. **The "expires in 7 days" wording is legal-risk — flagged in `README-legal-review.md`.** |
| `add_card_link_sms` | SMS | Customer | en/es/fr | Add-card magic-link SMS. Same 7-day expiry flag. |

## Templates flagged as admin-only (always English)

The following notification categories are ALWAYS sent in English regardless of the recipient's or tenant's locale. They fire to admin/staff/super-admin recipients only:

* `lead_admin_notification_email` — inbound-lead admin fanout
* `service_request_email` / `service_request_sms` — ops-line pings when a customer taps "Request Service"
* `stripe_sync_ambiguous_matches` — weekly digest to super-admin
* Password reset admin escalation (K30 flow)

These are covered by the `resolve_recipient_locale(audience="admin")` return value being hard-locked to `"en"`. No template files under `es/` or `fr/` exist for these keys.

## Not-yet-migrated (kept English at the send site)

The following send sites remain hard-coded in English pending a future D-phase. When the recipient's `customer.locale` is set, the send site emits a WARNING log so ops can identify translation gaps in production:

* Visit-summary dynamic sections (chemistry rows, photos grid, algae observation notes)
* Invoice-sent notification (currently no dedicated template — piggy-backed on `marketing_templates`)
* Weekly digest emails (admin-only, so always English anyway)
* Marketing sequences (tenant-editable through the marketing UI — translations are the tenant's responsibility, not core-product)

## Feedback loop

Send translation corrections against this file via PR. Do NOT edit the `.html` / `.txt` template files directly without also updating `README-legal-review.md` if the affected sentence is legal-risk.
