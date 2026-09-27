# SPEC: MARCO Lead-Sense (consolidated, canonical)

**Status:** QUEUED. **DO NOT START.**
Saved at: Feb-2026 (during MARCO Sub-phase D debug window).

**Precedence rules:**
- Old third-party `intentify.io` CDN brief → **CANCELED**.
- Field name: `marco_lead_sense_id` (per most recent brief, NOT `lead_sense_pixel_id` from earlier version).
- Existing infrastructure to reuse: `public_widget_key`, `_VALID_SOURCES` whitelist in `routers/leads.py`, `AttributionSettingsPanel`, `LeadDetail.jsx`, `LeadsDashboardPage.jsx`, `routers/webhooks.py` intake.
- New infrastructure to build: `frontend/public/widget/lead-sense.js`, `POST /api/lead-sense/track`, `visitor_intent` collection, tenant settings field, source-tag bypass.

## Sub-phases (5)

### LS-A — Tenant field + JWT-derived tenant isolation
- `backend/routers/tenants.py`: add `marco_lead_sense_id: str | None` to tenant settings sub-doc.
- Auto-generate slug-safe id (12-char nanoid) on first request if unset.
- PATCH endpoint: **strictly derive tenant_id from JWT session — never trust body-supplied tenant_id**. Cross-tenant PATCH must return 403.
- Idempotent migration `marco_lead_sense_id_v1.py` backfills all existing tenants.
- Test: cross-tenant PATCH attempt returns 403, JWT-derived tenant_id resolves correctly.

### LS-B — Self-hosted tracker + intake endpoint + `visitor_intent` collection
- New static file `frontend/public/widget/lead-sense.js`:
  - Captures `current_url`, `referrer`, anonymized `session_id` (localStorage-cached UUID).
  - Reads `data-ls-id` attribute from its own `<script>` tag.
  - Sends via `navigator.sendBeacon` (fallback to `fetch(..., {keepalive: true})`) to `POST /api/lead-sense/track`.
  - Include utility to identify known leads (email hash) if a form is filled on same session.
- Backend endpoint `POST /api/lead-sense/track` in `backend/routers/marketing.py` (or new `backend/routers/lead_sense.py` — your call, note it):
  - Public route, resolves tenant via `data-ls-id` → `tenants.marco_lead_sense_id`.
  - **Origin allow-list**: verify `Origin` header against tenant's registered domains. Reject if not allowed. Use the existing `public_widget_key` allow-list pattern (grep first).
  - IP → company resolution: **STUB for now** (`company: null` if unavailable). Wire a real provider in a follow-up. Grep for existing IP-lookup helpers first — reuse if any.
  - Writes to new `visitor_intent` collection: `{tenant_id, session_id, current_url, referrer, ip, company, user_agent, occurred_at}`.
- Migration: create indexes on `tenant_id`, `session_id`, `occurred_at`.

### LS-C — Lead tagging with `_VALID_SOURCES` bypass
- `routers/webhooks.py` intake (existing): when a lead is created from a `visitor_intent` conversion event, set `source = "MARCO Lead-Sense"`.
- `routers/leads.py` `_VALID_SOURCES` whitelist: DO NOT append the new source to the whitelist. Instead, add a bypass — the whitelist enforces manual-entry sources, but system-generated sources (from webhook intake with a trusted flag) persist verbatim. Add a `_SYSTEM_SOURCES` set for `MARCO Lead-Sense` (and other pixel/webhook sources) that skips the whitelist check.
- Test: manual lead creation with source `"MARCO Lead-Sense"` from an unauthenticated user is still rejected; system webhook path persists it verbatim.

### LS-D — UI: source badge + settings panel + embed code
- `frontend/src/pages/leads/LeadDetail.jsx` and `LeadsDashboardPage.jsx`: add `"MARCO Lead-Sense"` to the source label map. Badge color: Navy `#1B1F5C` background, Blue `#3B82F6` border. Preserve all `data-testid` attributes.
- `AttributionSettingsPanel` (grep for existing file): add a "MARCO Lead-Sense" settings section with:
  - Read-only display of `marco_lead_sense_id`.
  - "Rotate ID" button (admin-only, calls PATCH).
  - Embed Code preview using the shared `CodeSnippet.jsx` component:
    ```html
    <script async src="https://app.plofv.com/widget/lead-sense.js" data-ls-id="RESOLVED_ID"></script>
    ```
  - Substitutes real `marco_lead_sense_id` into the snippet before render — no `%7B%7BTENANT_WIDGET_KEY%7D%7D` literal reaches the DOM.
  - Copy button with "Copied!" feedback.
- If `CodeSnippet.jsx` doesn't exist yet, create it per the earlier spec (props: `code`, `bgColor` default `#03002e`, `borderColor` default `#3B82F6`).

### LS-E — Origin allow-list safety hardening
- Extend `public_widget_key` allow-list pattern to `marco_lead_sense_id` intake:
  - Each tenant maintains a list of authorized domains (probably already in the widget-key model — grep).
  - `POST /api/lead-sense/track` checks `Origin` against this list. Reject 403 if not allowed.
  - Emit a `security_event` log entry on rejected requests (or reuse existing pattern).

## Dependencies (must land before LS starts)
- MARCO Sub-phase E (proactive cron) committed — so the notification bell / SSE path is stable before Lead-Sense-Alert notifications wire in.
- Pool Service PS-A/B/C/D committed — orthogonal but reduces cross-cutting risk.

## Tests
- `backend/tests/test_lead_sense_tenant_field.py`: field addition, JWT-derived tenant, cross-tenant 403, migration idempotent.
- `backend/tests/test_lead_sense_intake.py`: tracker POST, Origin allow-list, IP stub, `visitor_intent` row shape.
- `backend/tests/test_lead_sense_source_tagging.py`: system webhook path persists `"MARCO Lead-Sense"` verbatim; manual entry with same source string rejected.
- `frontend/src/test/leadSenseBadge.test.jsx`: badge renders on LeadDetail + LeadsDashboardPage.
- `frontend/src/test/attributionSettingsLeadSense.test.jsx`: settings panel renders id, snippet contains resolved id (not placeholder), copy button works, rotate button (admin-only) works.
