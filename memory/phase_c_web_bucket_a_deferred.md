# Phase C.web Bucket A — Deferred items + α post-mortem

> **Produced**: Feb 2026 — During Batch-3 investigation (schedule + customer themed sweep).
> Previous landmarks: α `2878a6be9`, β `ac341143b`, γ `c3d9ed911`.
> Current failing-suite count post α/β: **51 files** (down from 58).
> Of the 51, **7 are already triaged in γ** → true remaining pool = **44 files**.
> **Status**: Batch 3-6 PAUSED pending user decisions on the material findings below.

---

## 🛑 CRITICAL — α post-mortem (requires user ruling)

The α commit (`2878a6be9`) widened the K71 `_locked` array in
`QuoteInvoiceDetail.jsx` from `_doc_type === "invoice" && _st === "paid"` to
`["sent", "accepted", "paid", "past_due", "unpaid", "overdue"].includes(_st)`.

This "restore source" directive was based on `/app/memory/phase_c_web_bucket_c_rca.md`
entry **#3** which classified `quote-invoice-detail-ack-bypass-aged.test.jsx`
as a suspected source regression. That classification was **incorrect**.

### What the RCA missed

Two sibling policy-anchor tests were ALREADY green on the pre-α source and
assert the OPPOSITE invariant (narrow lock, no silent-bypass path):

**1. `src/test/doc-lock-policy-relax.test.jsx`** — asserts:
```jsx
expect(QID_SRC).toMatch(
  /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/,
);
expect(QID_SRC).not.toMatch(
  /_silentBypass\s*=\s*_role\s*===\s*"super_admin"/,
);
const silentBypassFalseLines =
  QID_SRC.match(/const\s+_silentBypass\s*=\s*false\s*;/g) || [];
expect(silentBypassFalseLines.length).toBeGreaterThanOrEqual(2);
```
Post-α this file **fails 3 assertions** — all three because α restored the
widened array literal + would require `_silentBypass = _role === "super_admin"`
to satisfy the ack-bypass test's lint on the lock-dialog path.

**2. `src/test/quote-invoice-detail-super-admin-silent-bypass.test.jsx`**
asserts the inverse of the above:
```jsx
expect(SRC).toMatch(/_silentBypass\s*=\s*_role\s*===\s*"super_admin"/);
```
Pre-α, source had `_silentBypass = false` → this test was ALREADY FAILING
pre-α, meaning the super-admin bypass had been intentionally retired by
the DOC-LOCK-POLICY-RELAX phase.

### The actual history, inferred from comments in `QuoteInvoiceDetail.jsx` lines 1495-1502

> *"DOC-LOCK-POLICY-RELAX · Feb-2026 — estimates are now always editable
> regardless of status. Invoices are editable unless the status is `paid`
> (the only user-defined read-only state). `void` / `cancelled` are terminal
> and 409 server-side, but we don't gate them here either — let the backend
> be the single source of truth for lock state."*

→ Policy progression:
1. **Original**: narrow `paid`-only client lock.
2. **Ack-bypass widen**: expanded to the 6-status array + added
   `_silentBypass = _role === "super_admin"` so super_admins still edit.
3. **DOC-LOCK-POLICY-RELAX** (the current prod intent): reverted to narrow
   `paid`-only lock + `_silentBypass = false` (backend is now the single
   source of truth; client over-locking caused support tickets).

The `quote-invoice-detail-ack-bypass-aged.test.jsx` test file is a stranded
anchor from phase #2. The DOC-LOCK-POLICY-RELAX phase retired phase-#2's
behavior but forgot to delete / rewrite the ack-bypass test file.

### Required user decision (please pick ONE)

**Option α.rollback** (my recommendation):
- Revert the K71 `_locked` widening in `QuoteInvoiceDetail.jsx` at the two
  save sites (lines ~1504 + ~1812) back to
  `_locked = _doc_type === "invoice" && _st === "paid";`.
