# Feature: Responsive Quote/Estimate Line-Items Stacked Layout (Mobile Parity)

## Summary
Converted all Quote, Estimate, and Invoice detail screens from horizontal row-based line-item layouts to vertically stacked cards. This eliminates horizontal overflow on narrow devices (375px+) and ensures touch-friendly Decline/Restore buttons.

## Files Modified

| File | Changes |
|------|---------|
| `app/estimate-view/[id].tsx` | Itemized + grouped line items → stacked cards; Decline/Undo buttons → full-width ≥44px; removed `groupRow` row layout |
| `app/quote/[id].tsx` | Line items → stacked cards; Internal Margin table wrapped in `<ScrollView horizontal>` |
| `app/invoice/[id].tsx` | Line items → stacked cards; Internal Margin table wrapped in `<ScrollView horizontal>` |
| `app/i/[token].tsx` | Line items → stacked cards (magic-link public invoice) |

## Design Pattern — Stacked Card

Each line item renders as an independent card:

```
┌─────────────────────────────┐
│ Description text             │
│ 2 qty × $150.00             │
│ ─────────────────────────── │
│ Subtotal            $300.00  │
│ [ Decline (full-width) ]     │  ← minHeight: 44px
└─────────────────────────────┘
```

### Key Style Tokens
- `lineCard` — `backgroundColor: "#F8FAFC"`, `borderRadius: radius.md`, `borderWidth: 1`, `padding: spacing.md`
- `lineCardSubtotalRow` — row with top border separator
- `lineDeclineBtn` / `undeclineBtn` — `minHeight: 44`, full-width, centered text
- `lineCardDeclined` — `opacity: 0.55` for declined items

## Margin Table (Admin Only)
The Internal Margin table in `quote/[id].tsx` and `invoice/[id].tsx` is wrapped in `<ScrollView horizontal>` with `minWidth: 480` on the content container. This allows the 6-column table to scroll horizontally within its card without affecting the root scroll.

## Constraints
- No fixed widths on outer wrappers
- No root horizontal ScrollView
- Decline buttons ≥ 44px tap target (enforced via `minHeight: 44`)
- All group/decline API logic preserved (approve, decline, undo-decline, group-decline, group-restore)
- No new dependencies introduced

## Verification
- Screenshots verified at 375px viewport width (iPhone SE)
- All 4 files lint-clean (ESLint)
- Metro bundler compiles successfully
