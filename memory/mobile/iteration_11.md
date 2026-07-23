# Iteration 11 — Phase 13: Mobile Parity Backfill

## Tier A — DONE
| Item | Status | Detail |
|------|--------|--------|
| A1. Leads system | DONE | List (status filters, search) + Detail (contact, actions, notes, timeline, close-won convert, close-lost with reason) |
| A2. Referrals+Credits (Customer) | DONE | Phase 10 status pills (Pending/Waiting Xd/Credited/Voided), credit balance |
| A3. Card-on-file (Customer detail) | DONE | Tri-state toggle, cached card display, "Reset to tenant default", credits banner |
| A4. Add-card WebView | DONE | WebView wrapper for mobile-responsive web Stripe SetupIntent form |

## Tier B — DONE
| Item | Status | Detail |
|------|--------|--------|
| B5. Equipment Trackers | DONE | Type tabs (filter/salt_cell), status tabs (current/coming_due/past_due), search, row cards |
| B6. Admin Referrals | DONE | Summary card + list with status pills |
| B6. Promo Codes | DONE | Code list, type badge, amount, toggle active |

## Tier B — DEFERRED
| Item | Status | Reason |
|------|--------|--------|
| B7. Customer Credits tab | DEFERRED | `/api/customers/{id}/credits` works but building a separate tab is low priority — credits balance shown on customer detail |
| B8. Tenant settings (12C) | DEFERRED | `/api/tenant/settings` returns 404 — no accessible endpoint for timezone picker or auto-send toggle |
| B9. Promo code on invoice | DEFERRED | Requires deeper invoice viewer modifications — `POST /api/promo-codes/validate` works but PaymentIntent integration needs careful handling |

## Navigation Wiring
- Admin global menu tiles: "Leads" (Customers section), "Service Tracking" (Operations section)
- Admin more.tsx links: "Service Tracking", "Admin Referrals", "Promo Codes"
- Tech global menu: "Service Tracking" (My Records section)
- Customer portal: "Refer & Earn" already wired from previous iteration

## Role Gates Verified
- Tech → `/admin/referrals` = "Not authorized"
- Tech → `/tracking` = ALLOWED (techs need tracker access)
- Customer → `/leads` = "Not authorized"
- Customer → `/referrals` = Full referral page

## Endpoint Inventory
| Endpoint | HTTP | Status | Used In |
|----------|------|--------|---------|
| GET /api/leads | GET | 200 | leads/index.tsx |
| GET /api/leads/{id} | GET | 200 | leads/[id].tsx |
| PATCH /api/leads/{id} | PATCH | 200 | leads/[id].tsx (status change) |
| POST /api/leads/{id}/note | POST | 200 | leads/[id].tsx |
| POST /api/leads/{id}/close-won | POST | 200 | leads/[id].tsx |
| POST /api/leads/{id}/close-lost | POST | 200 | leads/[id].tsx |
| GET /api/equipment/trackers | GET | 200 | tracking/index.tsx |
| GET /api/admin/referrals | GET | 200 | admin/referrals.tsx |
| GET /api/promo-codes | GET | 200 | settings/promo-codes.tsx |
| PATCH /api/promo-codes/{id} | PATCH | 200 | settings/promo-codes.tsx (toggle) |
| PATCH /api/customers/{id} | PATCH | 200 | customer/[id].tsx (card override) |
| GET /api/customers/{id}/credits | GET | 200 | customer/[id].tsx (balance display) |
| POST /api/customers/{id}/send-card-link | POST | 404 | DEFERRED |
| GET /api/tenant/settings | GET | 404 | DEFERRED |

## Dependencies
Zero new dependencies installed.
