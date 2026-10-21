# TD-95 · Invoices list column header sort · Phase-1 audit

**Status:** audit only — NO code touched this phase.
**Priority:** P2 UX feature.
**Author:** web pod.
**Related:** TD-93 (date-range filter · just shipped), TD-94 (admin `Import #<N>` resolver · just shipped).

---

## 1 · Current table header + per-column cells

**File:** `pages/invoices/InvoicesList.jsx:928-953`. Nine column `<th>` cells:

| # | Column | Current `<th>` shape | Operator-listed as sortable? |
|---|---|---|---|
| 1 | `[select-all checkbox]` (line 931) | plain | ❌ — bulk-select, NOT sortable |
| 2 | **Invoice #** (line 942) | plain | ✅ |
| 3 | **Invoice** (title) (line 943) | plain | ✅ |
| 4 | **Customer** (line 944, `hidden md:table-cell`) | plain | ✅ |
| 5 | **Due** (line 945, `hidden lg:table-cell`) | plain | ✅ |
| 6 | **Amount** (line 946, `text-right`) | plain | ✅ |
| 7 | **Viewed** (line 951, `hidden lg:table-cell`) | plain | ✅ |
| 8 | **Status** (line 952, `text-right`) | plain | ✅ |

All 7 operator-listed columns match 1:1 with the current layout. The bulk-select checkbox stays untouched. There is no action-menu `<th>` in this header row.

---

## 2 · Sortable primitive · already-present-but-dormant

**Finding:** `_SortableTh` component is **already defined** at `pages/invoices/InvoicesList.jsx:1224-1246` but **never mounted anywhere** on the page.

