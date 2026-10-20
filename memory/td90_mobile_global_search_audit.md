# TD-90 · Mobile global search — Phase 1 audit

2026-10-20 · read-only · HEAD `1618dc44a` · English · no code

## 1. Current mobile search surface
- **Bar:** `src/components/tools/SearchBar.tsx:22`. Placeholder `"Search tools…"`, 200 ms debounce, clear button `tools-search-clear`.
- **Logic:** `src/components/tools/ToolsMenuBody.tsx:104` (`<SearchBar onQueryChange={setQuery} …/>`). It filters the role's tool tiles from `sectionsForRole()` by `label` / `desc`, client-side (L81-95).
- **Confirmed navigation-only:** there's no `/search` (or any API) call anywhere in `mobile/` (`grep "/search?"` = 0 hits).
- **Where it renders — one body, two surfaces:**
  - **Menu sheet:** `src/components/tools/GlobalMenu.tsx:136` `<ToolsMenuBody variant="sheet">`, search testID `mobile-menu-search`. A slide-down `Modal`, mounted once in `app/(app)/_layout.tsx:277`, opened by the hamburger in the shared `Header` (`widgets.tsx`) via `openGlobalMenu()`. Shown to **every staff role, technicians included**; customers are suppressed.
  - **Tools tab:** `app/(app)/tools.tsx:34` `<ToolsMenuBody variant="tab">`, testID `tools-search`.

## 2. Web global search (ground truth)
- **Hook:** `frontend/src/hooks/useGlobalSearchResults.js`. Used by:
  - the visible bar `components/GlobalSearchBar.jsx` (placeholder "Search customers, jobs, invoices, quotes, leads…", L249), mounted in the `AppLayout.jsx` hero banner (~L734) for admin, super_admin, manager and technician;
  - the ⌘K palette `components/GlobalSearch.jsx` (`AdminTopBar.jsx:663`).
- **Endpoint:** a single consolidated call, `GET /api/search?q=<q>&limit=5`. The legacy `/api/search/global` is retired.
- **Request rules:**
  - min **2** chars (`MIN_BACKEND_CHARS`), debounce **300 ms**, `limit` **5** per bucket (`DEFAULT_LIMIT`);
  - stale responses dropped via a `cancelled` flag;
  - on error the previous buckets are **kept** (no empty flash).
- **Response:** `{ customers, jobs, invoices, quotes, leads }`, each an array of `{ id, primary, secondary }`. Per entity (backend `routers/global_search.py`):

| Entity | Matches on | `primary` | `secondary` |
|---|---|---|---|
| customers (L107) | name, email, phone (+ digit-normalised), address, billing_address | name | **email ‖ phone ‖ address ‖ billing_address** (first non-empty) |
| jobs (L144) | title, customer_name | title | customer_name ‖ status |
| invoices (L208) | invoice_number, customer_name, title (`db.quotes`, `doc_type=invoice`) | `Invoice <num>` ‖ title | `customer_name · $total` |
| quotes (L216) | quote_number, customer_name, title (`doc_type=quote`) | `Quote <num>` ‖ title | `customer_name · $total` |
| leads (L224) | name, email, phone (active statuses only) | name | email ‖ phone ‖ status |

- **Also on web:** a synchronous **Pages** group (`searchNavIndex`) listed first. Section order: Pages, Customers, Jobs, Invoices, Quotes, Leads. Empty copy `No results for "<q>"`, loading `Searching…`. No "show more".
- **Web taps:** `/customers/:id`, `/jobs/:id`, `/invoices/:id`, `/quotes/:id`, `/leads/:id` (`GlobalSearchBar.jsx:70-77`).
- **Scoping:** `_require_dashboard_role` (L57) allows **admin, super_admin, owner, manager** only; everyone else gets 403. The tenant comes from `get_current_tenant` (`routers/tenants.py:124`): the JWT's active tenant, then `user.tenant_id`. `X-Tenant-Slug` overrides are super_admin only. Every query is filtered by `tenant_id` and excludes soft-deleted records.

