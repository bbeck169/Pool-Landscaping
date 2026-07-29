## Iteration 25 — Fix Batch: Header Layout + Next Service Day + Demo Logins
- **Commit**: a7d0054d3588021bad40d57ca234cbe04e990268
- **Date**: 2026-07-28
- **Changes**:
  - FIX 1: Restructured Header component — removed flexDirection:"row" from outer container, added headerRow wrapper. Fixes vertical one-char-per-line text rendering on Appointments page.
  - FIX 2: Added "Next Service Day" tile below Quick Actions on portal/home.tsx with populated and empty states
  - FIX 3: Added 4 demo login buttons gated on EXPO_PUBLIC_ENV=preview in login.tsx
  - Jest test infrastructure: jest.config.js + 3 test suites (14 tests total, all passing)
  - test_compromised_secret_not_present_anywhere: PASSED
- **Files modified**: `src/components/widgets.tsx`, `app/portal/home.tsx`, `app/login.tsx`, `.env`
- **Files created**: `jest.config.js`, `__tests__/demo-login.test.tsx`, `__tests__/next-service-day.test.tsx`, `__tests__/appointments-header.test.tsx`
- **Web files referenced**: None (bug fixes and feature addition)


## Iteration 24 — Phase 33 + 34 + 32 (Portal Parity + Offline Foundation)
- **Commit**: 6722a503f6c39e4a75b6285a944a5af6aaae8808
- **Date**: 2026-07-27
- **Changes**:
  - Phase 33: BrandLogo, forgot-password, portal home rewrite (CTA row, hero, concierge gradient, referral $55 gradient, last visit, media date grouping, request service simplify, Book Service deprecated)
  - Phase 34: Business card website row, referral $55, tour v2, auto-send completion banner, password reset/change flows, leads status enum (5 canonical), AI employee dedupe
  - Phase 32: offlineStore.ts, SyncManager.tsx, SyncStatusPill.tsx, root layout integration
- **Files modified**:
  - NEW: `src/components/BrandLogo.tsx`, `app/forgot-password.tsx`, `app/reset-password.tsx`, `app/settings/change-password.tsx`, `src/components/Tour.tsx`, `src/services/offlineStore.ts`, `src/services/SyncManager.tsx`, `src/components/SyncStatusPill.tsx`
  - REWRITTEN: `app/portal/home.tsx`, `app/portal/photos.tsx`, `app/portal/videos.tsx`, `app/portal/service-reports.tsx`, `app/request-service.tsx`, `app/portal/book.tsx`
  - EDITED: `app/login.tsx`, `app/card.tsx`, `app/referrals.tsx`, `app/job/[id].tsx`, `app/leads/index.tsx`, `app/leads/[id].tsx`, `app/(app)/more.tsx`, `app/(app)/index.tsx`, `app/_layout.tsx`, `src/components/job/styles.ts`
- **Web files referenced**: Phase 32/33/34 delegation briefs in `/app/memory/delegations/`


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


## Iteration 12 — Phase 13B: 3 Deferred Surfaces Complete
- **Commit**: 55b90923637c467e17c57c4c55ed9b11caa22993
- **Date**: 2026-07-23
- **Changes**:
  - **Credits tab (customer detail)**: Added full CREDIT BALANCE section to `customer/[id].tsx` — big balance card, paginated ledger (source/delta/date/actor), "Adjust" button → modal with dollar amount input, reason textarea (min 5 chars), live balance preview, INSUFFICIENT_BALANCE error handling. Uses `GET /api/customers/{id}/credits` and `POST /api/customers/{id}/credits/adjust`.
  - **Tenant Settings**: Created `settings/tenant.tsx` — timezone picker (5 US timezones as chip grid, AZ default), "Require card on file by default" switch, "Auto-send add-card link on creation" switch, "Next scheduled sync: Thu 02:00 · <TZ>" label, "Last changed Xd ago by ..." footer. Uses `GET/PATCH /api/tenants/mine/settings`.
  - **Invoice promo code**: Added collapsible "Have a promo code?" section to `invoice/[id].tsx` — input + Apply button, green pill for `next_invoice` discounts, blue pill for `account_credit` codes, red inline error for invalid codes, Remove button. `promo_code_id` passed to `createPaymentIntent`. Updated `payments.ts` to accept optional `promoCodeId`.
  - **Fixed send-card-link typo**: Changed `requestCard` in `customer/[id].tsx` from `/payments/request-method/${id}` to correct `/customers/${id}/send-card-add-link`.
  - Added "Tenant Settings" nav link to admin more.tsx.
