# Quote customer-view — grouped-layout LOCK-ON ship

**Status**: shipped (frontend + backend) · preview only · Feb-2026

## Reported bugs (from user screenshots)

The admin "Customer view preview" modal (`K79CustomerViewPreview`)
renders correctly: grouped by service category (Hardscaping, Rock
Install, Irrigation, Lighting, Drainage, Built-In Sitting Area,
Plants & Trees), per-group descriptions, per-group subtotals, total
$37,758.

The actual customer-facing surfaces (shared magic-link, customer
portal, PDF export) rendered the OLD raw itemized table:

- **Bug #1** — grouped layout NOT applied. Customer saw rows like
  "Pavers", "Quarter Minus", "Polymeric Sand" with `QTY/HR` +
  `VISITS` + `TOTAL` columns.
- **Bug #2** — line-level `TOTAL` column rendered `0.00` on every
  row (see `li.total` in `EstimateView.jsx`).
- **Bug #3** — per-row red "Decline" buttons on every line, causing
  visual clutter + potential confusion vs. the doc-level decline.

## Root causes

All three trace back to the same fork in `EstimateView.jsx`:

```js
// OLD — three gates disabled grouped for actionable magic-links.
const showGrouped = Boolean(
  as_customer
  && customer_view
  && customer_view.customer_group_display
  && !(token && actionable && !locked),
);
```

- The `customer_group_display` gate meant a stale/false toggle on the
  doc would drop the customer to itemized.
- The `!(token && actionable && !locked)` carve-out was originally
  added for Phase A's per-line decline UX — it FORCED itemized for
  ANY actionable magic-link, which is exactly the customer's screen.
- The itemized fallback rendered `{fmt(li.total)}` — but the
  customer serializer strips computed totals from the line items,
  so `li.total` was `0` → `0.00` on every row.
- Per-line decline buttons rendered inside the itemized loop, so
  they showed on the exact broken surface.

The PDF path (`backend/routers/estimate_viewer.py::estimate_pdf`)
had the same `customer_group_display` gate:

```py
# OLD — flag-off customer PDF fell to itemized 4-col.
grouped_mode = is_customer_pdf and bool(est.get("customer_group_display"))
```

## Fix — grouped-layout LOCK-ON

```js
// NEW — grouped is the SOLE customer-facing render mode.
const showGrouped = Boolean(as_customer && customer_view);
```

```py
# NEW — customer PDF is always grouped.
grouped_mode = is_customer_pdf
```

**Effect on all three bugs**:

- Bug #1 → fixed: customer view always renders the grouped table
  wired to the `customer_view` payload the backend already embeds
  via `_build_payload → build_customer_view_payload`.
- Bug #2 → fixed transitively: grouped rows use `g.subtotal`
  (server-computed as `sum(qty * unit_price)` in
  `services/quotes/customer_view.py::group_lines_for_customer`),
  never the stripped `li.total`.
- Bug #3 → fixed transitively: per-line Decline buttons only live
  inside the itemized loop, which no longer renders for customers.

**Additional Bug #3 spec** — a single "Decline Quote" button was
added below the totals footer:

```jsx
{as_customer && actionable && !locked && !isAdmin && !printable ? (
  <div data-testid="estimate-bottom-actions">
    <button
      data-testid="estimate-bottom-decline-quote-btn"
      onClick={() => setDeclineOpen(true)}
    >Decline Quote</button>
  </div>
) : null}
```

This complements the existing top-toolbar Decline button (unchanged)
and the mobile-header Decline (unchanged). Both fire the same
`setDeclineOpen(true)` → existing whole-quote decline flow.

## Field `customer_group_display` — status

**Preserved on the doc, ignored by every render surface.** Rationale:

- Removing the field would be a schema migration + admin UI removal +
  possible downstream analytics fix — out of scope for a UX bug fix.
- Keeping the field on-disk means future work can reactivate the
  toggle without a data migration (e.g. if we ever want an
  admin-controlled "show itemized preview to customer" flag).
- The admin toggle in `K79CustomerViewSection.jsx` is still wired to
  the field. It just has no effect on the customer surface. Note
  this in the UI copy if desired (out of scope).

Follow-up ticket: **Remove the admin `Customer view` toggle entirely
from `K79CustomerViewSection.jsx`** (or replace its label with a
"grouped layout is always on for customers" note).

## Files touched

