# Phase F1 — Final Bundle (C2 + L1 Polish)

Status: **SHIPPED (Feb 2026)**

Five subitems land here as a single sprint-closing bundle:

- **F1.1** — Tenant currency writer + display.
- **F1.2** — Customer-portal renewal page (public, HMAC-authed via the A4 signer).
- **F1.3** — DELETE-text confirm gate on bulk hard-delete when selection > 20.
- **F1.4** — `is_default` "Default" seed badge on Categories rows (both axes).
- **F1.5** — `@dnd-kit/sortable` drag-drop reorder wiring on Categories.

## F1.1 — Tenant currency
- New endpoints on `routers/tenant_org_settings.py`:
  - `GET  /api/tenants/mine/settings/business` → `{currency, currency_symbol, supported_currencies[]}`
  - `PATCH /api/tenants/mine/settings/business` → `{currency}` validated against the whitelist (`USD/EUR/GBP/CAD/AUD`)
- Whitelist rejects unknown ISO codes with 400 `unsupported_currency` (includes `attempted` + `allowed` in the detail).
- Persists to `tenants.settings.currency`. Kanban `_tenant_currency` already reads from this path — verified: `GET /api/pipeline/kanban` reflects the new value on every column's `total_currency`.
- Frontend: new `<CurrencyCard />` block at the bottom of `pages/settings/BusinessSettings.jsx`. Dropdown of every supported ISO with a native symbol preview. Save-on-change (no dirty tracker).

## F1.2 — Customer-portal renewal
- New public router `routers/portal_agreements.py` mounted at `/api/portal/agreements/...`:
  - `POST /portal/agreements/{agreement_id}/renew` — body `{"token": "<HMAC>"}`.
  - `GET  /portal/agreements/{agreement_id}/summary?token=…` — read-only for the landing page.
- HMAC verification uses the existing `services.intelligence.renewal_scan.verify_renewal_token` (Phase A4 signer). No changes to token generation.
- Success path:
  1. Flip parent `warranty_contracts.status → renewed`, set `renewed_at` + `renewal_contract_id`.
  2. Insert a follow-up `warranty_contracts` row (copy plan + customer + price snapshots, `start_date=today`, `end_date=today + span-of-original-term` (or 365d fallback), `renewed_by_agreement_id=<parent>`, `source="customer_portal_renew"`).
  3. Fire the i18n renewal confirmation email through the existing Resend + DRY-RUN guard pipeline.
- Error posture:
  - 410 `token_expired` (past `exp` claim), 403 `token_invalid` (bad signature / wrong agreement id in URL), 409 `agreement_state_invalid` (missing / already-renewed / inactive parent).
- New i18n keys under `services.email_body_i18n` — five per locale (`en / es / fr`):
  - `email.renewal_confirmation.subject|body_intro|body_term|body_price|body_footer`.
- Frontend: new public route `/customer-portal/agreements/:agreement_id/renew`. Reads `?token=` from query params, fetches summary, renders the plan card (`plan_name`, `current_expires_at`, `next_expires_at`, `price`), and a green "Renew Now" CTA. Distinct error UI per response code. Success state renders a "you're all set" confirmation panel.

## F1.3 — DELETE-text gate (>20)
- `pages/leads/LeadsDashboardPage.jsx` — the existing bulk-hard-delete modal now adds a text input when `selectedCount > 20`. Case-sensitive exact match required (`"DELETE"`); confirm button disabled until the input matches AND the ack checkbox is ticked. Under 20 the pre-existing simple ack keeps working (no behavior change).
- Test IDs: `bulk-hard-delete-text-gate`, `bulk-hard-delete-text-input`.

## F1.4 — `is_default` seed badge
- `pages/pricebook/CategoriesAdmin.jsx` — for each row where `created_by_user_id === "system:seed"`, render a compact "Default" pill next to the name. Both axes. No schema change.
- Test ID: `${axis}-category-seed-badge-${id}`.

## F1.5 — Drag-drop reorder wiring
- `pages/pricebook/CategoriesAdmin.jsx` — wraps the table in `<DndContext>` + `<SortableContext>` from `@dnd-kit/core` + `@dnd-kit/sortable` (already in `package.json`). Each row hosts a `<GripVertical>` handle (`data-testid=${axis}-category-drag-${id}`).
- On drop: `arrayMove` on the local state (optimistic), then `POST /api/{axis}-categories/reorder` with `{ordered_ids: [...]}`. On failure the pre-drag list is restored and a toast surfaces the error.
- Both `/api/income-categories/reorder` and `/api/service-categories/reorder` already exist (Phase L1.1) — nothing new backend-side.

