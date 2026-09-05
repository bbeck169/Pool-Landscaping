# Phase K53 · Feb-2026 — Widget → Leads pipeline diagnosis

**Status**: Diagnosis only.  No code changes.  Awaiting user green
light on fix scope.

**Environment note**: I investigated on **preview** (I don't have
Prod access).  Preview and Prod share the same code path unless a
static asset (widget JS) or a DB state diverges — both possibilities
are called out below.

---

## 1 · Which endpoint does the widget hit?

There are **two active families** of form-submission endpoints, with
**different behaviour** for the "no contact captured" case:

### Path A · LEGACY  · `marketing.py`
Two routes in this family:
* `POST /api/marketing/public/forms/{slug}/submit` (line 139)
* `POST /api/marketing/forms/{fid}/submit` (line 188)

Both call `lead_row_from_form_values()` unconditionally
(`marketing.py:153, 200`), which in turn falls back to
`WEBSITE_VISITOR_FALLBACK = "Website Visitor"` when
`extract_contact_fields()` returns `name=None`
(`services/lead_extraction.py:144`).

**→ These endpoints CAN and DO create empty "Website Visitor"
placeholder rows.**

### Path B · MODERN (K52-era) · `marketing_forms.py`
* `POST /api/widget/form/{fid}/submit` (line 425)

This is what the shipped widget script (`frontend/public/widget/form.js`
line 299) actually hits.  Guarded:
```py
if creates in ("lead", "both") and (email or phone):
    lead_id = await _upsert_lead_from_submission(...)
```
(marketing_forms.py:501)

**→ This endpoint CANNOT create empty placeholders.  If extraction
finds no email AND no phone, the submission is stored in
`db.form_submissions` but no lead row is created.**  (Silent drop —
also a bug, discussed below.)

### Which one does the currently-shipped embed script use?
The embed snippet the admin sees on `MarketingFormsPage.jsx:264` is:
```html
<script async defer
  src="{origin}/widget/form.js"
  data-widget-key="{publicKey}"
  data-form-id="{saved.id}"></script>
```
`widget/form.js` POSTs to `/api/widget/form/{FORM_ID}/submit` — i.e.
**Path B**, the guarded one.  Confirmed by inspecting
`frontend/public/widget/form.js` line 299 and the minified variant
`form.min.js` (both live in the repo, both hit Path B).

---

## 2 · Placeholder doc raw contents (from preview DB)

I queried the preview DB directly:

```
Total "Website Visitor" leads on preview: 0
form_submissions on preview: 3
widget_chat_conversations on preview: 16
```

**Preview has zero placeholder leads.**  This is significant — it
means the current preview code path is NOT producing new placeholders.
Whatever is on Prod is either:
* Legacy data from pre-P17 (before the extraction-fallback fix), or
* Data created via **Path A** (still active — not deprecated), or
* Data on a different tenant scope that isn't reachable from preview.

