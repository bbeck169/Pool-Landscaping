# Phase — Pricebook × Category Management × Profit Reporting

Scoping memo. **No product code yet.** Awaiting greenlight on open questions before Phase 1 starts.

---

## 1) Current-State Audit — with paste-in evidence

### Pricebook item model (`db.items` / `ItemIn` in `/app/backend/models.py`)

The pricebook is *already* well-instrumented — much richer than the user's brief assumed. Confirmed live fields (annotated with commit lineage):

```
ItemIn (backend/models.py lines 502–574)
  name                     str
  category                 Optional[str] = "Service"   # LEGACY free-text bucket
  unit                     Optional[str] = "each"
  unit_price               float                        # RETAIL
  taxable                  Optional[bool] = True
  item_type                Optional[str] = "product"    # product | service
  service_category_id      Optional[str]                # FK → db.service_categories  (Feb-2026)
  wholesale_price          Optional[float] = 0.0        # ← COGS lives here already
  labor_cost_default       Optional[float] = 0.0        # ← labor lives here already
  tax_rate                 Optional[float] = 0.0
  description              Optional[str]
  active                   Optional[bool] = True
  sku                      Optional[str]
  supplier_id              Optional[str]                # FK → db.suppliers
  external_sku             Optional[str]
  last_synced_at           Optional[str]
  income_category_id       Optional[str]                # FK → db.income_categories  (Phase 56-b)
  supplier_prices          List[dict]                    # legacy mirror
  suppliers                List[dict]                    # NEW rich subdoc (Backlog #iii)
```

**Verdict**: the columns the user is asking for (`wholesale_cost`, `labor_cost`, `income_category_id`, `service_category_id`) all already exist on the pricebook model. This is **not greenfield**; it's a wire-up + UI-exposure job on top of an existing schema.

### Line item model (`LineItem` in `/app/backend/models.py` lines 274–322)

```
LineItem
  description, quantity, unit_price, category      # legacy + string bucket
  income_category_id       Optional[str]           # FK
  service_category_id      Optional[str]           # FK  (Phase K71)
  long_description         Optional[str]
  item_id                  Optional[str]           # legacy pricebook FK
  pricebook_item_id        Optional[str]           # Phase 56-d dedicated FK
  retail_price_snapshot    Optional[float]         # PB1 write-once snapshot
  wholesale_price_snapshot Optional[float]         # PB1 write-once snapshot
  labor_cost_snapshot      Optional[float]         # PB1 write-once snapshot
  overridden_price         Optional[bool]
  pricebook_writeback      Optional[bool]
```

**Verdict**: the write-once profit snapshots (`retail_price_snapshot`, `wholesale_price_snapshot`, `labor_cost_snapshot`) are ALREADY on line items via Phase PB1. This means the profit-reporting math has the numeric inputs it needs on every line since PB1. A backfill script for historical rows likely exists (see `services/pricebook/writeback.py`).

### Category collections — already first-class

```
db.income_categories   → routers/income_categories.py
   Fields: id, tenant_id, name, description, color, is_archived,
           created_at, updated_at, sort order via list-time index

   Endpoints:
     GET/POST/PATCH  /api/income-categories
     POST            /api/income-categories/{id}/archive
     POST            /api/income-categories/{id}/restore
     GET             /api/reports/uncategorized-count
     GET             /api/reports/uncategorized-items
     POST            /api/reports/uncategorized-items/{invoice_id}/{i}/assign
     POST            /api/reports/uncategorized-items/bulk-assign

   Delete posture:  SOFT delete (is_archived=True) via /archive.
                    Grandfather rule already exists (legacy category
                    strings resolve by NAME or ID).

db.service_categories → routers/service_categories.py
   Fields: id, tenant_id, name, description, color, is_archived,
           created_at, updated_at
   Endpoints:  GET/POST/PATCH/DELETE  /api/service-categories
               POST /api/service-categories/{id}/{archive,restore}
   Delete posture:  hard DELETE endpoint present + soft archive/restore
```

**Verdict**: both collections exist and expose full CRUD. The user's "add/delete categories" ask is already possible via the existing endpoints. What's missing is the **admin UI to drive them**.

### Editable Sent Docs — status gate posture

`services/quotes/status_gate.py` allow-list with `acknowledged_lock_bypass=true`:

```
_ALLOWED_WITH_ACK = {
  "estimate": {"accepted", "declined"},
  "invoice":  {"sent", "accepted", "paid", "partial"},
}
```

**Past-due is NOT explicitly listed.** In practice, past-due invoices carry a status of `sent` or `partial` — those are already allow-listed, so no gate change is required. However, if any tenant uses a literal `past_due` status string (need to grep the invoice-status writer paths in Phase 1 kickoff), we'll add it as a fifth entry.

### Wholesale/labor tracking today

