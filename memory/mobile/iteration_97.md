# Iteration 97 — Phase 2 Quote-to-Lead Recipient Mobile Parity

## What was implemented
- **QuoteRecipientPicker** (`/app/mobile/src/components/quotes/QuoteRecipientPicker.tsx`):
  - Debounced search (300ms) hitting `GET /api/quote-recipients/search?q=<term>&limit=20`
  - Opens a Sheet with TextInput + FlatList results
  - Each result row shows Customer/Lead badge (blue/amber), display name, email/phone
  - Checkmark on currently selected item
  - Exported `RecipientTypeBadge` component for reuse

- **Quote creation** (`quote/new.tsx`):
  - Replaced legacy customer-only `Selector` + `Sheet` with unified `QuoteRecipientPicker`
  - Hybrid POST payload: customer → `{customer_id, recipient_type:"customer", recipient_id}`, lead → `{recipient_type:"lead", recipient_id}` (no customer_id)
  - Supports URL param pre-fill: `?recipient_type=&recipient_id=` and legacy `?customer_id=`
  - Validation updated: "Title and recipient are required"

- **Quote detail** (`quote/[id].tsx`):
  - `RecipientTypeBadge` with `testID="quote-recipient-type-badge"` next to customer name
  - Lead-invoice notice with `testID="invoice-lead-recipient-notice"` and exact copy text
  - Notice only renders when `isInvoice && recipient_type === "lead"`

## Web-to-mobile mapping
| Web component | Mobile equivalent |
|---|---|
| `QuoteRecipientPicker` (Popover + Command) | `QuoteRecipientPicker` (Sheet + FlatList) |
| `RecipientTypeBadge` (span) | `RecipientTypeBadge` (View + Text) |
| `data-testid` | `testID` |
| `onChange({type,id,name})` | `onChange({type,id,name})` |

## TestIDs implemented
- `quote-recipient-picker` — trigger button
- `quote-recipient-picker-selected-badge` — badge on trigger when value selected
- `quote-recipient-picker-search` — search input in sheet
- `quote-recipient-picker-loading` — loading indicator
- `quote-recipient-picker-empty` — empty state
- `quote-recipient-picker-item-{kind}-{id}` — result row
- `quote-recipient-picker-item-{kind}-{id}-badge` — badge in result row
- `quote-recipient-type-badge` — badge on detail screen
- `invoice-lead-recipient-notice` — lead-invoice notice

## Tests created
- `QuoteRecipientPicker.test.tsx` — 10 tests (badge, picker trigger, placeholder, selected state, sheet opening, disabled state)
- `QuoteInvoiceLeadBadge.test.tsx` — 6 tests (badge rendering, notice rendering, notice conditions, ConvertToInvoice regression)

## Known issues / deferred items
- None

## Dependencies installed
- None needed
