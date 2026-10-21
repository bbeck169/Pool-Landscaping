# TD-93 · Invoices page date-range filter + summary-stats reactivity · Phase-1 audit

**Status:** audit only — NO code touched this phase.
**Priority:** P2 feature add.
**Author:** web pod.
**Related tickets:** TD-80 (summary-stats parity on Active Accounts count mismatch · shipped).

---

## 1 · Admin Invoices page · current filter bar

**File:** `frontend/src/pages/invoices/InvoicesList.jsx:695-822` (`NavyFilterBar` cluster, Task-E migration Feb-2026).

Current filters, in render order:

| # | Control | Testid | Field | State source |
|---|---|---|---|---|
| 1 | `NavyFilterBar.Search` | `inv-search` | title + customer | local `q` state (client-side filter) |
| 2 | `NavyFilterBar.Select` payment status | `inv-filter-status` | enum `unpaid \| partial \| paid \| all` | URL `?payment_status=` (default `unpaid`) |
| 3 | `NavyFilterBar.Chip` late fee | `inv-filter-late-fee` | boolean | local `hasLateFee` (URL `?late_fee=1`) |
| 4 | raw `<button>` has-declined-items | `docs-filter-has-declined-items` | boolean | local `hasDeclined` |
| 5 | `NavyFilterBar.Select` card on file | `inv-filter-card` | enum `any \| yes \| no` | URL `?card=` |
| 6 | `NavyFilterBar.Select` + chip strip, categories | `inv-filter-category` | multi-select `string[]` | URL `?category=` repeated |

No date-range filter today.

---

## 2 · List endpoint — currently supported query params

**File:** `backend/routers/quotes.py:252-316` (`GET /quotes` handler).

Accepted params: `doc_type`, `include_deleted`, `category[]`, `card_on_file`, `customer_id`, `payment_status`, `view` (quotes-only), `limit`, `offset`, `slim`.

**No `date_from` / `date_to` support today.** Must be added.

---

## 3 · Date-field candidates on invoice document

Invoice is `db.quotes` doc with `doc_type == "invoice"`.  Date fields observed on the schema:

| Field | Semantic | Set when |
|---|---|---|
| `created_at` | row creation timestamp (ISO string) | invoice creation `POST /quotes` |
| `due_date` | invoice due date (date-only `YYYY-MM-DD`) | explicit or auto `+14d` on invoice create |
| `paid_at` | payment settled timestamp | reconciler + `record_payment` |

**Fields NOT present on this schema:**
- `invoice_date` — does not exist (operator-facing term maps to `created_at`).
- `issued_at` / `sent_at` — not stored on the main invoice doc.

**Canonical "invoice date"** in this codebase = **`created_at`**. (TD-72 BE migration operates on `created_at` as the date source of truth.)

**Candidates for the date-range filter:**
- `created_at` → "invoice date"
- `due_date` → "due date"
- (`paid_at` not useful for list filtering — would hide unpaid rows entirely)

---

## 4 · Backend `date_from` / `date_to` support — minimum change

Not supported today. Minimum change to `routers/quotes.py::list_quotes`:

1. Add two `Optional[str]` query params `date_from` + `date_to` (ISO date `YYYY-MM-DD`).
2. Add optional `date_field` param (enum: `created_at` | `due_date`, default `created_at`) to let the FE toggle without server-side guesswork.
3. Compose a `$and` entry on the Mongo query: `{date_field: {"$gte": date_from, "$lte": date_to}}`. Both bounds inclusive; `date_from` may compare ISO-string lex-order against `created_at` (full ISO) by converting to day-start / day-end at `+00:00`, or against `due_date` (date-only) by passing the raw string.
4. Reject invalid dates with `error_code=invalid_date_range` + `HTTP 400` (matches the existing `invalid_payment_status` + `invalid_view` pattern).
5. **Index concern** — `db.quotes.created_at` is already indexed via `tenant_recipient` compound (`migrations/quotes_recipient_index_v1.py:93`) + the service numbering compound (`services/invoice_numbering.py:172`). `due_date` does not have a dedicated index — a range scan on 10K+ rows would touch disk. Mitigation: compose `tenant_id + doc_type + (date_field)` compound index as part of the BE commit. ~5 LOC migration script.