- **Files modified**: `customer/[id].tsx` (credits section + adjust modal + card link fix), `invoice/[id].tsx` (promo code section), `src/api/payments.ts` (promo_code_id param), `(app)/more.tsx` (tenant settings link)
- **Files created**: `settings/tenant.tsx`
- **Endpoints verified**: `GET /api/tenants/mine/settings` 200, `PATCH /api/tenants/mine/settings` 200, `POST /api/customers/{id}/credits/adjust` 200, `GET /api/customers/{id}/credits` 200, `POST /api/promo-codes/validate` 200, `POST /api/customers/{id}/send-card-add-link` 200

## Iteration 12 — Timeclock Admin-Hide Parity
- **Commit**: a742fea63300f6c70240001042e67068d67f4388
- **Date**: 2026-07-23
- **Changes**:
  - Flipped `isLandscaper` logic in `LandscapingClockWidget.tsx` from `isAdminLike || hasLandscapeDept` to `!isAdminLike && hasLandscapeDept`
  - Added mount-site guards in both `index.tsx` and `schedule/calendar.tsx` to return null for admin/super_admin roles
  - Updated comment block to reflect new role gate logic
- **Files modified**:
  - `/app/mobile/src/components/LandscapingClockWidget.tsx` (line 54 logic flip + comment update)
  - `/app/mobile/app/(app)/index.tsx` (line 66 mount-site guard)
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (line 275 mount-site guard)
- **Web files referenced**: None (instructions were explicit)



## Iteration 13 — BUG H + BUG I Fix (Auto Clock-In error + Settings admin-only)
- **Commit**: 5501bd867bccdc2a9b4abadaed799f9c07d83f6e
- **Date**: 2026-07-24
- **Changes**:
  - **BUG H**: Fixed `storage.get is not a function` crash in Auto Clock-In screen.
    - Root cause: `src/background/autoClockin.ts` called `storage.get()` / `storage.set()` but the storage module exports `getItem()` / `setItem()`.
    - Fix: `storage.get` → `storage.getItem`, `storage.set` → `storage.setItem` (lines 53, 57)
    - Added missing `Tabs.Screen` registrations for `settings/auto-clockin` and `settings/lidar` in `(app)/_layout.tsx`
  - **BUG I**: Made Settings routes admin-only.
    - Root cause: `settings/_layout.tsx` had no role guard — any user could navigate to `/settings/*`.
    - Fix: Rewrote `settings/_layout.tsx` with role guard (admin/super_admin only); non-authorized users see "Not authorized" screen.
    - Also removed `manager` from `tenant.tsx` allowed list (was `admin|super_admin|manager`, now `admin|super_admin` only).
  - **LandscapingClockWidget**: Verified `isLandscaper = !isAdminLike && hasLandscapeDept` already correct ✅
- **Files modified**:
  - `/app/mobile/src/background/autoClockin.ts` (storage method names fix)
  - `/app/mobile/app/settings/_layout.tsx` (rewritten with admin role guard)
  - `/app/mobile/app/settings/tenant.tsx` (removed manager from allowed list)
  - `/app/mobile/app/(app)/_layout.tsx` (added Tabs.Screen for settings/auto-clockin and settings/lidar)
- **Verified via screenshots**:
  - Tech → Auto Clock-In: renders correctly, no error ✅
  - Tech → /settings/widgets: shows "Not authorized" gate ✅
  - Admin → /settings/tenant: shows full Tenant Settings ✅


## Iteration 14 — BUG H Regression Fix + Auto Clock-In Default-ON Feature
- **Commit**: d9c5d58c505885ffc4183363593c5b52a4090692
- **Date**: 2026-07-24
- **Changes**:
  - **BUG H Regression**: Previous fix was correct on disk but Metro bundler cache served old code.
    - Cleared `.metro-cache`, `node_modules/.cache`, `/tmp/metro-*`, `/tmp/haste-map-*`
    - Restarted mobile service. Verified error is gone.
    - Grepped all `storage.get`/`storage.set` calls — zero bad callsites remain.
  - **Feature: Auto Clock-In default ON**:
    - `src/background/autoClockin.ts`: Added `AUTO_CLOCKIN_EXPLICIT_KEY` sentinel. `isAutoClockinEnabled(role)` now accepts role param — returns `true` for techs on first visit (no explicit pref set), `false` for others.
    - `app/(app)/settings/auto-clockin.tsx`: Full rewrite with green/red ON/OFF status banner, role guard for non-techs, status text, info note about default-ON.
    - Toggle persistence: `setAutoClockinEnabled` writes both the pref and the explicit-flag so subsequent reads use the saved value.
  - **Backend gap flagged**: `PATCH /api/users/{id}` does NOT support `auto_clockin_enabled`. Pref is local-storage-only for now. Backend + web agent need to add the field.
- **Files modified**:
  - `/app/mobile/src/background/autoClockin.ts` (default-ON logic with explicit sentinel)
  - `/app/mobile/app/(app)/settings/auto-clockin.tsx` (full rewrite with ON/OFF banner)
