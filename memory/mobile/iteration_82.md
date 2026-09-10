## Iteration 82 — Mobile Parity: Task 3, Task 5, Task 6, PB2

### What was implemented

**Task 3 — Invoice Magic Link (`/i/:token`)**
- New screen: `/app/mobile/app/i/[token].tsx`
- Decodes JWT client-side to extract `invoice_id`
- Fetches via `GET /api/invoices/{iid}/full-magic?token=...`
- Read-only invoice render (company, bill-to, line items, totals, notes, payment stub)
- "Pay Now" button calls `POST /api/invoices/{iid}/request-payment-link-magic?token=...` then opens checkout URL in system browser via `Linking.openURL()`
- Invalid token → error state with "Link Invalid" message
- API error → retry button
- Test IDs: `public-invoice-magic-invalid-token`, `public-invoice-magic-root`, `magic-invoice-*`, `invoice-pay-now-btn`

**Task 5 — Save Stripe Card on File**
- New screen: `/app/mobile/app/portal/payment-methods.tsx`
  - Lists saved cards from `GET /customer-portal/payment-methods`
  - Remove card: `DELETE /customer-portal/payment-methods/{id}` with confirm dialog
  - Set default: `PATCH /customer-portal/payment-methods/{id}/set-default`
  - Empty state: "No cards on file" guidance
  - Test IDs: `portal-pm-list`, `portal-pm-row-{id}`, `portal-pm-default-chip-{id}`, `customer-pm-remove-{id}`, `customer-pm-set-default-{id}`, `portal-pm-empty-state`, `portal-pm-remove-confirm-dialog`
- Save card toggle on magic invoice pay flow: `magic-invoice-save-card-switch`
- "View all cards" link added to existing `/portal/payment-method.tsx`

**Task 6 — Quote/Estimate Terms & Conditions**
- Added `terms_and_conditions?: string` to `EstimateFull` type in `estimatesFull.ts`
- Added Terms section in `estimate-view/[id].tsx` between notes and disclaimer
- Populated terms → renders heading + paragraphs
- Empty/null/whitespace → collapsed "No terms" label with icon
- Test IDs: `estimate-terms-section`, `estimate-terms-heading`, `estimate-terms-body`, `estimate-no-terms`

**PB2 — Documented Gap**
- Created `/app/memory/MOBILE_PARITY_GAPS.md`
- Mobile has NO admin line-item editor for estimates/invoices
- Customer views do NOT expose override fields (stripped server-side)
- PB1 categories admin screen skipped per spec

### Web-to-Mobile Mapping
| Web Component | Mobile Screen |
|---|---|
| `PublicInvoiceMagic` (`/i/:token`) | `app/i/[token].tsx` |
| `PortalPaymentMethods` | `app/portal/payment-methods.tsx` |
| `DocTermsSection` | Inline in `app/estimate-view/[id].tsx` |
| `K71LineItemsEditor` (PB2) | GAP — no mobile editor |

### Tests Created
- `__tests__/task3-invoice-bypass-mobile.test.tsx` — 6 tests
- `__tests__/task5-save-card-mobile.test.tsx` — 4 tests
- `__tests__/task6-terms-mobile.test.tsx` — 6 tests
- `__tests__/pb2-line-item-overrides.test.tsx` — 4 tests
- Total: 20 new tests, all passing

### Dependencies Installed
None — all features use existing dependencies.

### Known Issues
None — all tests pass, no regressions.
