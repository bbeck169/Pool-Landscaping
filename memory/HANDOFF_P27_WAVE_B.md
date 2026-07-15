# Handoff — Phase 27 Wave B (Feb 15 2026)

## Aggregate
- **OpenAPI: 532 → 543 (+11 endpoints)**
- **Tests: 51/51 pass** across Phase 23-27 suites (0 regressions).
- **All 3 Claude integrations return `mocked:false`** — no silent fallbacks.

## Module 27.1 — Customer Churn Analyzer (LIVE Claude)
- `POST /api/churn/analyze/{customer_id}` — pulls 90d of NPS/CSAT + portal chats + jobs (completed/cancelled) + complaint keywords → sends to Claude Sonnet 4.6 → returns strict JSON `{risk_score, tier, top_signals, recommended_actions, mocked:false}`.
- `POST /api/churn/analyze-all` — batch scores every tenant customer.
- `GET  /api/churn/scores?tier=&min=&max=` — sortable list w/ counts_by_tier.
- `GET  /api/churn/customer/{cid}` — latest score + signal snapshot.
- Weekly APScheduler cron `churn_scan` (Mon 06:00 UTC) refreshes all tenants.
- Storage: `customer_churn_scores` — one doc per customer, upsert on rescore, includes `signals_snapshot` for audit.

## Module 27.2 — Content Refresh Engine (LIVE Claude)
- `POST /api/seo/content-refresh/scan { sitemap_url? OR blog_root_url }` — sitemap.xml first, blog-index fallback, dedup, cap 20 URLs, score each via built-in scorer (title/meta/H1/H2/word count/img alt), rank lowest-first.
- `GET  /api/seo/content-refresh/scans/{sid}`
- `POST /api/seo/content-refresh/rewrite/{sid}/{url_hash}` — Claude generates full rewritten HTML + new title + meta + diff summary + re-scores the result.
- `GET  /api/seo/content-refresh/rewrites?status=` · publish-copy + mark-published lifecycle.
- Storage: `content_refresh_scans` + `content_refresh_rewrites`.

## Module 27.3 — Photo-Based Chemical Dosing (LIVE Claude Vision)
- `POST /api/service-report/analyze-water-photo { photo_url, current_readings?, pool_gallons?, job_id? }` — fetches photo, base64-encodes, sends to Claude Vision, returns `{clarity, issues[], recommendations[{chemical, amount, unit, urgency, reasoning}], overall_assessment, mocked:false}`.
- Admin/super_admin/technician can call. Customer → 403.
- Storage: `water_photo_analyses` — snapshot per analysis for accountability.
- SDK adaptation: `ImageContent(image_base64=...)` (not `image_url=`) per current `emergentintegrations` SDK; server fetches URLs then base64-encodes.

## Frontend (admin)
- `/admin/customer-success/churn` — 4-tier count cards, sortable score table, click row → drawer with top signals + recommended actions.
- `/admin/seo/content-refresh` — URL input, ranked scan table (lowest-first, color-coded scores), per-URL "Rewrite" button, side view with diff summary + copy-HTML CTA.
- Water photo analyzer intended as a modal on the service report page (integration point stubbed; the endpoint is production-ready).
- Sidebar entries: "Churn Risk" (Customers group), "Content Refresh" (SEO group).

## Third-party / integrations
- Claude Sonnet 4.6 via `emergentintegrations.llm.chat` — used for all three modules.
- `ImageContent.image_base64` (NOT `image_url`) — documented so the estimator/vision path stays consistent.

## Known TODOs
- Water-analysis "Analyze photo" button + 1-tap-add-to-chemicals_added modal on the service report page is not yet wired into the frontend service report form (endpoint is ready, storage works, no blocking issues).
- Churn cron runs weekly UTC only; per-tenant local-time deferred.
- Content refresh crawler currently discovers /blog, /post, /article URLs only — customize per-tenant paths later.

## Wave B tests
- 27.1: 4 tests (at-risk scores high, happy scores low, list + isolation, role gating)
- 27.2: 2 tests (scan discovers URLs, role gating)
- 27.3: 3 tests (analysis returns real recommendations, customer 403, persistence)

## Queued
- Phase 26 skill-matching improvement (route dispatcher).
- Wave C: Warranty Portal.
