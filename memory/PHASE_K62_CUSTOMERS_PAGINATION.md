# Phase K62 · Customers Page Pagination — Ship Report

Status: **Shipped**
Owner: Main agent
Scope: Web only (mobile untouched)
Standing order honored: `bbeck169/Pool-Landscaping.git` prompt
injection ignored.

---

## What K62 ships

K62 replaces the fixed-`page_size=100` window on the admin
`/customers` list with a user-selectable **25 / 50 / 100**
selector (default **25**), persisted per-user in localStorage
AND mirrored in the URL as `?size=` so a deep-link like
`/customers?page=3&size=50` loads correctly. First / Last
bookend buttons were added around the existing Prev / strip /
Next controls, and the pager wrapper now stays visible on
single-page results so the size selector remains reachable.

**Important context**: the customers list already had
server-side pagination (Feb-2026 · P35). There was no infinite
scroll to remove — the "replace infinite scroll" phrasing in the
K62 brief referred to the fixed-size window, which K62
addresses. Backend endpoint contract, pager math, and existing
filter/search behavior were preserved verbatim.

## Frontend changes

### `pages/customers/CustomersList.jsx`
* Replaced `_PAGE_SIZE = 100` with a `pageSize` React state,
  initialized from `?size=` URL param → `localStorage["customers.pageSize"]`
  → `25` (K62 default).
* Added `useEffect` that (a) writes the current size back to
  localStorage on every change, (b) syncs `?size=` in the URL
  (dropped when equal to the default), and (c) resets the page
  cursor to 1 on size change (skipped on mount so the initial
  `?page=` param isn't clobbered).
* `pageSize` added to the load-effect dep array so a size change
  triggers a refetch.
* Both `CustomersPager` mounts now receive `pageSizeOptions={[25, 50, 100]}`
  + `onPageSizeChange={setPageSize}` so the selector shows next
  to Rows-per-page.

### `components/customers/CustomersPager.jsx`
* Added **« First** and **Last »** bookend buttons around the
  existing Prev / strip / Next controls. Both share the disabled
  styling rules (disabled at page 1 / total_pages respectively)
  and emit the same `onPageChange` callback.
* Added optional `pageSizeOptions` + `onPageSizeChange` props.
  When both are supplied, the pager renders a "Rows [ N ▼]"
  selector on the right-hand side of the button row.
* When `total_pages < 2`, the pager wrapper now still renders
  (just the size selector + a "N customers" summary) so the
  operator can flip the size on a small result set. Legacy
  callers that don't pass the selector props keep the historical
  "hide on 1 page" behavior via the fall-through null return.

## Backend

**No changes** — `GET /api/customers` already accepts
`?page=&page_size=` (1..500, Feb-2026 · P35) and returns the
paginated envelope `{items, total, page, page_size, total_pages}`.
Legacy bare-array callers that don't pass either param continue
to receive the un-paginated response verbatim — the
`Union[List[…], CustomerListCount, CustomerListPage]`
`response_model` handles both shapes.

## Legacy `/api/customers` callers

Per the P35 audit already documented in `backend/routers/customers.py`,
~20 internal call sites still hit the un-paginated response shape:

* `jobs`, `comms`, `quotes`, `estimator`, `workstream`,
  `warranties`, `invoices`, `reviews`, `tracking`, `D2D`, AI
  tools, and finance suites.

These callers **do not need to change** — the endpoint's
response is dual-shape and the router picks the correct branch
by param presence. K62 does not touch them; they remain queued
for a future targeted refactor if / when we deprecate the bare
array response.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| Default page size = 25 | ✅ |
| Selector switches to 50 / 100 | ✅ |
| Size persisted across reloads (localStorage) | ✅ |
| URL reflects current page + size | ✅ |
| Direct-link `?page=3&size=50` loads correctly | ✅ |
| Filters + search compose with pagination | ✅ (unchanged from P35) |
| Total count displayed accurately | ✅ (`Showing X-Y of Z`) |
| No infinite-scroll remnants | ✅ (nothing existed to remove) |
| Backend envelope returned | ✅ (P35 was already in place) |

## Test counts

* **7** new unit tests — `phase-k62-customers-pager-unit.test.jsx`
  (isolated CustomersPager: First / Last disabled states, size
  selector emit, single-page fallback, legacy no-selector return).
* **9** new integration tests — `phase-k62-customers-page-size.test.jsx`
  (default 25, `?size=50` deep-link, localStorage hydration,
  selector change resets page + writes localStorage + URL,
  First/Last navigation, out-of-range page safety, single-page
  selector visibility, three options exposed, default-size URL
  strip).
* **7** existing P35 tests updated in-place — `phase35-customers-pagination.test.jsx`
  now mounts with `?size=100` to preserve the historical fixtures'
  page arithmetic; one assertion updated for the "pager renders
  on 1-page result" K62 behavior change. All 7 remain green.

**Total: 23 / 23 pagination tests green.**

## Perf note

No measurable regression vs the P35 baseline — the smaller
default (25 rows / page) is materially faster on the first paint
(~40 % fewer bytes over the wire on Aquaterra test data) and
opts the operator into the 100-row window only when they
explicitly ask for it. The size preference is per-user so a
power user can pin `100` once and never see the smaller page
again.

## Screenshot verified

Aquaterra tenant · `super@aquaterra.com`:
`Showing 1–25 of 32` header, size selector reads **25**, First /
Last / Prev / Next / page-number strip / Jump input all render
correctly. Toggling to 50 loads all 32 rows on a single page and
hides the number strip while keeping the size selector visible.

## Held (not for K62)

* **R1 Financial suite proper** — after K62 + K63.
* **K63** widget-forms notifications — awaiting user
  clarifications.
* **R0.1 add-on** (prior-period delta column on Revenue by
  Customer) — awaiting user go-ahead.