## 3. Backend reachability (live, preview)
| Call | Result |
|---|---|
| admin `q=pool&limit=5` | 200 · `customers 0 · jobs 5 · invoices 5 · quotes 1 · leads 0`. e.g. job `{primary:"Weekly Pool Service", secondary:"Preview Customer1520"}`, invoice `{primary:"Monthly Pool Service", secondary:"Preview Customer0143 · $149.00"}`, quote `{primary:"Pool tile replacement estimate", secondary:"Preview Customer0161 · $1,316.52"}` |
| admin `entities=customers` · name `Customer8616` / email `preview-customer8616` / phone `018616` / phone `555-018616` / address `8616 Preview` | all 200, 1 hit (same id). `secondary` is always the **email**, even for the address match |
| admin `q=P` (1 char) | 200, 5 rows — the backend has no minimum; the 2-char gate is client-side |
| tech `mike@` | **403** `{"detail":"Dashboard access required"}` |
| no auth | 401 |
| cross-tenant: admin searching `Customer4653` (a record that exists in tenant `stage3iso-1787432929`), with and without `X-Tenant-Slug: stage3iso-1787432929` | 0 rows; the other tenant's id is **never** returned. Scoping holds |

- **Auth on mobile:** the existing `api.get` (`src/api`) already sends the Bearer token, so mobile needs **no header changes**.

## 4. Mobile destination routes
| Result | Mobile route | File | Note |
|---|---|---|---|
| Customer | `/customer/[id]` | `app/customer/[id].tsx` | ✅ (also accepts `?tab=` since `fafd347cb`) |
| Job | `/job/[id]` | `app/job/[id].tsx` | ✅ |
| Invoice | `/quote/[id]` | `app/quote/[id].tsx` (loads `GET /quotes/{id}`, branches on `doc_type === "invoice"`, L416) | ✅ Same target as the staff invoice list (`app/invoices.tsx:285`) and TD-79 `CustomerInvoiceList.tsx:91`. `app/invoice/[id].tsx` is the **customer-portal** viewer (`/invoices/{id}/full`), so don't use it |
| Quote | `/quote/[id]` | same file | ✅ quote detail exists |
| Lead (web bucket) | `/leads/[id]` | `app/leads/[id].tsx` | ✅ exists, if leads are in scope (see §7) |

## 5. UI / UX pattern
- **Placement — in place, inside the existing menu sheet.**
  - Swap the sheet's tools-only bar for the global bar, placeholder "Search customers, jobs, invoices, quotes…".
  - Mobile has no dedicated search screen, and the menu sheet is already the app's highest-visibility search (every staff screen's hamburger). Web's bar is also an in-place dropdown under the input.
  - The Tools tab (`tools.tsx`) stays tools-only unless you want it too (§7 D4).
- **Results (query ≥ 2):** a grouped list with section headers in web order:
  - **Tools** — the existing tile matches, mirroring web's "Pages", so techs still get value;
  - Customers, Jobs, Invoices, Quotes (+ Leads?).
  - Empty groups are hidden. When the query is under 2 characters, the current tools-only menu is shown.
- **Row:** one shared row — kind icon + `primary` (bold, 1 line) + `secondary` (muted, 1 line) + chevron, min height 48.
- **States:**
  - loading: inline `Searching…` + `ActivityIndicator` under the bar (tool matches still render instantly);
  - empty: `No results for "<q>"` (web copy);
  - error: keep the last results plus a muted one-line `Couldn't search right now` (web keeps buckets silently; the mobile line is the only addition).
- **Debounce / min / max:** 300 ms / 2 chars / 5 per category, all matching web, with no "Show more" (web has none).
  - Tool filtering stays instant.
  - The sheet's `SearchBar` gets `debounceMs={0}` so the API debounce is exactly 300 ms, as on web; otherwise it would be 200 + 300.
