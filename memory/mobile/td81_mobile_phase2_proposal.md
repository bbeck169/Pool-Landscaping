# TD-81 · Mobile Revenue-by-Category drill-down write-mode · Phase-2 proposal (mobile pod)

**Date**: 2026-10-21 · **Status**: proposal only, **no code**. STOP for operator decision.
**Input**: `memory/td81_mobile_revenue_drilldown_audit.md` (web-pod audit, `0f02f7a21`). That audit ended
"Awaiting operator decision on Option A/B/C", and no decision is recorded in TECH_DEBT.md or the commit log, so it
is unresolved. This doc re-sizes it with mobile-side recon (the web pod could not read `/app/mobile/`).

## 1 · Scope-reality corrections to the Phase-1 audit

| Phase-1 claim | Mobile reality (HEAD `4261f8225`) |
|---|---|
| Mobile target = `RevenueByCategoryTile.tsx` (67) + `app/reports/revenue-by-service.tsx` (163) | The drill-down is **`src/components/dashboard/IncomeDrillDownSheet.tsx` (90 LOC)**, opened from `RevenueByCategoryTile.tsx:51`. It already pages `GET /dashboard/income/by-category/rows` (cursor) and a row tap opens `/quote/<invoice_id>`. `revenue-by-service.tsx` is a different report |
| Need a new `K48ConfirmSheet` (~140) for non-privileged roles | **That branch can't be reached on mobile.** The revenue section renders only for `admin`/`super_admin` (`app/(app)/index.tsx:67,157`), and the BE `/rows` + audit endpoints are admin-gated. Every mobile viewer is A2-privileged, so the BU PATCH always auto-carries `confirm_edit_sent` + `acknowledged_lock_bypass` (web `DashboardDrillDownModal.jsx:641-643`). No confirm dialog is needed |
| Category edit = rebuild `line_items` and PATCH | The **revenue-by-category variant edits the invoice-level Business Unit** with a *minimal* body `{business_unit, business_unit_id, confirm_edit_sent, acknowledged_lock_bypass}` (web L590-693, "K48 verify-hotfix": do **not** send `line_items`). No GET-then-rebuild. Only the Service Unit / description / qty / price edits rebuild `line_items` |
| New `useServiceCategories` hook | BU options come from `GET /income-categories?include_archived=false` → `{items, total}` (16 in preview). One inline fetch per sheet lifetime is enough |

The Phase-1 estimate was "Partial ~770 LOC". The same user value (re-classify a revenue row's Business Unit) is
**~230-280 LOC including tests** on mobile.

## 2 · What the web row actually offers (income-by-category variant)

1. **BU Select** (invoice-level, money-neutral): `PATCH /quotes/{invoice_id}` with the minimal body, then
   best-effort `POST /dashboard/drilldown/line-item-audit {tile, invoice_id, line_index, field:"business_unit",
   before, after}`. On success, a "Moved to X" chip shows when the new bucket ≠ the current one. `void`/`cancelled` are
   hard read-only. Optimistic update with rollback.
2. **Service Unit Select** (line-level, rebuilds `line_items`). Preview tenant has service categories.
3. **Description / Qty / Unit price inline inputs** (money-changing, K41 lock and confirm flows).
4. "Open full edit" → full invoice editor.

## 3 · Options (re-sized)

| Option | Scope | Est. LOC (incl. tests) | Notes |
|---|---|---|---|
| A | Ship nothing (stay read-only) | 0 | Valid, but leaves the TD-84 "Uncategorized" flow with no mobile write primitive |
| **B-narrow (recommended)** | (1) BU re-classify only | ~230-280 | Highest value (fix a mis-bucketed paid invoice from the phone). Money-neutral. No confirm sheet. No line_items rebuild |
| B-plus | (1) + (2) Service Unit | ~380-450 | Adds the GET-rebuild-PATCH path plus a second picker. Higher regression surface (numeric validators on `line_items`) |
| C | (1)+(2)+(3) + Uncategorized report | ~1,500+ | Money-changing edits on a phone. K41/K48 confirm UX. Not recommended |

**B-narrow file plan**
- `src/lib/k48.ts` (~35): `k48StatusFlags(row)` + `buildBusinessUnitPatch(role, row, cat)`. These are pure, shared primitives (A2 role shim + K48 flags), **intended for TD-84 reuse**.
- `src/components/dashboard/BusinessUnitPickerSheet.tsx` (~70): a `Sheet` list of income categories, with the current one checked and a 44 pt rows. Reusable by TD-84.
- `IncomeDrillDownSheet.tsx` (+~50):
  - A trailing "Re-classify" button per row; row tap still opens the invoice.
  - Disabled with a note on `void`/`cancelled`.
  - Optimistic update, rollback, and toast on error.
  - "Moved to X" chip; audit companion POST.
  - `onEdited` → `RevenueByCategoryTile` refetch.
- `__tests__/td81-mobile-bu-reclassify.test.tsx` (~110, ~10 cases): payload shape (minimal, no `line_items`), A2 flags, terminal block, rollback on 4xx, audit best-effort (failure doesn't block), Moved-to chip, tile refetch, picker options from `items[]`.

## 4 · Operator decisions (STOP)

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| **T1** | Scope | A · B-narrow · B-plus · C | **B-narrow** |
| **T2** | Row interaction | (a) separate trailing "Re-classify" button, row tap stays → invoice · (b) long-press row → picker | **(a)**. Discoverable and keeps today's tap behaviour |
| **T3** | After-save | (a) web parity: row stays with a "Moved to X" chip; tile totals refetch on sheet close · (b) remove the row immediately and refetch the tile live | **(a)** |
| **T4** | TD-84 scaffolding | (a) put the K48/A2 helpers + BU picker in shared `src/lib` / `src/components/dashboard` for later TD-84 reuse, no TD-84 code now · (b) keep them private to the drill-down | **(a)**, sequential discipline kept (no TD-84 batching) |

## 5 · Adjacent finding (new candidate, not fixed)

- **TD-81-adj · mobile reads `/income-categories` with the wrong shape (P2, mobile).** The BE returns `{items, total}`.
  - `app/income-categories.tsx:20` uses `setCats(r.categories || [])`, so the mobile Income Categories admin screen always lists 0.
  - `app/quote/new.tsx:68` makes the same mistake, so the quote form falls back to the hard-coded `["Pool","Landscaping","Labor"]` instead of the tenant's 16 categories.
  - The fix is ~2 lines each. Propose a separate atomic ticket.

## 6 · Guardrails
Docs-only. No mobile/web/BE code. No deployment (TD-88 hold). Injection list unchanged (+ the "AI-powered Excel/CSV
importer on Customers page" variant now on watch). No new variants seen.
