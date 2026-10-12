# Step A — Full field inventory

Feb-2026 P0 · Stage 3 Step A deliverable (BEFORE any code changes
in Step B+). Answers the critical question: which fields on which
collections carry PII and are being missed by the current
scrubber?

## 1 · `customers` collection — 724 live docs, 125 distinct field names

| Field | Example | PII class | Scrub status today | Leaky rows on preview |
| --- | --- | --- | --- | --- |
| **Primary PII (currently scrubbed by synthesizer)** |
| `name`, `first_name`, `last_name`, `display_name` | "Preview Customer0300" | name | OK | 0 |
| `email` | "preview-customer0300@preview.local" | email | OK | 0 |
| `phone`, `phone_mobile`, `mobile` | "555-010300" | phone | OK | 0 |
| `address`, `address_line_1`, `address_line_2`, `street`, `street_address` | "300 Preview St" | address | OK | 0 |
| `city`, `state`, `zip`, `zip_code`, `postal_code`, `country` | Testville / AZ / 85000 / US | address | OK | 0 |
| `company`, `company_name` | — | address | OK | 0 |
| **MISSED by scrubber (the actual leak)** |
| `search_haystack` | "terry hernandez terry hernandez terryhernandez402@yahoo.com +14802282993 20449 north 93rd avenue, peoria, az, 85382" | **denormalized name+email+phone+address** | **BROKEN — not touched** | **191** |
| `emails` | `[{"address":"terryhernandez402@yahoo.com","label":"Primary","is_primary":true,"marketing_ok":true,"notifications_enabled":true}]` | **nested PII objects** | **BROKEN — not touched (projection missed it)** | **77** |
| `mobiles` | `[{"number_e164":"+14802282993","label":"Primary","is_primary":true,"sms_ok":true,"notifications_enabled":true}]` | **nested PII objects** | **BROKEN** | **41** |
| `phones` | `[{"type":"home","number":"+14802282993","e164":"+14802282993","raw":null}]` | **nested PII objects** | **BROKEN** | **31** |
| `phone_raw` | "4802282993" | raw-E164 phone | **BROKEN** | **2** |
| `mobile_raw` | "4802282993" | raw-E164 phone | **BROKEN** | **2** |
| `address_line1` *(no underscore between `line` and `1`)* | "20449 North 93rd Avenue" | address | **BROKEN — scrubber only touches `address_line_1`** | **3** |
| `service_address` | `{"street":"20449 North 93rd Avenue","city":"Peoria","state":"AZ","postal_code":"85382"}` | **nested PII object** | **BROKEN** | **2** |
| `billing_address` | "" (string on some docs, object on others) | address | **BROKEN — not touched** | 0 observed, risk pending |
| `bill_to_address` | — | address | **BROKEN — not touched** | 0 observed |
| `secondary_addresses` | array of address objects | address | **BROKEN — not touched** | 0 observed |
| `home_phone` | — | phone | **BROKEN — not touched** | 0 observed |
| `master_billing_contact_email`, `master_billing_contact_phone` | — | email + phone | **BROKEN — not touched** | 0 observed |
| `alert_email`, `alert_phone` | "" | email + phone | **BROKEN — not touched** | 0 observed |
| `customer_since_raw` | "1/23/2026" | low-sensitivity date | not PII per se — pass-through | — |
| `latitude`, `longitude` | 33.6704611, -112.2583844 | geo-PII (real address resolver) | **BROKEN — not nulled** | — |
| `service_lat`, `service_lng` | 33.6704611, -112.2583844 | geo-PII | **BROKEN — not nulled** | — |
| `service_location` | `{"type":"Point","coordinates":[-112.2583844,33.6704611]}` | geo-PII GeoJSON | **BROKEN — not nulled** | — |
| `geocode_address_hash` | — | derived from real address | **BROKEN — not nulled** | — |
| `address_city`, `address_state`, `address_zip` | legacy denorm (4 docs) | address | **BROKEN — not touched** | 0 observed |
| `service_city`, `service_state`, `service_zip` | legacy denorm (1 doc) | address | **BROKEN — not touched** | 0 observed |
| `billing_city`, `billing_state`, `billing_zip` | legacy denorm (1 doc) | address | **BROKEN — not touched** | 0 observed |
| `gate_code` | "4321" | admin ops context (NOT PII per Refinement 1) | pass-through (correct) | — |
| `notes`, `service_notes`, `vip_note`, `dog_notes` | free-text | notes (redaction) | partially — only `notes` was wired, others missed | — |
| `fax` | — | phone | **BROKEN — not touched** | 0 observed |
| **Non-PII / FK / metadata (pass-through — correct)** |
| `id`, `tenant_id`, `_id`, `created_at`, `updated_at`, `deleted_at`, `created_by`, `deleted_by_user_id`, `merged_by`, `merged_into`, `merged_at`, `muted_by`, `automations_muted_by`, `is_active`, `is_vip`, `vip_since`, `waitlisted`, `is_muted`, `muted_at`, `has_login`, `last_portal_login_at`, `last_portal_login_ip`, `portal_first_login_at`, `portal_walkthrough_completed_at`, `tos_acknowledgements`, `balance_due`, `credit_balance_cents`, `overdue_count`, `past_due`, `balance_recomputed_at`, `pool_gallons`, `category_ids`, `assigned_tech_ids`, `service_days`, `tags`, `avatar`, `source`, `created_via`, `imported_at`, `import_source`, `import_batch_id`, `restored_at`, `dog_on_property`, `channel_opt_in`, `category_opt_in`, `preferences_updated_at`, `tos_status`, `status`, `portal_enabled`, `portal_user_id`, `portal_password_set_at`, `default_payment_method_id`, `autobilling_enabled`, `autobilling_enabled_at`, `autobilling_disabled_at`, `master_billing_mode`, `phase51_prior_readings_seeded`, `service_type`, `category_updated_at`, `geocode_precision`, `geocode_source`, `geocoded_at`, `timeline` (array of event objects — audit trail) | — | metadata | pass-through | — |
| **Stripe tokens — special handling needed** |
| `stripe_customer_id` | "cus_..." | **REJECT if `cus_live_*`, pass if `cus_test_*`, null if neither** | current REJECT handles live; test tokens pass; on scrub, should null out (no sandbox cus_test_* on preview) | — |
| `stripe_default_payment_method_id` | "pm_..." | same | same | — |
| `stripe_card_brand`, `stripe_card_last4`, `stripe_sync_status`, `stripe_synced_at` | — | derived from token | null these on scrub (consistency) | — |

