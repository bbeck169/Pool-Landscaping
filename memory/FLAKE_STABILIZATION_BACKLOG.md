# Flake Stabilization Backlog

**Owner:** main agent (Preview).
**Created:** Feb-2026 · Housekeeping P2 · Round 2.
**Scope:** Frontend flakes that need production-code investigation
or a larger change than a Round 2 dispatch can absorb. Each entry
has a concrete fix proposal so the next dispatch can pick it up
without re-diagnosing.

---

## 1 · `portal-identity-and-add-card.test.jsx` — Category (d)

**Symptom:** 2 failing tests.

| Test | Assertion | Current reality |
| ---- | --------- | --------------- |
| Bug 2 · Item A · route wiring | `App.jsx` does NOT import `PortalPaymentMethods` (plural) | `App.jsx` still imports and routes to the plural component |
| Bug 2 · Item A · legacy file deleted | `src/pages/portal/PortalPaymentMethods.jsx` does not exist | file still exists |

**Root cause:** The test was authored ahead of a planned cleanup
(rename `PortalPaymentMethods.jsx` → `PortalPaymentMethod.jsx` and
drop the plural route). The cleanup was never landed — the plural
route + component are still live in production.

**Recommended fix — production cleanup ticket (P3):**

1. Grep for every reference to `PortalPaymentMethods` (plural) —
   `App.jsx` imports/routes, any internal Link/navigate calls, any
   `data-testid` strings, any router match for `portal/payment-methods`.
2. Consolidate onto the singular route + component
   (`portal/payment-method` + `PortalPaymentMethod`).
3. Delete `src/pages/portal/PortalPaymentMethods.jsx`.
4. Verify the two portal-identity tests turn green.

**Estimated LOC:** ~20 (mostly delete + one import rewrite in
`App.jsx`).

**Why deferred here:** Round 2 test-suite-hygiene dispatch is
capped at test-side changes plus at most 3 testid renames. Deleting
a production component + rewriting router wiring is squarely
production-code territory and needs its own review + smoke run.

---

## 2 · `pricebook-edit-item-modal.test.jsx` — Category (?)

**Symptom:** 1 failing test — `Save calls resolve-or-create for a
NEW income category name typed on Categories tab`. Test times out
at the default 5s vitest budget.

**Suspected root cause:** Mock-shape drift on the autocomplete
component or the resolve-or-create API adapter. When the test types
a fresh income-category name and clicks Save, the modal appears to
hang waiting for a resolver call that never resolves. Two candidate
causes worth checking in order:

1. The autocomplete's debounced query fires against `api.get`, but
   the test's `api.get` mock was authored before the debounce guard
   landed and no longer returns a resolved promise for the
   autocomplete lookup call.
2. The Save handler was refactored to await a category-side POST
   BEFORE the item save, but the mock returns `undefined` for the
   category POST (instead of `{id: "..."}`), so the item-save
   await never fires.

**Recommended investigation checklist:**

1. Add `console.log` in the test's `_setupApi` to see which
   endpoints are hit during the timing-out run.
2. Compare with the passing "existing category" test in the same
   file — it likely mocks the autocomplete GET with a real payload.
3. Extend `api.post` mock to return `{id: "cat-new", name: "..."}`
   for the resolve-or-create endpoint.
4. If the modal now uses a portal / react-query wrapper, wrap the
   render in the right providers (see other pricebook tests for the
   canonical helper).

**Estimated LOC:** 10–20 depending on which of the two hypotheses
lands. If hypothesis 2 wins it's a 2-line mock adjustment; if
hypothesis 1 wins it's a broader mock rewrite.

**Why deferred here:** Requires ~30 min of interactive debugging
plus potential provider-wrap changes. Not a mechanical fix — needs
its own dispatch.

---

## 3 · Follow-up

When either item above lands, remove that section from this file
and note the fix in the corresponding `HOUSEKEEPING_DISPATCH_*.md`
memo's ledger.
