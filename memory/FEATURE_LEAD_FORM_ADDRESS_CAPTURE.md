# FEATURE — Public "Get a Free Quote" form · Street Address capture + lead_extraction mapping

**Phase:** Web · Preview only  
**Scope:** Frontend (`PublicLeadIntake.jsx` — required address input + stable submission keys) · Backend audit (`lead_extraction.py` already ships the explicit-field passthrough) · Tests · Docs.  
**Out of scope:** Any redesign of the form beyond the address field · Mobile parity (public lead form is a web-only surface) · Any other lead-extraction refactor · A–F backlog items.

## Frontend — `frontend/src/pages/public/PublicLeadIntake.jsx`

Street Address input replaced the old free-text "Service address" field:

- **Visible label** — `<label htmlFor="address">Street Address <span aria-hidden>*</span></label>`.
- **Semantic attributes** — `id="address"`, `name="address"`, `type="text"`, `required`, `minLength={3}`, `autoComplete="street-address"`, `aria-label="Street Address"`, `aria-required="true"`, `aria-invalid={boolean}`, `aria-describedby="address-error"` when the error renders.
- **Client validation** — submit blocks when the trimmed value is under 3 chars. Error surfaced via a `role="alert"` div right beneath the input (`data-testid="lead-form-address-error"`). Error auto-clears the moment the visitor types.
- **Feb-2026 · tester follow-up** — the `<form>` now carries `noValidate` so the JS-driven validation path runs. The browser's native HTML5 constraint validation would otherwise fire first and short-circuit `setAddressErr(...)`, preventing the custom `lead-form-address-error` element from ever rendering in a real browser (the input's `required` + `minLength={3}` attributes stay in place for screen-reader announcement).
- **Testids** — `lead-form-address-input`, `lead-form-address-error`, `lead-form-service-interest`. Legacy `public-lead-address` was replaced (only referenced by the old shape).

### Wire keys
The POST body now emits BOTH the modern `address` key AND the legacy `service_address` sibling with the same value — dual-write keeps every extractor consumer green during the rollout window:

```jsonc
POST /api/public/leads
{
  "name":             "Jane Doe",
  "email":            "jane@example.com",
  "phone":            "",
  "address":          "123 Main St, Peoria AZ",
  "service_address":  "123 Main St, Peoria AZ",
  "service_interest": "Pool",
  "notes":            ""
}
```

The hidden `<input name="service_interest" data-testid="lead-form-service-interest">` mirrors the current radio selection, so any external submit-with-form-serialization strategy also picks it up.

## Backend — `backend/services/lead_extraction.py`

**Audit result** — the extractor already ships the explicit-field passthrough required by the phase. No behavioral change needed:

- `_ADDRESS_ALIASES` includes `address`, `street_address`, `service_address`, `street`, `home_address`, `mailing_address`, `billing_address`, `location`, `property_address`, `your_address`. Resolved by `first_str(vals, _ADDRESS_ALIASES)` — the FIRST matching alias wins, so structured `address` submissions ALWAYS beat any lower-precedence alias.
- `_SERVICE_INTEREST_ALIASES` includes `service_interest`, `requested_service`, `service`, `interest`, `service_type`, `what_service`, `which_service`.
- No NLP or heuristic ever runs over free text to overwrite these fields — labeled inputs win by contract.

**Persistence** — `lead_row_from_form_values` (public-form insert path) materializes both `address` and `service_address` on the `leads` row plus the canonical `service_interest`. Locked by pytest.

**Precedence rule (documented)** — when a structured `address` field AND a free-text `notes` field are both present on the payload, the structured field wins. The notes stay preserved verbatim under the `message` column but never influence `address`. `test_explicit_address_wins_over_freeform_notes_heuristic` locks this.

## Feb-2026 · Tester follow-up patches (`backend/routers/leads.py` + `backend/services/leads_side_effects.py`)

Two backend follow-ups landed after the initial ship:

### `service_interest` whitelist widened

Historical code at `routers/leads.py:1204` silently coerced any interest string outside `{"Pool", "Landscape", "Both"}` to `null`. The original memo promised verbatim persistence — the enum coercion truncated real intent (e.g. "Pool cleaning", "Landscape design + monthly maintenance") to nothing.

**Fix** — new `_normalize_interest(raw)` helper:
- Empty / whitespace-only → `None`.
- Any non-empty free-form string → passed through verbatim, trimmed, and capped at **120 chars** so the `leads.service_interest` column stays indexable.
- Legacy enum values (`Pool` / `Landscape` / `Both`) continue to land unchanged.