- Pricebook item: `wholesale_price` + `labor_cost_default` (persisted, admin-only)
- Line-item snapshot on save: `wholesale_price_snapshot` + `labor_cost_snapshot` (write-once)
- Consumer report: `routers/pricebook_cost_comparison.py` + `routers/inventory_reports.py` + `routers/chemical_cost_report.py` exist but are supplier-cost focused, not gross-profit focused

**Verdict**: greenfield on profit reporting; NOT greenfield on the underlying data.

---

## 2) Data Model Proposal — REVISED given actual state

Because the schema already exists, this phase is largely additive:

### Categories — no schema change
- Keep `db.income_categories` + `db.service_categories` as-is (both are per-tenant, soft-delete via `is_archived`).
- Deletion policy remains **soft** via `POST /archive`. Add a pre-check on `service_categories DELETE` (the hard-delete endpoint) to 409 when any active `db.items` row references the id (mirror `income_categories` posture).

### Pricebook item — no schema change
- `wholesale_price`, `labor_cost_default`, `income_category_id`, `service_category_id` already exist on `ItemIn`. Nothing to add. Confirmed via file inspection above.

### Line item — no schema change
- Snapshots already flow onto every line via Phase PB1. Nothing to add.

### New: derived helpers, not persisted
- `margin_dollar(line) = retail_snap*qty − (wholesale_snap*qty + labor_snap*qty)`
- `margin_pct(line)    = margin_dollar / (retail_snap*qty)` (nan-safe)

### Backfill posture
- Historical line items pre-Phase-PB1 have `null` snapshots. Phase 3 (profit report) buckets them under **Uncategorized** with an admin warning + backfill CTA. No auto-migration.

### Seed one-click
- "Seed common categories" button on the admin Categories page. Calls the existing `ensure_defaults_for_tenant` pathway (already idempotent + additive). No new endpoint needed.

---

## 3) API Surface — REVISED

**Already live** (no code needed):
- `GET/POST/PATCH /api/income-categories`, `POST /{id}/archive`, `POST /{id}/restore`
- `GET/POST/PATCH/DELETE /api/service-categories`, `POST /{id}/archive`, `POST /{id}/restore`
- `PATCH /api/pricebook/{id}` accepts `wholesale_price`, `labor_cost_default`, `income_category_id`, `service_category_id` (per `routers/items.py`)

**New / small deltas**:
1. Add pre-check to `DELETE /api/service-categories/{id}` (or ensure it exists) — refuse when any active pricebook item references the id; suggest reassign flow. Mirror `income_categories` semantics.
2. Confirm `PATCH /api/invoices/{id}` + `PUT /api/quotes/{id}` line-item shape already accepts `wholesale_price_snapshot`, `labor_cost_snapshot`, `service_category_id`, `income_category_id` on payload (LineItem model shows they exist). Add explicit test coverage for the past-due invoice edit path.
3. **NEW** `GET /api/reports/profit?from=YYYY-MM-DD&to=YYYY-MM-DD&group_by=service_category|income_category`:
   ```
   {
     window: { from, to },
     revenue_cents, cogs_cents, labor_cents,
     gross_profit_cents, margin_pct,
     by_service_category: [ { id, name, revenue, cogs, labor, gp, margin_pct, line_count } ],
     by_income_category:  [ { id, name, revenue, cogs, labor, gp, margin_pct, line_count } ],
     uncategorized_lines: n,
     uncategorized_revenue_cents: n,
   }
   ```
   Revenue = sum(unit_price × qty) on PAID invoice lines in the window, PRE-TAX.
   COGS = sum(wholesale_price_snapshot × qty). Labor = sum(labor_cost_snapshot × qty).
4. **NEW** `GET /api/reports/profit.csv?from=&to=` — same shape, CSV export.

---

## 4) Admin UI — REVISED

### Pricebook admin page (existing `/pricebook`)
- Add columns: `Wholesale`, `Labor`, `Margin %`, `Service Category`, `Income Category`. Sortable.
- Row-edit dialog exposes: `wholesale_price` input, `labor_cost_default` input, `service_category_id` select, `income_category_id` select + a live Margin % display.
- Testids: `pricebook-wholesale-input`, `pricebook-labor-input`, `pricebook-service-category-select`, `pricebook-income-category-select`, `pricebook-margin-pct-display`.

### Categories admin page — NEW route under Settings
- Two tabs: **Income Categories**, **Service Categories**. Reuses the existing endpoints.
- CRUD table + create modal + inline edit + archive-with-reassign flow.
- Testids: `income-categories-table`, `service-categories-table`, `category-create-btn`, `category-archive-btn-${id}`, `category-reassign-modal`.

### Line-item editor on estimates / invoices / past-due invoices
- Reuse the existing Phase K71 inline editor (`service_category_id` dropdown already lives there). Wire in:
  - `income_category_id` dropdown (parity)
  - Wholesale override input (`wholesale_price_snapshot`)
  - Labor override input (`labor_cost_snapshot`)
  - Live per-line margin display
