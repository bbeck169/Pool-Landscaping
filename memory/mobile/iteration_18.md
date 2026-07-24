# Iteration 18 — MEDIUM-Priority Parity Gap Documentation & Cleanup

## What was done

This iteration was purely administrative — finalizing documentation for code already built and auto-committed by the prior agent session.

### Code already committed (auto-commits from prior session)
- `b9415c5`: Settings screens (business-card, ai-brain, local-seo, website-seo, vanity-slugs), customer chemistry, more.tsx nav updates
- `63025b2`: Portal invoices/estimates navigation wiring fixes

### Documentation updates (this iteration)
1. Updated `MOBILE_PARITY_GAP.md` — 9 MEDIUM-priority items marked as ✅ completed
2. Updated summary counts (MEDIUM ~25 → ~16)
3. Appended commit_log.md entry
4. Added cache directories to `.gitignore` to prevent future git staging confusion

## Completed MEDIUM-Priority Items

| Route | Screen File | Status |
|-------|------------|--------|
| `/portal/invoices/:id` | `portal/invoices.tsx` → `invoice/[id].tsx` | ✅ Nav wired |
| `/portal/estimates/:id` | `portal/estimates.tsx` → `estimate-view/[id].tsx` | ✅ Nav wired |
| `/settings/business-card` | `settings/business-card.tsx` | ✅ Built |
| `/settings/ai-brain` | `settings/ai-brain.tsx` | ✅ Built |
| `/settings/local-seo` | `settings/local-seo.tsx` | ✅ Built |
| `/settings/website-seo` | `settings/website-seo.tsx` | ✅ Built |
| `/settings/vanity-slugs` | `settings/vanity-slugs.tsx` | ✅ Built |
| `/customers/:id/chemistry` (admin) | `customer/chemistry/[id].tsx` | ✅ Built |
| `/customers/:id/chemistry` (tech) | `customer/chemistry/[id].tsx` | ✅ Built |

## Known Issues
- `GET /api/jobs/next` — 404, flagged for backend team
- `PATCH /api/users/{id}` — doesn't support `auto_clockin_enabled`, flagged for backend team

## Remaining MEDIUM-Priority Gaps (~16)
See MOBILE_PARITY_GAP.md for full list. Key remaining areas:
- D2D sub-pages (map, knocks, open-leads, sold-leads)
- Marketing campaign CRUD, sequences CRUD, template detail
- Admin: recurring jobs, job requests, portal inbox, analytics
- Settings: payment-handles, billing, notifications
- Workforce: crew map
- Tracking: salt cell
- Ops hub
