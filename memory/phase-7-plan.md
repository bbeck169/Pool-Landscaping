# Phase 7 — AI Marketing Studio (confirmed scope, DO NOT BUILD YET)

Approved by the user on 2026-07-13. This is the definitive scope for Phase 7 whenever we get there. All features here are powered by `EMERGENT_LLM_KEY` (Claude Sonnet / Gemini / GPT via emergentintegrations). No FB/IG/X OAuth tokens are wired up in Phase 7 — those integrations remain "generate & copy" until the user provides credentials.

## In scope for Phase 7

1. **Brand memory** — per-tenant document (`brand_memory` Mongo collection). Stores voice/tone, target audience, service areas, unique selling points, disallowed phrases, brand color palette, competitor list. Editable settings page. All AI generations consult this doc as system context.
2. **Campaign briefs** — one-shot AI generator: user provides goal (spring pool opening, HOA outreach, service-area launch, etc.); AI returns a full multi-channel campaign draft = objective, audience segments, timeline, per-channel outputs (see #3), suggested CTAs, KPIs, budget hint.
3. **Post generator with platform-specific variants** — Facebook, Instagram, Nextdoor, Google Business Profile, X. Each with the platform's character limits, hashtag conventions, CTA style, and visual aspect-ratio hints. One prompt → 5 variants.
4. **AI-generated post visuals via Landscape-AI** — reuse the existing render pipeline (Phase 11) to produce a matching image per post variant.
5. **Human-in-the-loop approval queue** — all AI drafts land in a queue (`marketing_queue` collection) with `status: draft | approved | scheduled | published | rejected`. Approver adds comments, edits, and either schedules or publishes.
6. **Content calendar** — month/week view of scheduled + published posts across all channels; drag-to-reschedule; conflict warnings.
7. **Auto-scheduler** — cron-driven (APScheduler in `server.py`) that publishes queue items when their `scheduled_at` fires. For channels without OAuth, marks them as "ready to copy" instead of publishing.
8. **Performance dashboard** — impressions / clicks / leads / conversions by channel + campaign. Data ingested from optional analytics webhooks (GBP has this already); manual entry allowed for channels without APIs.
9. **AI review reply drafts** — extend the existing `gbp` router's AI reply flow to also cover FB reviews (via manual paste-in), with tone controls per brand memory.
10. **Multi-agent @mention chatter** — inside a campaign brief thread, the user can `@AI-Copywriter`, `@AI-Designer`, `@AI-Analyst` etc. Each is an AI Employee (existing router) with a specialized system prompt. Threads persist in `marketing_threads`.
11. **Sequence enrollment** — enroll a lead / customer segment into a marketing sequence (welcome, seasonal, service-launch). Reuses/extends the Phase 7 Sequence Automations engine.
12. **Seeded skill / template catalog** — ship with a starter library: "Spring pool opening", "Chlorine shortage FAQ", "HOA outreach", "Referral flywheel", "5-star review nudge", "Winterization checklist", etc. Each entry has a system-prompt slice and default channel matrix.

## Out of scope for Phase 7 (deferred / user must supply)

- FB / IG / X OAuth publishing — collect tokens later; render as "copy & paste" for now.
- Paid-ads spend/audiences — no ad-account integrations yet.
- Analytics ingestion beyond GBP + manual — add UTM parser only.

## Backend routers to add (Phase 7 only)

- `routers/brand_memory.py`   → GET/PUT `/api/brand-memory`
- `routers/marketing_ai.py`   → POST `/api/marketing/campaign-brief`, `/api/marketing/post-variants`, `/api/marketing/visual`, `/api/marketing/review-reply`, `/api/marketing/thread/@mention`
- `routers/marketing_queue.py`→ CRUD for queued posts, approve/reject, schedule, publish (no-op for un-connected channels)
- `routers/marketing_calendar.py` → GET `/api/marketing/calendar?month=YYYY-MM`
- Extend existing `sequences` (from Phase 7 automations) with `POST /api/sequences/enroll`.

## Frontend routes (Phase 7 only)

- `/marketing` – dashboard (widgets: KPIs, upcoming posts, approvals waiting, review-drafts)
- `/marketing/brand` – brand memory editor
- `/marketing/campaigns` – list + `/marketing/campaigns/new` (AI brief generator)
- `/marketing/posts` – post generator + variants
- `/marketing/calendar` – month/week schedule
- `/marketing/queue` – approval queue
- `/marketing/reviews` – AI review reply drafts (piggybacks on existing `/reviews`)
- `/marketing/templates` – seeded skill/template catalog editor

All admin-only. No customer/tech visibility.