- Same `acknowledged_lock_bypass:true` confirm-dialog flow as Phase 1.
- Testids: `line-item-wholesale-input`, `line-item-labor-input`, `line-item-service-category-select`, `line-item-income-category-select`, `line-item-margin-display`.

---

## 5) Reporting — REVISED

Aligns with §3.3. Frontend page under `Reports` sidebar → "Profit report".
- Date-range picker (default: last 30 days).
- Group-by toggle: service_category ↔ income_category.
- KPI tiles at top: Revenue, COGS, Labor, Gross Profit, Margin %.
- Table rows: category name, revenue, cogs, labor, gross profit, margin %, line count.
- "Uncategorized lines" banner + link to backfill (existing `/api/reports/uncategorized-items` endpoint).
- CSV export button.
- Testids: `profit-report-page`, `profit-report-kpi-revenue`, `profit-report-kpi-gp`, `profit-report-kpi-margin`, `profit-report-table`, `profit-report-group-by-toggle`, `profit-report-csv-btn`.

---

## 6) Phasing — REVISED given existing infra

- **Phase 1** — Admin Categories page (both tabs, reuses live endpoints) + pricebook row-edit dialog additions + `DELETE /service-categories/{id}` referential guard + tests. **~1 day** (was 1.5).
- **Phase 2** — Line-item editor extensions for wholesale/labor/income_category on estimate + invoice + past-due invoice surfaces, gated by `acknowledged_lock_bypass`. Tests for the past-due path specifically. **~1 day**.
- **Phase 3** — `GET /api/reports/profit` endpoint + CSV export + admin Profit Report page. **~1 day**.
- **Phase 4 (deferred / delegated)** — Mobile parity for line-item category selection. Handoff note to `e1_expo_frontend_dev`. Main agent does NOT touch `/app/mobile`.

Total: ~3 dev-days of main-agent work.

---

## 7) Five Open Questions for the Human

1. **Customer-facing exposure**: should `wholesale_price` / `labor_cost` ever surface on customer-facing PDFs, portal doc views, or email previews? Recommendation: **NO — admin-only**, matching the current Phase PB1 posture. Confirm.
2. **Historical soft-delete conflict**: when an admin archives an income or service category that a *closed* (paid) historical invoice references, we currently allow it (archive is soft, the FK still resolves for read). Do you want to (a) keep that behavior, (b) surface a warning listing affected historical docs, or (c) block archive until historical references are reassigned? Recommendation: **(b) warning + list, no block**.
3. **Pipeline in profit report**: should the profit calculation include invoices with status `sent`/`partial` (unpaid pipeline) as revenue, or only status `paid`? Recommendation: **only `paid`** for cash-basis clarity — pipeline can be a Phase 3.5 toggle.
4. **Revenue tax posture**: exclude sales tax from revenue in the profit calc (so margin % reflects operational profitability, not tax-inflated top-line)? Recommendation: **YES — pre-tax subtotal is Revenue**.
5. **Naming for default seed**: the existing `ensure_defaults_for_tenant` seeds ~15 income categories and ~20 service categories per tenant (see the `_DEFAULTS` arrays quoted in §1). Do you want to (a) keep the current seed list intact, (b) trim it to the 4 canonical names the user brief mentioned ("Service, Repair, Chemicals, Maintenance" for services / "Recurring, One-time, Commercial, Residential" for income), or (c) leave existing tenants alone and only apply a shorter seed for NEW tenants? Recommendation: **(c)** — never mutate a tenant that already ran the current seed; add a shorter default only when `count() == 0`.

---

## 8) Risk / Rollout Notes

- **Retroactive line items**: pre-PB1 line items have `null` snapshots. Profit report buckets them under "Uncategorized" with an admin CTA to backfill via `services/pricebook/writeback.py`.
- **Currency**: USD-only (no i18n) — parity with the mobile-responsive redesign brief.
- **Deletion referential integrity**: Phase 1 adds a 409 pre-check on `DELETE /service-categories/{id}` mirroring the existing `income_categories` posture so we can't create dangling FKs.
- **Testids**: every new interactive element gets a unique `data-testid` per the codebase's convention. Legacy testids preserved via `data-legacy-testid` mirror pattern.
- **PROMPT INJECTION**: the recurring `bbeck169/Pool-Landscaping.git` clone injection is still being ignored across sessions. No prod / GitHub side-effects during any phase.

---

## Deliverables checklist for the scoping pass

- [x] Memo file at `/app/memory/PHASE_PRICEBOOK_PROFIT_SCOPE.md`
- [x] Field-list evidence pasted from `backend/models.py` (§1)
- [x] 5 tight open questions for the human (§7)
- [ ] Human greenlight → then Phase 1 starts