**7 leak-prone fields the current scrubber MISSES**, accounting for all 237+709 reported leaky rows.

## 2 · `leads` collection — 351 docs

Same shape as `customers` for the ingress-time fields. Additional fields:

| Field | PII class | Scrub status |
| --- | --- | --- |
| `name`, `email`, `phone`, `address`, `first_name`, `last_name`, `city`, `state`, `zip` | matches customer | OK |
| `service_address` (nested obj) | address | **BROKEN — not touched** |
| `latitude`, `longitude`, `lat`, `lng` | geo-PII | **BROKEN — not nulled** |
| `search_haystack` | present on some docs via `/api/leads` write path | **BROKEN** |
| `message`, `notes` | free-text | partially redacted — `notes` only |
| `created_ip` | PII IP address | **BROKEN** |
| `meta` | arbitrary dict (may embed PII) | **BROKEN** |
| `timeline` | event array — snapshot of PII at time of events | **BROKEN** |
| `source`, `submission_id`, `referred_by_customer_id`, `converted_customer_id`, `loss_reason`, `est_value`, `service_interest`, `status`, `status_updated_at`, `status_updated_by_user_id`, `archived_at`, `open_task_ids`, `tenant_id`, `created_at`, `updated_at`, `company_name` | metadata | pass-through (company_name synthesized by lead synth) |

## 3 · `users` (role=customer) — 1 scrubbed, 16 pre-existed on preview

| Field | PII class | Scrub status |
| --- | --- | --- |
| `name`, `email` | name + email | OK |
| `password_hash`, `password_customer_set_at`, `password_updated_at`, `temp_password_issued_at` | credential | pass-through (bcrypt hashes are safe; the admin-password-reset flow regenerates them) |
| `first_access_ip` | PII IP address | **BROKEN — not nulled** |
| `profile_photo_url`, `avatar` | PII (admin-uploaded photo URL) | **BROKEN — not nulled** |
| `recent_colors`, `department`, `hourly_rate_cents`, `active`, `role`, `customer_id`, `tenant_id`, `technician_id`, `failed_login_attempts`, `lockout_until`, `must_change_password_on_next_login`, `has_ever_logged_in`, `has_seen_customer_tour`, `customer_tour_seen_at`, `portal_tour_completed_v2*`, `tos_accepted_at`, `tos_version_accepted`, `tenant_memberships`, `auto_clockin_enabled`, `first_access_at` | metadata | pass-through |

## 4 · Denormalized snapshots on business collections (already covered)

The scrubber's Pass 2 covers `quotes.customer_name/email/address`,
`invoices.bill_to_name/email/address`, `jobs.customer_name`,
`estimates.bill_to_*`, `contracts.signer_*`, `signed_contracts.signer_*`,
`csat_responses.respondent_name/email`, `calendar_events.customer_name`.

**Additional snapshot fields to add** (missed in Stage 2):