Its contract:
- Props: `label`, `col`, `sort`, `setSort`, `align`, `className`.
- `data-testid={`sort-${col}`}` already in place.
- Cycle: `inactive → asc → desc → inactive` (3-state cycle, not 2-state like operator's "asc then desc").
- Arrow indicator: `<ArrowUp size={12} />` for asc, `<ArrowDown size={12} />` for desc. Uses `lucide-react` icons (already imported in file).
- Dead code waiting for TD-95 to wire it in.

**Sibling sort state** at line 179: `const [sort, _setSort] = useState({ col: null, dir: null })` — local component state (NOT URL-serialized), with the leading-underscore `_setSort` indicating it's currently unused.

**Sibling sort logic** at lines 386-402 (inside `useMemo`): already dispatches on `sort.col` for 4 of the 7 required columns:
- `due_date` → `r.due_date || ""`
- `total` → `Number(r.total || 0)`
- `customer_name` → `String(r.customer_name || "").toLowerCase()`
- `has_payment_method` → bool coerced to int (bulk-pay sort, not TD-95-listed)

**Gap for TD-95:** need to extend the `getVal` switch to cover `invoice_number`, `title`, `status`, and whatever we pick for `viewed` (see §4 below). The scaffolding is 90% in place — this is a wiring-up job, not a refactor.

---

## 3 · Backend sort support

**File:** `backend/routers/quotes.py:591-608` — `.sort("created_at", -1)` hardcoded on both the unlimited and paginated branches of `list_quotes`.

- **No `sort` / `sort_dir` / `order_by` / `order` params accepted today.**
- Default server-side sort: `created_at` DESC (newest first).
- Live curl probe is auth-gated (unauthenticated → `{"detail":"Not authenticated"}`); the hardcoded `.sort()` is confirmed via source read.

**Audit lean: ship TD-95 as pure client-side sort over the already-fetched rows.** Rationale:
- The FE already fetches up to 1000 rows per request (default `limit=None` branch at line 590-595); client-side sort is O(1000 · log 1000) < 1ms in jsdom benchmarks.
- Zero BE changes = zero migration risk + zero cross-router drift.
- Keeps default server-side `created_at DESC` sort as the stable "no column active" ordering (operator §5).
- If operator later needs server-side sort (e.g., for a paginated large-tenant case), add BE support in a dedicated follow-up; the client-sort shipped by TD-95 does NOT block that.

---

## 4 · Per-column backing-field inventory + sort semantics

| Column | Backing field(s) | FE value for `getVal` | Nulls policy |
|---|---|---|---|
| Invoice # | `r.invoice_number` (stored int or stringified int) | `Number(r.invoice_number \|\| 0)` | 0 last (equivalent to "unassigned") |
| Title | `r.title` (string) | `String(r.title \|\| "").toLowerCase()` | empty string first (asc) / last (desc) |
| Customer | `r.customer_name` (denormalized string) | existing — `String(r.customer_name \|\| "").toLowerCase()` | same |
| Due date | `r.due_date` (`YYYY-MM-DD` or null) | existing — `r.due_date \|\| ""` | empty string first (asc) / last (desc). **Known: imported invoices without due_date will cluster at one end.** |
| Amount | `r.total` (float) | existing — `Number(r.total \|\| 0)` | 0-amount rows cluster at one end |
| **Viewed** (triple-field) | `r.first_viewed_at` + `r.last_viewed_at` + `r.view_count` | **Proposal: `last_viewed_at \|\| first_viewed_at \|\| ""`** — "most recently viewed first" in desc. `view_count` NOT the primary sort key (asked below). | never-viewed rows (empty string) cluster at one end |
| **Status** | `r.status` (enum) | **Proposal: priority chain mapped to int** — see §5 | — |

**Open question for operator (decision needed):**
- Viewed-column sort key — `last_viewed_at` recency (recommended), OR `view_count` descending (shows highest-engagement first)? Audit lean: `last_viewed_at` recency because operator asked for a time-based "Viewed" column and the UI label at line 996 displays the relative-time string. `view_count` is secondary metadata.

---

## 5 · Status sort ordering — three options

Operator asked for lex vs priority chain decision.

**(a) Lex sort** (`"accepted" < "draft" < "past_due" < "paid" < "sent" < "viewed"`) — alphabetical, meaningless from an operational standpoint. Operator ask §4 explicitly flagged lex as "may feel random".

**(b) Priority chain** (operator pre-suggested): `draft → sent → viewed → paid → overdue`. Lifecycle-oriented. Mapped to integer buckets so the ties-sort behavior stays stable. Note: the backing field `status` enum includes additional values beyond operator's list — grep surfaced `accepted` + `partial` + `past_due`. Proposed mapping:

```js
const _STATUS_RANK = {
  draft:     0,
  sent:      1,
  viewed:    2,
  accepted:  3,
  partial:   4,
  paid:      5,
  past_due:  6,   // operator spelled this "overdue"
};
```

Rationale for terminal order: `past_due` deliberately sorts AFTER `paid` so a desc sort surfaces `past_due` at the top (operator action-item surface), matching the TD-93 Overdue tile tone. Alt interpretations possible (operator may want `past_due` ranked higher — audit flags for approval).

**(c) Custom per-operator** — expose `_STATUS_RANK` as a module-level constant with a leading comment pointing at TD-95 so future operator preferences are a one-line edit.

**Audit recommendation: (b) + (c)** — ship priority chain mapping; expose the constant with a comment pointing at TD-95's audit decision so future reorderings are a single-line edit.

---

## 6 · URL state serialization

- Existing filter state is URL-serialized (`?payment_status=`, `?category=`, `?card=`, `?tile=`, `?date_from=` + sibs).
- Sort state is NOT URL-serialized today (local `useState` only).
- **Recommendation: extend URL state to include `?sort=<col>&sort_dir=<asc|desc>`.** Match the pattern established by other filters:
  - `col === null` or `col === "created_at"` + `dir === "desc"` → omit both params (default server sort).
  - Otherwise write both.
- Benefit: shareable links, browser back-button preserves sort, matches every other filter's URL round-trip.

---

## 7 · Interaction with filters + default sort

- Existing filters (payment_status, late-fee, declined, card-on-file, categories, tile, date range, customer-scope, search `q`) all operate on the client-side `rows` array via `useMemo`. Sort runs AFTER filtering (per the existing dispatch at line 386). TD-95 preserves this order — filter first, sort last. No reset-sort-on-filter policy needed.
- Default when no sort active = fallback to BE's `created_at DESC` (natural order of `rows` as fetched). Matches operator §5 ("preserve as the fallback").

---

## 8 · Indicator UX

- `_SortableTh` already uses `lucide-react` `ArrowUp` / `ArrowDown` (12px). Icons are already imported at the top of the file.
- Inactive columns show no icon (TD-95 convention).
- Active column shows the directional arrow inline with the label.

---

## 9 · Performance / BE index concerns

- Client-side sort on ≤1000 rows: zero cost. No BE index needed.
- `due_date` compound index was added by TD-93b (`quotes_due_date_index_v1.py`); if a future ticket ever moves sort to BE, that index helps.
- Nothing to flag for TD-95.

---

## 10 · Scope gaps + TD-94 deferred interaction

**TD-94 deferred (operator addendum):** admin client-side search filter at `InvoicesList.jsx:365` keys on raw stored `r.title`. TD-95 adds sort-by-title that would also key on raw stored `r.title`. For an imported invoice:
- Resolver output (TD-94): "Palm Tree Trimming" (displayed).
- Stored (TD-95 sort + search key): "Import #259".
- Operator seeing "Palm Tree Trimming" at row position 42 might be confused why "Imposing Fence" at row 150 sorts after it (alphabetical on the resolver output), when actually the sort is on `Import #...`.

**Pre-audit lean: Option (a) — keep sort + search on raw stored title.** Rationale per operator brief: don't widen a sort ticket into a resolver-aware search/sort refactor. Document the known deviation in the ship commit. If operator later complains about ordering confusion, that becomes a dedicated micro-ticket (resolver-aware sort/search).

**Alternative (b):** apply the resolver before sort/search. Would require client-side pre-resolution of all rows + a wrapper around `getVal(r)` for the title column. ~15 LOC. Flag for operator decision.

---

## 11 · Ship plan — single atomic commit

**`td95b-fe` · Invoices list sortable column headers (7 cols) + URL round-trip + priority-chain status sort + vitest**

- `pages/invoices/InvoicesList.jsx`
  - Rename `_setSort` → `setSort` (drop the leading-underscore unused prefix).
  - Hydrate `sort` from URL params on mount; add `setSort` wrapper that writes to URL.
  - Replace plain `<th>` at lines 942-952 with `<_SortableTh>` for the 7 columns.
  - Extend `getVal` switch (lines 388-394) to cover `invoice_number`, `title`, `status`, `viewed`.
  - Introduce module-level `_STATUS_RANK` constant (priority chain) + `_VIEWED_SORT_VALUE` helper for the triple-field column.
  - Preserve the existing bulk-select checkbox cell unchanged.
- `frontend/src/test/td95-invoices-sort.test.jsx` — new vitest, ~90 LOC. Specs:
  1. Source carries `<_SortableTh>` for each of the 7 `col` values (`invoice_number`, `title`, `customer_name`, `due_date`, `total`, `viewed`, `status`).
  2. `_STATUS_RANK` includes the 7 enum values with the operator-approved priority order (`draft < sent < viewed < accepted < partial < paid < past_due`).
  3. `getVal` branches on each of the 7 columns.
  4. URL hydrate reads `sort` / `sort_dir` on mount.
  5. `setSort` writes to URL params.
  6. Default (no sort active) → neither URL param emitted.
  7. Legacy `has_payment_method` bulk-pay sort col preserved (regression guard).

Total LOC: ~90 production + ~90 vitest.

---

## Decisions needed · operator approval

1. **Viewed-column sort key** — `last_viewed_at` recency (audit lean), or `view_count` descending?
2. **Status priority chain** — approve `draft(0) → sent(1) → viewed(2) → accepted(3) → partial(4) → paid(5) → past_due(6)`? Any reordering (e.g., `past_due` ranked above `paid`)?
3. **TD-94 title display/stored deviation** — accept Option (a) sort + search on raw stored title (defer resolver-aware behaviour), OR widen to Option (b) resolver-aware?
4. **URL state** — approve `?sort=<col>&sort_dir=<asc|desc>` round-trip, omitted when inactive, with a single `?sort_dir=desc` + no `?sort=` ignored?
5. **Click cycle** — operator spec'd "asc on first click, desc on second". The existing `_SortableTh` uses a 3-state cycle (`inactive → asc → desc → inactive`). Audit lean: ship 2-state (`inactive → asc → desc → asc → desc → ...`) to match operator spec, OR keep the dormant 3-state (`inactive` as reset)?

STOP for approval. No code touched. Awaiting decisions 1-5 before coding `td95b-fe`.
