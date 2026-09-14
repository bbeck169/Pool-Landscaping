# Iteration 94 — Responsive Quote/Estimate Stacked Card Layout

## What was implemented
- **Stacked card layout** for line items across 4 screens:
  - `app/estimate-view/[id].tsx` — both itemized and grouped line items
  - `app/quote/[id].tsx` — admin quote detail
  - `app/invoice/[id].tsx` — authenticated invoice detail
  - `app/i/[token].tsx` — magic link public invoice
- **Full-width Decline/Restore buttons** with `minHeight: 44px` tap targets
- **Horizontal ScrollView** wrapping Internal Margin tables in quote and invoice detail

## Web-to-mobile mapping decisions
- No web files were modified; this was a mobile-only layout improvement
- The stacked card pattern was designed for narrow mobile viewports (375px+)
- Margin tables kept their 6-column flex layout but wrapped in horizontal scroll

## New styles introduced
- `lineCard`, `lineCardDeclined`, `lineCardHeader`, `lineCardSubtotalRow`, `lineCardSubtotalLabel`
- `lineCardLateFee` (invoice only)
- Updated `lineDeclineBtn`/`undeclineBtn` from small inline buttons to full-width 44px+ buttons

## Removed styles
- `lineRow`, `lineRowDeclined`, `groupRow`, `lineRight` — replaced by stacked equivalents

## Known issues
- None

## Dependencies installed
- None

## Verification
- ESLint: all 4 files clean
- Metro: bundled successfully (2316 modules)
- Screenshots: verified at 375px viewport — no horizontal overflow, cards render correctly