- **Verified via screenshots**:
  - Fresh tech login → Auto Clock-In ON by default ✅
  - Toggle to OFF → Red banner "Auto Clock-In is OFF", Status: Stopped ✅
  - No errors after Metro cache clear ✅

## Iteration 15 — Move Weather Widget to Bottom of Schedule Page
- **Commit**: 9b1bfad97faa9c73cf4fe1f5477274a520c5539b
- **Date**: 2026-07-24
- **Changes**:
  - Removed `<WeatherWidget>` from the top wrapper (line 276) in `schedule/calendar.tsx`
  - Passed `weatherWidget` as a React element prop to both `GridView` and `CalendarView`
  - Grid view: Renders weather at bottom of existing ScrollView content
  - Calendar view: Converted root from `<View>` to `<ScrollView>` with weather at bottom, added `nestedScrollEnabled` for horizontal calendar scroll
  - Both modes scroll as one continuous page with weather at the end
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (weather position + scroll structure)
- **Verified via screenshots**:
  - Standard phone (390×844) Grid: weather below job list ✅
  - Standard phone (390×844) Calendar: weather below week columns ✅
  - Tablet (768×1024) Grid: weather at bottom, clean layout ✅


## Iteration 16 — Breadcrumb Navigation for All Roles
- **Commit**: 34da0757101dd28bf259898fde08875323e3f788
- **Date**: 2026-07-24
- **Changes**:
  - Created shared `Breadcrumbs` component (`src/components/nav/Breadcrumbs.tsx`) — tappable segments, chevron separators, ellipsis collapse on narrow screens with popover modal
  - Created `useBreadcrumbs` hook (`src/hooks/useBreadcrumbs.ts`) — auto-derives breadcrumbs from `usePathname()` + user role. Tech root = "Schedule", Admin root = "Dashboard", Customer root = "Home". Root screens return empty (no breadcrumbs). 150+ segment labels mapped.
  - Created `BreadcrumbBar` wrapper (`src/components/nav/BreadcrumbBar.tsx`) — for screens with custom headers
  - Integrated into shared `Header` (`src/components/widgets.tsx`) — covers 120+ screens automatically
  - Added `BreadcrumbBar` to key custom-header screens: time-clock.tsx, marketing/index.tsx, marketing/templates.tsx, settings/widgets.tsx, settings/tenant.tsx, settings/promo-codes.tsx
- **Files created**:
  - `/app/mobile/src/components/nav/Breadcrumbs.tsx`
  - `/app/mobile/src/components/nav/BreadcrumbBar.tsx`
  - `/app/mobile/src/hooks/useBreadcrumbs.ts`
- **Files modified**:
  - `/app/mobile/src/components/widgets.tsx` (Header — auto breadcrumbs)
  - `/app/mobile/app/time-clock.tsx` (BreadcrumbBar)
  - `/app/mobile/app/marketing/index.tsx` (BreadcrumbBar)
  - `/app/mobile/app/marketing/templates.tsx` (BreadcrumbBar)
  - `/app/mobile/app/settings/widgets.tsx` (BreadcrumbBar)
  - `/app/mobile/app/settings/tenant.tsx` (BreadcrumbBar)
  - `/app/mobile/app/settings/promo-codes.tsx` (BreadcrumbBar)
- **Verified via screenshots**:
  - Admin: Dashboard (root, no BC) ✅, Dispatch Board (L3) ✅, Comms (L2) ✅, Marketing (L2) ✅, Templates (L3) ✅, Settings > Widgets (L3) ✅, Tenant (L3) ✅, Team (L2) ✅
  - Tech: Schedule (root, no BC) ✅, Time Clock (L2) ✅, Handbook (L2) ✅
  - Customer: Portal Home (root, no BC) ✅, Invoices (L2) ✅, Messages (L2) ✅
  - Sizes: iPhone SE (375x667) ✅, iPhone 13 (390x844) ✅, iPad (768x1024) ✅




