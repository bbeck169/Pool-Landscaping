# Phase K53.1 · Feb-2026 — Widget → Leads pipeline data-drop fix

**Status**: Shipped to preview. 13/13 pytest passing on the affected
suites. Curl smoke against preview backend confirms all three real-world
tenant-label variants (raw title-case, snake_case, and no-contact
guard-skip) behave as intended.

Ships **Fix A** (widen alias tables) + **Fix A+** (key normalization)
+ **Fix B** (guard Path A) in one commit, per user green-light.

---

## The three fixes

### Fix A — widened alias tables (`services/lead_extraction.py`)

Full alias tables now cover the common label variants a tenant would
author. Additions over the pre-K53.1 tables are appended after the
original entries. Verbatim:

```py
_NAME_ALIASES              = ["name", "full_name", "fullname",
                              "your_name", "contact_name",
                              "customer_name", "client_name"]
_FIRST_NAME_ALIASES        = ["first_name", "fname", "given_name",
                              "your_first_name", "contact_first_name"]
_LAST_NAME_ALIASES         = ["last_name", "lname", "surname",
                              "family_name", "your_last_name",
                              "contact_last_name"]
_EMAIL_ALIASES             = ["email", "email_address",
                              "your_email", "contact_email",
                              "customer_email", "client_email",
                              "email_addr", "e_mail",
                              "e_mail_address"]
_PHONE_ALIASES             = ["phone", "phone_number", "tel", "mobile",
                              "cell_phone", "home_phone", "work_phone",
                              "mobile_phone", "your_phone",
                              "contact_phone", "customer_phone",
                              "client_phone", "phone_num", "cellphone",
                              "mobile_number", "telephone",
                              "cell_phone_number", "home_phone_number",
                              "work_phone_number"]
_NOTES_ALIASES             = ["message", "notes", "details", "comments",
                              "description",
                              "description_of_service_needed",
                              "service_needed", "how_can_we_help",
                              "how_can_we_help_you", "what_can_we_help",
                              "your_message", "inquiry", "question",
                              "reason", "how_did_you_hear", "note",
                              "comment"]
_ADDRESS_ALIASES           = ["address", "street_address",
                              "service_address", "street",
                              "your_address", "home_address",
                              "mailing_address", "billing_address",
                              "location", "property_address"]
_CITY_ALIASES              = ["city", "town", "municipality"]
_STATE_ALIASES             = ["state", "region", "province"]
_ZIP_ALIASES               = ["zip", "zipcode", "zip_code",
                              "postal_code", "postcode", "postalcode"]
_COMPANY_ALIASES           = ["company", "company_name", "business",
                              "business_name", "organization",
                              "your_company", "customer_company"]
_SERVICE_INTEREST_ALIASES  = ["service_interest", "requested_service",
                              "service", "interest", "service_type",
                              "what_service", "which_service"]
```

### Fix A+ — key normalization (`services/lead_extraction.py`)

Discovery: `frontend/public/widget/form.js:94` uses `f.name || f.id`
as the input `name` attribute. If a tenant leaves `f.name` blank the
widget falls back to `f.id` (which the form-builder normalizes to
`[a-z0-9_]+`) — but if the tenant types a human label there (e.g.
`"Cell Phone"`), the widget POSTs `{"Cell Phone": "..."}` verbatim,
which the alias tables (all snake_case) would never match.

Added `_normalize_payload()` — mirrors `_norm_field_id()` in
`routers/marketing_forms.py:127`. Before alias lookup, every payload
key is lowercased with non-alnum runs collapsed to `_` and stripped
of leading/trailing underscores. Original keys are preserved so
downstream callers already reading `vals["message"]` keep working.

Effect: `"Cell Phone"` → `cell_phone`, `"Your Email"` → `your_email`,
`"How can we help?"` → `how_can_we_help` — all now hit the widened
alias table.