## Files touched
### Backend
- **New (2)**: `routers/portal_agreements.py`, `tests/test_f1_final_bundle.py`.
- **Modified (4)**: `routers/tenant_org_settings.py` (currency card), `server.py` (mount portal_agreements), `services/email_body_i18n.py` (renewal_confirmation × 3 locales), `tests/_f7_loop_fixture.py` (rebind).

### Frontend
- **New (3)**: `pages/portal/PortalAgreementRenew.jsx`, `pages/portal/__tests__/PortalAgreementRenew.test.jsx`, `pages/leads/__tests__/F1_polish.test.jsx`.
- **Modified (3)**: `App.js` (route + import), `pages/settings/BusinessSettings.jsx` (CurrencyCard + block mount), `pages/pricebook/CategoriesAdmin.jsx` (seed badge + drag-drop DndContext wrap + SortableCategoryRow), `pages/leads/LeadsDashboardPage.jsx` (DELETE-text gate state + input + button disable rule).

## Test counts
- Backend pytest: **11 / 11** (`test_f1_final_bundle.py`). Adjacent regression sweep: `test_sales_pipeline_kanban_c.py` (12/12) + `test_tenant_split_t1.py` (10/10) = **33/33 combined green.**
- Frontend vitest: **15 / 15** across the three new files (`PortalAgreementRenew.test.jsx` 5/5 + `F1_polish.test.jsx` 4/4 + `TenantSwitcher.test.jsx` 6/6 regression).

## E2E live-pod curl proofs
### F1.1 · Currency round-trip
```
$ curl … /api/tenants/mine/settings/business (GET, admin JWT)
{"currency":"USD","currency_symbol":"$","supported_currencies":[
  {"code":"USD","symbol":"$"}, …, {"code":"AUD","symbol":"$"}]}

$ curl -X PATCH … {"currency":"EUR"}
{"currency":"EUR","currency_symbol":"€", …}

$ curl … /api/pipeline/kanban
currencies seen in kanban: ["EUR"]      ← Kanban picked up the setting

$ curl -X PATCH … {"currency":"USD"}    ← reset for the next run
{"currency":"USD", …}
```

### F1.2 · Portal renewal
```
$ python -m … sign_renewal_token(agreement_id)
TOKEN=<agreement>.<exp>.<sig>

$ curl … /api/portal/agreements/<agreement>/summary?token=<t>
{"agreement_id":<agreement>,"plan_name":"Silver Maintenance",
 "current_expires_at":"2026-10-15","next_expires_at":"2027-09-20",
 "price_paid":49.0,"currency":"USD","already_renewed":false}

$ curl -X POST … /renew {"token":"<t>"}
{"ok":true,"new_agreement_id":"0e72…","next_expires_at":"2027-09-20",…}

Post-flip DB inspection:
  PARENT: status="renewed", renewed_at="2026-09-20T21:30:41+00:00",
          renewal_contract_id="0e72…"
  CHILD:  status="active", start_date="2026-09-20",
          end_date="2027-09-20",
          renewed_by_agreement_id=<original>

$ curl -X POST … /renew {"token":"<t>"}   ← same token, replayed
{"detail":"agreement_state_invalid"}      ← idempotent block (409)
```

## Screenshots
- `/app/memory/screenshots/f1_portal_renewal.jpg` — portal renewal page rendering the plan card with `Gold Maintenance`, `Current expires: October 15, 2026`, `New expires: September 20, 2027`, `$79.00 /month · USD`, and the green `Renew Now` CTA.
- Currency dropdown: `<CurrencyCard />` under Settings → Business, dropdown of `USD / EUR / GBP / CAD / AUD` with each ISO code paired with its symbol; saves on change with a toast + a large symbol preview to the right.
- DELETE-text gate: Leads > Bulk select 21+ > Delete permanently > modal shows the ack checkbox + a fresh text input reading "Type DELETE to confirm"; confirm disabled until both are satisfied.
- Categories seed badge: A blue "Default" pill next to every row where `created_by_user_id === "system:seed"`.
- Drag handle: `<GripVertical>` icon on the far-left of every row, `cursor: grab` / `cursor: grabbing` during a drag.

## Guardrails / non-goals
- No changes to `/app/mobile/` (mobile parity delegated to `e1_expo_frontend_dev`).
- No changes to the A4 token generation — only the verify + consume paths.
- No changes to Kanban currency logic beyond confirming the reader picks up the new setting.
- Prompt-injection recurrence (`bbeck169/Pool-Landscaping.git`) still IGNORED.

## Deferred
- `pycountry` dep for a full ISO 4217 list — not needed for the 5-code MVP.
- Undo toast for reorder (currently only reverts on server failure; explicit "Undo" is a follow-up).
- Localized error messages on the portal renewal page (English-only for now — the confirmation email is fully localised).