## Iteration 17 — HIGH-Priority Parity Gap Build (STEP 2)
- **Commit**: cef1e0420c3dc55cbb2d207307bb6717b93a8273
- **Date**: 2026-07-24
- **Changes**:
  - **Customer Service Reports List** (`portal/service-reports.tsx`): Full list screen with kind chips (Pool/Landscape/Service), date formatting, tech name, loading skeleton, empty state, pull-to-refresh, navigation to detail. API: `GET /api/customers/me/service-reports`.
  - **Customer Service Report Detail** (`portal/service-report/[id].tsx`): Rich detail screen with header card (kind icon, chips, status), algae observation banner, water chemistry readings with qualitative band chips (Below/Average/Above Avg/Elevated), chemicals added list, service checklist with check/uncheck indicators, customer notes section, visit photos grid, all with pull-to-refresh. API: `GET /api/customers/me/service-reports/{id}`.
  - **Customer Service Detail** (`portal/service/[id].tsx`): Customer-facing job detail with status pill, title, date, tech, address, service checklist (done/undone with icons), water reading chips, photos grid, notes section, pull-to-refresh. API: `GET /api/jobs/{id}`.
  - **Admin Broadcasts** (`marketing/broadcasts.tsx`): Full broadcasts page with batch list (expandable rows showing recipients), stat pills (sent/failed/suppressed/no-contact), relative time display, compose bottom sheet with channel selection (Email/SMS toggles), subject/body inputs, live preview with estimated recipient counts & cost, send confirmation modal, role gate (admin/super_admin only), loading skeletons, empty state, pull-to-refresh. API: `GET /api/mass-messaging/batches`, `GET /api/mass-messaging/batches/{id}`, `POST /api/mass-messaging/preview`, `POST /api/mass-messaging/send`.
  - **Navigation wiring**: Added "Service Reports" card to customer portal home grid. Updated portal/services.tsx to navigate to customer-scoped `/portal/service/{id}` (was navigating to full admin `/job/{id}`). Added "Broadcasts" link to admin More screen.
- **Files created**:
  - `mobile/app/portal/service-reports.tsx`
  - `mobile/app/portal/service-report/[id].tsx`
  - `mobile/app/portal/service/[id].tsx`
  - `mobile/app/marketing/broadcasts.tsx`
- **Files modified**:
  - `mobile/app/portal/home.tsx` (added Service Reports to SECTIONS)
  - `mobile/app/portal/services.tsx` (rewrote to use inline card instead of JobCard, navigate to portal-scoped detail)
  - `mobile/app/(app)/more.tsx` (added Broadcasts admin link)
- **Web files referenced**:
  - `frontend/src/pages/portal/PortalServiceReports.jsx` (service reports list+detail)
  - `frontend/src/pages/portal/PortalPages.jsx` (PortalServiceDetail, PortalServices)
  - `frontend/src/pages/marketing/BroadcastsPage.jsx` (broadcasts list)
  - `frontend/src/components/mass-messaging/MassMessagingComposeDialog.jsx` (compose flow)
  - `frontend/src/components/mass-messaging/MassMessagingCard.jsx` (compose CTA)
- **Endpoints used**: `/api/customers/me/service-reports`, `/api/customers/me/service-reports/{id}`, `/api/jobs/{id}`, `/api/mass-messaging/batches`, `/api/mass-messaging/batches/{id}`, `/api/mass-messaging/preview`, `/api/mass-messaging/send`
- **Lint**: All 7 files clean ✅
- **Build**: Metro bundled 1897 modules successfully ✅
- **Note**: Mobile tunnel CDN serving cached "Preview Unavailable" page — platform-level issue, not code. Local service responds 200 on port 3001.


## Iteration 18 — MEDIUM-Priority Parity Gap Documentation & Cleanup
- **Commit**: 7d4e358 (docs), b9415c5 (code), 63025b2 (portal nav)
- **Date**: 2026-07-24
- **Changes**:
  - **Documentation only** — all code was already auto-committed in prior session
  - Updated `MOBILE_PARITY_GAP.md`: marked 9 MEDIUM-priority items as completed
    - Portal Invoice detail nav wiring ✅
    - Portal Estimate detail nav wiring ✅
    - Settings: Business Card, AI Brain, Local SEO, Website SEO, Vanity Slugs ✅
    - Customer Chemistry (tech route + admin route) ✅
  - Updated summary counts: MEDIUM reduced from ~25 to ~16
  - Added `.pytest_cache/`, `.ruff_cache/`, `backend.template.bak/` to `.gitignore`
  - Cleaned git staging area of cache file noise
- **Files modified**:
  - `memory/MOBILE_PARITY_GAP.md` (9 line items updated + summary section)
  - `memory/mobile/commit_log.md` (appended this entry)
  - `memory/mobile/iteration_18.md` (created)
  - `.gitignore` (cache directories added)

## Iteration 21 — Full Parity Audit + Patch (8 Web Changes)
- **Commit**: 8c6677d
- **Date**: 2026-07-26
- **Changes**:
  - Item 2: Team page — bottom sheet action menu (Reset Password + Delete + Undelete), permission matrix
  - Item 3: Supercool integration settings page (new screen)
  - Item 4: Content Studio MVP (new screen — prompt + aspect + generate + library)
  - Item 6: GBP "Generate branded image" per-draft button + sheet
  - Item 7: Login demo gating on `show_demo_logins` from `/api/config/public`
  - Item 8: 401 handler in api.ts + AuthProvider logout callback
  - Item 1: Confirmed WeekStrip already at parity ✅
  - Item 5: Deferred — RepairCalculatorPage has no mobile equivalent
