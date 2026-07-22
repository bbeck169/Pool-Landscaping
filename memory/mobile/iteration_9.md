# Iteration 9 — Phase 5B: Mobile Parity Tier 2 Backfill

## What was implemented

### Screens wired and verified:
1. **Referrals** (`/referrals`) — Customer referral code, share button, rewards summary, referral history. Role-gated to customer role.
2. **Marketing Hub** (`/marketing`) — Admin hub linking to Templates, Segments, Sequences, Review Requests, Analytics, Suppressions. Role-gated to admin.
3. **Templates** (`/marketing/templates`) — Email/SMS template list with status indicators.
4. **Segments** (`/marketing/segments`) — Audience segments with system/custom badges and recipient counts.
5. **Sequences** (`/marketing/sequences`) — Drip campaign sequences with step counts.
6. **Review Requests** (`/marketing/review-requests`) — Review request queue.
7. **Analytics** (`/marketing/analytics`) — KPI cards (sends, open rate, click rate, etc.), campaign summary, recent campaigns.
8. **Suppressions** (`/marketing/suppressions`) — Unsubscribe/bounce list with search, empty state.
9. **Widget Configs** (`/settings/widgets`) — AI Chat widget configs and Form Builder configs, read-only.

### Navigation wiring:
- Added "Refer & Earn" to customer portal SECTIONS in `portal/home.tsx`
- Added "Widget Configs" and "Suppressions" links to admin links in `more.tsx`
- Fixed Marketing Studio route in `sections.ts` (was `/(app)/marketing`, now `/marketing`)

### Routing fixes:
- Deleted conflicting `marketing.tsx` root-level file (was causing Expo Router layout-leaf conflict with `marketing/` directory)
- Created `marketing/_layout.tsx` (Stack layout) for proper directory-based routing
- Created `settings/_layout.tsx` (Stack layout) for settings directory

### Role gates verified:
- Tech user accessing `/marketing` → "Not authorized" lock screen with "Marketing is available to admins only."
- Customer user accessing referrals → Full referral code, rewards, and history

## Web-to-mobile mapping
| Web Feature | Mobile Screen | API Endpoints |
|---|---|---|
| Referral Rewards | `/referrals` | `GET /api/referrals/me`, `GET /api/customer-portal/referrals/my` |
| Marketing Templates | `/marketing/templates` | `GET /api/marketing/templates` |
| Marketing Segments | `/marketing/segments` | `GET /api/marketing/segments` |
| Marketing Sequences | `/marketing/sequences` | `GET /api/marketing/sequences` |
| Review Requests | `/marketing/review-requests` | `GET /api/marketing/review-requests` |
| Marketing Analytics | `/marketing/analytics` | `GET /api/marketing/analytics/overview` |
| Suppressions | `/marketing/suppressions` | `GET /api/marketing/suppressions` |
| Widget Configs | `/settings/widgets` | `GET /api/instaquote/configs`, `GET /api/admin/forms` |

## Deferred items
- **Next Job card**: `GET /api/jobs/next` returned 404. Backend endpoint does not exist. Deferred per instructions.
- **Weather forecast strip**: Already implemented in prior iteration (24-hour hourly strip + 5-day forecast on admin dashboard and tech calendar). No additional changes needed.

## Dependencies installed
- None (all dependencies were already available)

## Known issues
- None
