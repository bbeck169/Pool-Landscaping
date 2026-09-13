# Mobile Parity — Send Quote to Customer

## Status: COMPLETE
**Date**: 2026-09-13

---

## Summary

Implemented the "Send to Customer" action on the mobile quote detail screen,
mirroring the web's `SendToCustomerModal.jsx` toolbar button + modal.

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `src/components/quotes/SendToCustomerSheet.tsx` | 328 | Bottom-sheet modal: recipient preview, override toggle, note textarea (≤500), Send/Cancel |
| `__tests__/send-to-customer-sheet.test.tsx` | 188 (6 tests) | Full coverage: visibility, recipient pre-fill, override, char cap, success toast, error handling |

## Files Modified

| File | Change |
|------|--------|
| `app/quote/[id].tsx` | Added import of `SendToCustomerSheet` + `mapApiError`, `sendOpen` state, send icon button in header (admin + non-invoice gated), render sheet with quote props |

## Endpoint Consumed

| Endpoint | Method | Body |
|----------|--------|------|
| `/quotes/{qid}/send-to-customer` | POST | `{ recipient_email?: string, note?: string }` |

Response: `{ quote_id, status, sent_at, email_sent, recipient }`

## Test Coverage (6 tests)

1. Does not render when `visible=false`
2. Shows recipient pre-filled from `quote.customer_email`
3. Override toggle reveals email input; typed value sent in POST body
4. Note textarea caps at 500 characters
5. Successful POST fires `showToast` with success message + calls `onSent` + `onClose`
6. 403/400 error surfaces `mapApiError` message, sheet stays open

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Alert vs Toast | **Toast only** | Send-to-customer is routine, not destructive. The modal itself serves as the confirmation step. |
| Placement | Header icon button (send-outline) | Adjacent to Duplicate icon, matching existing action pattern. Only visible for admin + non-invoice quotes. |
| RBAC gate | `isAdmin` (admin / super_admin / manager) | Consistent with existing quote detail role checks. Technicians and customers see nothing. |

## Deviations from Spec

None — implementation matches the spec exactly:
- Same endpoint, same body shape, same response handling
- `mapApiError` for errors, `showToast` for success
- Sheet stays open on error (allows user to correct)
- Recipient from `quote.customer_email` serializer field

## Prior Dispatches — UNTOUCHED

- Dispatch A (14 tests): ✅ all green
- Dispatch B (11 tests): ✅ all green