- **Files created**: settings/integrations/_layout.tsx, settings/integrations/supercool.tsx, marketing/content-studio.tsx
- **Files modified**: team.tsx (overwrite), login.tsx, gbp/index.tsx, src/api.ts, src/auth.tsx


## Iteration 20 — WeekStrip Daily Job Count Badges
- **Commit**: e03929b
- **Date**: 2026-07-26
- **Changes**:
  - WeekStrip: added `counts` prop (Record<string, number>), renders small text badge below each day when count > 0
  - calendar.tsx: added `weekCounts` useMemo computing per-date job counts from the fetched `jobs` array (normalized `scheduled_date` to first 10 chars for mixed-format dates)
  - Badge styling: muted gray default, brand color when selected
- **Files modified**:
  - `mobile/src/components/schedule/WeekStrip.tsx` (counts prop + badge rendering + styles)
  - `mobile/app/(app)/schedule/calendar.tsx` (weekCounts useMemo + counts prop pass-through)
- **Web files referenced**:
  - `frontend/src/components/schedule/WeekStrip.jsx` (behavior reference)



## Iteration 19 — WeekStrip + Colored Left-Border (Schedule Page Parity)
- **Commit**: a95c658
- **Date**: 2026-07-26
- **Changes**:
  - **WeekStrip component** (`src/components/schedule/WeekStrip.tsx`): 7-day Mon–Sun strip with left/right chevron week navigation, selected-day filled circle, today-dot marker, auto-selects today on mount. Port of `frontend/src/components/schedule/WeekStrip.jsx`.
  - **getStatusBorderColor helper** (`src/utils/scheduleStatus.ts`): `completed` → red `#DC2626`, everything else → blue `#2563EB`. Port of `frontend/src/pages/schedule/CalendarSchedule.jsx` export.
  - **Schedule screen integration** (`app/(app)/schedule/calendar.tsx`): WeekStrip placed between LandscapingClockWidget and mode switch. `onSelectDate` drives existing `focus` state. JobRow cards get 4px left border colored by status.
- **Files created**:
  - `mobile/src/components/schedule/WeekStrip.tsx`
  - `mobile/src/utils/scheduleStatus.ts`
- **Files modified**:
  - `mobile/app/(app)/schedule/calendar.tsx` (imports + WeekStrip insertion + border style on JobRow)
- **Web files referenced**:
  - `frontend/src/components/schedule/WeekStrip.jsx`
  - `frontend/src/pages/schedule/CalendarSchedule.jsx` (getStatusBorderColor)
- **Verified via screenshots**:
  - WeekStrip renders with 7 days, chevrons, selected circle ✅
  - Today dot visible when navigating other weeks ✅
  - Blue left-border on Open/Scheduled jobs ✅
  - Red left-border on Closed/Completed jobs ✅
  - WeekStrip syncs with grid day-nav buttons ✅

- **Web files referenced**: None


## Iteration 26 — Phase F1-mobile: File Upload/Display Components
- **Commit**: a7f575ea940e2652f50c437914f8060502a51bee
- **Date**: 2026-07-28
- **Changes**:
  - **API client** (`src/api/files.ts`): uploadFile (XHR+FormData with progress), deleteFile (POST), listFilesByEntity (GET with query params), buildAuthedDownloadUrl (?auth= query), downloadToLocalCache (expo-file-system/legacy), humanBytes, mimeAllowed validators. MAX_UPLOAD_SIZE_BYTES = 25MB.
  - **AuthedImage** (`src/components/files/AuthedImage.tsx`): Renders file from API using expo-image with ?auth={token} query. Loading/error/fallback states.
  - **FileUpload** (`src/components/files/FileUpload.tsx`): Take Photo (expo-image-picker camera), Choose from Library (library), Choose File (expo-document-picker for PDF/video). Client-side size (25MB) + MIME validation. XHR upload with progress bar. Thumbnail preview (local URI pre-upload, AuthedImage post-upload). Remove button. Single + multi-file modes.
  - **FileList** (`src/components/files/FileList.tsx`): FlatList with AuthedImage thumbnails for images, Ionicons for PDF/video. Delete with Alert confirm. Pull-to-refresh. Loading/empty/error states.
  - **Demo screen** (`app/dev/file-upload.tsx`): Route /dev/file-upload, gated on EXPO_PUBLIC_ENV=preview. Renders FileUpload + FileList with dev entity.
  - **Barrel export** (`src/components/files/index.ts`): Re-exports all 3 components.
  - **Tests** (`__tests__/file-upload-components.test.tsx`): 22 tests — API helpers (5), FileUpload (7), AuthedImage (3), FileList (5), Demo screen env gate (2). All green.
  - Auth pattern consumed: `getAuthToken()` from `@/src/api` → `storage.secureGet(TOKEN_KEY)` (SecureStore on iOS, AsyncStorage on web).
  - Import convention: `expo-file-system/legacy` for cacheDirectory + downloadAsync (SDK 54 new API).
  - Compromised-secret guard: PASSING ✅
  - Total test suite: 36/36 passing (22 new + 14 existing)
