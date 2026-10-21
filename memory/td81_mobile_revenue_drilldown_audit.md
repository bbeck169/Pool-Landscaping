# TD-81 · Mobile Revenue-by-Category drill-down · parity audit

**Date:** 2026-02-18
**Scope:** read-only comparison between web admin Revenue-by-Category drill-down and the mobile equivalent — to size the mobile write-mode port (recategorize + category-audit).
**Verdict:** **STOP · scope exceeds the 300-LOC roll-through budget by a large multiple.** Mobile write-mode port requires a dedicated Expo-specialist dispatch.

---

## 1 · File inventory

### Web (feature source)

| File | LOC |
|---|---|
| `frontend/src/components/dashboard/RevenueByCategoryTile.jsx` | 206 |
| `frontend/src/components/dashboard/IncomeByServiceCategoryTile.jsx` | 155 |
| `frontend/src/components/dashboard/DashboardDrillDownModal.jsx` | **2033** |
| `frontend/src/pages/reports/UncategorizedItemsReport.jsx` | ~400 |
| `frontend/src/pages/admin/Dashboard.jsx` (consumer) | ~900 |

### Mobile (parity target)

| File | LOC |
|---|---|
| `mobile/src/components/dashboard/RevenueByCategoryTile.tsx` | 67 |
| `mobile/app/reports/revenue-by-service.tsx` | 163 |

**Mobile code mentions zero edit affordances** (grep for `onEdit`, `setEdit`, `PATCH`, `Picker`, `Select`, `TextInput` across both files → **zero matches**). Mobile is strictly a bucket viewer + an unfiltered drill-down table.

---

## 2 · Web feature surface absent on mobile

The web admin drill-down modal (`DashboardDrillDownModal.jsx`) carries the following edit affordances that mobile does not currently expose. Each is a load-bearing invariant from a prior ship; the mobile port must either carry them all (parity-complete) OR explicitly ship as read-only (minimum).

### 2.a · Per-row inline edit on income rows (K41 / K48 / A2)

- Editable fields (per `EDITABLE_INCOME_FIELDS`): `description`, `quantity`, `unit_price`, `category` ("Business Unit").
- Lock rules:
  - **K41 money-neutral rule:** category-only edits bypass the invoice-total lock (subtotal / tax / total unchanged).
  - **K48 confirmation flow:** `sent`/`paid`/`partially_paid`/`refunded` invoices require explicit `confirm_edit_sent` / `confirm_edit_paid_invoice_number` on the PATCH body. Non-category fields show a confirmation modal; category fields piggyback on Atomic A2 auto-pass.
  - **K48 terminal statuses** `void` / `cancelled` reject even with confirmations → row is hard-read-only.
  - **Atomic A2 role-aware auto-pass:** `admin` / `super_admin` / `manager` / `owner` auto-carry `confirm_edit_sent` + `acknowledged_lock_bypass` on category PATCH bodies so sent / accepted invoice categories re-classify without the friction dialog. Non-privileged roles still hit the dialog.
  - **K73 crew-aware authz** on PATCH (tech-side authorisation that gates downstream write access).
- Shared select source: tenant-scoped `service_categories` fetched once per modal lifetime; empty-list fallback renders a read-only chip (defensive).

### 2.b · Category-audit flows

- Row deep-link to Uncategorized Items Report (`UncategorizedItemsReport.jsx`) that drills into line-items with missing/invalid categories, bulk-reclassify UI, CSV export.
- Preserves K48 confirmation flow + A2 bypass + tenant scoping.

### 2.c · Live recompute

- Optimistic row update + rollback on PATCH failure.
- Tile bucket totals auto-refresh via `onEdited` callback → drill-down parent → tile.

---

## 3 · Port sizing estimate

### Minimum (read-only parity confirmation)

~0 LOC. Mobile is already read-only. No change required. Operator receives a confirmation receipt that mobile matches the "read-only" shape.

### Partial (category edit only — reclassify a line item)

| Component | Est LOC |
|---|---|
| Mobile `DrillDownModal.tsx` (new) — row list + inline Picker for category | ~250 |
| Mobile `services/invoiceLineItemPatch.ts` — PATCH wrapper + K48 flags + A2 role auto-pass | ~120 |
| Mobile `hooks/useServiceCategories.ts` — tenant-scoped select source | ~60 |
| Mobile `components/K48ConfirmSheet.tsx` — bottom sheet for sent/paid confirm | ~140 |
| Vitest / Jest coverage on the above | ~200 |
| **Total** | **~770 LOC** |

### Full (web parity — all editable fields + category-audit flow)

| Component | Est LOC |
|---|---|
| Mobile `DrillDownModal.tsx` (full editable row + K48 + A2 + K41 + K73 integration) | ~700 |
| Mobile `UncategorizedItemsReport.tsx` port | ~400 |
| Mobile bulk-reclassify sheet | ~200 |
| Mobile CSV export (share-sheet integration) | ~100 |
| Shared services (patch wrapper, categories hook, auth role shim) | ~250 |
| Test coverage (Jest + detox snapshot) | ~400 |
| **Total** | **~2050 LOC** |

Even the **partial / category-edit-only** port exceeds the operator's 300-LOC roll-through ceiling by ~2.5×. Full parity exceeds it by ~7×.

---

## 4 · Recommendation

**STOP · operator decision required.** Pick one of three paths:

### Option A — ship nothing (recommended if operator judgement matches)

Mobile intentionally stays read-only on this surface. Field techs don't typically re-categorize revenue line items from a phone; the admin desk is where it happens. Zero LOC. Zero test matrix. Zero regression risk.

### Option B — ship the category-edit-only slice

Mobile gains the single highest-value edit (reclassify a line item's Business Unit) and nothing else. ~770 LOC across 5 new files. Requires:
- Expo-specialist dispatch (web pod cannot touch `/app/mobile/`).
- K48 confirmation port — field techs on sent/paid invoices need the sheet or they'll silently fail PATCH.
- A2 role gate — tenant-admin flag must flow through mobile auth context.

### Option C — ship full web parity

Mobile matches web line-for-line. ~2050 LOC across ~10 files. Requires a dedicated multi-week Expo-specialist dispatch and detox regression coverage.

---

## 5 · Guardrail status for this audit

- Audit-only, no code written.
- Zero `/app/mobile/` edits.
- Single memory-doc write (this file).
- Scope exceeds roll-through budget → STOP triggered.
- Recommendation attached; operator decides next action.

**Awaiting operator decision on Option A/B/C.** If A, this doc is the receipt and no further commits land. If B or C, operator dispatches to the Expo specialist with this audit as the brief.

---

## Amendment · 2026-10-21 · scope correction + outcome (mobile pod)

- **Scope correction:** the mobile drill-down is `mobile/src/components/dashboard/IncomeDrillDownSheet.tsx` (90 LOC, opened from `RevenueByCategoryTile.tsx`), not `app/reports/revenue-by-service.tsx`.
  - The K48 confirmation sheet is not needed on mobile: the revenue section is admin/super_admin only, so the A2 auto-pass always applies.
  - The revenue-by-category BU edit is a minimal invoice-level PATCH, with no `line_items` rebuild.
  - Re-sized from ~770 to ~230-280 LOC. See `memory/mobile/td81_mobile_phase2_proposal.md`.
- **Decision:** Option **B-narrow** (Business Unit re-classify only).
- **Shipped:** `284ce35c9` (`td81-b1-fe`, shared primitives) + `7f8cf5beb` (`td81-b2-fe`, drill-down wiring). Ship record in `memory/TECH_DEBT.md` § TD-81.
