# TD-94 · Admin Invoices list `Import #N` title → first line item name · Phase-1 audit

**Status:** audit only — NO code touched this phase.
**Priority:** P2 display-time fix.
**Author:** web pod.
**Related tickets:** TD-71 (portal `Import #N` resolver · shipped `5baf91f86`), TD-72 (BE stored-title rewrite · DEFERRED prod), TD-72b (portal estimates · `106153aa2`), TD-79 (customer-profile overview invoice list · `db3ef6d2f`).

---

## 1 · Admin Invoices list row renderer

**File:** `frontend/src/pages/invoices/InvoicesList.jsx:966`.
```jsx
<td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}
    onClick={() => navigate(`/invoices/${r.id}`)}>{r.title}</td>
```

- Currently renders raw `r.title` straight from BE.
- **Already bold** via `font-semibold` — operator ask (b) is satisfied by the existing styling. No wrapper change needed.
- **No date prefix wrapper** — the cell is plain `{r.title}` with no `created_at` / `due_date` prepend. Operator ask §4 is a no-op (nothing to remove).
- Sibling cell at line 965 renders `r.invoice_number` under its own `data-testid`; TD-94 does NOT touch that cell.

---

## 2 · Line item shape on invoice doc

Grep for existing usage in `frontend/src/lib/portalInvoiceTitle.js:87-91`:
```js
const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
if (items.length > 0 && items[0] && typeof items[0] === "object") {
  const li = String(items[0].title || items[0].description || "").trim();
  if (li) return li;
}
```

- Array field name on invoice doc: **`line_items`**.
- Per-item field for display: **`title`** (primary) OR **`description`** (fallback).
- Both are strings; `.trim()` + non-empty check already in use by TD-71.
- The invoice list fetch does NOT request `slim=1`, so `line_items[]` IS included on every row (`slim=1` would drop it per `routers/quotes.py:496-504`). No BE change needed to make the field available.

---

## 3 · Admin / portal title-resolver surfaces today

| Surface | File:line | Resolver | Fallback terminus |
|---|---|---|---|
| Admin Invoices main list | `pages/invoices/InvoicesList.jsx:966` | **NONE — raw `r.title`** | n/a (shows raw stored title) |
| Admin Customer-profile Overview invoice tile | `components/customers/CustomerInvoiceList.jsx:207` | `resolvePortalInvoiceTitle` (TD-79) | `"Invoice"` neutral |
| Portal invoices list | `pages/portal/PortalPages.jsx` (per TD-71 scope) | `resolvePortalInvoiceTitle` | `"Invoice"` neutral |
| Portal invoice detail | TD-71 scope | `resolvePortalInvoiceTitle` | `"Invoice"` neutral |