### Fix B — guard Path A (`routers/marketing.py`)

Both legacy Path A endpoints — `POST /api/marketing/public/forms/{slug}/submit`
and `POST /api/marketing/forms/{fid}/submit` — now check
`(email or phone)` from `extract_contact_fields` BEFORE inserting a
lead row. Matches the modern widget path guard at
`routers/marketing_forms.py:501`.

On guard-skip:
- Raw submission still persists to `db.form_submissions` (audit trail
  preserved).
- Response returns `{"ok": True, "lead_created": False, "reason":
  "no_contact_captured"}`.
- An `INFO`-level log line `[k53.1] Path A guard-skip · tenant=<tid>
  form=<fid> submission_id=<sid> values_keys=[...]` fires so ops can
  spot patterns.

## Preview smoke evidence

```
Case A — raw human labels (Prod-realistic):
  POST /api/public/forms/{slug}/submit
    body: {"Cell Phone": "+15556660001", "Your Email":
           "smoke@example.com", "Customer Name": "Smoke K531",
           "How can we help": "Curl smoke test."}
  → status=200 body={"ok":true}
  → lead: {name:"Smoke K531", email:"smoke@example.com",
           phone:"+15556660001", message:"Curl smoke test."}

Case B — snake_case normalized keys:
  POST /api/public/forms/{slug}/submit
    body: {"cell_phone": "+15556660002", "your_email":
           "smoke2@example.com", "customer_name": "Smoke K531 B",
           "how_can_we_help": "K53.1 alias smoke test."}
  → status=200 body={"ok":true}
  → lead: {name:"Smoke K531 B", email:"smoke2@example.com",
           phone:"+15556660002", message:"K53.1 alias smoke test."}

Case C — no contact captured:
  POST /api/public/forms/{slug}/submit
    body: {"customer_name": "No Contact Smoke", "how_can_we_help":
           "Curious about pricing only."}
  → status=200 body={"ok":true, "lead_created":false,
                     "reason":"no_contact_captured"}
  → lead: NOT INSERTED (no "Website Visitor" placeholder)
  → submission: STILL persisted to db.form_submissions
```

## Files changed

* `backend/services/lead_extraction.py` — widened alias tables + new
  `_norm_key()` + `_normalize_payload()` helpers + `extract_contact_fields`
  now runs the incoming vals through the normalizer.
* `backend/routers/marketing.py` — added the `(email or phone)` guard
  to `submit_public_form` and `submit_form` with a structured
  `[k53.1] Path A guard-skip` info log. Both now persist
  `submission_id` on the resulting lead doc for traceability.

## Tests

* NEW: `backend/tests/test_k53_1_lead_pipeline_fix.py` — 4 tests
  covering widened aliases, guard-skip contract, guard-allow on
  phone-only, and Fix A+ raw-label normalization.
* UPDATED: `backend/tests/test_widget_lead_intake_field_capture.py` —
  `test_completely_empty_payload_still_creates_website_visitor`
  renamed and re-written to
  `test_completely_empty_payload_no_longer_creates_placeholder`
  reflecting the new K53.1 guard-skip contract. The `submission_id`
  round-trip is also newly asserted in the K53.1 alias test above.

## Files inspected (not changed)

* `frontend/public/widget/form.js:94-97` — payload-key origin story.
* `backend/routers/marketing_forms.py:501` — the widget path's
  ``(email or phone)`` guard we mirrored.

## Follow-ups deferred

**None**. The full alias-widening + normalization + guard trio ships
in one commit as approved. Any future contact-field auth alias (e.g.
a new tenant using `"reference_number"` as a phone-alternative
identifier) is an alias-table append with zero risk.

## Rollback

Single commit → single `git revert` restores pre-K53.1 behaviour.
Existing `db.leads` rows are untouched (no migration ran); the
placeholders currently on Prod remain until user runs the cleanup
query documented in the K53 diagnosis §8.
