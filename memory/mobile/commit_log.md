# Mobile Commit Log

## Iteration 1 — Templates Library Phase 3 (Mobile UI)
- **Commit**: 3af1fd6a6290b4d058770eb1b46944015c9b18f8 (base)
- **Date**: 2026-07-18
- **Changes**:
  - Created templates library screen with two-tab layout (Library / My Templates)
  - Created template fill screen with autosave, finalize, duplicate, delete, PDF download
  - Created 4 template components: TemplateCard, TemplateFieldRenderer, TemplateTableField, TemplateStatusPill
  - Added hidden tab screens in `_layout.tsx` for templates routes
  - Added Templates tile to both admin and technician Tools hub sections
  - Added Templates Library link to More/Admin links
- **Files created**:
  - `mobile/app/(app)/templates/index.tsx`
  - `mobile/app/(app)/templates/[id].tsx`
  - `mobile/src/components/templates/TemplateCard.tsx`
  - `mobile/src/components/templates/TemplateFieldRenderer.tsx`
  - `mobile/src/components/templates/TemplateTableField.tsx`
  - `mobile/src/components/templates/TemplateStatusPill.tsx`
- **Files modified**:
  - `mobile/app/(app)/_layout.tsx` — added hidden tab screens for templates
  - `mobile/src/components/tools/sections.ts` — added Templates tile to admin + tech
  - `mobile/app/(app)/more.tsx` — added Templates Library admin link

## Iteration 2 — Offline Draft Support
- **Commit**: 15a0dcefdd2c2df77cf8478788c1582ace1ec5af
- **Date**: 2026-07-18
- **Changes**:
  - Created `offlineTemplateDrafts.ts` — full offline-draft module (snapshot CRUD, pending queue CRUD, FIFO flush, merge logic, global listeners)
  - Rewrote `[id].tsx` fill screen with offline integration: snapshot-before-PATCH, queue-on-failure, merge-on-load, finalize-block
  - Added offline indicator pill in header, "Saved locally" state, local-edits-merged banner
  - Registered global NetInfo + AppState listeners in root `_layout.tsx`
  - Updated PRD with complete offline-draft behavior documentation
- **Files created**:
  - `mobile/src/utils/offlineTemplateDrafts.ts`
- **Files modified**:
  - `mobile/app/(app)/templates/[id].tsx` — offline-draft integration
  - `mobile/app/_layout.tsx` — global listener registration
  - `memory/PRD.md` — Phase 3 documentation with offline-draft section

## Iteration 3 — Phase 4 · Batch A Mobile Signature Pad
- **Commit**: dff7a798966099aecacdbde2754e106163dbb97e
- **Date**: 2026-07-18
- **Changes**:
  - Installed `react-native-signature-canvas@5.1.0`
  - Created `SignaturePadModal.tsx` — full-screen modal with WebView-based drawing canvas
  - Refactored signature branch in `TemplateFieldRenderer.tsx` — replaced plain-text stamp with drawing pad modal, added Image thumbnail display, backward compat for 3 value shapes
  - Updated PRD with Phase 4 Batch A Mobile subsection
- **Files created**:
  - `mobile/src/components/templates/SignaturePadModal.tsx`
- **Files modified**:
  - `mobile/src/components/templates/TemplateFieldRenderer.tsx` — signature refactor
  - `mobile/package.json` — added react-native-signature-canvas
  - `memory/PRD.md` — Phase 4 Batch A Mobile subsection


## Iteration 4 — Phase 5B · Video Uploads (Mobile Expo)
- **Commit**: ad8709e66264ffff2d3e37e4a018763f13860b13
- **Date**: 2026-07-19
- **Changes**:
  - Installed `expo-video@3.0.16` (SDK 54 compatible)
  - Created video API client (`media.ts`): upload with XHR progress, PATCH, DELETE, stream URL builder, offline guard
  - Created `VideoMediaUploader` component: tile grid, record/pick, progress, visibility toggle, delete
  - Created `VideoPlayerModal`: full-screen expo-video player with native controls
  - Created customer portal Videos screen with entity grouping
  - Integrated video section into job detail + estimate detail screens
  - Added Videos entry to customer portal nav
  - Added microphone + video permissions to app.json
  - Updated PRD with Phase 5B subsection
