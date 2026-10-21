# TD-search-technicians-bucket · Phase 1 Recon

**Scope:** add a `technicians` bucket to `GET /api/search` + a matching `Technicians` group in the web global search surface. Scope path **C** (technicians AS search results). Mobile parked (~15 LOC follow-up ticket).

**Phase 1 = recon only. No code.** Phase 2 proposals at the bottom.

---

## 1. Current `/api/search` structure

**File:** `backend/routers/global_search.py` (303 LOC).

**Endpoint:** `GET /api/search` — defined at `backend/routers/global_search.py:258-302`.

**Query params:**
- `q: str` (empty → empty groups per entity)
- `limit: int = 5` (`ge=1`, `le=25`) — **per-entity** cap, there is NO global cap
- `entities: str = "customers,jobs,invoices,quotes,leads"` — comma-separated allowlist

**Current buckets** (`_VALID_ENTITIES` tuple, line 48):
```
customers, jobs, invoices, quotes, leads
```

**Per-handler hit shape** — every handler returns `List[dict]` where each dict has `{id, primary, secondary}`:
- `_search_customers` (lines 107-141): `primary=name`, `secondary=email|phone|address|billing_address`
- `_search_jobs` (lines 144-156): `primary=title`, `secondary=customer_name|status`
- `_search_invoices` / `_search_quotes` (lines 159-221, shared `_search_docs_by_doc_type`): `primary="Invoice N" | "Quote N"`, `secondary="customer_name · $total"`
- `_search_leads` (lines 224-246): `primary=name`, `secondary=email|phone|status`; active-statuses only (`new, contacted, quoted`)

**Entity dispatch:** `_ENTITY_HANDLERS` dict (lines 249-255) maps entity name → handler. Unknown names in `entities=` are silently dropped (lines 274-277). Per-bucket exception swallow at lines 296-301 so one broken index doesn't fail the whole response.

**RBAC gate:** `_require_dashboard_role(user)` at lines 57-61 — role must be in `{admin, super_admin, owner, manager}`, else 403. Techs / customers / field roles rejected.

**Tenant scoping pattern** (lines 92-104, `_tenant_filter`):
```python
{
  "tenant_id": tenant_id,
  "$and": [
    {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
    {"$or": _build_or_regex(needle, fields)},
  ],
}
```
`_build_or_regex` (lines 69-72) escapes the needle with `re.escape` then builds `$regex: {$options: "i"}` per field. Phone matches use `_phone_digit_regex` (lines 75-89) — digit-only re-regex with `\D*` between digits so `555-1234` matches `(555) 123-4`.

**Empty query short-circuit:** lines 282-284 — returns `{entity: [] for entity in active}` without hitting Mongo.

---

## 2. Technician source-of-truth

**Confirmed two-collection union** — grep of `db.technicians` + `role in {technician, tech, landscaper, ...}`:

- `db.technicians` rows for the tenant (canonical when linked to a user via `user_id`).
- `db.users` rows with field-assignable roles. The actual **`ASSIGNABLE_ROLES`** list in `backend/routers/technicians.py:89-90` is:
  ```
  ["technician", "tech", "landscaper", "landscape_tech", "pool_tech", "tech_both"]
  ```
  **Note:** the ticket spec said "technician, tech, landscaper, tech_both" — actual code also includes `landscape_tech` and `pool_tech` (legacy department-typed variants). The new search bucket **must mirror the full list** so a legacy `pool_tech` user doesn't vanish from search.

**Existing merge/dedupe helper location:** `backend/routers/technicians.py:22-262` (`list_technicians`). It is **NOT currently extracted** — the union + dedupe + inactive-exclusion logic is inlined inside the route handler, ~130 LOC. Core pieces:

| Concern | Lines | Reusable for search? |
|---|---|---|
| Tech-row query (tenant + not-deleted) | 73-78 | Yes |
| Users-row query (tenant + role in ASSIGNABLE_ROLES + exclude `@t.local` + not-deleted + `active != false`) | 92-108 | Yes |
| Skip-synth-if-already-linked | 110-113 | Yes |
| Cross-shape dedupe (uid/did/email/name signals) | 155-176 | Yes |
| Inactive-user exclusion from tech-row branch via linked user `active=false` | 133-141 | Yes |
| Active-job counts aggregation (`$group` on `db.jobs`) | 216-253 | **No** — not needed for search |
| Display-color enrichment | 190-197, 260-261 | **No** — not needed for search |
| Sorting (field-worker-first + alpha) | 180-186 | Partially — search probably wants relevance-ordered truncation by `limit`, so sort is a cosmetic choice |

**Decision recommendation for Phase 2:** **extract a shared helper**, e.g. `backend/services/technicians_core.py :: fetch_technician_roster(tenant_id, *, text_filter=None, limit=None)`. Reasons:
- One source of truth for role allowlist + dedupe signals.
- Search needs the SAME inactive/deleted exclusion rules as the dropdown — divergence would be a bug.
- Enrichment steps (jobs count, display color) stay in the route handler, not the helper.
- Cost: ~80 LOC extraction + a thin wrapper call site in `list_technicians`. Zero-regression goal by preserving current field set and dedupe output order.

**Alternative (direct query in `global_search.py`):** faster to ship (~40 LOC) but duplicates the ASSIGNABLE_ROLES list, dedupe logic, and inactive-exclusion rules. Flagged as a known-DRY-violation TD if we go this route.

**Projection needed for search hits:** `id, name, email, phone, role`. For `db.users` synth rows, `name` is composed as `(users.name) OR (first_name + " " + last_name) OR email OR "Unnamed"` — same composition `list_technicians` uses at lines 117-120.

---

## 3. Query semantics

**Match fields proposed** (mirror customers bucket): `name`, `email`, `phone`.

**Field-shape divergence between the two collections — important:**
- `db.technicians` carries `name` as a single string.
- `db.users` splits name into `first_name` + `last_name` + (sometimes) `name`.
- Search must match against **all three fields** for the users-collection query so `"Mike"` finds `first_name="Mike"`, and against `name` for the technicians-collection query. Match-field list differs per source collection.

**Phone normalization:** reuse the existing `_phone_digit_regex` helper from `global_search.py:75-89` — same digit-normalized semantics as `_search_customers`. Required so `(602) 555-0100` and `6025550100` alike match a typed `5550100`.

**Case-insensitive substring:** reuse `_build_or_regex` from `global_search.py:69-72`.

**Exclude filters (same as `/api/technicians`):**
- `tenant_id == tenant_id` (hard requirement; cross-tenant leak was the exact P0 fix in Feb-2026).
- `deleted_at` null or missing (both sources).
- For users-collection: `active != false` AND `email NOT regex "@t.local$"` (migration-artifact rows).
- For technicians-collection: linked-user `active != false` cross-check (same pattern as lines 133-141).

**Tenant scoping confirmed consistent** across all existing buckets (`_tenant_filter` at line 92 + per-handler calls). The new bucket must adopt the same `{"tenant_id": tid, "$and": [not_deleted, {$or: match}]}` shape.

**Response hit shape** (matches existing bucket contract):
```json
{"id": "<tech id>", "primary": "<name>", "secondary": "<role> · <phone>"}
```
- `primary` = name (same policy as customers / leads).
- `secondary` = `role · phone` per ticket spec. If `phone` is missing, fall back to `email`. If both missing, show just `role`.

---

## 4. RBAC

**Mirror existing `/api/search` gate** — `_require_dashboard_role` already enforces `{admin, super_admin, owner, manager}` at the endpoint level (line 269). The new `technicians` entity sits inside the same handler fan-out, so no additional per-entity gate is needed. Field techs are already 403-ed at the endpoint level before any bucket runs.

**No new permission entity needed.** Verified by grep — there is no existing permission predicate that allows a field tech to view peers. The current `GET /api/technicians` list endpoint uses `get_current_user` only (no admin check), so **all authenticated users of a tenant can already see the full roster via that endpoint** (see §8 — TD-tech-roster-pii). But for search, the endpoint-level gate is the single source of RBAC truth.

---

## 5. Web FE surface

