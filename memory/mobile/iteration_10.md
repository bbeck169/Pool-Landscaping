# Iteration 10 — Phase 5B Tier 2 Completion Pass

## Audit Results

| Screen | Status | Detail |
|--------|--------|--------|
| Referrals (`/referrals`) | DONE | Code card, share, rewards, history, Call Now. Customer-gated. |
| Marketing Hub (`/marketing`) | DONE | 6 cards linking to sub-screens. Admin-gated. |
| Templates (`/marketing/templates`) | FIXED | Was using wrong endpoint `/comms/email-templates`. Now uses `/marketing/templates`. Field mapping corrected. |
| Segments (`/marketing/segments`) | DONE | Correct endpoint, shows system/custom badges. |
| Sequences (`/marketing/sequences`) | DONE | Correct endpoint, shows step counts. |
| Review Requests (`/marketing/review-requests`) | FIXED | Field mapping corrected: `reviewed_at` not `review_left_at`, null `customer_name` handled, added `channel`/`variant`/`source` chips. |
| Analytics (`/marketing/analytics`) | FIXED | Complete rewrite to match actual API shape: `campaigns.total_sent` (was 417), `sequences.total_enrolments` (was 79), etc. Was showing all 0s before. |
| Suppressions (`/marketing/suppressions`) | DONE | Correct endpoint, empty state works. |
| Widget Configs (`/settings/widgets`) | DONE | Both `/instaquote/configs` and `/admin/forms` working. |
| Weather Widget | DONE | Current + 24h hourly strip + 5-day forecast + radar. |
| Next Job | DEFERRED | `GET /api/jobs/next` returns 404 — backend endpoint missing. |
| ClickToCall (bonus) | CREATED | Mobile parity component at `src/components/telephony/ClickToCallButton.tsx`. |

## Navigation Wiring
- Customer portal SECTIONS: "Refer & Earn" → `/referrals`
- Admin `more.tsx`: "Widget Configs" → `/settings/widgets`, "Suppressions" → `/marketing/suppressions`
- Marketing hub card navigation: all 6 sub-screen links working
- Marketing directory `_layout.tsx`: Stack layout
- Settings directory `_layout.tsx`: Stack layout

## Role Gates Verified
- Tech → `/marketing` = "Not authorized" lock screen
- Customer → `/referrals` = Full referral page
- Admin → all marketing screens = Full access

## Tier 1 Regression Check — All Intact
- Invoice viewer (365 lines) ✓
- Estimate viewer (360 lines) ✓
- Workstream detail (419 lines) ✓
- Job detail (540 lines) ✓
- Push notifications (75 lines) ✓
- Business card (275 lines) ✓
- Field report (233 lines) ✓
- Checklist (714 lines) ✓

## Endpoints Hit (verbatim)
- `GET /api/marketing/templates` → 200 (144 templates)
- `GET /api/marketing/audience-segments` → 200 (48 segments)
- `GET /api/marketing/sequences` → 200 (112 sequences)
- `GET /api/marketing/review-requests` → 200 (7 items)
- `GET /api/marketing/analytics/overview` → 200
- `GET /api/marketing/campaigns` → 200
- `GET /api/marketing/suppressions` → 200 (0 items)
- `GET /api/instaquote/configs` → 200
- `GET /api/admin/forms` → 200 (200 forms)
- `GET /api/referrals/me` → 200 (customer) / 403 (admin — expected)
- `GET /api/customer-portal/referrals/my` → 200 (customer)
- `GET /api/jobs/next` → 404 (DEFERRED)
- `GET /api/widget/forms` → 404 (not used, using `/admin/forms` instead)

## Dependencies Installed
None — zero new dependencies.

## Known Issues
- `/api/jobs/next` → 404. "Next Job" card not built. Backend endpoint does not exist.
