# Flake Stabilization Backlog

**Owner:** main agent (Preview).
**Created:** Feb-2026 · Housekeeping P2 · Round 2.
**Updated:** Feb-2026 · Housekeeping Batch A — items 1 + 2 resolved.
**Scope:** Frontend flakes that need production-code investigation
or a larger change than a Round 2 dispatch can absorb. Each entry
has a concrete fix proposal so the next dispatch can pick it up
without re-diagnosing.

---

## 1 · `portal-identity-and-add-card.test.jsx` — RESOLVED (Batch A)

**Original symptom:** 2 failing tests — assertions that
`PortalPaymentMethods` (plural) was no longer imported by `App.js`
AND that the file itself was deleted.

**Fix landed (Feb-2026 · Housekeeping Batch A):** Completed the
stalled production cleanup end-to-end:

1. Removed the `PortalPaymentMethods` import from `App.js` (line 369).
2. Removed the stranded `Route path="portal/profile/payment-methods"`
   from `App.js` (was line 1350). Grep confirmed no `Link` / `navigate`
   references outside the file itself.
3. Deleted `frontend/src/pages/portal/PortalPaymentMethods.jsx`.
4. Deleted `frontend/src/test/task5-save-card-on-file.test.jsx` — it
   exercised the deleted component; equivalent coverage lives on
   the singular `<PortalPaymentMethod>` component tested through
   `portal-identity-and-add-card.test.jsx` itself.

**Straggler grep results (all treated as archival — untouched):**

- `CHANGELOG.md` — 4 historical mentions (dev journal). Left as-is.
- `memory/PHASE15_DELIVERABLES.md`, `memory/promote_to_prod_checklist.md`
  — historical archives. Left as-is.
- `memory/HOUSEKEEPING_DISPATCH_P2.md` — prior memo describing the
  gap; superseded by this section.
- `mobile/app/portal/payment-methods.tsx` +
  `mobile/__tests__/task5-save-card-mobile.test.tsx` — mobile
  codebase (`/app/mobile/`). Standing guardrail: do not touch.
  Mobile mirror lifecycle is the mobile specialist's territory.

**Test result:** `portal-identity-and-add-card.test.jsx` now green
(previously 2 failing, no skips reintroduced by the fix).

---

## 2 · `pricebook-edit-item-modal.test.jsx` — RESOLVED (Batch A)

**Original hypotheses:** memo §2 (Round 2) proposed two candidates —
(1) autocomplete debounced query mock returning `undefined`, and
(2) resolve-or-create endpoint returning `undefined` for the
category POST. **Both hypotheses were wrong.**

**Actual root cause:** testid drift (category **c**, not **?**).
The failing test used the testid prefix `ei-income-cat-*`, but the
production `CategoryAutocomplete` component renders its testids
scoped to whatever `testidPrefix` prop the parent passes. For the
income-category slot in `EditItemModal.jsx`, that prop is
`pricebook-income-category-select` — so the real testids in the
DOM are `pricebook-income-category-select-input`,
`pricebook-income-category-select-create`, and
`pricebook-income-category-select-option-<id>`. The test's
`findByTestId("ei-income-cat-create")` was timing out because the
node genuinely didn't exist.

**Fix landed:** pure test-side rename in
`frontend/src/test/pricebook-edit-item-modal.test.jsx`. Zero
production-JSX touched.

**Lesson for future memos:** grep for the actual `data-testid` in
production source before hypothesizing about mock shape — a
5-second grep would have caught this immediately.

**Test result:** `pricebook-edit-item-modal.test.jsx` — 11 passed,
0 failed (was 1 failing).

---

## 3 · Follow-up

Both entries above are now closed. Future flakes appended here
should follow the same "concrete fix proposal + estimated LOC"
convention.
