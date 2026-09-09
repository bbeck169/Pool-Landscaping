# Iteration 79 — Port Three Web Features to Mobile

## What was implemented

### ITEM 1 — Line-Item Decline + Top-Level Approve/Decline (Phase A)
- Rewrote `estimate-view/[id].tsx` with full Phase A support:
  - Per-line decline button (`estimate-line-item-decline-${i}`) on each line item
  - Decline dialog modal with optional 200-char reason field
  - Declined lines: strike-through + "Declined" chip (`estimate-line-item-declined-chip-${i}`)
  - Undecline button (`estimate-line-item-undecline-${i}`) to restore declined lines
  - Top-level GREEN Approve (`estimate-toolbar-customer-approve`) and RED Decline (`estimate-toolbar-customer-decline`) toolbar
  - Adjusted totals block (`estimate-totals-adjusted-row`) showing "Original: strikethrough → Adjusted: bold"
  - Accepted pill (`estimate-accepted-pill`) / Declined pill (`estimate-declined-pill`)
  - Status guards: toolbar only renders when status in {sent, viewed}
  - 409 `already_finalized` friendly toast handling
  - Magic-link token fetched on load for Phase A portal endpoints
- Updated `estimatesFull.ts` with new API functions: `fetchMagicLinkToken`, `declineLineItem`, `undeclineLineItem`, `approveViaToken`, `declineViaToken`

### ITEM 2 — Schedule Refresh Button
- Added refresh button (`schedule-refresh`) in schedule header toolbar
- Spinner while refreshing (`schedule-refresh-spinner`)
- Calls `load(true)` with force bypass
- Debounce built-in (disabled while refreshing)
- No full re-mount or navigation reset — just re-fetches data

### ITEM 3 — VIP Pill + NavigateJobButton inline with customer name
- Moved NavigateJobButton from `cardRight` to customer name row
- Moved VIP badge to same row (name → nav button → VIP pill)
- Status pill stays on far right in `cardRight` — untouched
- New `vipBadgeInline` style without `marginTop` or `alignSelf: flex-start`

## Files modified
- `/app/mobile/app/estimate-view/[id].tsx` — Full Phase A rewrite
- `/app/mobile/src/api/estimatesFull.ts` — New API functions for Phase A
- `/app/mobile/app/(app)/schedule/calendar.tsx` — Refresh button + VIP/Nav inline
- `/app/mobile/__tests__/parity-phase-a.test.tsx` — New test file (8 tests)

## Test results
- 8/8 tests passing in parity-phase-a.test.tsx
- Screenshot verified: estimate approve/decline, line decline dialog, schedule refresh button, inline nav+VIP

## Known issues
- No VIP jobs in demo data, so VIP pill inline couldn't be visually verified (code is correct per logic)
- Schedule refresh button is small (34x34) in the header toolbar — visible but compact