- **Files created**:
  - `mobile/src/api/media.ts`
  - `mobile/src/components/media/VideoMediaUploader.tsx`
  - `mobile/src/components/media/VideoPlayerModal.tsx`
  - `mobile/app/portal/videos.tsx`
- **Files modified**:
  - `mobile/app/job/[id].tsx` — added VideoMediaUploader
  - `mobile/app/estimator/[id].tsx` — added VideoMediaUploader
  - `mobile/app/portal/home.tsx` — added Videos nav entry
  - `mobile/app.json` — permissions
  - `mobile/package.json` — added expo-video
  - `memory/PRD.md` — Phase 5B subsection


## Iteration 5 — Communications Subsystem · Phase 4 (Mobile Parity)
- **Commit**: 23e1f06
- **Date**: 2026-07-20
- **Changes**:
  - 11 new files: `src/api/comms.ts`, 2 components (SendStatusPill, ChannelIcon), 8 screens (hub, templates list/detail, automations list/detail, sends list/detail, test-send)
  - Wired Comms tile to ADMIN_SECTIONS and added 8 hidden routes to `_layout.tsx`
  - All screens verified via screenshots: templates (8 email templates listed), automations (5 rules with toggles), sends (100 records with QUEUED status), test-send form
- **Files modified**: comms.ts, SendStatusPill.tsx, ChannelIcon.tsx, comms/index.tsx, templates/index.tsx, templates/[code].tsx, automations/index.tsx, automations/[code].tsx, sends/index.tsx, sends/[id].tsx, test-send.tsx, sections.ts, _layout.tsx
- **Web files referenced**: api/comms.js, CommsPages.jsx, SendStatusPill.jsx

## Iteration 6 — Mobile Parity Slice (Tech + Admin Roles)
- **Commit**: 1fd0acb
- **Date**: 2026-07-20
- **Changes**:
  - PART A (Tech): WeatherWidget, RainFlag badge, VIP badge, MultiContact viewer, CustomerTasks tab, SendCreateSheet, Campaigns list, ServiceNotes
  - PART B (Admin): AIDockDrawer, WeatherWidget (shared), CreditsBudgetChip
  - Role gate enforced: Tech & Customer roles NEVER see AI Dock, credits chip, or AI-adjacent UI
  - Bug fix: MultiContact.tsx crash — mapped `number_e164`/`address` from objects instead of treating as strings
- **Files created**:
  - `mobile/src/api/aiDock.ts`
  - `mobile/src/api/weather.ts`
  - `mobile/src/components/ai/AIDockDrawer.tsx`
  - `mobile/src/components/ai/CreditsBudgetChip.tsx`
  - `mobile/src/components/customers/CustomerTasks.tsx`
  - `mobile/src/components/customers/MultiContact.tsx`
  - `mobile/src/components/customers/SendCreateSheet.tsx`
  - `mobile/src/components/customers/ServiceNotes.tsx`
  - `mobile/src/components/weather/RainFlag.tsx`
  - `mobile/src/components/weather/WeatherWidget.tsx`
- **Files modified**:
  - `mobile/app/(app)/_layout.tsx` — hidden route for campaigns
  - `mobile/app/(app)/index.tsx` — role-gated dashboard widgets
  - `mobile/app/(app)/schedule/calendar.tsx` — weather on calendar
  - `mobile/app/campaigns.tsx` — new campaigns screen
  - `mobile/app/customer/[id].tsx` — Tasks, MultiContact, ServiceNotes, SendCreate, VIP badge
- **Web files referenced**: WeatherWidget, AIDock sidebar, CreditsBudget, CampaignsList, CustomerDetail

## Iteration 7 — AI Dock Bug Fix (Identifier Mismatch)
- **Commit**: 89321db
- **Date**: 2026-07-21
- **Changes**:
  - **Root cause**: Mobile used legacy `chatSimple` endpoint with string slugs; backend expects UUID-based conversation flow
  - Refactored `aiDock.ts`: replaced `chatSimple` with `createConversation`, `sendConversationMessage`, `approveAction`, `rejectAction`
  - Rewrote `AIDockDrawer.tsx` ChatView: conversation state management, proper message parsing, pending action cards
  - Fixed action card display fields: `label/action_type` → `title/action`, `description` → `summary`
  - Verified via screenshots: chat works, approve works, credits debit, no "AI employee not found" error