I can't dump the Prod doc from here.  User: if you can run this
against the Prod DB and paste the redacted output, that pins the
hypothesis down:
```
db.leads.findOne({name: "Website Visitor"},
                 {tenant_id: 1, source: 1, status: 1,
                  created_at: 1, page_url: 1, submission_id: 1,
                  message: 1, notes: 1, email: 1, phone: 1});
```
The `source`, `page_url`, and `submission_id` fields will tell us
which of the two paths (or a third we haven't found) created it.

---

## 3 · Widget-side POST payload shape

**`frontend/public/widget/form.js` — the `<form>.onsubmit` handler**
(lines ~230-280 of the un-minified variant, confirmed identical in
`form.min.js`):

```js
Array.prototype.forEach.call(n.elements, function(e) {
    if (e.name) {
        // ... type-branch (checkbox/radio/select/file/etc.)
        u[e.name] = e.value;
    }
});
var payload = {
    answers: u,             // { <FormField.name>: <value>, ... }
    page_url: location.href
};
if (turnstile) payload.turnstile_token = ...;
fetch(BACKEND + "/api/widget/form/" + FORM_ID + "/submit",
      { method: "POST",
        headers: {"Content-Type": "application/json",
                  "X-Widget-Key": WIDGET_KEY},
        body: JSON.stringify(payload) });
```

**Each `e.name` is the tenant-authored `FormField.name`.**  Per
`marketing_forms.py :: FormField` schema (line 133):
```py
class FormField(BaseModel):
    id: str          # normalised to lowercase alnum+underscore
    name: str        # free text, 1..60 chars — TENANT-AUTHORED
    label: Optional[str] = None
    type: str
    ...
```

`_norm_field_id()` at `marketing_forms.py:127` lowercases the input
and strips to `[a-z0-9_]+`, so a label like "Your Name" becomes an
id like `your_name`.  But **`name` is free text** — the tenant can
type whatever they want.

Where the widget uses `e.name` for the payload key, this becomes a
tenant-authored string that flows straight into the alias-lookup
below.

---

## 4 · Server-side schema / validator

**`services/lead_extraction.py`** — the shared extractor.  The alias
tables at lines 20-56 (KEY finding, this is what matches or fails):

```py
_NAME_ALIASES         = ("name", "full_name", "fullname")
_FIRST_NAME_ALIASES   = ("first_name", "firstname", "first", "given_name")
_LAST_NAME_ALIASES    = ("last_name", "lastname", "last",
                         "family_name", "surname")
_EMAIL_ALIASES        = ("email", "email_address", "e_mail")
_PHONE_ALIASES        = ("phone", "phone_number", "mobile", "cell",
                         "tel")
_ADDRESS_ALIASES      = ("address", "street", "street_address",
                         "service_address")
_CITY_ALIASES         = ("city", "town", "municipality")
_STATE_ALIASES        = ("state", "region", "province")
_ZIP_ALIASES          = ("zip", "zipcode", "postal_code",
                         "postalcode")
_COMPANY_ALIASES      = ("company", "company_name", "organization")
_SERVICE_INTEREST_ALIASES = ("service_interest", "service",
                             "interest", "service_type")
_MESSAGE_ALIASES      = ("message", "notes", "note", "details",
                         "comments", "comment", "question")
```

The lookup is **exact key match, case-insensitive via
`k.lower().strip()`**.  Nothing is fuzzy-matched, nothing is
normalized further, no label-scan.

---

## 5 · Root cause hypothesis (ranked by likelihood)

### H1 · Legacy data · MOST LIKELY
The user's placeholder is pre-existing data from a pre-P17 era when
Path B (or an earlier variant) DID create placeholders.  The P19
migration (`backend/migrations/task_p19_backfill_empty_website_visitor_leads.py`)
was written specifically to backfill this class of lead, which
confirms it was a historical problem.  The migration must not have
been run against Prod, or must have been run before the specific
placeholder was created.

**Verification**: check `created_at` on the placeholder — if it
predates the P17/P19 phase deploys, this is confirmed.  The user's
screenshot showed date "2026-08-31" — that's future-dated relative
to today (Feb 2026), which suggests either a display bug OR a bad
clock-set on submission.  Need Prod DB dump to verify.

### H2 · Widget hits Path A · SECOND MOST LIKELY
The user (or a developer they hired) may have hand-coded a `<form
action="/api/marketing/public/forms/{slug}/submit">` on their public
website (e.g. copied from an older doc, or wired a Wix / Wordpress
form to that URL directly).  Path A creates placeholder leads
whenever extraction fails, which happens when the form's field
`name` attributes don't match any of the aliases in §4.

**Verification**: check `source` and `submission_id` on the Prod
placeholder.  Path A sets `source = form.get("name") or "Web Form"`.
Path B sets `source = f"form:{form.get('slug') or form.get('id')}"`.
Different source string tells us which route.

### H3 · Tenant's form field labels don't match the alias table · LIKELY CONTRIBUTING
Even on Path B (where the guard silently drops leads), a tenant's
form might have fields labeled like:
* "Your Name" → `your_name` — NOT in alias table (missing).
* "Full Name" → `full_name` — ✓ matches.
* "Contact Email" → `contact_email` — NOT in alias table.
* "Cell Phone" → `cell_phone` — NOT in alias table.  ("cell" alone
  matches, but "cell_phone" does not.)
* "Phone Number" → `phone_number` — ✓ matches.
* "Home Address" → `home_address` — NOT in alias table.
* "How can we help?" → `how_can_we_help` — NOT in alias table (should
  land in `message`).

**This is a real gap.**  If a tenant uses common labels like "Cell
Phone" or "Your Email", extraction fails and Path B silently
drops the lead.  This is NOT what created the visible placeholder
(Path B doesn't create them), but it IS why users would see
"missing leads" on Prod — leads that never got created at all.

**Verification**: check `db.form_submissions.find({tenant_id: <tid>})`
on Prod — if there are submissions with no matching lead,
extraction is the culprit.

### H4 · Cross-tenant slug collision · REAL BUG BUT UNRELATED
`marketing.py:132` has a fallback lookup:
```py
form = await db.forms.find_one(
    {"$or": [{"slug": slug}, {"id": slug}]})   # no tenant_id filter
```
If two tenants author a form with the same slug (e.g. "contact"),
whoever's row Mongo returns first wins — and the lead lands on
that tenant.  This is a real bug (P2 severity) but doesn't explain
the visible "Website Visitor" placeholder.

### H5 · Stale widget served on Prod
Unlikely.  The widget JS is a static asset served from
`frontend/public/widget/form.js`.  If Prod is behind on frontend
deploys, they'd serve an older widget, but the current widget's
POST target hasn't changed in a while (`/api/widget/form/{fid}/submit`).
I'd need to `curl app.plofv.com/widget/form.js` and diff against
HEAD to confirm — I can't reach Prod.

**Verification the user can do:**
```
curl -s https://app.plofv.com/widget/form.js | grep -c "widget/form/"
```
Should match `grep -c "widget/form/" frontend/public/widget/form.js`
in HEAD.

### H6 · Tenant misroute / anti-spam nuke
Ruled out.  No `sanitize_lead` / `strip_pii` / `honeypot` middleware
found.  Only sanitization is `_verify_turnstile` which either passes
through unchanged or 400s.

---

## 6 · Proposed fix scope (four options — user picks)

### Fix A · Widen the alias table (defensive, low risk)
Extend `services/lead_extraction.py` alias tables to cover common
tenant field-label patterns:
```py
_NAME_ALIASES  += ("your_name", "contact_name", "customer_name",
                   "client_name", "cust_name")
_EMAIL_ALIASES += ("your_email", "contact_email", "customer_email",
                   "client_email", "email_addr", "e_mail_address")
_PHONE_ALIASES += ("your_phone", "contact_phone", "customer_phone",
                   "client_phone", "phone_num", "phone_number",
                   "cell_phone", "cellphone", "mobile_number",
                   "mobile_phone", "telephone", "home_phone")
_ADDRESS_ALIASES += ("your_address", "home_address", "mailing_address",
                     "billing_address", "location")
_MESSAGE_ALIASES += ("how_can_we_help", "what_can_we_help",
                     "your_message", "inquiry", "reason",
                     "description")
```

**Impact**: catches more submissions on both Path A and Path B.
On Path B, fewer leads are silently dropped.  On Path A, fewer
placeholders are created (extraction succeeds → placeholder path
never hits).

**Verification**: add pytest cases with 5-6 tenant-authored label
variations, assert extraction resolves them correctly.

### Fix B · Kill Path A's placeholder-creation
Add the same `if email or phone` guard to `marketing.py:153` and
`marketing.py:200` — never create placeholders from Path A either.
Preserves the Path A endpoints (in case any tenant has a hand-coded
form still hitting them) but stops the empty-placeholder class of
row from ever landing.

**Trade-off**: any current user hitting Path A whose form doesn't
have matched fields loses the "at least I know someone submitted
something" affordance.  Could be paired with a warning row in
`db.form_submissions` view.

**Verification**: pytest for Path A — POST with unmatched fields
→ 200 OK, no lead created, submission still recorded.

### Fix C · Store submission + create placeholder + backfill button
Keep the placeholder-creation but link it to the raw submission via
`submission_id`, and add a "Backfill from submission" button in the
lead detail view that scans the raw `db.form_submissions.answers`
and offers the admin a fuzzy-match UI to map unrecognized keys onto
the standard slots.

**Trade-off**: heaviest fix.  Introduces admin UI + a mapping-config
per tenant.  Best long-term answer for tenants with weird label
conventions.

### Fix D · Field-label mapping in form config
Extend `FormField` schema with an optional `contact_slot` enum:
```py
class FormField(BaseModel):
    ...
    contact_slot: Optional[Literal["name","first_name","last_name",
                                    "email","phone","address","city",
                                    "state","zip","message"]] = None
```
Then the extractor prefers `contact_slot` when set, falling back
to the alias table.  Admin authors the form and explicitly binds
"How can we help?" to `contact_slot="message"`.

**Trade-off**: schema change + form-builder UI change + migration
to backfill existing forms.  Cleanest long-term architecture.

---

## Recommendation

**Ship Fix A + Fix B together as K53.1** — that's the immediate
bug-fix pass:
* Fix A widens the alias table to catch the common label misses
  (lowest-risk change, high-value).
* Fix B removes the "Website Visitor" placeholder as a class of row
  from Path A, so tenants stop seeing them entirely.

**Then discuss Fix D as a K54** — the schema/form-builder change
that eliminates the guessing.

**Do NOT run the P19 backfill blindly** — the P19 script only fills
placeholders when it can find a matching submission with real data.
If the placeholders on Prod were created from empty submissions,
P19 won't help them.

## Fix test/verification plan (for whichever fix ships)

1. **Unit tests** (`services/lead_extraction.py`): add cases for
   every new alias entry (Fix A) and the guard bypass (Fix B).
2. **Route tests** (`test_widget_lead_intake_field_capture.py` is
   already in the repo — extend it): submit a form with common
   tenant label patterns, assert lead is created with correct
   fields populated (not "Website Visitor").
3. **Cross-tenant regression** (H4 aside): confirm existing tests
   for Path A / Path B tenant scoping still pass.
4. **Prod DB audit query** (user runs, output redacted):
   ```
   db.leads.aggregate([
     { $match: { name: "Website Visitor" } },
     { $group: { _id: "$tenant_id", count: {$sum: 1},
                 sources: {$addToSet: "$source"} } }
   ])
   ```
   Tells us how widespread the placeholder problem is on Prod
   and which sources are responsible.

---

## Files inspected

* `backend/routers/marketing.py` — Path A (legacy public forms)
* `backend/routers/marketing_forms.py` — Path B (K52-era widget)
* `backend/routers/leads.py` — `/public/leads` direct-write path
  (correctly guarded, not a suspect)
* `backend/routers/widget_chat.py` — chat widget (correctly guarded,
  not a suspect)
* `backend/services/lead_extraction.py` — shared extractor with
  narrow alias tables
* `backend/services/migrations/leads_backfill_from_form_submissions_v1.py`
* `backend/migrations/task_p19_backfill_empty_website_visitor_leads.py`
* `frontend/public/widget/form.js` + `form.min.js` — the deployed widget
* `frontend/public/widget/chat.js` + `chat.min.js` — the chat variant
* `frontend/src/pages/marketing/MarketingFormsPage.jsx` — admin
  form-builder (embed snippet generator)
* Preview DB — `db.leads.count({name: "Website Visitor"}) → 0`

## Files NOT changed
None.  Diagnosis-only pass.
