# FIX — Public estimate viewer · line-item duplication regression

**Severity:** Customer-facing (P0) · **Preview only** — user must redeploy for production to receive the fix.  
**Reported:** email magic-link public estimate rendered every line item TWICE (once as the desktop table AND once as the mobile card list) on ≥640px viewports.

## Root cause

`.ev-lines-cards` in `frontend/src/components/EstimateView.css` declared `display: flex` unconditionally at the base rule. Tailwind's `sm:hidden` utility (used on the mobile card `<ul>`) compiles to `.sm\:hidden { display: none }` at ≥640px. Both selectors have identical CSS specificity (single class), so the **later declaration wins** — and because `EstimateView.css` is imported after the Tailwind base layer, the custom `display: flex` beat the responsive `display: none`, keeping the mobile card list visible on desktop widths in addition to the desktop table.

The class name comment in the CSS already documented the intended behavior ("`sm:hidden` toggles display") but the base declaration silently violated it.

## Fix

Move the `display: flex` (plus `flex-direction` / `gap`) inside a `@media (max-width: 639.98px)` block. The base rule now only carries layout-neutral resets (`list-style`, `margin`, `padding`) so Tailwind's `.sm\:hidden` naturally hides the cards at ≥640px, and the flex layout only kicks in at the mobile breakpoint where the cards are visible.

```css
.ev-lines-cards {
  list-style: none;
  margin: 12px 0 4px;
  padding: 0;
}
@media (max-width: 639.98px) {
  .ev-lines-cards {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
}
```

## Prevention

`frontend/src/test/estimate-view-line-item-duplication-fix.test.jsx` locks two invariants:

1. **JSDOM render** — a payload with N line items produces exactly N desktop `estimate-line-item-row-<i>` cells AND N mobile `estimate-line-item-card-<i>` cells (both branches always mount in the DOM; CSS gates them at runtime).
2. **CSS source lock** — the base `.ev-lines-cards { ... }` rule (outside any `@media`) MUST NOT declare `display: …`. A regression that resurrects the unconditional `display: flex` is caught immediately.

## Files touched

- `frontend/src/components/EstimateView.css` — base rule slimmed, `display: flex` moved to `@media (max-width: 639.98px)`.
- `frontend/src/test/estimate-view-line-item-duplication-fix.test.jsx` (new · 3 tests).
- `memory/FIX_ESTIMATE_VIEW_LINE_ITEM_DUPLICATION.md` (this doc).

## Rollout note

Preview build carries the fix. Production is still running the pre-fix bundle at `https://app.plofv.com` — the user needs to redeploy to push the CSS change live.