- Keep the RecurringJobs portion of α as-is (that one was a legitimate fix).
- Rewrite `quote-invoice-detail-ack-bypass-aged.test.jsx` to assert the
  **narrow** lock + `_silentBypass = false` invariants (effectively
  retire the Phase-#2 behavior lock).
- `doc-lock-policy-relax.test.jsx` + `quote-invoice-detail-super-admin-silent-bypass.test.jsx`
  stay as-is; the super-admin test's `_silentBypass = _role === "super_admin"`
  anchor needs the same test-stale flip (DOC-LOCK-POLICY-RELAX retired it).

**Option α.extend**:
- Keep the α widening.
- Additionally restore `_silentBypass = _role === "super_admin"` at both save sites.
- Flip `doc-lock-policy-relax.test.jsx` to assert the widened invariants.
- This re-opens the "client over-locks" support-ticket risk the
  POLICY-RELAX phase explicitly fixed.

**Option α.keep-split** (status quo):
- Keep α as shipped.
- Defer the 2 conflicting policy-anchor tests to this doc permanently.
- Accept that the test suite has 3 mutually-incompatible lock policies locked.

---

## Remaining 44 failing files — categorized

### Group A1 — straight regex-drift repairs (likely 1-3 lines per test file) — **~17 files**
Source behavior correct; test regex / substring anchor needs updating.

- `schedule-job-notes.test.jsx` — `if (!jobNote && !custNote)` regex misses the new 4-way guard `if (!jobNote && !custNote && !pool && !landscape)`.
- `schedule-optimize-route.test.jsx` — `onOpenBulkReorder=` arrow-form regex drift.
- `schedule-per-tech-filter.test.jsx` — `techId && j.technician_id !==` arrow-filter regex drift.
- `task-b-schedule-cache-window.test.jsx` — `bulkMove` async arrow-form regex drift.
- `pages/schedule/__tests__/schedule-customer-clickthrough.test.jsx` — `user?.role === "admin"` regex drift.
- `customer-first-access-filter.test.jsx` — `noPaymentFilter, neverLoggedIn,` dependency-array ordering.
- `customer-primary-address-line.test.jsx` — `indexOf("marker") === -1` indicates the marker string was renamed.
- `customer-profile-tabs.test.jsx` — `/jobs?customer_id=${encodeURIComponent(id)}` URL regex drift.
- `customers-list-waitlist-tab.test.jsx` — `/customers?waitlisted=true&count_only=true` URL regex drift.
- `admin-topbar-cleanup-cluster-reorder.test.jsx` — cluster-ordering `indexOf()` marker drift.
- `header-cleanup-bell-cluster.test.jsx` — same cluster-ordering drift.
- `concierge-avatar-parity.test.jsx` — `<AIAvatar name={e.name}>` regex drift.
- `k52-theming.test.js` — `rgba(255,255,255,0.1...)` background color-token drift.
- `k63-lead-alerts-settings.test.jsx` — `import LeadAlertsSettings from "@/pages/...` regex drift.
- `k68-customer-status-tab-counts.test.jsx` — effect-dep-array probe returns null, likely renamed effect.
- `leads-bulk-hard-delete-and-polish.test.jsx` — `disabled={busy || !hardAcknowledge...}` + `.filter((r) => r.ok)` regex drift.
- `n5-t1-page-header-adoption.test.jsx` — timeout (test probably await `findByTestId` on a renamed element).
- `p34-launch-hardening.test.jsx` — `path?.endsWith("/portal") ? "pt-16"` regex drift.
- `p47-missed-status-badge.test.jsx` — `testid="tile-next-service"` + `"None scheduled"` string drift.
- `p49-service-report-restyle.test.jsx` — likely CSS token / shadow-sm class drift.
- `phase-n2-input-restyle-refinement.test.jsx` — `colors.searchIcon` token drift on Search icons.
- `phase30-4-confirm-modal-migration.test.jsx` — `showConfirm` import regex drift in mobile route files (mobile scope — defer per rules).
- `phase35-mobile-finance-parity.test.jsx` — `api.get("/recurring-jobs")` string drift (mobile — defer).
- `phase40-time-off.test.jsx` — `import TimeOffPage from "@/pages/...` regex drift.
- `phase47c-add-card-restore.test.jsx` — `import AddCardPage from "@/pages/...` regex drift.
- `phase48-admin-customer-contact-redesign.test.jsx` — `<h1[^>]*text-3xl[^>]*>{custome...}</h1>` regex drift.
- `portal-home-cta-row-mobile-clearance.test.jsx` — `\bmt-12\b` className drift (likely renamed to `mt-14` or similar).
- `portal-quick-actions-wiring.test.jsx` — `function ActionTile(...)` regex drift.
- `queue-item-4-comms-ui-polish.test.jsx` — `import AdminCommsSuppressionLog` drift.
- `app-compiles-smoke.test.jsx` — `PortalWarranties` import count drift (likely 0, path renamed).
- `pdfImportTotalColumn.test.jsx` — trailing `Verbatim` label glued onto formatted currency (`$400.00Verbatim`). Source added a "Verbatim" sibling node — regex needs `/^\$400\.00/` (prefix match) OR test fixture needs to query a specific child.
- `task-m-job-reopen-ui.test.jsx` — `const locked = !!report.submit...` regex drift.

### Group A2 — Bucket B drift surfaced after α landed (useAuth mock null) — **~8 files**
All fail with `Cannot destructure property 'user' of 'useAuth(...)' as it is null.`
This is Bucket B (test-harness mock drift), not Bucket A. Needs a shared
`vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }))`
fixture OR each test file to add its own `vi.mock("@/auth", …)` block.

- `invoice-line-item-price-editable.test.jsx`
- `invoice-pricebook-writeback.test.jsx`
- `invoice-save-errors-inline.test.jsx`
- `p16-1-1-estimate-combobox-gap.test.jsx`
- `quotes-summary-tiles.test.jsx`
- `pages/quotes/__tests__/QuoteInvoiceNew.pricebook.test.jsx` (timeout — likely same root cause stuck in a loading loop that depends on `useAuth`)
- `phase40-tab-count-refresh.test.jsx` (timeout — same hypothesis)
- `n5-t1-page-header-adoption.test.jsx` (timeout, suspect same)
- `app-layout-mobile-nav-role-gate.test.jsx` (`expected null not to be null` — same auth null leak)

### Group A3 — α conflict (3 files, see post-mortem above)
- `doc-lock-policy-relax.test.jsx` ⚠️
- `quote-invoice-detail-super-admin-silent-bypass.test.jsx` ⚠️
- (`quote-invoice-detail-ack-bypass-aged.test.jsx` is now green, but it's one
   of the three mutually-incompatible anchors — resolution depends on your
   α rollback / extend / keep-split decision.)

### Group A4 — already triaged (γ, do NOT touch here) — 7 files
`chemical-application-form.test.jsx`, `phase-mobile-drawer-parity.test.jsx`,
`quote-decline-reopen.test.jsx`, `rules-of-hooks-guard.test.jsx`,
`schedule-numbered-reorder.test.jsx`, `settings-sprocket-visibility.test.jsx`,
`task-a-sidebar-recurring-jobs.test.jsx`.

---

## Recommended next-dispatch shape

Given the α conflict + context budget, I recommend you split the next
dispatch into two independent lanes you can prioritize:

### Lane 1 (small, HIGH priority — unblocks policy sanity)
Rule α.rollback / α.extend / α.keep-split (see post-mortem). Scope: 2-3
files max.

### Lane 2 (medium, resumable at your pace)
Approve Group A1 as pure regex-drift sweep (**17 files**, 1-3 line changes
each, 3-retry-per-file policy). I can batch these in 2-3 commits of 6-8
files each. Expected success rate: ~90% (deferred files land back in this
doc).

### Lane 3 (medium — needs test-harness decision)
Approve Group A2 pattern: either (a) a shared `src/test/_helpers/mockAuth.js`
module that each affected file imports, OR (b) per-file `vi.mock("@/auth")`
blocks. Scope: 1 shared helper file + 8 test files = 9 files.

---

## Statistics

- Pre-sweep failing: 58
- Post α/β/γ: 51 (-7)
- True remaining pool: 44 (minus 7 γ-triaged)
- α conflict: 3 files
- Bucket B (useAuth) drift: 8 files
- Pure Bucket A regex drift: ~20-25 files
- Mobile scope (defer per rules): 2 files (`phase30-4-confirm-modal-migration`, `phase35-mobile-finance-parity`)

**Blocking question**: your ruling on α (rollback / extend / keep-split).
Everything else can proceed in parallel after that one call.
