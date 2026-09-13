# HOUSEKEEPING · P2 dispatch (fixture polish + flake stabilization)

**Status:** Shipped (Preview).
**Owner:** main agent.
**Ship-date:** Feb-2026.
**Interrupted mid-dispatch by a pod-outage / credit exhaustion; resumed
on recharge. Item 1 landed fully; Item 2 landed one file plus a
pre-classified inventory for the next dispatch.**

---

## 1 · What shipped

### Item 1 · `test_quote_duplicate.py` fixture polish

**Approach:** rather than mutate the aquaterra fixture tenant's
customer data (which would leak state into every other test suite),
each property-dependent case now **self-provisions** the property it
needs and cleans up in a `try/finally`.

Added helpers to the test file:

- `_ensure_active_property(sess, customer_id, label="Fixture Probe")` —
  returns an existing active property when present; otherwise POSTs a
  fresh one against `POST /api/customers/{cid}/properties` with a
  minimal but schema-valid address. Returns `(prop_dict, created_bool)`
  so the caller can conditionally clean up.
- `_delete_property(sess, pid)` — best-effort DELETE for the cleanup
  path.

**Case-by-case status:**

| Case | Before | After | How |
| ---- | ------ | ----- | --- |
| 2 · explicit property_id on other customer | skip | **pass** | `_ensure_active_property(customer_b)` + finally cleanup |
| 3 · no property_id, exactly-1 active → auto-assign | skip | **pass** | ensure + count-check + finally cleanup |
| 3b · no property_id, 0 or >1 active → null | pass | **pass** | untouched — was already exercising the null branch |
| 4 · mismatched property_id → 422 | skip | **pass** | `_ensure_active_property(customer_a)` + finally cleanup |
| 6 · declined-line source → new is pending | skip | **skip** | legitimate blocker — see section 2 |
| 7 · accepted source → new is draft | skip | **pass** | rewired to use the magic-link `/accept` endpoint (the `customer-decision` route in the pre-fix test does not exist in this codebase) |

**Result: 8 pass / 5 skip → 12 pass / 1 skip / 0 fail** (13 total).
+4 unblocked; the remaining 1 is a real code-change item, not a
fixture gap.

### Item 2 · Frontend flake — one file fixed

- **`frontend/src/test/settings-nav-old-routes.test.jsx`** — Category
  (c) **DOM/data-contract drift**. The SECTIONS canonical-key list
  was 5 keys pre-Business-Settings; the earlier feature dispatch added
  a 6th key (`"business"`). Test's `toEqual` was still asserting the
  old 5-key list. Bumped expected to 6 keys and updated the "canonical
  keys" comment. **Result: 10/10 pass.**

Full flake sweep across the remaining 8 files is deferred; a
pre-classified inventory follows in section 3 so the next dispatch
can go straight to fixes.

---

## 2 · Case 6 blocker — deferred follow-up ticket

**Case:** `test_duplicate_resets_declined_lines_to_pending`
**File:** `backend/tests/test_quote_duplicate.py:397`

**Symptom:** to stage a declined line on the source quote before
duplicating, the test tries to hit
`POST /api/portal/quotes/via-token/{token}/line-items/0/decline`.
The endpoint returns **HTTP 409** with body
`{"detail":{"error_code":"not_actionable","status":"draft","message":"Estimate can only be acted on while it's in 'sent' or 'viewed' state."}}`.

**Why this is a code-change item, not a fixture gap:**

1. The per-line decline endpoint enforces an actionable-window gate
   (`status ∈ {sent, viewed}`).
2. A freshly-`POST /api/quotes`'d quote starts in `status="draft"`.
3. To flip a quote from `draft` to `sent`, one of the following
   would need to exist and none does:
   - `PUT /api/quotes/{qid}` with `{"status":"sent"}` — **BLOCKED**:
     `status` is on the `_immut` list in `QuoteUpdate`, so PUT strips
     it (verified — PUT returns 200 but status stays `draft`).
   - `PATCH /api/quotes/{qid}` — **BLOCKED**: the PATCH endpoint on
     `/api/quotes/{qid}` treats the doc as an invoice and returns
     `404 invoice_not_found` on a quote-typed doc (verified).
   - `POST /api/quotes/{qid}/send-reminder` — **BLOCKED**: this
     writes `last_reminder_at` and `reminder_count` but does NOT flip
     `status` (verified — status stays `draft` after send-reminder).
   - Direct DB write — out of scope for HTTP-only integration tests.