- **Files created**:
  - `mobile/src/api/files.ts`
  - `mobile/src/components/files/AuthedImage.tsx`
  - `mobile/src/components/files/FileUpload.tsx`
  - `mobile/src/components/files/FileList.tsx`
  - `mobile/src/components/files/index.ts`
  - `mobile/app/dev/file-upload.tsx`
  - `mobile/__tests__/file-upload-components.test.tsx`
- **Web files referenced**: `frontend/src/api/files.js`, `frontend/src/components/files/FileUpload.jsx`, `frontend/src/components/files/AuthedImage.jsx`, `frontend/src/components/files/FileList.jsx`

## Iteration 27 — Wave M1: F2b + F2c.2
- **Commit**: 21d0ca66c96e92b0fac1e6cede626fd1bbe4f45a
- **Date**: 2026-07-28
- **Changes**:
  - **F2b InvoiceAttachments**: New component wrapping FileUpload+FileList with purpose=invoice_attachment, linked_entity_type=invoice. Role-gated: admin/super_admin/manager can upload+delete; customer/tech read-only. Wired into invoice/[id].tsx and estimate-view/[id].tsx after Notes section.
  - **F2c.2 JobBeforeAfterPhotos**: New component with dual "Before"/"After" sections, each with FileList filtered by purpose (job_before_photo / job_after_photo). Read-only mode hides if both empty (deferred render: hidden container fetches counts first). Wired into portal/service/[id].tsx below legacy Photos section.
  - **FileList purpose prop**: Added optional `purpose` prop that passes through to `listFilesByEntity` for purpose-filtered queries.
  - **Barrel export updated**: Added InvoiceAttachments, canUploadInvoiceAttachment, JobBeforeAfterPhotos.
  - Tests: 50/50 passing (14 new in 2 suites). Compromised-secret guard: PASSING.
- **Files created**:
  - mobile/src/components/files/InvoiceAttachments.tsx
  - mobile/src/components/files/JobBeforeAfterPhotos.tsx
  - mobile/__tests__/invoice-attachments.test.tsx
  - mobile/__tests__/job-before-after-photos.test.tsx
- **Files modified**:
  - mobile/src/components/files/FileList.tsx (added purpose prop)
  - mobile/src/components/files/index.ts (barrel)
  - mobile/app/invoice/[id].tsx (wired InvoiceAttachments)
  - mobile/app/estimate-view/[id].tsx (wired InvoiceAttachments)
  - mobile/app/portal/service/[id].tsx (wired JobBeforeAfterPhotos readOnly)

## Iteration 28 — Wave M2: F2a + F2c.1
- **Commit**: 121dc668ed1cf9a95eb6c279f0235751ed9e672a
- **Date**: 2026-07-28
- **Changes**:
  - **F2a Job Before/After Photos**: Wired JobBeforeAfterPhotos into job/[id].tsx below VideoMediaUploader. readOnly={isCustomer} for role-based access. Alongside legacy base64 photo system (untouched).
  - **F2c.1 Portal Booking Photos**: Refactored request-service.tsx: (1) capture message_id/id/request_id from POST response, (2) FileUpload card on confirmation (purpose=portal_booking_photo, linkedEntityType=booking_request, max 5), (3) replaced auto-navigate with Done button. Backend returns {message_id, message:{id}} — both captured.
  - Tests: 59/59 passing (9 new in 2 suites). Compromised-secret guard: PASSING.
- **Files created**:
  - mobile/__tests__/f2a-job-photos.test.tsx (4 tests)
  - mobile/__tests__/f2c1-booking-photos.test.tsx (5 tests)
- **Files modified**:
  - mobile/app/job/[id].tsx (added JobBeforeAfterPhotos import + section)
  - mobile/app/request-service.tsx (capture createdId, FileUpload on confirmation, Done button, styles)
- **Verified via screenshots**:
  - Job detail: Before/After Photos card with upload buttons + file list + delete ✅
  - Booking confirmation: "Add Photos" card with Take Photo / Choose from Library / Choose File ✅
- **Surprise**: Backend returns `message_id` not `id` for service requests. Fixed ID capture to accept both.