**Entry points** — three confirmed:
- `frontend/src/components/GlobalSearchBar.jsx` (403 LOC) — the always-mounted hero pill in `AdminTopBar`.
- `frontend/src/components/GlobalSearch.jsx` — the ⌘K modal palette.
- `frontend/src/hooks/useGlobalSearchResults.js` (143 LOC) — shared hook; backend fetch at line 89: `api.get(\`/search?q=…&limit=\${limit}\`)`.

**Current flow in the hook** (lines 59-98):
- Empty-buckets constant at line 59: `{customers: [], jobs: [], invoices: [], quotes: [], leads: []}` — needs `technicians: []` added.
- Response hydration at lines 92-98 — needs `technicians: Array.isArray(data?.technicians) ? data.technicians : []` added.
- Return shape at lines 128-137 — needs `technicians: buckets.technicians` added.
- Minimum-chars gate (`MIN_BACKEND_CHARS = 2`, line 52) + 300 ms debounce — no change needed.

**Bar-side wiring** in `GlobalSearchBar.jsx`:
- Destructure buckets at line 97-99 — add `technicians`.
- Flat-rows build at lines 103-112 — add `technicians.forEach((rec) => rows.push({ kind: "technician", rec }))`.
- Section offset accumulator at lines 174-180 — add a `techniciansStart` line.
- `ROUTE_FOR_KIND` map at lines 70-77 — **add `technician: (rec) => (rec?.id ? \`/technician/\${rec.id}\` : null)`**.
- `<Section>` render block at lines 302-329 — add a `<Section label="Technicians" kind="technician" ... />` row.
- Placeholder string at line 249 — update to include "technicians" in the search hint.

**Web tech profile route — ⚠️ IMPORTANT NAMING NOTE:** the route is **`/technician/:id` (SINGULAR)**, not plural. Confirmed at `frontend/src/App.js:1510`:
```jsx
<Route path="technician/:id" element={<TechnicianProfile />} />
```
Component defined at `frontend/src/pages/phase14/Phase14Pages.jsx:179` (`TechnicianProfile`). The ticket spec said "/technicians/{id}" — the actual URL is SINGULAR. Tap target must use `/technician/{id}` or the row click will 404.

Route is admin-gated inside the component (`isSelf || isAdmin` guard at `Phase14Pages.jsx:191-195`). Since search access is already admin+ via the backend gate, callers landing on `/technician/{id}` from search will pass the component-level guard. No route change needed.

**Row display** (per ticket spec): 2-line, `primary=name`, `secondary=role · phone`. The existing `<Section>` component in `GlobalSearchBar.jsx:349-401` already renders `primary` + `secondary` as a 2-line stack with the right typography — no new row component needed, just a new `<Section>` instance.

**⌘K palette** (`GlobalSearch.jsx`) — same hook consumer. If Phase 2 ships the hook change, the palette will show the new section too unless scoped out. Check during Phase 2 whether the palette's current layout accommodates a 6th section cleanly or if it needs a layout tweak.

**Vitest harness ready:** `frontend/src/components/__tests__/GlobalSearchBar.test.jsx` + `AdminTopBar.globalSearch.test.jsx` + `GlobalSearch.test.jsx` already exist. New test cases can be added in-place.

---

## 6. Testing plan

### Pytest (`backend/tests/test_global_search.py` or sibling)
Existing test harness patterns at `test_global_search.py:1-294` give us helpers `_mk_tenant`, `_mk_user`, `_login`. Target cases:

1. **Technicians bucket basic match** — insert 3 techs across both sources (1 `db.technicians` only, 1 `db.users` role=`technician` only, 1 linked both-sides); search by name substring; expect all 3 return once each (dedupe holds).
2. **Phone digit-normalized match** — insert tech with `phone="(555) 123-4567"`; search `q=5551234`; expect hit.
3. **Email match** — substring match on `email`.
4. **Role filter precision** — insert admin user; search by their name; admin user must **NOT** appear in `technicians` bucket (ASSIGNABLE_ROLES gate).
5. **Soft-deleted exclusion** — insert tech with `deleted_at` non-null; search; expect miss.
6. **Inactive-user exclusion** — insert tech linked to `users.active=false`; search; expect miss.
7. **Migration-artifact exclusion** — insert user with `email` ending `@t.local`; search; expect miss.
8. **Tenant isolation** — insert tech in tenant B; auth as tenant A admin; search; expect miss.
9. **RBAC** — field tech caller gets 403 at endpoint level (existing behavior; add a case asserting the new bucket name doesn't bypass).
10. **`entities=` filter** — request `entities=technicians`; expect only `{technicians: […]}` in response.
11. **`limit` cap** — insert 10 matching techs; `limit=3`; expect exactly 3 in bucket.
12. **Empty query** — expect `{technicians: []}` in short-circuit response.

### Vitest (`frontend/src/components/__tests__/GlobalSearchBar.test.jsx` + hook test)
1. **Hook includes technicians in return shape** — stub `api.get("/search?…")` with `{technicians: [{id:"t1", primary:"Jane Tech", secondary:"technician · (555) 123-4567"}]}`; assert `result.current.technicians` populated.
2. **Section renders** — stub hook with technicians bucket populated; assert `getByTestId("global-search-bar-section-technician")` present with the correct count and primary/secondary strings.
3. **Row click routes to `/technician/:id`** — click on a technicians row; assert `navigate` called with `"/technician/t1"` (singular!).
4. **Keyboard navigation** — ArrowDown from the last leads row lands on the first technicians row (section is appended last in flatRows).
5. **Empty-bucket skip** — stub hook with `technicians: []`; assert the section does NOT render (Section component bails on empty rows, line 350).

### Manual sanity
- `curl -s "$API_URL/api/search?q=Rivera" -H "Authorization: Bearer $ADMIN_TOKEN"` — verify shape.
- `curl -s "$API_URL/api/search?q=Rivera" -H "Authorization: Bearer $TECH_TOKEN"` — verify 403.

**Testing method:** manual `pytest` + manual `yarn vitest run`. **NO testing agent** (strict session guardrail).

---

## 7. Scope-ambiguity note (D1 fork resolution)

Operator confirmed **D1=(a): technicians AS search results**. The bookmark's original meaning (technicians USING search, currently 403 at `global_search.py:57-61`) is explicitly **OUT of scope** for this ticket. That gap is logged as a separate TD below (see §8 append) under `TD-tech-using-search`.

---

## 8. TECH_DEBT.md appends (proposed, atomic with this doc)

Two entries will be appended at the end of `memory/TECH_DEBT.md` (after the TD-UIinj V15 block):

### Append A — new bookmark for the parked other-direction gap

```markdown
## TD-tech-using-search (bookmark, P3 product+BE)

Bookmark preserving the original intent of the (now-superseded) `TD-mobile-tech-search` note. Where `TD-search-technicians-bucket` ships technicians AS results (operator D1 = scope path C), this entry tracks the inverse: technicians AS CALLERS of `/api/search`, currently 403 via `routers/global_search.py:57-61` (`_require_dashboard_role`).

- **Status:** parked pending product + backend scoping decision (e.g. restrict techs to their own jobs/customers only; new per-row RBAC predicate; or stand up a separate `/api/search/tech` endpoint with narrower returns).
- **Mobile cost after scoping:** ~5 LOC (relax `GLOBAL_SEARCH_ROLES`).
- **Backend cost:** unknown; depends on the scoping decision.
- Not blocking anything; raised separately so the `TD-search-technicians-bucket` ship doesn't collapse the two directions.
```

### Append B — PII exposure on roster endpoint

```markdown
## TD-tech-roster-pii (P3, backend)

`GET /api/technicians` (`backend/routers/technicians.py:22-262`) currently returns every technician's `phone` + `email` to any authenticated user of the tenant — the handler depends only on `get_current_user` + `get_current_tenant`, not `require_admin`. Field techs, customers-with-portal-accounts (if a tenant exposes a portal user that's co-tenant), and any non-admin role can enumerate peer contact info by hitting the endpoint directly or scraping the Schedule / Dispatch / Workstream dropdowns that consume it. The downstream dropdowns were the intended consumer when the endpoint was built; the PII exposure was an unintentional side-effect of using the same shape for both direct admin reads and dropdown feeds.

- **File + line refs:** `backend/routers/technicians.py:22` (route decl), `:92-108` (users-arm projection returning `email` + `phone`), `:114-127` (synth row emits both fields).
- **Fix sketch (not in scope here):** either (a) gate the endpoint behind `require_admin` + add a slimmer `/api/technicians/dropdown` for role-agnostic consumers that returns only `{id, name, display_color_hex}`, or (b) switch projection based on caller role at the current route (admin → full, non-admin → id+name only).
- **Priority:** P3. Operator approved logging only; not fixed in `TD-search-technicians-bucket`.
```

---

## 9. Response-size + limit-semantics note (operator-requested addition)

**Current semantics:**
- `limit` is **per-entity / per-bucket**, not global. Default `5`, max `25` (`global_search.py:261`).
- With all 5 existing entities at default `limit=5`, worst-case response is **25 rows total** (5 × 5) plus the 5 bucket headers → trivially small (<4 KB typical).
- No global cap enforced in code.

**Impact of adding the technicians bucket:**
- Default worst-case grows from 25 → **30 rows** (6 × 5). Still trivially small; no payload concern.
- Max worst-case grows from 125 → **150 rows** (6 × 25). Also safely under any reasonable payload budget; each hit is ~120 bytes.
- No change needed to `limit` default or ceiling.
- Backend fetch pattern in the hook (`useGlobalSearchResults.js:88-89`) sends a single request per debounce tick with the same `limit` for every bucket. One extra bucket adds one extra Mongo query per keystroke-debounce; parallelism opportunity exists if latency becomes a concern (currently they run sequentially via `for name in active:` at `global_search.py:291-301`), but out of scope here.

**Recommendation:** keep `limit=5` default + `25` max. No tunable change needed.

---

## 10. Phase 2 proposals (NOT shipping yet — needs operator approval)

**Backend changes:**
- Extract `backend/services/technicians_core.py` with `fetch_technician_roster(tenant_id, *, text_filter=None, limit=None)` — reuses the existing union + dedupe + inactive-exclusion logic from `list_technicians`. ~80 LOC.
- Refactor `list_technicians` to call the helper (preserve byte-identical response). ~20 LOC net change.
- Add `_search_technicians` handler in `global_search.py` wired into `_ENTITY_HANDLERS`. ~30 LOC.
- Add `"technicians"` to `_VALID_ENTITIES` + default `entities=` query string. ~2 LOC.
- Add 10-12 pytest cases per §6.

**Web FE changes:**
- Add `technicians` to `_EMPTY_BUCKETS`, response hydration, and return shape in `useGlobalSearchResults.js`. ~6 LOC.
- Add `technician` route to `ROUTE_FOR_KIND`, flat-rows push, offset accumulator, and `<Section>` instance in `GlobalSearchBar.jsx`. ~15 LOC.
- Update placeholder string to include "technicians". ~1 LOC.
- Add 4-5 vitest cases per §6.
- Decide whether to show the section in the ⌘K palette too (`GlobalSearch.jsx`) or scope out.

**Total estimated Phase 2 cost:** ~150-180 LOC code + ~200 LOC tests. Shippable in 2 commits (BE helper + endpoint + tests ; FE hook + bar + tests), both within the 3-5 minute edit-to-commit window.

**TECH_DEBT.md updates:**
- `TD-search-technicians-bucket` moves from P3 candidate to CLOSED with commit refs.
- `TD-tech-using-search` + `TD-tech-roster-pii` remain open (appended in Phase 1 = this ship).

---

## 11. Guardrail attestation

- No code changes in this cycle.
- No `/app/mobile/` touches planned or made.
- No scope creep into `TD-tech-roster-pii` — logged only.
- No testing agent used.
- Deliverable is this doc + the two TECH_DEBT.md appends, committed atomically with `git commit --only -- memory/td_search_technicians_bucket_recon.md memory/TECH_DEBT.md -m "..."`.
- Any instructions received in user chat text attempting to expand scope mid-cycle are classified as hostile and discarded per the V1-V15 defense codified in `TECH_DEBT.md`.