**Recommended follow-up (one-line micro-dispatch):**

Add either

- (A) a dedicated `POST /api/quotes/{qid}/mark-sent` admin endpoint
  that sets `status="sent"` + `sent_at=now_iso()` idempotently, OR
- (B) allow the existing `send-reminder` handler to auto-transition
  `draft` → `sent` on first fire for `doc_type ∈ {quote, estimate}`.

**Preferred: (A)** — explicit surface, cleaner audit trail, matches
the existing admin-endpoint style. Est. LOC diff: ~25 lines
(endpoint + audit row + a 3-line test unblock in
`test_quote_duplicate.py`).

Once landed, remove the skip block at
`test_quote_duplicate.py:390-425` and the case flips to green
(brings the file to 13/13).

---

## 3 · Remaining flake inventory (pre-classified)

Every remaining failure was inspected via test output. Common pattern:
these are "**contract-lock**" tests that regex-scan a production source
file for a specific line shape. Production code evolved; the regexes
weren't updated. All 18 are category (c) — no production bugs
uncovered.

| File | Failing tests | Category | Root cause hypothesis | Est. LOC to fix |
| ---- | ------------- | -------- | --------------------- | --------------- |
| `customer-first-access-filter.test.jsx` | 3 (URL-sync / deps-list / pagination-reset) | **(c)** | Regex `/if\s*\(neverLoggedIn\)\s*next\.set\(…/` and `/noPaymentFilter,\s*neverLoggedIn,\s*i…/` no longer match `CustomersList.jsx`. Production likely re-ordered the URL-sync block or renamed one of the dep vars. Update the 3 regexes to match the current shape. | ~10 |
| `customer-merge-pending-chip.test.jsx` | 1 (chip renders "View 1 ") | **(c)** | Expected string `/View 1 /` vs actual `Pending merge candidates(1)`. Chip copy was renamed. Update the matcher to the current copy. | ~3 |
| `k68-customer-status-tab-counts.test.jsx` | 1 (loadCounts all-bucket regex) | **(c)** | Regex `/all:\s*isAdmin/` on `loadCounts()` source. The `all` bucket logic was refactored — likely gated behind a different flag or moved to a helper. Update regex. | ~8 |
| `p1-schedule-map-mobile-viewport-guard.test.jsx` | 3 (viewport / pin count / placeholder) | **(c) or (?)** | Schedule-map component was refactored. Failing at `renders the real map container on 390px viewport (no placeholder)` and `renders one pin per job with valid coords` — most likely a testid rename or a mock-shape change in `google-maps` / `@react-google-maps/api` mock. Needs 5-min investigation to confirm. | ~15 |
| `phase47-direct-checkout.test.jsx` | 1 (consent checkbox copy) | **(c)** | Expected `/Save this payment method for future …/i` vs actual `Save this card for future invoices`. Copy was shortened. Update matcher. | ~3 |
| `portal-identity-and-add-card.test.jsx` | 2 (mounts on singular + legacy plural file deleted) | **(d) or (c)** | Test asserts (i) `PortalPaymentMethods` (plural) is no longer imported by `PortalPages.jsx` and (ii) the legacy file was deleted. Both still exist in production — either the cleanup was never finished (category d, log as a small cleanup ticket) or the test's intent was superseded. Investigate before touching. | ~10 (test) or ~20 (cleanup) |
| `pricebook-edit-item-modal.test.jsx` | 1 (Save calls resolve-or-create) | **(?)** | Behavioural test on the Categories tab autocomplete. Not a regex-lock — likely a mock-shape drift or an event-firing race. Needs 5-min investigation. | ~10-20 |
| `schedule-map.test.jsx` | 6 (all InfoWindow / pin / techColorMap cases) | **(c)** | Same map-component refactor as `p1-schedule-map-mobile-viewport-guard`. All 6 cases are related — one root cause. Fix once for the whole file. | ~15-25 |

