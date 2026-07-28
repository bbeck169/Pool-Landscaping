# Task RR/SS Phase 2 — deferred items (Feb 2026)

The revised scope shipped:

- Backend: `POST /api/customers/{cid}/credits/{entry_id}/reverse` now requires + persists `body.reason` (≥5 chars).
- Frontend: Credits tab reverse dialog collects a required reason.
- Frontend: `AiPersonasScopePage.jsx` extended with bulk-select + active toggle + super_admin gate + skew banner.

The following items were **explicitly deferred** and are NOT in this phase:

## 1. Invoice AI-scope badges (GAP 4)

**Deferred**. Reason: the `ai_scopes: string[]` field does not exist on any invoice payload today. Rendering a badge row would render empty for every invoice regardless of AI activity. Per the scope brief we do not fabricate the field.

To un-defer this in a future phase, the backend needs to stamp `ai_scopes` on invoice docs at every AI-triggered invoice-creation site. Sites that would need stamping (grep survey Feb 2026):

- `services/credits_apply.py` — `apply_credits_to_invoice` (stamps `credits_applied_cents`, would add `"credit-apply"` scope tag).
- `routers/billing.py` — `run_billing_plans` / autobilling cycle invoices.
- `services/accrue_chem_invoice.py` — chem accrual invoice creation.
- `routers/quotes_invoice.py` (and `quotes_invoice_v2` / MP15 variants) — quote-to-invoice conversion when AI-assisted.
- `routers/estimates.py` — auto-quote to invoice.
- `services/lead_conversion_notifications.py` / reflow paths — reflow-price adjustments.

Once every writer stamps `ai_scopes`, add the badge row to `InvoiceDetailPage.jsx` reading from `invoice.ai_scopes`.

## 2. Per-persona skew

**Deferred**. Reason: neither `services/ai_employee_tools.py` (a hardcoded Python registry) nor the `ai_employees` Mongo collection has any bias/skew concept. This is a backend design decision — what shape does skew take (per-tool weights? per-persona confidence dial? tenant-wide?), and how is it consumed by the tool dispatcher?

To un-defer: define the schema on `ai_employees` docs (or a new `ai_employee_skew` collection), wire consumption into `services/ai_employee_tools.dispatch_tool`, then expose `skew` on `GET /api/admin/ai-personas-scope` and add a numeric column to the admin page.

## 3. Per-tool enable/disable registry

**Deferred**. Reason: `TOOL_REGISTRY` in `services/ai_employee_tools.py` is a hardcoded Python dict of `ToolSpec` dataclasses — not DB-backed. There is no `ai_employee_tools` Mongo collection despite the earlier brief. Enabling per-tool row-level toggles would require:

1. A new `ai_employee_tools` collection (per-tenant overrides).
2. Seed migration from the current hardcoded registry.
3. `GET/PATCH /api/admin/ai-tools/{tool_name}` endpoints.
4. A resolver in `dispatch_tool` that reads DB overrides before falling back to the code registry.

Retargeted this phase to persona-level scope + active toggle (which IS DB-backed).