LOC estimate for BE: ~25 LOC in `quotes.py` + ~20 LOC migration script + ~15 LOC pytest coverage.

---

## 5 · Summary stats · current semantics

**File:** `backend/routers/payments_summary.py` (single endpoint `GET /payments/summary`).

| Stat | Current computation | Date dimension today | Accepts range? |
|---|---|---|---|
| `collected_this_month` | sum of `amount_paid` where `paid_at >= month_start` | **fixed to current UTC month** | ❌ |
| `outstanding_total` + `outstanding_count` | balance > 0 AND status in {sent, accepted, past_due} | **as-of-now snapshot** | ❌ |
| `overdue[]` list | subset of outstanding with status == `past_due` | **as-of-now snapshot** | ❌ |
| Aging buckets (0-30 / 31-60 / 61-90 / 90+) | **client-side** from `rows` via `due_date` (`InvoicesList.jsx:273-290`) | derived from loaded rows | ✅ (automatic — reactivates with list filter) |

All stats except Aging are computed server-side with hardcoded date logic. Aging is already date-range-reactive by construction (it operates on the already-filtered client rows).

**Minimum change to make summary stats range-reactive:** extend `/payments/summary` to accept `date_from` + `date_to` + `date_field` params and apply them to the aggregation (semantics proposed in §6).

LOC estimate: ~30 LOC in `payments_summary.py` + ~20 LOC pytest.

---

## 6 · Proposed summary-stats semantics with a custom range

Operator ask explicitly flagged this as a semantic design question. Audit proposals:

| Stat | Range-inactive (today) | Range-active (proposed) | Dynamic label |
|---|---|---|---|
| Collected this month | sum `amount_paid` where `paid_at` ∈ current month | sum `amount_paid` where `paid_at` ∈ [from, to] | **"Collected in range"** (switch label when `date_from`/`date_to` set) |
| Outstanding | balance > 0, status live, as-of-now | balance > 0, status live, where **`date_field` ∈ [from, to]** (filters invoices CREATED or DUE in range, not "as-of-to" — point-in-time balance history is a bigger ticket) | **"Outstanding (in range)"** when active |
| Overdue count | count of status == past_due as-of-now | count of status == past_due where `date_field` ∈ [from, to] | **"Overdue count (in range)"** |
| Aging | client-side from loaded rows | automatic — already derived from filtered list | label unchanged |

**Rationale for Outstanding + Overdue:**
- Audit explicitly rejects "as-of-to-date historical reconstruction" (requires replay of status transitions; out of scope for this ticket — belongs in a Reports surface, not an operational filter).
- Filtering by "invoices created/due in range with current status live" matches operator intuition when scanning a specific month/quarter.
- "Collected in range" is a true aggregation over `paid_at` and WILL respect the range cleanly.

**Open question for operator — see §Decisions below.**

---

## 7 · Existing date-range UX pattern — reuse `NavyFilterBar.DatePicker`

**File:** `frontend/src/components/ui/NavyFilterBar.jsx:245-270`.

Primitive renders a labelled `<input type="date">` with navy styling + `colorScheme: "dark"`. Already used by:
- `pages/chemical/ChemicalApplicationsList.jsx:338-349` (From + To + Tech filter cluster)
- `pages/workstream/WorkstreamPage.jsx:651-660`
- `pages/comms/NotesArchive.jsx:200-210`

**Reuse this.** Two side-by-side pickers (`label="From"` + `label="To"`) matches the three existing precedents exactly. Alternative primitive `@/components/DateRangePicker` has presets + Custom (more feature-rich) but has URL-param side-effects and visual chrome that would clash with the current `NavyFilterBar` aesthetic. **Not reusing it.**

---

## 8 · Which date field is the default · THREE OPTIONS

Options enumerated per operator ask §8:

| Option | Default | Toggle? | UI chrome | Rationale |
|---|---|---|---|---|
| **(a) Fixed to `invoice_date` (`created_at`)** | `created_at` | ❌ | 2 pickers (From / To) | Simplest, matches most CRMs. Operator loses "find all invoices due in Q1" use case. |
| **(b) Default `invoice_date`, small toggle `By [Invoice date \| Due date]`** | `created_at` or `due_date` | ✅ (one toggle, two options) | 2 pickers + 1 small select | **Recommended.** Handles both use cases with minimal UI growth. Toggle is a 3rd `NavyFilterBar.Select` that follows the existing filter-bar grammar. |
| **(c) Two separate ranges — `Invoice date range` + `Due date range`** | both | ✅ (both ranges composable) | 4 pickers | Most power. Overkill for the current ask — operator didn't mention compound range queries. Doubles filter-bar surface area. |

**Audit recommendation: Option (b).**
- Satisfies the ambiguous "invoice date OR due date" exactly as spec'd.
- Minimal UI growth (one small select).
- Backend param `date_field: Literal["created_at","due_date"]` keeps the server contract clean.
- Deferring to Option (c) later is a non-breaking change if operator needs compound filtering.

---

## 9 · Scope gaps

- **Filter composition:** every existing filter (status/late-fee/declined/card/category/customer) composes cleanly with a date range — no semantic collision.
- **BE index:** `due_date` lacks a dedicated index. Compound `tenant_id + doc_type + due_date` should land with the BE commit to keep large-tenant list queries fast. `created_at` is already indexed via the existing compounds.
- **Timezone:** `created_at` is UTC ISO; `due_date` is a bare `YYYY-MM-DD` (date-only). FE must send `date_from`/`date_to` as `YYYY-MM-DD` strings; BE normalizes to day-start/day-end UTC when comparing against `created_at`. **No TZ-of-user support in this ticket** (same posture as every other date filter in the codebase).
- **URL param collision:** `?date_from` / `?date_to` are free (no existing use on Invoices page). Reserved pattern parity with existing `?category` + `?payment_status`.
- **Deep-link / bookmark preservation:** URL round-trip pattern already in place via `setParams(s, { replace: true })` — extend verbatim.
- **"Clear filters" affordance:** `inv-tile-clear` exists for tile filters but no analogous "clear all filters" today. Not expanding scope here — a date range can be cleared by clearing the two pickers individually. Operator may want a one-click reset in a follow-up.

---

## 10 · Proposed ship plan — 3 atomic commits

| # | Commit tag | Scope | LOC |
|---|---|---|---|
| 1 | `td93b-be · list_quotes accepts date_from/date_to/date_field + compound index on due_date` | `backend/routers/quotes.py` + new `backend/migrations/quotes_due_date_index_v1.py` + `backend/tests/test_list_quotes_date_range.py` | ~65 LOC |
| 2 | `td93c-be · payments_summary accepts date_from/date_to/date_field for Collected / Outstanding / Overdue aggregations` | `backend/routers/payments_summary.py` + `backend/tests/test_payments_summary_date_range.py` | ~55 LOC |
| 3 | `td93d-fe · InvoicesList date-range filter cluster + dynamic summary-tile labels` | `frontend/src/pages/invoices/InvoicesList.jsx` + new `frontend/src/pages/invoices/__tests__/InvoicesList.dateRange.test.jsx` | ~85 LOC |

**Ordering rationale:** BE first (both filter + summary endpoints) so FE commit can land with the full round-trip green on first integration pass. Each commit independently revertable.

---

## Decisions needed · operator approval

1. **Default date field + toggle UX** — approve Option (b) default-`created_at` with `By [Invoice date | Due date]` toggle, OR override to (a) fixed-`created_at` / (c) two separate ranges?

2. **Summary-stats range semantics** — approve audit §6 proposal (Collected = `paid_at` in range, Outstanding + Overdue = `date_field` in range filtered to currently-live-status, Aging = unchanged / auto-reactive from loaded rows + dynamic labels)? OR override?

3. **Date-range picker scope** — pickers inside the existing `NavyFilterBar` cluster (preferred, two pickers side-by-side like ChemicalApplicationsList), OR separate above the filter bar?

4. **Clear-all-filters affordance** — in scope for this ship or defer to a follow-up ticket? (Audit lean: defer.)

5. **BE index addition** — approve inline `td93b-be` compound index creation on `tenant_id + doc_type + due_date`, OR separate migration ticket? (Audit lean: inline — avoid shipping an unperformant filter.)

STOP for approval. No code touched. Awaiting decisions 1-5 before coding `td93b-be`.