## Iteration 29 — Wave M3: F2d + F2e + F2f
- **Commit**: 7b8cb177ed06dfe860c073227ec113c0cb9095c0
- **Date**: 2026-07-28
- **Changes**:
  - **F2d Chat Attachments**: Rewrote chat.tsx with paperclip button (ActionSheetIOS/Alert menu for camera/library/document), `pending[]` queue for uploaded attachments, pending chips strip above composer with remove buttons, `attachment_ids` included in send payload, inline attachment links rendered under each message.
  - **F2e Persona Avatar Upload**: Rewrote ai-employees.tsx with camera icon overlay on each persona row, Modal bottom-sheet with FileUpload (purpose=persona_avatar), PATCH `/api/ai-employees/{eid}` with avatar_url on upload, "Reset to default" restores built-in avatar path, AuthedImage for existing custom avatars.
  - **F2f Staff Profile Photo**: Created new profile.tsx screen at /app/(app)/profile.tsx. Mirrors web MyProfilePage: fetches /api/auth/me, shows AuthedImage or InitialBadge fallback, FileUpload (purpose=staff_profile_photo), PATCH /api/users/me on upload, "Remove photo" button, Identity card (name/email/role). Profile card in more.tsx now tappable with chevron navigating to profile.
  - Tests: 77/77 passing (18 new in 3 suites). No regressions.
- **Files created**:
  - mobile/app/(app)/profile.tsx
  - mobile/__tests__/f2d-chat-attachments.test.tsx (5 tests)
  - mobile/__tests__/f2e-persona-avatar.test.tsx (6 tests)
  - mobile/__tests__/f2f-staff-profile.test.tsx (7 tests)
- **Files modified**:
  - mobile/app/(app)/chat.tsx (F2d: full rewrite with attachment flow)
  - mobile/app/ai-employees.tsx (F2e: added avatar upload modal)
  - mobile/app/(app)/more.tsx (F2f: profile card now tappable → profile screen)
- **Web files referenced**: frontend/src/pages/chat/TeamChatPage.jsx, frontend/src/components/personas/PersonaAvatarUploadModal.jsx, frontend/src/pages/account/MyProfilePage.jsx, frontend/src/pages/admin/AiPersonasScopePage.jsx

## Iteration 30 — Phase M3 Portal Chat Attachments (B2 parity)
- **Commit**: 7c5bcbe066e37008ae4e70e92e06f2ed20400d58
- **Date**: 2026-07-29
- **Changes**:
  - Rewrote `portal/chats/[id].tsx` with full attachment parity matching web PortalChatsPage.jsx:
    - Paperclip button (customer-only) → ActionSheetIOS/Alert menu → camera/library/document picker
    - Upload to `POST /api/files/upload` with purpose=portal_chat_attachment, linked_entity_type=customer, linked_entity_id=customer_id
    - `pending[]` state with removable chips strip above composer
    - `attachment_ids` sent with message in POST body
    - Inline image thumbnails (AuthedImage) + non-image file cards (name/size/download icon)
    - Tap attachment → download via expo-file-system + share via expo-sharing
    - Error handling: 403 → Alert, 413 → Alert, network → Alert, permission → link to Settings
    - Send disabled when uploading or (no text AND no pending)
  - Tests: 10 new in `__tests__/PortalChatAttachments.test.tsx`. 87/87 total passing, 0 regressions.
- **Files modified**:
  - mobile/app/portal/chats/[id].tsx (full rewrite with attachment support)
- **Files created**:
  - mobile/__tests__/PortalChatAttachments.test.tsx (10 tests)
- **Web files referenced**: frontend/src/pages/portal/PortalChatsPage.jsx, frontend/src/components/chat/ChatAttachmentTile.jsx

## Iteration 31 — Fix: Expo Web paperclip inert (Platform.OS === "web" branch)
- **Commit**: c34e9ad57007db9750d7545b916e318f77d77eb1
- **Date**: 2026-07-29
- **Changes**:
  - Added `Platform.OS === "web"` branch to `pickAttachment()` in both:
    - `app/portal/chats/[id].tsx` (portal chat)
    - `app/(app)/chat.tsx` (team chat)
  - On web: hidden `<input type="file" multiple accept="image/*,video/*,application/pdf">` rendered in composer area
  - Paperclip tap → `webFileInputRef.current.click()` → browser native file picker
  - New `uploadWebFile(file: File)` handler creates FormData with native File object (not RN {uri,name,type} convention)
  - `handleWebFileChange` processes selected files and resets input for re-selection
  - Native iOS (ActionSheetIOS) and Android (Alert.alert) paths completely unchanged
  - 1 new test: "on Platform.OS=web, tapping paperclip does NOT call ActionSheetIOS or Alert.alert"
  - Tests: 88/88 passing, 0 regressions
- **Files modified**:
  - mobile/app/portal/chats/[id].tsx
  - mobile/app/(app)/chat.tsx
  - mobile/__tests__/PortalChatAttachments.test.tsx