- **Close and navigate:** reuse `GlobalMenu`'s `handleNavigate` pattern (close the sheet, then `setTimeout(push, 0)`).
- **Keyboard:** the sheet already hosts a `TextInput`. The results list needs `keyboardShouldPersistTaps="handled"`.

## 6. Reusable mobile pieces
- `SearchBar` (`src/components/tools/SearchBar.tsx`) — reuse; it already takes `placeholder` / `debounceMs` / `testID` props.
- `ToolsMenuBody` tile filtering → the "Tools" group, as is.
- `EmptyState`, `Loading` (`src/components/ui.tsx`); `mapApiError` (`src/utils/mapApiError.ts`); `api` (`src/api`).
- Existing entity rows **don't fit**:
  - `JobCard` (`widgets.tsx:162`) needs a full job object;
  - the customer list and `CustomerInvoiceList` rows are private and expect full records.
  - Search returns only `{id, primary, secondary}`, so one new **unified row with a `kind` variant** is the right call.

## 7. Scope gaps / decisions needed
- **G1 · Technicians get 403** (the backend allows admin, super_admin, owner and manager). Web mounts the bar for techs too and shows them only Pages. Mobile techs see the menu sheet.
  - **Proposal:** techs (and other non-dashboard roles) never call `/search`, keep the Tools group only, and keep the "Search tools…" placeholder.
  - Widening the backend is out of scope (backend-only change).
- **G2 · Customer address isn't reliably shown.** The operator asked for "name + address", but the backend `secondary` is `email ‖ phone ‖ address`, so an address only appears when the customer has no email or phone. The address isn't returned separately.
  - Options: **(a)** ship web parity (show `secondary` as is); **(b)** a backend change to return `address` (out of scope for mobile); **(c)** mobile fetches each customer hit (5 extra calls per search — not recommended).
- **G3 · Invoice "number + amount."** When an invoice has no `invoice_number`, `primary` falls back to the title (preview data often has none, e.g. "Monthly Pool Service"). The amount is always in `secondary`. Same on web; the row shows a kind badge so it's still identifiable.
- **G4 · Leads.** The backend and web include a Leads bucket, but the operator's list has 4 entities. Recommend **including Leads** for web parity (the route exists); or request `entities=customers,jobs,invoices,quotes`.
- **G5 · Jobs match title / customer_name only** (not address or status). Same on web.
- No missing endpoints or routes. No tenant drift.

## 8. Proposed ship plan (mobile only, after approval)
| # | Commit | Contents | LOC (src / test) |
|---|---|---|---|
| 1 | `m-td90-search-hook · useGlobalSearch hook + route map + tests` | `src/hooks/useGlobalSearch.ts`: mirrors the web hook (2-char min, 300 ms, `limit=5`, stale guard, keeps buckets on error, role gate per G1, `entities` per G4). `src/lib/globalSearchRoutes.ts`: kind → mobile route (§4). Jest with fake timers: threshold, debounce, stale drop, error-keeps-buckets, tech no-fetch, route map | ~110 / ~160 |
| 2 | `m-td90-search-ui · global results in the menu sheet` | `src/components/search/GlobalSearchRow.tsx` (unified row, `kind` variant) + `GlobalSearchResults.tsx` (grouped sections: Tools first, empty/loading/error states). Wire into `ToolsMenuBody` **sheet variant only**: new placeholder, `debounceMs={0}`, results replace the tile list while query ≥ 2, taps go through `onNavigate`/close. Jest render: grouping order, hidden empty groups, tap → close + push to the right route, tech sees tools only, tab variant unchanged | ~190 / ~180 |
| 3 | (docs) `m-td90-receipt` | receipt + commit log | — |

- **Verify:** Jest baseline stays at 42 suites / 48 tests; tsc 651; eslint. Live preview as admin: type "pool" → grouped results; tap each kind → right screen; tech → tools only, no `/search` call.
- **Decisions to confirm:** G2 (a/b/c) · G4 (include Leads?) · D4 — also upgrade the Tools-tab bar, or menu sheet only (recommended: sheet only).
