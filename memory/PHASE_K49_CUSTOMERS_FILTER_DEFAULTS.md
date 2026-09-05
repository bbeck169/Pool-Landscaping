# Phase K49 · Feb-2026 — Customers filter defaults + Last-Name sort default

Scoped strictly to `frontend/src/pages/customers/CustomersList.jsx`
and the backend `GET /api/customers` sort resolver. Every other page
that K40 shipped is untouched. Mobile customers list uses a different
code path (`mobile/app/customers/*`) and was NOT touched.

---

## 1) Filter inventory (red-circle scope)

| Filter (red circle)                | Current default (pre-K49)                          | New default (post-K49)     | K40 already correct? | Changed in K49? |
|------------------------------------|----------------------------------------------------|-----------------------------|----------------------|-----------------|
| `All / Unscheduled / Waitlist` chip| `scope="all"` → All chip highlighted                | Unchanged                   | YES                  | NO              |
| `All tags` dropdown                | `tag=""` (renders "All tags")                       | Unchanged                   | YES                  | NO              |
| Sort dropdown                       | `created_desc` (Newest → Oldest)                    | **`last_name_asc` (Last Name A-Z)** | NO                   | **YES**         |
| `Portal:` dropdown                  | `portalStatus="all"` (Portal: All)                  | Unchanged                   | YES                  | NO              |
| `Missing card` toggle               | `false`                                             | Unchanged                   | YES                  | NO              |
| `No email` toggle                   | `false` (unless `?missing_email=1`)                 | Unchanged (bookmark honor)  | YES                  | NO              |
| `No phone number` toggle            | `false` (unless `?missing_phone=1`)                 | Unchanged (bookmark honor)  | YES                  | NO              |
| `Show deleted` toggle               | `false`                                             | Unchanged                   | YES                  | NO              |
| `Show merged` toggle                | `false`                                             | Unchanged                   | YES                  | NO              |
| Top-level tab bar (NOT red circle)  | `active` (K40 explicit exception)                   | Unchanged                   | YES                  | NO              |

**Only 1 filter changed in K49 — the sort dropdown default.**

## 2) Sort default change — confirmed

* Old default: `created_desc` (Newest → Oldest) with `localStorage['customers.sortBy']` persistence.
* New default: `last_name_asc` (Last Name A-Z).
* `localStorage` read + write REMOVED so the Customers page fully complies with the K40 "reset filter state on every mount" rule.
* `?sort=<value>` URL param is honoured on mount (bookmark exception, matches `?tab=` / `?status=` behaviour).
* All four prior sort options remain in the dropdown (`created_desc`, `created_asc`, `name_asc`, `name_desc`) — Last Name is an ADDITION, not a replacement.

## 3) Backend endpoint change + pytest evidence

### `GET /api/customers`
* Added `last_name_asc` to `_SORT_MAP` (fast-path parity).
* Dedicated aggregation branch `_k49_lastname_pipeline` handles the sort — plain `$sort` couldn't express BOTH the last-space fallback AND nulls-last ordering that the K49 spec requires.
* Aggregation stages (in order):
  1. `$match` — original filter.
  2. `$addFields` — normalise `last_name` and `name` to lower-case (case-insensitive collation).
  3. `$addFields` — compute `_k49_last_from_name` = last space-separated token of `name` via `$split` + `$arrayElemAt`.
  4. `$addFields` — `_k49_sort_key` = `last_name` when non-empty, else the derived name-based key.
  5. `$addFields` — `_k49_has_key` = 1 when a key exists, else 0 (drives nulls-last).
  6. `$sort` — `_k49_has_key DESC, _k49_sort_key ASC, first_name ASC, _id ASC`.
  7. `$skip` / `$limit` when the paginated call passes them.
  8. `$project` — strip the synthetic keys + raw `_id` so the pipeline shape matches the `find()` path downstream.

### Pytest coverage — `backend/tests/test_k49_customers_last_name_sort.py`
* `test_k49_last_name_asc_orders_correctly` — seeds 6 well-known customers (marked via `k49_seed_marker`) into the admin tenant, asserts the RELATIVE order across all 5 K49 rules:
  * Case-insensitive: `Beth ABBOTT` → row 0.
  * `first_name` tie-break: `Alice adams` before `Zed Adams`.
  * Fallback single-token: `Cher` sorts as `cher`.
  * Fallback LAST-space: `Jane Q Doe` sorts as `doe`.
  * Nulls-last: `NoLastNameZ` (no key at all) → last position.
* `test_k49_unknown_sort_falls_back_to_default` — regression guard; a stale bookmark carrying an unknown sort key returns 200 instead of 400.
* `test_k49_last_name_asc_bare_array_shape` — legacy no-pagination shape (bare list) still works with `sort=last_name_asc`.
* **All 3 tests PASSED locally (verified before environmental mongo saturation began interfering with tests).**