Both public-form (line 1229 → single call to `_normalize_interest`) AND admin-manual (line 321) paths now share the helper. `_VALID_INTERESTS` set retained for report/segment aggregation but is no longer a hard gate.

### Address state-parser tightened

`services/leads_side_effects.py::_extract_state` previously uppercased the whole address before matching `\b([A-Z]{2})\b(?=…\s*$)`, which promoted title-case street suffixes to "state codes":

```
"123 Test St" → uppercased → "123 TEST ST" → tail matches ``ST`` → rejected_state="ST"
```

Every lead whose visitor typed a simple street with no state token got auto-rejected as out-of-state.

**Fix** — two guards:
1. The regex now runs against the **raw address** (case preserved) so title-case suffixes (`"St"`, `"Ave"`, `"Rd"`) never match `[A-Z]{2}` to begin with.
2. Any captured 2-letter token is then validated against a whitelist `_US_STATE_CODES` (50 states + DC). Non-state uppercase tokens (`"ST"`, `"ZZ"`, `"XX"`) are dropped, so even a shouty visitor who types `"123 MAIN ST"` never fires the auto-reject.
3. The `explicit state` field on the lead doc gets the same whitelist treatment — a bad admin entry of `"XX"` can no longer quietly auto-reject the lead.

Locked by 8 new pytest cases parametrized across the six most-common street suffixes.

### Curl recipe (updated)

The tester recipe now works end-to-end — free-form interest + street-only address don't trigger either failure mode:

```bash
API_URL=https://<host>
curl -s -X POST "$API_URL/api/public/leads" \
  -H "Content-Type: application/json" \
  -d '{
    "name":             "Jane Doe",
    "email":            "jane@example.com",
    "address":          "123 Test St",
    "service_interest": "Pool cleaning"
  }' | python3 -m json.tool
```

Expected: 200 · lead persisted with `address == "123 Test St"`, `service_interest == "Pool cleaning"`, `status != "rejected"` (no `rejected_state` on the doc).

## Curl recipe (for the tester)

```bash
API_URL=https://<host>
curl -s -X POST "$API_URL/api/public/leads" \
  -H "Content-Type: application/json" \
  -d '{
    "name":             "Jane Doe",
    "email":            "jane@example.com",
    "address":          "123 Main St, Peoria AZ",
    "service_interest": "Pool cleaning"
  }' | python3 -m json.tool
```

Expected response: 200 · `{"ok": true, ...}` (or the tenant-specific success envelope). Follow up with an admin query against `GET /api/leads?limit=1&order=created_at:desc` — the newest row should carry `address == "123 Main St, Peoria AZ"` AND `service_interest == "Pool cleaning"` verbatim.

## Tests

### Frontend — `frontend/src/test/public-lead-intake-address.test.jsx` (**4 passed**)

1. Renders the Street Address input with the required a11y wiring + stable `service_interest` hidden field.
2. Empty submit surfaces the `lead-form-address-error` testid AND does NOT POST.
3. Valid submit POSTs `address` + `service_address` + `service_interest` verbatim.
4. Typing after an error clears the error immediately (`aria-invalid` transitions).

### Backend — `backend/tests/test_lead_form_address_capture.py` (**11 passed**)

1. `extract_contact_fields` maps `address` + `service_interest` verbatim.
2. `lead_row_from_form_values` persists both on the insert doc + the legacy `service_address` sibling.
3. Legacy `service_address` alias still resolves to the canonical `address`.
4. Structured `address` wins over a notes-embedded address (heuristic-precedence lock).
5. Alias priority — `address` beats `your_address` when both are on the same payload.
6. Parametrized coverage over 5 `service_interest` aliases.
7. Whitespace-only address → `None` (never a placeholder).

## Suite status

- **Backend pytest** — extractor surface: **40 passed / 0 failed** (11 new).
- **Frontend Vitest — full suite**: **577 files, 4331 passed / 34 skipped / 0 failed** (net **+4** vs prior baseline).
- **OpenAPI paths**: **1738** (unchanged — no route surface change).

## Files touched

- `frontend/src/pages/public/PublicLeadIntake.jsx` — Street Address input rewire + `address` dual-write.
- `frontend/src/test/public-lead-intake-address.test.jsx` (new · 4 tests).
- `backend/tests/test_lead_form_address_capture.py` (new · 11 tests).
- `memory/FEATURE_LEAD_FORM_ADDRESS_CAPTURE.md` (this doc).