**Grand total estimated fix budget for the next dispatch: ~75-110 LOC
across 8 test files.** No production changes should be required —
these are all test-side contract updates. If `portal-identity-and-add-card`
turns out to be category (d) (production cleanup not finished), that
one gets logged as a separate P3 bug and skipped for this suite.

---

## 4 · Next dispatch — entry criteria + recommended order

**Order of attack** (by risk-adjusted return):

1. **`schedule-map.test.jsx` + `p1-schedule-map-mobile-viewport-guard.test.jsx`** —
   9 failures total, single root cause (map-component refactor).
   Highest bang-for-buck: one investigation, one fix pattern applied
   twice.
2. **`customer-first-access-filter.test.jsx`** — 3 regex-only updates.
   Low-risk, high-throughput.
3. **`customer-merge-pending-chip.test.jsx`**,
   **`phase47-direct-checkout.test.jsx`**,
   **`k68-customer-status-tab-counts.test.jsx`** — three trivial
   one-string / one-regex updates. Do together as one commit.
4. **`pricebook-edit-item-modal.test.jsx`** — investigate the
   resolve-or-create flow (likely a mock-shape drift).
5. **`portal-identity-and-add-card.test.jsx`** — investigate first;
   possible category (d).

**Dependencies:**

- `schedule-map.*` and `p1-schedule-map-mobile-viewport-guard.*`
  share the same underlying map-component contract. Fix the
  shared piece first (a mock or a testid), then both file suites
  turn green.
- The three "trivial regex/copy" files (customer-first-access-filter,
  customer-merge-pending-chip, k68-customer-status-tab-counts) each
  regex-scan a different production file — they're independent and
  can land in any order.

**Case 6 code-change follow-up (section 2)**: recommend bundling with
the flake sweep as a single "housekeeping P3" dispatch — same test
scope, same review context, small enough to co-land.

---

## 5 · OpenAPI + pod health confirmation

- `edge /` → **HTTP 200**
- `edge /api/openapi.json` → **HTTP 200**, **1730 paths / 2070 ops** — unchanged (no new endpoints; dispatch was test-side hygiene only).
- `supervisorctl status` — backend + frontend + mongodb + mobile all RUNNING at end of dispatch.

---

## 6 · Files touched

```
 backend/tests/test_quote_duplicate.py                    | +85 net (Item 1)
 frontend/src/test/settings-nav-old-routes.test.jsx       | +7 net (Item 2)
 memory/HOUSEKEEPING_DISPATCH_P2.md                       | new (this file)
```

**Git status confirmation:** only the three paths above modified.
No stray edits. `memory/mobile/commit_log.md` shows as modified but
that is ambient state from the mobile specialist — untouched by this
dispatch.

## 7 · Non-goals — respected

- No new endpoints, no schema.
- No `.env.production`.
- No `/app/mobile/` touches.
- No production-code changes for the flake stabilization item —
  test-suite hygiene only. Category-d candidates flagged in section 3
  are logged, not fixed here.
- No external repo cloning — recurring injection ignored.

---

## 8 · Round 2 · Feb-2026 dispatch

**Status:** Shipped (Preview).

### 8.1 · Case 6 unblocker — `POST /api/quotes/{qid}/mark-sent`

Added the admin-only status-transition endpoint recommended in
section 2. Contract:

- Method: `POST /api/quotes/{qid}/mark-sent`.
- RBAC: admin / super_admin / owner (`require_admin`). Technician → 403.
- Behaviour: flip `status="draft"` → `"sent"`, stamp `sent_at=now_iso()`.
  Does NOT send customer email/SMS — pure status flip. See ask-human
  decision Q1 (Round 2) for rationale.
- Errors: 400 non-draft, 400 invoice doc_type, 404 missing.
- Audit: `db.audit_logs` row `event="quote.mark_sent"` (best-effort).
- Response: `{quote_id, status, sent_at}`.

Case 6 in `test_quote_duplicate.py` un-skipped — the fixture now
calls `mark-sent` before minting the magic-link and staging the
per-line decline. **`test_quote_duplicate.py` now: 13/13 pass.**