- **Files modified**:
  - `mobile/src/api/aiDock.ts` — full API rewrite for conversation flow
  - `mobile/src/components/ai/AIDockDrawer.tsx` — ChatView rewrite + action card field fix
- **Web files referenced**: backend/routers/ai_employees.py (endpoint schema), frontend AI Dock patterns

## Iteration 8 — Phase 5A + 5A.2 Mobile Mirror
- **Commit**: db8bb93
- **Date**: 2026-07-22
- **Changes**:
  - Tech UX cleanup: removed Field Estimator + Property Lookup from TECH_SECTIONS + techLinks
  - Added role-gate screens for estimator + property-lookup (techs → "Not available on your role")
  - Workstream restricted to admin/super_admin only with role-gate UI
  - Workstream: removed status filters, default completed-only, title "Workstream — Completed Jobs"
  - NEW Service Log detail at /workstream/[id]: 4 sections (Log Details + Water Test + Chemicals/Notes + Images)
  - EMAIL DOOR HANGER button with 429 cooldown handling
  - FieldReport checklist now backend-driven via GET /api/checklists/daily
  - Work Stream moved to adminLinks in More screen
  - Business Card confirmed correct for techs (company only, no My Card)
- **Files created**:
  - `mobile/src/api/serviceLog.ts`
  - `mobile/app/workstream/[id].tsx`
- **Files modified**:
  - `mobile/app/workstream.tsx` (rewrite)
  - `mobile/src/components/tools/sections.ts`
  - `mobile/src/components/job/FieldReport.tsx`
  - `mobile/app/(app)/more.tsx`
  - `mobile/app/(app)/estimator/index.tsx`
  - `mobile/app/(app)/property-lookup.tsx`
- **Web files referenced**: none (backend API-only integration)


## Iteration 9 — Phase 5B: Mobile Parity Tier 2 Backfill
- **Commit**: fbad81524a3c5b04c7a0ed482bb6bf199dec022a
- **Date**: 2026-07-22
- **Changes**:
  - Wired 9 Tier 2 screens into navigation (referrals, marketing hub, templates, segments, sequences, review-requests, analytics, suppressions, widget configs)
  - Fixed Expo Router conflict: deleted root `marketing.tsx`, created `marketing/_layout.tsx` Stack layout
  - Created `settings/_layout.tsx` Stack layout
  - Added "Refer & Earn" to customer portal SECTIONS
  - Added "Widget Configs" and "Suppressions" to admin links in `more.tsx`
  - Fixed Marketing Studio route in `sections.ts` from `/(app)/marketing` to `/marketing`
  - Verified role gates (tech blocked from marketing with "Not authorized" screen)
  - All lint clean across all 9 screen files
  - Deferred "Next Job" card (backend 404 on `GET /api/jobs/next`)
- **Files modified**: `app/marketing/_layout.tsx` (new), `app/settings/_layout.tsx` (new), `app/portal/home.tsx`, `app/(app)/more.tsx`, `src/components/tools/sections.ts`, `app/settings/widgets.tsx`
- **Files deleted**: `app/marketing.tsx` (route conflict)
- **Web files referenced**: None (screens were already built by prior agent)


## Iteration 10 — Phase 5B Tier 2 Completion Pass
- **Commit**: fd96aec6ab2e9ec360d1b6834a10cfe62b8012bb
- **Date**: 2026-07-22
- **Changes**:
  - Fixed templates screen: switched from `/comms/email-templates`+`/comms/sms-templates` to canonical `GET /api/marketing/templates`; fixed field mappings (`name` not `code`, `active` not `is_active`); added `category` and `system` badges
  - Fixed analytics screen: completely rebuilt to match actual API shape (`campaigns.total_sent/active/delivered/opened/clicked/converted`, `sequences.total_enrolments/active/completed/halted`, `review_requests.total/sent/opened/reviewed/review_rate_pct`); was showing all 0s before due to expecting non-existent `totals`/`rates` keys
  - Fixed review-requests screen: corrected field mappings (`reviewed_at` not `review_left_at`, handle null `customer_name`, display `channel`/`variant`/`source` chips, timestamp display with proper `requested_at` fallback)
  - Created `ClickToCallButton.tsx` (bonus): mobile parity for Phase 6B telephony — primary native `tel:` dialer via `Linking.openURL`, secondary RC ring-out via `POST /api/rc/call`, intent logging via `POST /api/rc/log-outbound`
  - All lint clean, all role gates verified, all Tier 1 files intact
