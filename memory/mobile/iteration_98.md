# Iteration 98 — Phase 3 Quote Lifecycle Parity

## Survey Findings
1. **Mobile quotes list screen**: `/app/mobile/app/(app)/quotes.tsx` — existed with 3-option doc_type filter
2. **Quote detail screen**: `/app/mobile/app/quote/[id].tsx` — has ConvertToInvoiceButton, recipient badge
3. **Role-check pattern**: `canUserConvertToInvoice()` from `convertToInvoice.ts` — same role set {admin, super_admin, owner, manager}
4. **API helper**: `api.get()` supports query strings in path (e.g., `/quotes?view=open`) — no extension needed
5. **Confirm dialog**: `Alert.alert()` with Cancel/Destructive buttons — matches existing pattern in detail screen
6. **Toast pattern**: `showToast(msg, variant)` from `useToast()` hook
7. **No STOP triggers** found

## Toggle Fix Applicability
**N/A for mobile** — The mobile quote detail screen has no editable K71-style line-items editor and no grouped/individual display toggle. Line items are view-only. The web commit `d75ef21c4` toggle fix does not apply.

## What Was Implemented

### New files:
- `/app/mobile/src/utils/quoteLifecycle.ts` — 4 exported helpers:
  - `canUserDeclineOrReopenQuote(role)` — role gate for decline/reopen
  - `shouldShowDeclineButton({isInvoice, docStatus, convertedInvoiceId, canDecline})` — visibility predicate
  - `shouldShowReopenButton({isInvoice, docStatus, canReopen})` — visibility predicate
  - `shouldHideConvertWhenDeclined(docStatus)` — Phase 3 regression guard

### Modified files:
- `/app/mobile/app/(app)/quotes.tsx`:
  - Admin: 4-option lifecycle view filter (Open/Converted/Declined/All), testID `quotes-list-filter-{open|converted|declined|all}`
  - Default fetch: `?view=open`
  - Row Decline/Reopen buttons with role gating
  - Alert.alert confirm dialog, 400-aware toasts, lifecycleBusy latch
  - Non-admin: legacy doc_type filter preserved

- `/app/mobile/app/quote/[id].tsx`:
  - `qd-decline-quote` button with Alert.alert confirm + 400 handling
  - `qd-reopen-quote` button with Alert.alert confirm + 400 handling
  - ConvertToInvoiceButton hidden when `status==="declined"`
  - All Phase 1/2 testIDs preserved

### Test file:
- `/app/mobile/__tests__/QuoteDeclineReopen.test.tsx` — 28 tests

## TestIDs Implemented
| testID | Location | Description |
|--------|----------|-------------|
| `quotes-list-filter` | List screen | Filter container |
| `quotes-list-filter-open` | List screen | Open filter option |
| `quotes-list-filter-converted` | List screen | Converted filter option |
| `quotes-list-filter-declined` | List screen | Declined filter option |
| `quotes-list-filter-all` | List screen | All filter option |
| `quote-row-decline-{id}` | List screen | Decline button per row |
| `quote-row-reopen-{id}` | List screen | Reopen button per row |
| `qd-decline-quote` | Detail screen | Decline button |
| `qd-reopen-quote` | Detail screen | Reopen button |

## Dependencies Installed
None

## Known Issues
None