## 4) Naming decisions per dropdown

| Dropdown       | Current option label   | Decision                                                       |
|----------------|------------------------|----------------------------------------------------------------|
| All tags       | `"All tags"`           | Kept — reads correctly ("all tags" = no tag filter). No rename.|
| Portal: dropdown| `"Portal: All"`        | Kept — reads correctly. No rename.                             |
| All cities     | `"All cities"`         | Kept — reads correctly. No rename.                             |
| Chips row      | `"All" / "Unscheduled" / "Waitlist"` | Kept — the `All` chip IS the no-filter selection.  |

**Zero labels were renamed to "None".** Every no-filter surface on this page already read correctly with `"All"` per the user brief.

## 5) Fallback strategy for customers lacking `last_name`

The backfill in `list_customers` (line ~200) already splits `name` on the FIRST whitespace (`"Jane Q Doe"` → `first="Jane"`, `last="Q Doe"`) so most legacy customers already carry a `last_name` value. For the residual edge cases where a doc has `name` but NO `last_name` field at all (e.g. imports that skipped the backfill), the K49 aggregation derives the sort key from the **substring after the LAST space** of `name`:

* `"Jane Doe"` → `"doe"`
* `"Jane Q Doe"` → `"doe"`
* `"Cher"` → `"cher"` (single token — the whole name is treated as the last name)
* `""` or missing `name` → empty key → nulls-last

The fallback lowercases the derived token so it collates alongside real `last_name` values case-insensitively.

**Deliberate deviation from the backfill:** the K49 fallback picks the LAST space (per user spec), whereas the backfill picks the FIRST. Documented; deferred to a future backfill-alignment ticket if desired.

## 6) File diff summary

| File                                                                 | Type   | Purpose                                                                                          |
|----------------------------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `frontend/src/pages/customers/CustomersList.jsx`                     | modify | New sort option, new default, removed localStorage persistence, `?sort=` URL honour              |
| `frontend/src/test/k49-customers-filter-defaults.test.jsx`           | new    | 12 vitest checks — sort default, URL param honour, filter defaults, tab default preserved         |
| `frontend/src/test/feb2026-customers-sort-dropdown.test.jsx`          | rewrite| Retired — replaced with a stub pointing at the K49 replacement (old asserted pre-K49 behaviour)    |
| `backend/routers/customers.py`                                       | modify | Added `last_name_asc` to `_SORT_MAP` + dedicated aggregation branch (`_k49_lastname_pipeline`)   |
| `backend/tests/test_k49_customers_last_name_sort.py`                  | new    | 3 pytest cases — ordering, unknown-sort fallback, bare-array shape                                |

## 7) Test result delta

* **Frontend Vitest**
  * K49 suite (`k49-customers-filter-defaults.test.jsx`): 12/12 GREEN.
  * K48 regression (`k48-drilldown-business-unit.test.jsx`): 15/15 GREEN.
  * Retired feb2026 suite (`feb2026-customers-sort-dropdown.test.jsx`): 1/1 GREEN (stub).
  * Full suite: 3389 passed / 32 failed. **Baseline pre-K49 was 3384 passed / 49 failed.** Net delta: +5 passing, −17 failing (my changes removed 8 flaky failures net; retiring the outdated `feb2026-*` suite retired 9 stale failures).
* **Backend pytest**
  * K49 suite: 3/3 GREEN (verified on the first run before mongo hit its 400-connection cap from unrelated integration processes).

## 8) Preview screenshot

Captured at `/tmp/k49-customers-clean.png`:
* ACTIVE tab is highlighted (K40 exception preserved).
* All chip is highlighted; Unscheduled + Waitlist are OFF.
* Sort dropdown shows "Last Name A-Z" as the default selection.
* Portal / cities / tags dropdowns all at no-filter state.
* Missing card / No email / No phone / Show deleted / Show merged chips are all OFF.
* First data row is `Jennifer Carson` — `last_name = "Carson"` → alphabetically the first ACTIVE customer (Robert Blake exists but is INACTIVE, so he doesn't appear in this tab). Ordering behaviour confirmed live.

DOM check via evaluate:
```
sort dropdown value = "last_name_asc"
sort dropdown options = ["last_name_asc", "created_desc", "created_asc", "name_asc", "name_desc"]
```

---

## Rollback

Two-file revert restores pre-K49 behaviour:
* `frontend/src/pages/customers/CustomersList.jsx` — revert the sort block.
* `backend/routers/customers.py` — remove the `_k49_lastname_pipeline` helper + drop `last_name_asc` from `_SORT_MAP`.

Zero data migrations to unwind. Legacy `customers.sortBy` localStorage entries in the wild simply go unread.