| File | Change | LoC |
|---|---|---|
| `frontend/src/components/EstimateView.jsx` | `showGrouped` simplified to `Boolean(as_customer && customer_view)`; new bottom "Decline Quote" button block | ~30 |
| `backend/routers/estimate_viewer.py` | `grouped_mode = is_customer_pdf` (dropped the toggle check) | ~10 |
| `frontend/src/test/estimate-view-grouped-lock.test.jsx` | **New** — 6 tests covering grouped-lock invariants | 175 |
| `frontend/src/test/public-estimate-landing-valid-token.test.jsx` | Updated the Batch #4 · Item 1 test's assertions to match new contract (grouped table + bottom decline btn, no per-line decline) | ~15 |
| `backend/tests/test_quote_pdf_grouped_lock.py` | **New** — 3 tests covering PDF grouped-lock (customer toggle-off, toggle-on, internal escape hatch) | 220 |
| `memory/FEATURE_QUOTE_CUSTOMER_VIEW_GROUPED.md` | **New** — this doc | 130 |

## Test matrix

**Frontend** (Vitest):

| Test | Case | Asserts |
|---|---|---|
| `renders the grouped table on customer magic-link even when customer_group_display is FALSE` | Bug #1 | Grouped rows present, no itemized table |
| `group subtotals show real prices (not $0.00)` | Bug #2 | Row numeric cell != "0.00" |
| `does NOT render per-line Decline buttons on the customer view` | Bug #3a | No `estimate-line-item-decline-*` testids |
| `renders exactly ONE bottom 'Decline Quote' button` | Bug #3b | Exactly one `estimate-bottom-decline-quote-btn` present |
| `hides the bottom Decline button once the doc is locked` | UX guardrail | Button gone post-accept/decline |
| `hides the bottom Decline button on non-actionable statuses` | UX guardrail | Button gone on draft |
| `renders grouped layout + top approve/decline + bottom Decline Quote button on a valid actionable token` (Batch #4 · Item 1) | Updated contract | Grouped table, no per-line, bottom-decline present |

**Backend** (pytest + reportlab byte-scan):

| Test | Case | Asserts |
|---|---|---|
| `test_customer_pdf_uses_grouped_layout_even_when_toggle_off` | PDF Bug #1 | PDF has "Service" header, NOT "Qty/Hr" / "Visits" |
| `test_customer_pdf_uses_grouped_layout_when_toggle_on` | Regression | Grouped path still works on toggle=True |
| `test_internal_pdf_still_renders_itemized_admin_view` | Admin escape hatch | `?internal=1` still yields the admin itemized columns (`Cost/Rate`, `Margin %`) |

## Screenshots / DOM excerpt for verification

Before (customer screenshot from user):

```
| DESCRIPTION | QTY/HR | VISITS | TOTAL |
| Pavers      | 100    | 1      | 0.00  | [Decline]
| Quarter Min | 8      | 1      | 0.00  | [Decline]
| Poly Sand   | ...    | 1      | 0.00  | [Decline]
...
```

After (from `estimate-view-grouped-lock.test.jsx`, DOM excerpt):

```html
<table class="iv-lines" data-testid="estimate-grouped-table">
  <thead>
    <tr><th>Service</th><th>Subtotal</th></tr>
  </thead>
  <tbody>
    <tr data-testid="estimate-grouped-row-cat-hardscape">
      <td><b>Hardscaping</b>
          <div class="ev-group-desc">Pavers + poly sand</div></td>
      <td class="iv-num">4200.00</td>
    </tr>
    <tr data-testid="estimate-grouped-row-cat-plants">
      <td><b>Plants & Turf</b>
          <div class="ev-group-desc">Drought-tolerant mix.</div></td>
      <td class="iv-num">750.00</td>
    </tr>
  </tbody>
</table>
... totals footer ...
<div data-testid="estimate-bottom-actions">
  <button data-testid="estimate-bottom-decline-quote-btn">
    Decline Quote
  </button>
</div>
```

## Follow-up

- Remove the `Customer view` admin toggle UI from
  `K79CustomerViewSection.jsx` (or replace it with a static note).
  Optional — the toggle is now a no-op for customer rendering. If
  the admin flow relies on the field for something else (e.g. an
  internal preview mode), leave it and add a copy update.
- Consider a schema-migration script to remove
  `customer_group_display` from `db.quotes` documents after N weeks
  of soak. Not required.