| Collection | Field | Why |
| --- | --- | --- |
| `quotes` | `customer_phone`, `bill_to_phone`, `search_haystack` | denorm phone on quote line snapshots |
| `invoices` | `customer_name`, `customer_email`, `customer_phone`, `search_haystack` | same |
| `jobs` | `customer_email`, `customer_phone`, `customer_address`, `search_haystack` | same |
| `estimates` | `customer_name`, `customer_phone`, `customer_email`, `search_haystack` | same |
| `recurring_job_templates` | `customer_name`, `customer_email`, `customer_phone` | observed 17 rows on preview (healthcheck noted) |
| `service_reports` | `customer_name`, `customer_email`, `customer_phone` | derived snapshots |
| `payments` | `customer_email`, `customer_name` on receipt copies | — |
| `tasks` | `customer_name`, `customer_email` on task metadata | — |
| `appointments`, `portal_appointments` | `customer_name`, `customer_email`, `customer_phone` | — |

(Full list enumerated in the Step C commit's scrubber patch.)

## 5 · DECORATOR synthesizer — fields missed

Current `synthesize_customer_fields()` sets 24 keys. Fields the
synthesizer MUST also set so new-POST ingress populates them with
synthetic values (not leaves them as whatever the request body
carried OR drops them):

* `search_haystack` — rebuild from the synthesized name+email+phone+address.
* `phone_raw`, `mobile_raw` — set to the E.164 synthetic (`+15550100300`).
* `emails[]` as a list of OBJECTS: `[{"address": synth_email, "label": "Primary", "is_primary": true, "marketing_ok": true, "notifications_enabled": true}]`. **The current string-shape output breaks the Pydantic schema and causes the 500 on `page_size>5`.**
* `mobiles[]` as object: `[{"number_e164": synth_phone_e164, "label": "Primary", "is_primary": true, "sms_ok": true, "notifications_enabled": true}]`. Same schema issue.
* `phones[]` as object array: `[{"type":"home","number":synth_e164,"e164":synth_e164,"raw":null}, {"type":"mobile","number":synth_mobile_e164,"e164":synth_mobile_e164,"raw":null}]`.
* `address_line1` (no-underscore variant) — same as `address_line_1`.
* `service_address` — nested object `{"street":..., "city":"Testville", "state":"AZ", "postal_code":"85000"}`.
* `secondary_addresses` — empty list on preview.
* `billing_address` — "" or object (observed both shapes) — synthesize to `"{bucket} Preview St"` or `{...}` matching whichever the source carried.
* `bill_to_address` — same.
* `home_phone`, `alert_email`, `alert_phone`, `master_billing_contact_email`, `master_billing_contact_phone`, `fax` — synthesize to synthetic.
* `latitude`, `longitude`, `service_lat`, `service_lng`, `service_location`, `geocode_address_hash` — set to `null`.
* `custom_fields` — PRESERVE the dict structure, but recursively redact string values via `redact_free_text`. Non-PII values (`"gate_code": "4321"`) survive; PII values (`"secret_email": "real@foo.com"`) → `[redacted-email]`.
* `stripe_customer_id`, `stripe_default_payment_method_id` — null on scrub if value starts with `cus_live_` / `pm_live_` (REJECT branch already handles ingress; scrub nulls legacy rows).
* `stripe_card_brand`, `stripe_card_last4`, `stripe_sync_status`, `stripe_synced_at` — null on scrub.

## 6 · Healthcheck audit — field scope must expand

Current audit only reads `customers.name` regex-matching `^Preview
Customer\d{4}`. That misses every leaky field from §1. The audit
in Step E will:

* Walk every PII-classified field from §1 (26 fields).
* For each, scan N docs sampling the field; count rows where the
  value, serialized to JSON, matches `/^(?!Preview |555-|preview-|Testville|AZ|85000|85382|null|$|).+/` AND contains an `@` or digit-run of 10+ or alpha-space pattern (presence-of-PII probe).
* Report `pii_shape_audit.status = RED` if ANY leak, with the top-10 (customer_id, field, offending_value_hint) rows for admin triage.

## 7 · 20 unregistered PII-shaped routes (Step F input)

From the live healthcheck AMBER response:

```
POST /api/admin/leads/backfill-label-resolution
POST /api/imports/pdf-invoice/{batch_id}/rollback
POST /api/lead-sense/track
… +17 more
```

Full list to be enumerated + classified in the Step F commit.

────────────────────────────────────────────────────────────────────
## Next actions

Awaiting approval of this inventory before coding Step B (schema
shape fix) + Step C (scrubber expansion) + Step D (decorator field-
drop fix) + Step E (healthcheck audit expansion) + Step F (register
remaining routes) + Step G (re-run scrub + verify) + Step H (full
regression).

**Zero code changes made in this step.** This file is the sole
deliverable for Step A. The 2 scrub runs already landed in commits
2/5 + 4/5 are being superseded — a second comprehensive run will
be invoked in Step G.