- **Files modified**: `app/marketing/templates.tsx` (rewritten), `app/marketing/analytics.tsx` (rewritten), `app/marketing/review-requests.tsx` (rewritten)
- **Files created**: `src/components/telephony/ClickToCallButton.tsx`
- **Endpoints verified**: `/api/marketing/templates` (200), `/api/marketing/analytics/overview` (200), `/api/marketing/review-requests` (200), `/api/marketing/campaigns` (200), `/api/marketing/audience-segments` (200), `/api/marketing/sequences` (200), `/api/marketing/suppressions` (200), `/api/instaquote/configs` (200), `/api/admin/forms` (200), `/api/referrals/me` (200 for customer), `/api/customer-portal/referrals/my` (200 for customer), `/api/jobs/next` (404 — deferred)


## Iteration 11 — Phase 13: Mobile Parity (Leads/Card-on-file/Trackers/Referrals/Promo)
- **Commit**: 64ce7a1cf1a4d2096a8cdf54355cdeee793fe528
- **Date**: 2026-07-23
- **Changes**:
  - **Leads (Tier A1)**: Fixed `leads/index.tsx` API parsing (`{rows: [...]}` format, capitalized statuses); moved `leads.tsx` → `leads/index.tsx` to resolve Expo Router conflict; created `leads/[id].tsx` full Phase 8 detail (contact card, status, source badge, action buttons — Close Won convert, Close Lost with reason modal, Mark Contacted/Quoted, On Hold, Archive, notes editor, timeline); added `leads/_layout.tsx`
  - **Card-on-file (Tier A3)**: Enhanced `customer/[id].tsx` — green "Card on file (Visa •••• last4)" status, yellow "No card — required" warning, tri-state Switch + "Reset to tenant default" ghost button, credits balance banner when > 0
  - **Portal add-card (Tier A4)**: Created `portal/add-card.tsx` WebView wrapper for the already mobile-responsive web Stripe SetupIntent form
  - **Referrals (Tier A2)**: Updated `referrals.tsx` with Phase 10 status pills (Pending / Waiting Xd / Credited / Voided)
  - **Trackers (Tier B5)**: Created `tracking/index.tsx` — type tabs (All/Filter/Salt Cell), status tabs (All/Past Due/Coming Due/Current with counts), search, row cards with type icon + customer + address + interval + dates
  - **Admin Referrals (Tier B6)**: Created `admin/referrals.tsx` — summary card + list with status pills
  - **Promo Codes (Tier B6)**: Created `settings/promo-codes.tsx` — code list + type badge + amount + uses + active toggle
  - **Navigation**: Added Leads + Service Tracking to admin global menu tiles; added Tracking/Admin Referrals/Promo Codes to admin more.tsx links; added Service Tracking to tech nav
- **Files created**: `leads/[id].tsx`, `leads/_layout.tsx`, `tracking/index.tsx`, `tracking/_layout.tsx`, `admin/referrals.tsx`, `admin/_layout.tsx`, `settings/promo-codes.tsx`, `portal/add-card.tsx`
- **Files modified**: `leads/index.tsx` (moved + fixed), `referrals.tsx`, `customer/[id].tsx`, `(app)/more.tsx`, `src/components/tools/sections.ts`
- **Endpoints verified**: `/api/leads` 200, `/api/leads/{id}` 200, `/api/leads/{id}/close-won` 200, `/api/leads/{id}/close-lost` 200, `/api/leads/{id}/note` 200, `/api/equipment/trackers` 200, `/api/admin/referrals` 200, `/api/promo-codes` 200, `/api/customers/{id}/credits` 200, `/api/promo-codes/validate` 200, `PATCH /api/customers/{id}` 200
- **404 endpoints (deferred)**: `/api/customers/{id}/send-card-link` (all variations), `/api/tenant/settings`, `/api/jobs/next`