**Scope gap observation (worth flagging to operator):** `CustomerInvoiceList.jsx` is an admin surface (admin viewing a customer's detail tab) BUT consumes the portal-facing resolver → shows neutral `"Invoice"` as last-resort. If TD-94 adds a separate admin resolver with `Import #N` fallback for the main Invoices list, admins will see two slightly different behaviours on two admin surfaces for the SAME imported invoice:
- Main Invoices list → `"Import #259"` (traceable to the import run).
- Customer profile overview tile → `"Invoice"` (customer-friendly neutral).

Audit lean: this split is semantically correct. Operator's TD-94 ask explicitly favours traceability on the main admin list; TD-79's choice to reuse the portal resolver on the customer tile was deliberate (customer-adjacent surface). Flag it in the receipt; don't widen scope.

---

## 4 · Three resolver options (per operator brief)

| Option | Shape | LOC | Admin + portal semantics distinct? |
|---|---|---|---|
| **(a) Reuse `resolvePortalInvoiceTitle` as-is** | 4-branch (`service_description` → first `line_items[].title` → `notes` trimmed → `"Invoice"`) | ~2 LOC call-site change | ❌ merges — admin last-resort becomes `"Invoice"` instead of `Import #N`. Operator traceability lost. |
| **(b) New thin helper `resolveImportedInvoiceTitleFromLineItem`** | 2-branch (`isImportedPlaceholderTitle(invoice) ? firstLineItemName \|\| title : title`) | ~20 LOC helper + ~2 LOC call-site + ~15 LOC vitest | ✅ clean distinct semantics |
| **(c) Options arg on `resolvePortalInvoiceTitle`** | Same 4-branch with `{ fallbackToOriginal: true }` flag that skips the `notes` + `"Invoice"` branches | ~15 LOC on existing helper + ~2 LOC call-site | ⚠️ widens the single helper's surface — more drift risk long-term |

**Audit recommendation: Option (b).**
- Operator ask §4 is strictly "first line item name, else existing title" — thinner than TD-71's 4-branch chain.
- Reuses TD-71's `isImportedPlaceholderTitle` predicate (already exported from `lib/portalInvoiceTitle.js:48`).
- Keeps admin + portal semantics cleanly distinct — avoids future drift surprises.
- Fits inside a single <30 LOC helper file + <20 LOC vitest + ~1 LOC call-site change.

---

## 5 · Other admin surfaces reading the invoice title

Grep for `r.title` / `invoice.title` / `row.title` across admin invoice/quote routes:

| File:line | Context | Scope decision |
|---|---|---|
| `pages/invoices/InvoicesList.jsx:365` | Search filter — `[r.title, r.customer_name]` substring match | **Flag only** — client-side search keys on raw stored title. If operator wants Palm-Tree-Trimming to be searchable, resolver output needs to join the needle set. Out-of-scope lean: imported invoices with no line items keep searching on `Import #N`; those with line items are searchable only on the imported title + customer name. Add a note in receipt. |
| `pages/invoices/InvoicesList.jsx:966` | **PRIMARY TD-94 TARGET** | Swap to resolver output. |
| `pages/quotes/QuotesList.jsx:591` | Quotes list title cell | **Out of scope** — operator ask is Invoices only. Imported quotes are a theoretically-adjacent problem but not raised. |
| `components/customers/CustomerInvoiceList.jsx:207` | TD-79 customer-profile tile | **Out of scope** — already resolved via `resolvePortalInvoiceTitle`. |
| `pages/invoices/MasterInvoice.jsx` | Master-invoice summary | Grep did not surface `r.title` reads; row display shape differs. Out of scope. |
| `components/invoices/BulkChargeModal.jsx` / `BulkApplyCreditModal.jsx` / `PdfInvoiceUploadSidePanel.jsx` | Modal row renderers | Grep required; audit lean: these list invoice numbers + totals, not titles. Flag only, no touch. |

---

## 6 · Scope gaps · sort / filter / future TD-95

- **Sort by title** (TD-95 is queued strictly after TD-94): TD-95 will likely add a column header sort on `title`. If TD-95 keys off the stored `r.title` (not the resolver output), imported rows will sort as `"Import #N"` while displaying as `"Palm Tree Trimming"` — a known-benign display/sort deviation.
  - Audit lean: flag in receipt. TD-95 audit should decide whether sort-by-title keys on the resolver output or the stored field. Server-side sort naturally keys on stored field (indexed); client-side resolver-aware sort would be an opt-in enhancement.
- **Search filter** (per §5 row 1): keys on stored `r.title`. Same deviation — flagged, out of scope for TD-94.
- **TD-72 BE migration (deferred prod)**: when operator runs it, stored titles get rewritten to the resolver output + the TD-94 display-time resolver becomes a no-op for already-migrated rows (the title no longer matches `isImportedPlaceholderTitle`'s regex). Fallback-to-stored behaviour means migrated rows pass through cleanly. No ordering issue between TD-72 and TD-94.
- **TD-93 date-range filter (just shipped)**: zero interaction. TD-93 filters on `created_at` / `due_date`; TD-94 affects display-time string only.

---

## 7 · Proposed ship plan · single atomic commit

**`td94b-fe` · admin InvoicesList Import-title display-time resolution + vitest**

- `frontend/src/lib/importedInvoiceTitle.js` — new 2-branch resolver (~25 LOC):
  ```js
  import { isImportedPlaceholderTitle } from "./portalInvoiceTitle";

  export function resolveImportedInvoiceTitleFromLineItem(invoice) {
    if (!invoice || typeof invoice !== "object") return "";
    const originalTitle = invoice.title == null ? "" : String(invoice.title);
    if (!isImportedPlaceholderTitle(invoice)) return originalTitle;
    const items = Array.isArray(invoice.line_items) ? invoice.line_items : [];
    if (items.length > 0 && items[0] && typeof items[0] === "object") {
      const li = String(items[0].title || items[0].description || "").trim();
      if (li) return li;
    }
    return originalTitle; // fall back to Import #N
  }
  ```
- `frontend/src/pages/invoices/InvoicesList.jsx:966` — swap `{r.title}` for `{resolveImportedInvoiceTitleFromLineItem(r)}`; add the import line at the top.
- `frontend/src/test/importedInvoiceTitle.test.jsx` — new vitest, ~6 specs:
  1. Non-imported invoice → returns original title unchanged.
  2. Imported invoice with line items → first `line_items[0].title`.
  3. Imported invoice with line items, missing `title`, has `description` → returns `description`.
  4. Imported invoice with empty `line_items` → falls back to original `Import #N`.
  5. Imported invoice with `line_items[0]` title/description both empty/whitespace → falls back to original.
  6. Null / non-object / missing invoice → returns empty string.

Total LOC: ~55 lines of production code + vitest.

---

## Decisions needed · operator approval

1. **Resolver strategy** — approve Option (b) new thin helper, OR override to (a) reuse portal resolver / (c) options arg on `resolvePortalInvoiceTitle`?
2. **Scope gap on customer-profile tile** — accept the admin-main-list vs admin-customer-tile semantic split as deliberate (main list = traceable `Import #N` fallback; customer tile = neutral `"Invoice"`), or widen TD-94 to unify?
3. **Search filter + sort-by-title (future TD-95)** — accept the display/stored deviation as benign and defer to TD-95 audit, or add resolver-aware search in TD-94 scope?

STOP for approval. No code touched. Awaiting decisions 1-3 before coding `td94b-fe`.