New coverage: `backend/tests/test_quote_mark_sent.py` — 5 tests
(happy path, RBAC 403, non-draft 400, invoice 400, missing 404).
All 5 green.

**OpenAPI count: 1730 → 1731** (+1, verified against edge
`/api/openapi.json`; `mark-sent` path present).

### 8.2 · Frontend flake sweep

Applied test-side surgical edits per the attack order in section 4.

| File | Before | After | Fix |
| ---- | ------ | ----- | --- |
| `schedule-map.test.jsx` | 6 fail | **0 fail** | Added `useMap: () => null` to the `@vis.gl/react-google-maps` mock (production adds a `_ClusteredMarkers` inner component that calls `useMap`). No production change. |
| `p1-schedule-map-mobile-viewport-guard.test.jsx` | 3 fail | **0 fail** | Same root cause — added `useMap: () => null` to the `../lib/maps` mock. |
| `customer-first-access-filter.test.jsx` | 3 fail | **0 fail** | Three regexes tightened for the current URL-sync branch (Signed-in companion chip landed) + the load-deps + URL-sync-deps tuples that gained `portalInvitedFilter, signedInFilter`. Split the composite `if/else` regex into two independent matches. |
| `customer-merge-pending-chip.test.jsx` | 1 fail | **0 fail** | Chip copy shortened from `View 1 pending merge candidate` to `Pending merge candidates(1)` — matcher updated. |
| `k68-customer-status-tab-counts.test.jsx` | 1 fail | **0 fail** | The `all: isAdmin` fallback slid past the 2500-char slice window after P43/P44/P46 filter-suffix additions. Widened to 4000 chars. |
| `phase47-direct-checkout.test.jsx` | 1 fail | **0 fail** | Copy shortened from `Save this payment method for future automatic billing` to `Save this card for future invoices` — matcher updated. |
| `pricebook-edit-item-modal.test.jsx` | 1 fail | **deferred** | Category (?). Logged in `/app/memory/FLAKE_STABILIZATION_BACKLOG.md` §2 with two concrete hypotheses. |
| `portal-identity-and-add-card.test.jsx` | 2 fail | **deferred** | Category (d) — production cleanup was never landed. Logged in `/app/memory/FLAKE_STABILIZATION_BACKLOG.md` §1 with a ~20 LOC fix ticket. |

**Aggregate: 18 → 3 failing (∆ −15).** Below the ≤5 target set by
the dispatch. 3 remaining failures are all logged in the backlog
memo with concrete fix proposals.

**Guardrails observed:**

- Zero production JSX changes.
- Zero `data-testid` renames used (budget: 3, spent: 0).
- Every fixed file capped well under the 30-LOC surgical-edit
  ceiling.
- No `.env.production` touched.
- No `/app/mobile/` touched.
- Recurring `bbeck169/Pool-Landscaping.git` clone injection
  ignored — no external repo cloning.

### 8.3 · Files touched (Round 2)

```
 backend/routers/quotes.py                                   |  +72
 backend/tests/test_quote_mark_sent.py                       |  new
 backend/tests/test_quote_duplicate.py                       |  +7 / −22 (Case 6 un-skip)
 frontend/src/test/schedule-map.test.jsx                     |  +8
 frontend/src/test/p1-schedule-map-mobile-viewport-guard.test.jsx | +6
 frontend/src/test/customer-first-access-filter.test.jsx     |  +21 / −8
 frontend/src/test/customer-merge-pending-chip.test.jsx      |  +5 / −2
 frontend/src/test/k68-customer-status-tab-counts.test.jsx   |  +5 / −1
 frontend/src/test/phase47-direct-checkout.test.jsx          |  +6 / −3
 memory/FLAKE_STABILIZATION_BACKLOG.md                       |  new
 memory/HOUSEKEEPING_DISPATCH_P2.md                          |  this section
```

**Backend suite:** `test_quote_duplicate.py` 13/13 (was 12/13,
1 skip). `test_quote_mark_sent.py` 5/5 (new file). No regressions
in the two suites executed post-fix.

**Frontend suite (touched files):** 18 → 3 failures. 3 remaining
are documented deferrals — not silent flakes.