## Iteration 32 — Phase PB1-M: Price Book Wholesale + Profit Report + Invoice Margin
- **Commit**: 852e8da64fc6fec644143e8d8e53c98c1011180f
- **Date**: 2026-07-29
- **Changes**:
  - **A. Price Book admin**: Updated `price-book.tsx` with wholesale_price and labor_cost_default columns (admin-only `W:` and `L:` badges under each item). Added edit sheet with wholesale + labor input fields. PATCH /api/items/{id} on save.
  - **B. Invoice detail internal margin**: Added amber "Internal margin — not shown to customer" section to `quote/[id].tsx` (which is where the invoice list navigates). Shows per-line W/u, L/u, Rev, COGS, Profit columns plus totals row with margin %. Gated to admin/super_admin/manager roles. Fixed isAdmin check to include super_admin + manager.
  - **C. Profit Report screen**: New `profit-report.tsx` admin-only screen. Range pills (This Month / Last Month / QTD / YTD / Custom), dimension toggle (Service/Income Category), 5 summary tiles, sortable breakdown table, Export CSV button. Forbidden screen for non-admin roles.
  - **D. Role gating**: All surfaces gated to admin + super_admin + manager. Customer + technician cannot see wholesale/labor/cogs/margin anywhere. Test verifies customer view has zero internal strings.
  - Added "Profit Report" link in more.tsx admin section.
  - Tests: 111/111 total (88 existing + 23 new). 0 regressions.
- **Files created**:
  - mobile/app/profit-report.tsx
  - mobile/__tests__/ProfitReport.test.tsx (9 tests)
  - mobile/__tests__/InvoiceInternalMargin.test.tsx (7 tests)
  - mobile/__tests__/PriceBookAdmin.test.tsx (7 tests)
- **Files modified**:
  - mobile/app/price-book.tsx (wholesale/labor columns + edit sheet)
  - mobile/app/quote/[id].tsx (internal margin section + isAdmin fix)
  - mobile/app/invoice/[id].tsx (internal margin section — standalone viewer)
  - mobile/app/(app)/more.tsx (Profit Report nav link)
- **Web files referenced**: ProfitReportPage.jsx, QuoteInvoiceDetail.jsx, PriceBookPage.jsx


## Iteration 33 — Phase G1: GPS Tracker Service + Time Clock Integration
- **Commit**: b637d516b86424e7fe341e49e20c6b76b60b8fb7
- **Date**: 2026-07-29
- **Changes**:
  - Fixed backend `gps_ingest.py` double-nested HTTPException detail (6/6 tests now pass)
  - Created `src/services/gpsTracker.ts`: foreground GPS tracking via expo-location, AsyncStorage buffering (max 60 pings), batch flush to POST /api/gps/pings, 409 auto-stop
  - Updated `time-clock.tsx`: auto-start tracking on clock-in, stop+flush on clock-out, best-effort resume on screen mount with open shift, green "Location tracking on" pill
  - No new dependencies or `app.json` changes needed (already had location permissions)
- **Files created**:
  - mobile/src/services/gpsTracker.ts
- **Files modified**:
  - mobile/app/time-clock.tsx (G1 GPS tracker hooks + green pill UI)
  - backend/routers/gps_ingest.py (HTTPException detail fix)
- **Web files referenced**: None (backend-only endpoints, no web frontend equivalent)

## Iteration 34 — Phase G1: Complete GPS Ping Ingest (re-issued, self-contained)
- **Commit**: 3807f9325dc594353ff749be8977c972a7194ee7
- **Date**: 2026-07-29
- **Changes**:
  - Rewrote `backend/routers/gps_ingest.py` with full spec: role gating, source enum, 24h freshness, lat/lon/accuracy ranges, dedup on (user_id, captured_at, source), 413 batch cap, 409 gates
  - Rewrote `backend/tests/test_gps_ingest.py` with 11 test cases (all green)
  - Rewrote `mobile/src/services/gpsTracker.ts`: foreground watch + background task, buffer flush at 20/2min/foreground, 409 auto-stop, 413 split-and-retry
  - Rewrote `mobile/app/time-clock.tsx`: G1 hooks + green pill + fixed font.semiBold→font.semibold TS errors
  - Created `mobile/__tests__/GpsTracker.test.ts` with 7 tests (all green)
  - Updated `mobile/app.json` permission strings for compliance
  - Backend smoke: 409 disabled, 200 single+dedup, 413/422/403 all verified
  - Jest: 118/118 (0 regressions). Pytest G1: 11/11. G0: 12/12.
- **Files created**:
  - mobile/__tests__/GpsTracker.test.ts
- **Files modified**:
  - backend/routers/gps_ingest.py (full rewrite)
  - backend/tests/test_gps_ingest.py (full rewrite)
  - mobile/src/services/gpsTracker.ts (full rewrite)
  - mobile/app/time-clock.tsx (G1 hooks + green pill + TS fix)
  - mobile/app.json (permission strings)
- **Web files referenced**: None (backend-only endpoints)

