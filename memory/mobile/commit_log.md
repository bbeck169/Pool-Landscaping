## Iteration FLEET-B — FLEET-B GPS Emission + Manual Check-ins

- **Commit**: cedc6d5f87fc001273e34878170b23a9f2915618
- **Date**: 2026-09-28
- **Changes**:
  - Created `/app/mobile/src/services/fleet/locationEmitter.ts` — Core foreground-only GPS emitter
  - Created `/app/mobile/src/components/fleet/FleetStatusChip.tsx` — Header chip (Green/Yellow/Red + modal)
  - Created `/app/mobile/src/components/fleet/CheckInButtons.tsx` — "On My Way" / "Arrived" for job detail
  - Created `/app/mobile/src/components/fleet/FleetPauseToggle.tsx` — Settings toggle "Pause tracking"
  - Created `/app/mobile/src/hooks/useFleetEmitter.ts` — Root-level hook to init emitter for techs
  - Created `/app/mobile/QA_FLEET_B.md` — Manual QA test checklist
  - Modified `app/_layout.tsx` — Added `useFleetEmitter()` hook
  - Modified `app/(app)/_layout.tsx` — Added FleetStatusChip to header area
  - Modified `app/(app)/more.tsx` — Added FleetPauseToggle in "Fleet Tracking" section
  - Modified `app/job/[id].tsx` — Added CheckInButtons for fleet check-in
  - Modified `app/job/[id]/checklist.tsx` — Added CheckInButtons for fleet check-in (primary route)
  - Installed `expo-battery` dependency
- **Files modified**:
  - mobile/src/services/fleet/locationEmitter.ts (NEW)
  - mobile/src/components/fleet/FleetStatusChip.tsx (NEW)
  - mobile/src/components/fleet/CheckInButtons.tsx (NEW)
  - mobile/src/components/fleet/FleetPauseToggle.tsx (NEW)
  - mobile/src/hooks/useFleetEmitter.ts (NEW)
  - mobile/QA_FLEET_B.md (NEW)
  - mobile/app/_layout.tsx (MODIFIED)
  - mobile/app/(app)/_layout.tsx (MODIFIED)
  - mobile/app/(app)/more.tsx (MODIFIED)
  - mobile/app/job/[id].tsx (MODIFIED)
  - mobile/app/job/[id]/checklist.tsx (MODIFIED)
  - mobile/package.json (expo-battery added)
- **Web files referenced**:
  - frontend/src/pages/admin/FleetMembership.jsx
  - frontend/src/pages/admin/DispatchBoard.jsx
  - backend/routers/fleet.py (API contract reference)
- **Dependencies installed**: expo-battery
- **Known issues**: None — all lint checks pass, app compiles and renders correctly

## Iteration 97 — Phase 2 Quote-to-Lead Recipient Mobile Parity
- **Commit**: 9078b9cd61d161afe3a6cbc3bc5a07696f5aabb0
- **Date**: 2026-10-03
- **Changes**:
  - Created `QuoteRecipientPicker.tsx` — unified Customer/Lead picker hitting `GET /api/quote-recipients/search`
  - Exported `RecipientTypeBadge` component for reuse on detail screen
  - Replaced legacy customer-only picker in `quote/new.tsx` with `QuoteRecipientPicker`
  - Updated POST `/quotes` payload to send `{recipient_type, recipient_id, customer_id?}` based on recipient type
  - Added `quote-recipient-type-badge` (Customer/Lead pill) on quote detail screen
  - Added `invoice-lead-recipient-notice` for lead-recipient invoices with exact copy
  - Supports URL param pre-fill (`?recipient_type=&recipient_id=` and legacy `?customer_id=`)
  - ConvertToInvoiceButton regression check — still renders for lead-recipient quotes
- **Files modified**:
  - mobile/src/components/quotes/QuoteRecipientPicker.tsx (NEW)
  - mobile/app/quote/new.tsx (MODIFIED)
  - mobile/app/quote/[id].tsx (MODIFIED)
  - mobile/__tests__/QuoteRecipientPicker.test.tsx (NEW)
  - mobile/__tests__/QuoteInvoiceLeadBadge.test.tsx (NEW)
- **Web files referenced**:
  - frontend/src/components/quotes/QuoteRecipientPicker.jsx
  - frontend/src/pages/quotes/QuoteInvoiceNew.jsx
  - frontend/src/pages/quotes/QuoteInvoiceDetail.jsx
- **Dependencies installed**: None
- **Known issues**: None — all 16 new tests pass, app compiles, lint clean

## Iteration 98 — Phase 3 Quote Lifecycle Parity (Decline/Reopen + View Filter)
- **Commit**: 00f21b6c00c74eb58db5f98491d976f4e70116d5
- **Date**: 2026-10-03
- **Changes**:
  - Created `quoteLifecycle.ts` — utility helpers: `canUserDeclineOrReopenQuote`, `shouldShowDeclineButton`, `shouldShowReopenButton`, `shouldHideConvertWhenDeclined`
  - Modified `quotes.tsx` (list screen):
    - Admin sees 4-option lifecycle view filter (Open/Converted/Declined/All) with testID `quotes-list-filter`
    - Default fetch uses `?view=open`
    - Row-level Decline button (`quote-row-decline-{id}`) on open rows with role gate
    - Row-level Reopen button (`quote-row-reopen-{id}`) on declined rows with role gate
    - Alert.alert confirm dialog before POST
    - 400-code-aware toasts (already_declined, already_converted, not_declined)
    - Non-admin still sees legacy doc_type filter (all/quote/invoice)
  - Modified `quote/[id].tsx` (detail screen):
    - Added Decline button (`qd-decline-quote`) in actions area — role-gated, visible on open quotes
    - Added Reopen button (`qd-reopen-quote`) — role-gated, visible on declined quotes
    - ConvertToInvoice now HIDDEN when `status==="declined"` (Phase 3 regression guard)
    - Alert.alert confirm dialog + 400-aware toasts for both actions
    - All existing testIDs preserved (qd-convert-to-invoice, qd-view-converted-invoice, quote-recipient-type-badge, invoice-lead-recipient-notice)
  - Created `QuoteDeclineReopen.test.tsx` — 28 tests covering utilities, list filter/rows, detail visibility, regression guards
- **Files modified**:
  - mobile/src/utils/quoteLifecycle.ts (NEW)
  - mobile/app/(app)/quotes.tsx (MODIFIED)
  - mobile/app/quote/[id].tsx (MODIFIED)
  - mobile/__tests__/QuoteDeclineReopen.test.tsx (NEW)
- **Web files referenced**:
<<<<<<< Updated upstream
  - frontend/src/pages/quotes/QuotesList.jsx
  - frontend/src/pages/quotes/QuoteInvoiceDetail.jsx
- **Dependencies installed**: None
- **Known issues**: None — 28 new tests + 25 Phase 1/2 regression tests all green, lint clean
- **Toggle fix**: N/A for mobile — detail screen has no editable line-items toggle (view-only)

## Iteration 112 — Phase 8M: Hey Marco wake-word arm-on-click (mobile parity)
- **Commit**: 52fc01fe0240d54d8c4e3906b9b354ec283383cc
- **Date**: 2026-10-09
- **Changes**:
  - `useMarcoWakeWord` rewritten: no auto-start; returns `{supported, permitted, listening, isArmed, arm, disarm, toggle}`; `onPhraseDetected` opt; unmount releases mic
  - `wakeWordService`: added `isWakeWordSupported()`; `startWakeWord(cb, {requirePrefs})` (default true = legacy behavior)
  - NEW `MarcoMicController.tsx` (MarcoMicProvider: role gate admin/super_admin/manager/owner, 10-min idle auto-disarm, AppState background/inactive disarm, silent disarm on role loss, toasts) + `MicToggleButton.tsx` (pulse ring when armed) + `marcoMicContext.ts`
  - Mounted provider in `app/_layout.tsx` (inside ToastProvider); button in shared `Header` right cluster (widgets.tsx)
  - No audio feedback anywhere in arm/disarm/detect
- **Files modified**: mobile/src/hooks/useMarcoWakeWord.ts, mobile/src/services/marco/wakeWordService.ts, mobile/src/components/marco/{MarcoMicController,MicToggleButton}.tsx, mobile/src/components/marco/marcoMicContext.ts, mobile/app/_layout.tsx, mobile/src/components/widgets.tsx, mobile/__tests__/marco-wake-word-arm.test.tsx (NEW, 15 tests), mobile/__tests__/marco-mobile-chat.test.tsx
- **Web files referenced**: frontend/src/components/marco/MarcoMicController.jsx, frontend/src/hooks/useWebWakeWord.js
- **Dependencies installed**: None

## Iteration 113 — Phase 9-M: Crews audit + Customers tiles + list/profile perf
- **Commit**: 10e050e480814a0db6f18fee87f618a7d7423969
- **Date**: 2026-10-09
- **Changes**:
  - Crews: mobile `app/crews.tsx` is a ComingSoonPage re-export; no crew writes anywhere in mobile → stale-closure fix is a NO-OP (source-grep regression lock added)
  - PortalOnboardingHealthTile → 3 cards (Activated / Signed in / Cards on file), Invited + Chase + Never-logged-in cards removed; toggle via `activeKey`/`onToggle`; helpers `tileKeyFromParams` / `tileParamsFor`
  - Customers list: tile state in route params (`router.setParams`, `useLocalSearchParams`) → portal_activated=1 / first_access=any / has_payment_method=true(+is_active=true); `portalInvitedFilter` removed; `slim=1`; page_size 100 → 50 (existing onEndReached infinite scroll)
  - Customer profile: `?slim=1` + parallel `/customers/{id}/summary`; Job History → `CustomerJobsSection` (collapsible, summary badge, lazy `/jobs?customer_id=&limit=50&offset=0&sort=scheduled_date_desc`, Load more, 5-min TTL via new `useCustomerTabCache`)
- **Files modified**: see `git log -1 --name-only 10e050e48` (11 files)
- **Web files referenced**: frontend/src/pages/ops/OpsHub.jsx, frontend/src/components/customers/PortalOnboardingHealthTile.jsx, frontend/src/pages/customers/CustomersList.jsx, frontend/src/pages/customers/CustomerDetail.jsx, frontend/src/hooks/useCustomerTabCache.js
- **Dependencies installed**: None
- **Tests**: full suite 43 failed suites / 51 failed tests = identical to baseline (set-diff empty)

## Iteration 114 — Phase 19: final mobile parity batch (4 deferred follow-ups)
- **Commits**:
  - F1 `3471057b4bd8d614c223a1c1127f0b7b53df73a0` — technician pay-rates edit sheet (team.tsx kebab + TechnicianPayRatesModal.tsx + phase19-pay-rates test)
  - F2 `b892afe1099a1b237d5f8b95446f74b38648a6c7` — phase35-customers-pagination repair (inputColors mock, router params, page_size 50)
  - F3 `a61203503d846b054d715b0a40dbd57671232c6a` — TemplateOrderedSections + ServiceReport wrap + phase19-template-reorder test
  - F4 `f89aad77cf95c0678bb64993c07b4500a8583e18` — portal readability regression lock (shell NOT needed on mobile)
- **Date**: 2026-10-09
- **Web files referenced**: frontend/src/components/team/TechnicianPayRatesModal.jsx, frontend/src/pages/ops/OpsHub.jsx, frontend/src/components/form-renderer/TemplateFieldContext.jsx, frontend/src/pages/tech/ServiceReport.jsx, frontend/src/components/portal/PortalPageShell.jsx
- **Dependencies installed**: None
- **Tests**: full suite 42 failed suites / 48 failed tests vs true baseline 43/51 — zero new failures; phase35 fixed.
=======
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


## Iteration 36 — Phase P11a: App Store config + privacy manifest cluster
- **Commit**: a47777754349672cc85da45210845aa77b0c7dca
- **Date**: 2026-08-21
- **Changes**:
  - Item 1: Regenerated icon.png from 512x512 RGBA to 1024x1024 RGB (no alpha) via image generation
  - Item 2: Added expo.ios.privacyManifests block with 4 Required Reason API declarations
  - Item 5: Added expo.ios.config.usesNonExemptEncryption = false
  - Item 6: Added expo.ios.buildNumber = "1"
  - Item 7: Added NSSpeechRecognitionUsageDescription to infoPlist
  - JSON validity confirmed; 497 tests pass (same as before, 9 pre-existing failures unchanged)
- **Files modified**:
  - mobile/app.json (config + privacy manifest + buildNumber + encryption + speech perm)
  - mobile/assets/images/icon.png (regenerated)
- **Items NOT touched**: 3 (account deletion), 4 (privacy policy), 8, 9, 10



## Iteration 30 — Phase P11c: App Store Handoff Docs (Items 8, 9, 10)
- **Commit**: f4bf293d225e08022b4b8f28302f0f1ef05cdbb2
- **Date**: 2026-08-21
- **Changes**:
  - **Item 8 (Data Collection)**: Created comprehensive App Store Connect privacy questionnaire mapping — 22 Apple data sub-types audited against backend DB collections (`gps_pings`, `users`, `customers`, `leads`, `jobs`, `files`, `invoices`, `stripe_charges`) and mobile SDKs (`expo-location`, `expo-image-picker`, `react-native-webrtc`). Includes copy-paste answers for App Store Connect and privacy nutrition label summary.
  - **Item 9 (Mapbox Token)**: Documented public (`pk.`) vs secret (`sk.`) token wiring, EAS Secrets setup, and security checklist. Added `__DEV__`-gated startup guard in `_layout.tsx` that warns if EXPO_PUBLIC_MAPBOX_TOKEN is a placeholder. Updated `.env.example` with annotated Mapbox entries.
  - **Item 10 (Screenshots)**: Documented all required App Store screenshot sizes (6.7", 6.5", 5.5", iPad 12.9", iPad 13"), recommended 5 optimal screens with marketing captions, and outlined 4 capture methods (Xcode Simulator, physical device, react-native-view-shot, Fastlane).
  - Lint: `_layout.tsx` clean ✅
  - Pre-existing: Mapbox web CSS bundling error (`mapbox-gl/dist/mapbox-gl.css`) — not introduced by this change.
- **Files created**:
  - `/app/memory/appstore_submission_handoff.md`
- **Files modified**:
  - `/app/mobile/app/_layout.tsx` (added Mapbox `__DEV__` guard useEffect, +15 lines)
  - `/app/mobile/.env.example` (rewritten with full annotated Mapbox entries)
- **Web files referenced**: None (backend `server.py` scanned for DB collections only)


## Iteration 31 — Phase P13: Fix Mapbox env var deprecation in app.json
- **Commit**: f4bf293d225e08022b4b8f28302f0f1ef05cdbb2 (uncommitted changes on top)
- **Date**: 2026-08-21
- **Changes**:
  - Removed deprecated `RNMapboxMapsDownloadToken` property from `@rnmapbox/maps` plugin config in `app.json`. Plugin now reads `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` directly from env at build time (empty `{}` options object).
  - Updated `.env.example` Mapbox secret token comment block to explain that the plugin auto-reads the env var and that EAS secret provisioning is required for cloud builds.
  - JSON validity confirmed. Zero occurrences of deprecated PascalCase key remain.
  - No changes to `backend/` or `frontend/`.
- **Files modified**:
  - `/app/mobile/app.json` (line 148-152: plugin options `{ "RNMapboxMapsDownloadToken": "..." }` → `{}`)
  - `/app/mobile/.env.example` (expanded Mapbox secret token comment)
- **NOTE (CORRECTED 2026-08-28, support ticket #238711)**: This change WAS the fix. Emptying the plugin options to `{}` is exactly what let iOS and Android build green from Aug 22 to Aug 27. The `eas secret:create` instruction is NOT actionable here: the Expo project is an Emergent-managed **partner account**, so there is no EAS CLI access to create a project secret. The token is read from `mobile/.env` at build time. Do NOT re-add the plugin prop.


## Iteration 32 — Phase P14: Split DailyRouteMap into platform-specific files
- **Commit**: f4bf293d225e08022b4b8f28302f0f1ef05cdbb2 (uncommitted changes on top)
- **Date**: 2026-08-21
- **Changes**:
  - Renamed `DailyRouteMap.tsx` → `DailyRouteMap.native.tsx` (unchanged Mapbox implementation)
  - Created `DailyRouteMap.web.tsx` — web fallback with zero @rnmapbox/maps imports; renders a dashed placeholder card matching the ScheduleMap.web.tsx pattern
  - Created `DailyRouteMap.tsx` — barrel re-export selector (pattern b, matching ScheduleMap.tsx precedent)
  - Created `__tests__/daily-route-map-web.test.tsx` — 4 tests proving web variant never triggers @rnmapbox/maps import
  - Web bundle verification: Mapbox CSS error (`mapbox-gl/dist/mapbox-gl.css`) is GONE. Next web error is unrelated expo-sqlite WASM issue.
  - Consumer imports unchanged: `calendar.tsx`, `schedule-daily-route-map.test.tsx`, `optimize-route-flow.test.tsx`
  - No Platform.OS guards removed (none existed as workarounds)
  - Jest: 70 suites (67 pass / 3 pre-existing fail), 512 tests (503 pass / 9 pre-existing fail)
  - No changes to `backend/` or `frontend/`
- **Files created**: `DailyRouteMap.web.tsx`, `DailyRouteMap.tsx` (selector), `__tests__/daily-route-map-web.test.tsx`
- **Files renamed**: `DailyRouteMap.tsx` → `DailyRouteMap.native.tsx`
- **Files deleted**: none (original renamed)


## Iteration 33 — Phase P15: Fix expo-sqlite WASM web bundle error
- **Commit**: f4bf293d225e08022b4b8f28302f0f1ef05cdbb2 (uncommitted changes on top)
- **Date**: 2026-08-21
- **Changes**:
  - **Case A** applied: single wrapper module `src/lib/offline/cache.ts` was the only direct importer of expo-sqlite.
  - Renamed `cache.ts` → `cache.native.ts` (SQLite implementation, unchanged)
  - Created `cache.web.ts` — in-memory Map-backed shim with same public API (12 exports)
  - Created `cache.ts` — barrel re-export selector (matching ScheduleMap/DailyRouteMap pattern)
  - Created `__tests__/offline-cache-web.test.tsx` — 6 tests proving web shim works without expo-sqlite
  - **Web bundle: BUILDS SUCCESSFULLY** — `Bundled 11615ms (2190 modules)` — zero errors
  - Consumer imports unchanged: auth.tsx, login.tsx, apiCache.ts, calendar.tsx, checklist.tsx, job/[id].tsx
  - No Platform.OS guards removed (none existed)
  - Jest: 71 suites (68 pass / 3 pre-existing fail), 518 tests (509 pass / 9 pre-existing fail)
  - No changes to `backend/` or `frontend/`. No new deps installed.
- **Files created**: `cache.web.ts`, `cache.ts` (selector), `__tests__/offline-cache-web.test.tsx`
- **Files renamed**: `cache.ts` → `cache.native.ts`


## Iteration 34 — Phase P16: Mapbox config hardening + Expo OTA updates + MapErrorBoundary
- **Commit**: f4bf293d (uncommitted changes on top)
- **Date**: 2026-08-27
- **Changes**:
  - **Task 1a**: ~~Restored `RNMapboxMapsDownloadToken: "$RNMAPBOX_MAPS_DOWNLOAD_TOKEN"` in `@rnmapbox/maps` plugin config in `app.json`.~~ **REVERTED 2026-08-28 (support ticket #238711) - this broke EVERY iOS and Android build.** The claim that "EAS resolves this at build time from the project's secret env var" is FALSE: `app.json` is static JSON and nothing expands `$VAR` in it. The literal string was handed to Mapbox as the download password and rejected with HTTP 401 (iOS `Install pods`, Android `Run gradlew`). Plugin options are back to `{}`; the token is read from the `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` environment variable. Do NOT re-add this prop.
  - **Task 1b**: Created `src/components/MapErrorBoundary.tsx` — class component with `getDerivedStateFromError` + `componentDidCatch`. Fallback: amber card with "Route map unavailable — {error.message}" and Retry button. Wraps `<DailyRouteMap>` in `calendar.tsx`.
  - **Task 2**: Enabled Expo OTA updates: `enabled: true`, `checkAutomatically: "ON_LOAD"`, `fallbackToCacheTimeout: 0`, URL `https://u.expo.dev/bdd4bc95-5d7c-46d8-8243-0b6ed1e9aa19` (project ID from `expo.extra.eas.projectId`). `runtimeVersion` with `policy: "appVersion"` was already present.
  - JSON validity: ✅. Lint: MapErrorBoundary clean ✅, calendar.tsx pre-existing hook warnings only.
  - iOS bundle: Bundled successfully (1953 modules). Mobile service RUNNING, 200 OK.
  - No changes to `backend/` or `frontend/`. No new deps. No external repos cloned.
- **Files created**: `src/components/MapErrorBoundary.tsx`
- **Files modified**: `app.json` (Mapbox plugin + updates config), `calendar.tsx` (+import, +ErrorBoundary wrap)


## Iteration 35 — Phase P17: Android OOM fix on Schedule Grid view
- **Commit**: f4bf293d (uncommitted changes on top)
- **Date**: 2026-08-27
- **Root causes**: (1) 74-day fetch window with no range cache, (2) non-virtualized .map() rendering, (3) no fetchedRangeRef — every focus change re-fetched
- **Changes**:
  - **Fix 1**: Narrowed fetch window from `-14/+60` days (74d) to `-7/+14` days (21d). Added `fetchedRangeRef` with 3-day margin — day-tap navigation within cached range skips network entirely.
  - **Fix 2**: Replaced `jobs.map()` ScrollView render with `<FlatList>` — `initialNumToRender=10`, `maxToRenderPerBatch=10`, `windowSize=7`, `removeClippedSubviews=true` (Android). Only ~10 job cards rendered at a time vs all-at-once.
  - **Fix 3**: All bulk-action handlers now call `load(true)` to force-refetch after mutations.
  - Memory profile improvement: ~70% reduction in initial fetch payload (21d vs 74d), ~90% reduction in rendered components (10 vs all).
  - iOS bundle: Bundled successfully (1953 modules)
  - Jest: 81 suites (76 pass / 5 pre-existing fail), 568 tests (557 pass / 11 pre-existing fail)
  - No changes to `backend/` or `frontend/`. No new deps. No external repos.
- **Files modified**: `calendar.tsx` (fetchedRangeRef cache, FlatList virtualization, force-reload on mutations)


## Iteration 36 — Phase P18: Consolidate bulk-action buttons into dropdown menu
- **Commit**: f4bf293d (uncommitted changes on top)
- **Date**: 2026-08-27
- **Changes**:
  - Replaced 3-row, 6-button bulk-action pill cluster with a single "Actions" button + Modal dropdown
  - Dropdown lists all 6 actions vertically: Select all, Complete, Move, Delete, Assign, Rearrange
  - Each action shows colored dot accent + count + disabled state when 0 selected
  - Role gating preserved: admin-only actions hidden for techs (adminOnly flag), entire trigger gated behind canWrite
  - "Clear" button remains inline outside dropdown for quick access when items are selected
  - Dropdown closes on: action tap, backdrop press, Android back button (onRequestClose)
  - Added `actMenuStyles` StyleSheet for the dropdown card, rows, and backdrop
  - Updated `schedule-select-all.test.tsx` to validate new dropdown pattern (7 assertions)
  - OOM fix from P17 fully intact: fetchedRangeRef, FlatList virtualization, ±14d window
  - Jest: 82 suites (77 pass / 5 pre-existing fail), 576 tests (565 pass / 11 pre-existing fail)
  - No changes to `backend/` or `frontend/`. No new deps. No external repos.
- **Files modified**: `calendar.tsx` (replaced pill row with Actions dropdown), `schedule-select-all.test.tsx` (updated to match new pattern)


## Iteration 37 — Phase P19: Fix Quick Access broken routes (Unmatched Route bug)
- **Commit**: f4bf293d (uncommitted changes on top)
- **Date**: 2026-08-27
- **Root cause**: QUICK_ACCESS_ITEMS route strings didn't match actual Expo Router file paths:
  - `/(app)/invoices` → no file under `(app)/`; real file at top-level `app/invoices.tsx`
  - `/(app)/estimates` → no such file at all; estimator at `app/(app)/estimator/index.tsx` (different name)
  - `/(app)/customers` → was correct (file + tab exist)
- **Changes**:
  - Fixed `ToolsMenuBody.tsx` QUICK_ACCESS_ITEMS routes:
    - Invoices: `/(app)/invoices` → `/invoices`
    - Estimates: `/(app)/estimates` → `/(app)/estimator`
  - Registered `estimator/index`, `estimator/[id]`, `estimator/new` as hidden tabs in `(app)/_layout.tsx`
  - Jest: 82 suites (77 pass / 5 pre-existing), 576 tests (565 pass / 11 pre-existing). 0 regressions.
  - Web bundle: 2195 modules, compiled clean.
  - No changes to `backend/` or `frontend/`. No new deps. No external repos.
- **Files modified**: `ToolsMenuBody.tsx` (2 route fixes), `(app)/_layout.tsx` (3 hidden tab registrations)


## Iteration 38 — Phase v: Multi-body service reports + pricebook effective_cost + notification audit
- **Commit**: f4bf293d (uncommitted changes on top)
- **Date**: 2026-08-27
- **Changes**:
  - **Ship 1 (Multi-body service reports)**:
    - Created `src/lib/waterBodies.ts` — body types, reading allow-lists, required fields, validators, factory helpers (port of web `lib/waterBodies.js`)
    - Created `src/components/checklist/WaterBodyPanel.tsx` — per-body card with filtered chemistry inputs, chemicals editor, notes, remove button
    - Created `src/components/checklist/WaterBodyManager.tsx` — manages water_bodies[] array, add-body picker sheet, remove-with-confirm
    - Modified `app/job/[id]/checklist.tsx` — integrated WaterBodyManager into pool flow: auto-seeds water_bodies[0] from legacy report, includes water_bodies in PATCH body, handles 422 chemistry_core_readings_missing with per-body field highlighting
    - Modified `app/portal/service-report/[id].tsx` — multi-body display when water_bodies.length > 1 with type badges and per-body readings grid
  - **Ship 2 (Pricebook effective_cost)**:
    - Modified `app/price-book.tsx` — swapped wholesale_price display to effective_cost with "from N suppliers" line
  - **Ship 3 (Notification audit)**:
    - Audited 7 mobile notification triggers — ALL delegate to backend endpoints, none bypass guardrails. No flags raised.
  - **Tests**: Created `__tests__/water-bodies.test.tsx` — 18 tests covering constants, validators, WaterBodyManager, WaterBodyPanel. All pass.
  - Jest: 83 suites (78 pass / 5 pre-existing), 594 tests (583 pass / 11 pre-existing). 0 regressions.
  - No changes to `backend/` or `frontend/`. No new deps. No external repos.
- **Files created**: `src/lib/waterBodies.ts`, `src/components/checklist/WaterBodyPanel.tsx`, `src/components/checklist/WaterBodyManager.tsx`, `__tests__/water-bodies.test.tsx`
- **Files modified**: `app/job/[id]/checklist.tsx`, `app/portal/service-report/[id].tsx`, `app/price-book.tsx`


## Iteration — Ship 1, 2, 3: Mobile Parity (Dashboard tiles, Customer Delete UX, formatCustomerName)
- **Commit**: 47278d5f2d483726ccd02aa4ed05caa1c5c552ee
- **Date**: 2026-08-29
- **Changes**:
  - **Ship 3 (formatCustomerName)**: Created `/app/mobile/src/utils/formatCustomerName.ts`. Swept 25+ files replacing raw `customer_name` renders with `formatCustomerName(item)`. Orphan-safe on all surfaces.
  - **Ship 1 (Dashboard tiles)**: Replaced legacy Customers/Technicians tiles with Active/Inactive Customers using `active_customers_count` / `inactive_customers_count`. Technicians tile removed.
  - **Ship 2 (Customer Delete UX)**: Created `CustomerDeleteModal.tsx` (3-button modal) + `RestoreCustomerButton.tsx`. Wired into `customer/[id].tsx` with 409 handling. Added `include_deleted` chip + `canManageDeleted` gate + soft-deleted row styling to `customers.tsx`.
  - **Jest tests**: 5 new suites, 32 tests — all pass.
- **Files created**: `src/utils/formatCustomerName.ts`, `src/components/customers/CustomerDeleteModal.tsx`, `src/components/customers/RestoreCustomerButton.tsx`, 5 test files
- **Files modified**: `app/(app)/index.tsx`, `app/customer/[id].tsx`, `app/(app)/customers.tsx`, + ~22 files for formatCustomerName sweep
- **Component code changes during test wiring**: ZERO


## Iteration — Phase O2: Test & Empirical Proof Pass
- **Commit**: b176f7cbd89e08bc2c05cf8f7bb3668a3459a343
- **Date**: 2026-08-29
- **Changes**:
  - **Jest test suite** (4 files, 27 tests — ALL GREEN):
    - `__tests__/client-uuid.test.ts` (3 tests) — RFC-4122 format, 1000-unique, no Math.random
    - `__tests__/sync-db.test.ts` (3 tests) — Fresh migration v0→v1, idempotent re-run, config round-trip
    - `__tests__/sync-queue.test.ts` (10 tests) — Enqueue, online dispatch, offline hold, reconnect flush, max-retry shelving, network error resilience, triggerSyncNow, retrySingle, status counts, clearDone
    - `__tests__/sync-status.test.ts` (11 tests) — Empty counts, online/offline flag, pending/failed counts, last_sync_at config, queue subscribe/unsubscribe, netBus event fire/unsub
  - **In-memory SQLite mock** fixes: INSERT handler now handles mixed `?` and literal VALUES; UPDATE handler handles mixed `?` and literal SET values + multiline SQL (`[\s\S]` regex fix)
  - **jest.config.js**: Added `uuid` to `transformIgnorePatterns` exception list (ESM compat)
  - **Empirical proof script** (`scripts/empirical-proof-o2.cjs`): EP-1 Boot, EP-2 Airplane toggle, EP-3 Force-quit — all pass
- **Files created**: `__tests__/sync-status.test.ts`, `scripts/empirical-proof-o2.cjs`
- **Files modified**: `__tests__/sync-queue.test.ts`, `__tests__/sync-db.test.ts` (mocks were already there; fixed INSERT/UPDATE handlers), `jest.config.js` (uuid transform)
- **Component code changes during test wiring**: ZERO (all fixes confined to test mocks)


## Iteration — Phase O5: Full Read Parity
- **Commit**: 20208daab917b282df60df222d2f9097421c0720
- **Date**: 2026-08-29
- **Changes**:
  - **readCache.ts** (92 lines): Generic SQLite `read_cache` table — writeCache, readCache, invalidateCache, invalidateCachePrefix, clearAllCache
  - **useOfflineQuery.ts** (111 lines): Shared hook — read cache → render → fetch online → write cache → re-render. No infinite loops. isStale/isOffline/error tracking.
  - **cacheInvalidation.ts** (98 lines): Maps 10 op_types to cache prefixes. `invalidateForEntry()` called from queue dispatch success path.
  - **OfflineGate.tsx** (63 lines): Category-D screen wrapper — shows "No connection" state.
  - **12 screens wired with cache read/write fallback** (Category B):
    - Dashboard, Customers list, Customer detail, Quotes list, Quote detail, Invoices list, Price Book, Notifications, Technicians, Team, Service Report detail, Dispatch Board
  - **3 screens wrapped with OfflineGate** (Category D):
    - AI Estimator, AEO Suite, AI Chat
  - **Queue dispatch** now calls `invalidateForEntry()` on success
  - **Jest: 1 suite, 12 tests — ALL GREEN** (readCache round-trip, invalidation, prefix delete, clearAll, cache invalidation mapping, offline/online contract)
  - **Empirical proof: 15/15 PASS** (10 category-B + 5 category-D)
- **Files created**: readCache.ts, useOfflineQuery.ts, cacheInvalidation.ts, OfflineGate.tsx, o5-offline-query.test.ts, empirical-proof-o5.cjs
- **Files modified**: 12 screen files + queue.ts
- **Total tests across O2+O3+O5**: 64 all green


## Iteration — Phase O3: Mobile Hardening — Service Log Offline + Photo Pipeline
- **Commit**: f0b12e73c4be59ba7726a8c7bc1577c4d13a0ed5
- **Date**: 2026-08-29
- **Changes**:
  - **Offline service-log plumbing** (`offlineServiceLog.ts`, 95 lines):
    - `cacheServiceReport()` / `getCachedServiceReport()` — SQLite round-trip
    - `markDirty()` / `clearDirty()` — local-edit flags
    - `submitOffline()` — enqueues `service_report.upsert` with full payload into sync_queue
    - Checklist screen submit now uses `submitOffline()` when offline → "Submitted (pending sync)"
  - **Photo pipeline** (`photoWorker.ts`, 324 lines):
    - `downscaleAndStage()` — expo-image-manipulator 2048px JPEG 0.85 → documentDirectory staging
    - `insertPendingPhoto()` / `capturePhoto()` — SQLite photos_pending table
    - `flushPhotos()` — upload worker with base64 encoding + `POST /jobs/{jid}/photos` + X-Idempotency-Key
    - 3-failure stalling, `retryStalled()` / `retryAllStalled()`
    - `purgePhotosForEntity()` — orphan cleanup when parent entity deleted
    - `cleanupUploaded()` — delete local files after server confirmation
    - `wirePhotoAutoUpload()` — auto-flush on network:online event
  - **job.arrive** (`jobArrive.ts`, 24 lines):
    - `enqueueJobArrive()` — queues `job.arrive` op through sync_queue
    - Job detail On My Way button now routes through sync queue (offline-safe)
  - **Conflict detection starter** (`conflicts.ts`, 144 lines):
    - `recordConflict()` — persists 409 responses in `sync_conflicts` SQLite table
    - `onConflict()` — event subscription for UI (O6 will render diff banner)
    - `getUnresolvedConflicts()` / `resolveConflict()` / `getConflictCount()`
    - Queue dispatch (`queue.ts`) now captures 409 → records conflict
  - **Barrel re-export** (`index.ts`) updated with all O3 modules
  - **App boot** (`_layout.tsx`) now calls `wirePhotoAutoUpload()`
  - **Package additions**: `expo-image-manipulator@57.0.14`, `expo-image-loader@57.0.1`
  - **Jest: 4 suites, 25 tests — ALL GREEN**
  - **Empirical proof: 5/5 PASS** (queue drain, 2 ops done, 3 photos uploaded, 0 pending, dirty cleared)
- **Files created**: offlineServiceLog.ts, photoWorker.ts, conflicts.ts, jobArrive.ts, 4 test files, empirical proof
- **Files modified**: index.ts, queue.ts, _layout.tsx, [id].tsx, checklist.tsx, jest.config.js
- **Component code changes**: queue.ts (conflict detection in catch block), [id].tsx (arrive → sync queue), checklist.tsx (submitOffline), _layout.tsx (wirePhotoAutoUpload)

## Iteration 42 — Phase O6: Full Write Parity + Sync UI Polish
- **Commit**: da3cb17b44df8c1298101effe25daf3681a9c1c2
- **Date**: 2026-08-29
- **Changes**:
  - Created offlineWrite utility (src/services/offlineWrite.ts) — unified write wrapper with automatic offline fallback
  - Created 6 sync UI components: OfflineBanner, PendingChangesChip, ConflictSheet, SyncToast, StoragePressureBanner, ManualSyncButton
  - Created storageWatchdog service (src/services/storageWatchdog.ts)
  - Wired 18 W-A write flows (silent offline queue) and 12 W-B flows (queue with warning) across 17 screen/component files
  - Expanded cacheInvalidation.ts from ~7 to 30+ op_types
  - Integrated all sync UI into root _layout.tsx, dashboard header, and More screen
  - Fixed dashboard load() callback syntax error
  - 12 Jest tests all passing (__tests__/o6-write-parity.test.ts)
- **Files modified**: 34 files (10 new, 24 modified)
  - New: src/services/offlineWrite.ts, src/services/storageWatchdog.ts, src/components/sync/{OfflineBanner,PendingChangesChip,ConflictSheet,SyncToast,StoragePressureBanner,ManualSyncButton,index}.tsx, __tests__/o6-write-parity.test.ts
  - Modified: app/_layout.tsx, app/(app)/index.tsx, app/(app)/more.tsx, app/job/[id].tsx, app/job/new.tsx, app/job/[id]/checklist.tsx, app/customer/new.tsx, app/dispatch.tsx, app/time-clock.tsx, app/time-off.tsx, app/landscape-time-clock.tsx, app/settings/notifications.tsx, src/components/job/FieldReport.tsx, src/components/job/MaintenanceLog.tsx, src/components/job/ServiceIssues.tsx, src/components/schedule/CouldNotServiceButton.tsx, src/components/customers/ServiceNotes.tsx, src/components/customers/CustomerTagsSection.tsx, src/components/customers/MuteControlSheet.tsx, src/components/gps/GpsConsentModal.tsx, src/components/LandscapingClockWidget.tsx, src/components/NewLeadForm.tsx, src/services/cacheInvalidation.ts
- **Web files referenced**: frontend/src/apiClient.js, frontend/src/App.js (for flow mapping)

## Iteration 43 — Targeted lint fixes: no-redeclare + rules-of-hooks
- **Commit**: 9bab96c
- **Date**: 2026-08-29
- **Changes**:
  - Fix 1: Renamed type `MentionDetail` → `MentionDetailData` in `app/aeo/mention-detail.tsx` to resolve no-redeclare collision with the default-exported function of the same name.
  - Fix 2: Hoisted all hooks in `app/(app)/schedule/calendar.tsx` above the `if (role === "customer") return <Redirect>` early return (moved to just before the JSX return). Eliminates ~30 rules-of-hooks errors.
  - Fix 3: Hoisted all hooks in `app/(app)/jobs.tsx` above the `if (isAdmin) return <Redirect>` early return (moved to just before the JSX return). Eliminates ~7 rules-of-hooks errors.
- **Files modified**: app/aeo/mention-detail.tsx, app/(app)/schedule/calendar.tsx, app/(app)/jobs.tsx
- **Tests**: 17/17 schedule tests passing, Metro bundler clean

## Iteration 44 — Phase S2: Soshie Hub Mobile (3 tabs, full web parity)
- **Commit**: e862c7a4e7831f6c7dc07903f2cae2a14d7f1170
- **Date**: 2026-08-30
- **Changes**:
  - Created `app/soshie/index.tsx` — SoshieHub shell with 3 segment tabs (Brand Brain / Autopilot / Review Queue), admin guard, offline banner
  - Created `app/soshie/BrandBrainTab.tsx` — brand memory read-only display + re-ingest modal with URL/paths inputs + empty state with CTA + loading skeletons
  - Created `app/soshie/AutopilotTab.tsx` — global kill switch toggle, 8-platform grid with per-platform toggle + cadence stepper + connection/coming-soon badges, Reddit hard-blocked (disabled + Manual Only badge, no PATCH on tap), recent actions feed, optimistic toggles with revert on error
  - Created `app/soshie/ReviewQueueTab.tsx` — pending/flagged/deferred action list, sort oldest-first, per-card preview + flag chips + media thumbnail + brand_score, Publish now (always confirm_flags=1), Reject, Edit draft modal (PATCH + re-moderate), pull-to-refresh, empty state
  - Created `__tests__/soshie-hub.test.tsx` — 8 tests all passing
  - Added Soshie nav entry to `src/nav/adminNav.ts` (AI Employees group)
- **Files modified**: 6 files (5 new, 1 modified)
  - New: app/soshie/{index,BrandBrainTab,AutopilotTab,ReviewQueueTab}.tsx, __tests__/soshie-hub.test.tsx
  - Modified: src/nav/adminNav.ts
- **Web files referenced**: frontend/src/pages/soshie/{SoshieHub,BrandBrainTab,AutopilotSchedulesTab,ReviewQueueTab}.jsx
- **Tests**: 8/8 new tests passing + 12/12 O6 regression tests passing
- **Metro**: Bundle compiled cleanly (2251 modules, 1967ms)


## Iteration 45 — Independent QA Verification Pass
- **Commit**: 9ceb90a44df90bf44cb551da546ed3983ba85a24
- **Date**: 2026-08-30
- **Changes**:
  - Full QA smoke test of all recently completed features
  - Verified Metro bundler compiles 2278 modules with zero errors
  - Jest: 701/722 pass (8 pre-existing failures, 0 new regressions)
  - Targeted feature tests: 32/32 pass (brand-logo 12, soshie-hub 7, o6-write-parity 13)
  - Lint clean on 7 key files: useTenantBrand.ts, BrandLogo.tsx, widgets.tsx, soshie/index.tsx, offlineWrite.ts, login.tsx, _layout.tsx
  - Local service 200 OK on port 3001; backend responsive on public URL
  - Expo preview tunnel sleeping (platform CDN issue, documented)
- **Files modified**: None (QA-only pass)

## Iteration 46 — Settings Hub + Sprocket + Typed-Confirm Removal
- **Commit**: 261f868a / f269ac0f
- **Date**: 2026-08-30
- **Changes**:
  - Created `app/settings/index.tsx` — 4-tab Settings Hub (General, Branding, Integrations, Social) gated to admin/super_admin
  - Created `src/components/settings/PlatformGrid.tsx` — extracted 8-platform connect grid from AutopilotTab
  - Modified `src/components/widgets.tsx` — added SettingsSprocket gear icon in Header, testID=`header-settings-sprocket`, visible only for admin/super_admin
  - Modified `app/soshie/AutopilotTab.tsx` — removed platform grid (now on Settings → Social), kept kill switch + recent actions + redirect message
  - Modified `src/components/portal/DeleteAccountSection.tsx` — removed typed-confirm TextInput, confirm button is now immediately enabled
  - Updated `__tests__/phase11b-delete-account-section.test.tsx` — updated to test new single-click confirm flow
  - Updated `__tests__/soshie-hub.test.tsx` — updated Autopilot tests to match new architecture (grid moved to Settings → Social)
  - Created 3 new test files: settings-hub-mobile, settings-sprocket-visibility, mobile-no-typed-confirm
  - All 5 new/modified test suites pass (25/25 tests)
  - Zero new regressions (8 pre-existing failures unchanged)
  - Lint clean on all modified files
- **Files modified**: app/settings/index.tsx, src/components/settings/PlatformGrid.tsx, src/components/widgets.tsx, app/soshie/AutopilotTab.tsx, src/components/portal/DeleteAccountSection.tsx
- **Files referenced from web**: frontend/src/layouts/SettingsHub.jsx, frontend/src/layouts/AdminTopBar.jsx, frontend/src/pages/settings/IntegrationsPages.jsx, frontend/src/pages/settings/SettingsSocial.jsx, frontend/src/components/common/ConfirmDeleteDialog.jsx
- **Deferred**: Mobile admin logo upload UI (Branding tab read-only), in-app OAuth flows (Integrations tab links to web)

- **Conclusion**: All recently shipped features verified functional with no regressions

## Iteration 47 — B2 Stripe Card + ACH Native Capture
- **Commit**: 0f783f77b267944756a8213640c6783fa3ed412d
- **Date**: 2026-08-30
- **Changes**:
  - Installed `@stripe/stripe-react-native@0.50.3` with Expo config plugin (merchant id: merchant.com.poolscape.crm)
  - Created `app/customer/[id]/payment-methods.tsx` — full payment methods screen with list, add card, add ACH, remove, offline handling
  - Created `src/api/stripe.ts` — typed API helpers (getStripeConfig, createSetupIntent, attachPaymentMethod, listPaymentMethods, removePaymentMethod)
  - Created `src/components/stripe/PaymentMethodRow.tsx` — card/ACH row component with verification chips, default badge, remove button
  - Created `src/lib/stripeSdk.tsx` + `src/lib/stripeSdk.web.tsx` — platform-safe Stripe SDK wrapper (native re-exports real SDK, web exports no-op stubs)
  - Created `src/services/sync/db.web.ts` — web shim for expo-sqlite to fix pre-existing wasm resolution failure on Metro web bundling
  - Modified `app/customer/[id].tsx` — replaced "Send Link" primary button with "Manage" → navigates to payment-methods screen; kept "Send add-card link" as secondary
  - Created 4 test suites: stripe-payment-sheet-init, stripe-payment-methods-list, stripe-offline-banner, stripe-attach-round-trip
  - 10 new tests, all passing
  - Full regression: 726/747 (8 pre-existing failures, 0 new)
  - Web bundle: 2273 modules, clean
  - Lint clean on all files
- **Files modified**: app/customer/[id].tsx, app.json
- **Files created**: 10 new files (1,240 LOC total)
- **Note**: Expo prebuild required for actual PaymentSheet native functionality. Web preview uses no-op stubs with graceful "native build required" alert.
- **Note**: Fixed pre-existing expo-sqlite web wasm bundling issue with db.web.ts shim (was masked by cached Metro bundle)


## Iteration 48 — Schedule NavigateJobButton (Mobile Parity)
- **Commit**: 5a8ae43deb819fb99c211e716a024bd32553b808
- **Date**: 2026-08-30
- **Changes**:
  - Created `src/services/navigation/mapsDeepLink.ts` (84 LOC) — resolveDestination, buildGoogleMapsUrl, openMaps with iOS/Android/Web platform routing
  - Created `src/components/schedule/NavigateJobButton.tsx` (89 LOC) — Pressable with navigate-outline icon, animated press, disabled toast, testID mirror
  - Mounted NavigateJobButton in `app/(app)/schedule/calendar.tsx` JobRow action cluster (after CouldNotServiceButton)
  - Created `__tests__/navigate-job-button.test.tsx` (185 LOC) — 12 tests: helpers + component rendering/behavior
  - Created `__tests__/mapsDeepLink.test.ts` (117 LOC) — 7 tests: per-platform URL scheme selection
  - All 19 new tests pass
  - Full regression: 745/766 (8 pre-existing failures, 0 new)
  - Web bundle: 2272 modules, clean
  - Lint clean on all files
  - `expo-linking` already installed (no new dependencies)
- **Files modified**: app/(app)/schedule/calendar.tsx (import + mount)
- **Files created**: 4 new files (475 LOC total)
- **Web reference**: frontend/src/components/schedule/NavigateJobButton.jsx, frontend/src/test/schedule-navigate-button.test.jsx



## Iteration 67 — Phase K29: Dynamic app.config.js + Mapbox secret cleanup
- **Commit**: 4851ac251c72dddad77d4b23d7a20effbc5c16cd
- **Date**: 2026-09-02
- **Changes**:
  - Deleted `mobile/app.json` (static config replaced by dynamic `app.config.js`)
  - `app.config.js` reads Google Maps keys via `process.env` at build time:
    - iOS: `ios.config.googleMapsApiKey` (flat key — correct iOS schema)
    - Android: `android.config.googleMaps.apiKey` (nested — correct Android schema)
  - Stripped secret Mapbox `sk.` token (`RNMAPBOX_MAPS_DOWNLOAD_TOKEN`) + comments from `.env`
  - Public `pk.` Mapbox token (`EXPO_PUBLIC_MAPBOX_TOKEN`) left intact
  - Validation: `npx expo config --json` parses correctly from `app.config.js`
  - Validation: `npx expo-doctor` — 18/18 checks passed
  - Screenshot: App renders correctly after config migration
- **Files deleted**: mobile/app.json
- **Files modified**: mobile/.env (removed 6 lines: sk. token + comments)
- **Files referenced**: mobile/app.config.js (created in prior turn), mobile/package.json

## Iteration 68 — Phase K32: Tech-scoped mobile Schedule (no filters, auto-scope)
- **Commit**: 7eedcadf5d6c67cffe2efaa5b6420f2c8b7b24d5
- **Date**: 2026-09-03
- **Changes**:
  - `isTech` now checks both `"technician"` and `"tech"` role spellings
  - `load()` auto-appends `&technician_id=<user.id>` for tech role users
  - `load()` skips `crew_id` param for tech role (irrelevant since filter hidden)
  - CrewFilterBar hidden when `isTech` (wrapped in `!isTech && crews.length > 0`)
  - `isTech` passed to GridView; removed stale eslint-disable directive
  - Admin/manager/dispatcher unchanged (no technician_id forced, crew filter visible)
  - Tests: 6 new (k32-tech-scoped-schedule.test.tsx), all passing
  - API verified: admin sees 14 jobs, tech scoped sees 3 (same endpoint, different params)
- **Files modified**: `app/(app)/schedule/calendar.tsx` (+8/-4 lines)
- **Files created**: `__tests__/k32-tech-scoped-schedule.test.tsx` (6 tests)


## Iteration 69 — Hotfix M1 + M2: Schedule bulk-action authz + row styling
- **Commit**: 0d93c65d35fac767b09d68edc772b63dd8f62ac9
- **Date**: 2026-09-07
- **Changes**:
  - M1: Bulk-action "Actions" dropdown fully unmounted for tech role (`isAdmin` gate)
  - M2: OnMyWayButton → navy #1B1F5C fill, white text (both variants)
  - M2: CouldNotServiceButton → red #DC2626 fill, white text (both variants)
  - M2: NavigateJobButton → 44×44 navy pill, filled icon, removed dead import
  - M2: JobNotesCallout → white bg with amber left-accent (was amber fill)
  - Tests: 10 new (hotfix-m1-m2-schedule.test.tsx), 6 K32 regressions pass
- **Files modified**: calendar.tsx, OnMyWayButton.tsx, CouldNotServiceButton.tsx, NavigateJobButton.tsx, JobNotesCallout.tsx
- **Files created**: __tests__/hotfix-m1-m2-schedule.test.tsx


## Iteration 70 — Hotfixes M3 + M4 + M5
- **Commit**: db0d3ff1d56a4e2d8ccba1a47bde5947bb66fb33
- **Date**: 2026-09-08
- **Changes**:
  - M3-A: Customers-nearby panel — NO-OP (mobile has no customer layer on D2D)
  - M3-B: Zillow enrichment button + data panel on knock edit Sheet (d2d/index.tsx)
    - "Pull property data" / "Refresh Zillow data" labels, cached fields pre-rendered
    - Error toasts: 503 (not configured), 429 (rate limited), generic
  - M4: Trainings — NO code changes (verified no client-side filtering)
  - M5: Checklist load() rewritten with per-status-code error handling
    - 429→retry+cache→"Server busy", 401/403→login, 5xx→retry button
    - Telemetry logging via POST /api/telemetry/mobile-crash (best-effort)
  - Tests: 20 new (4 M3 + 3 M4 + 13 M5), all 36 total pass
- **Files modified**: app/d2d/index.tsx, app/job/[id]/checklist.tsx
- **Files created**: __tests__/hotfix-m3-d2d-zillow.test.tsx, __tests__/hotfix-m4-trainings.test.tsx, __tests__/hotfix-m5-checklist-429.test.tsx


## Iteration 71 — Phase 1 Offline Read Cache for Field Techs
- **Commit**: 2c82722981aa2eab95484be23b28545176bfb10d
- **Date**: 2026-09-08
- **Changes**:
  - NEW: routeHydrator.ts — proactive cache engine (today's route → SQLite)
  - NEW: useRouteHydration.ts — React hook for hydration state + auto-trigger
  - NEW: useCachedJobIds.ts — check which jobs are cached (for "Cached ✓" pills)
  - NEW: offline-diagnostics.tsx — hidden settings screen (cache stats, rebuild, purge)
  - MOD: job/[id].tsx — offline-first reads + "showing cached copy" banner + clean empty state
  - MOD: checklist.tsx — hydrator cache integration + "Not cached for offline" empty state
  - MOD: calendar.tsx — trigger hydrator, "Cached ✓" pill per job row, OfflineBadge stats
  - MOD: OfflineBadge.tsx — "Offline — X of Y jobs cached • synced time"
  - MOD: auth.tsx — clearAllReadCache() on logout
  - MOD: readCache.ts — countCacheKeys() + cacheByteSize() for diagnostics
  - Tests: 16 new (phase1-offline-read.test.tsx), 39 total passing
  - Doc: /app/memory/PHASE_OFFLINE_1_READ_CACHE.md
- **Files created**: src/services/routeHydrator.ts, src/hooks/useRouteHydration.ts, src/hooks/useCachedJobIds.ts, app/(app)/settings/offline-diagnostics.tsx, __tests__/phase1-offline-read.test.tsx
- **Files modified**: app/job/[id].tsx, app/job/[id]/checklist.tsx, app/(app)/schedule/calendar.tsx, src/components/OfflineBadge.tsx, src/auth.tsx, src/services/readCache.ts



## Iteration 72 — Phase 2: Offline Write Queue + Auto-Sync
- **Commit**: 2c82722981aa2eab95484be23b28545176bfb10d
- **Date**: 2026-09-08
- **Changes**:
  - Created Sync Center screen at /settings/sync-center
  - Created SyncBadge component for schedule header
  - Created PendingSyncPill for per-job pending indicators
  - Created usePendingOps/usePendingEntityIds hooks
  - Created videoWorker.ts (30s cap, auto-upload, retry stalled)
  - DB migration v2: videos_pending table
  - Queue concurrency limiter: max 3 entity syncs
  - Wired OnMyWayButton through offlineWrite for offline support
  - Added cache invalidation for video.upload, checklist.answer, checklist.update, job.complete, on_my_way
  - Updated barrel exports in sync/index.ts
- **Files created**: app/settings/sync-center.tsx, src/services/sync/videoWorker.ts, src/hooks/usePendingOps.ts, src/components/SyncBadge.tsx, src/components/PendingSyncPill.tsx
- **Files modified**: src/services/sync/db.ts, src/services/sync/queue.ts, src/services/sync/index.ts, src/services/cacheInvalidation.ts, src/components/schedule/OnMyWayButton.tsx, app/(app)/schedule/calendar.tsx
- **Web files referenced**: frontend/src/components/schedule/OnMyWayButton.jsx (offline write parity)

## Iteration 73 — Phase 2 Follow-up: Three Missing Wire-ups
- **Commit**: 2c82722981aa2eab95484be23b28545176bfb10d
- **Date**: 2026-09-08
- **Changes**:
  - Wired checklist autosave offlineWrite() queued handling + pill text "Saved — will sync when online"
  - Wired Mark Complete via job.complete op_type + Alert toast on queued
  - Added AppState foreground trigger (inactive/background → active flushes sync queue + photos + videos)
  - Wired wireVideoAutoUpload() in boot sequence
  - Updated sync-db.test.ts for v2 migration expectations
- **Files modified**: app/job/[id]/checklist.tsx, app/job/[id].tsx, app/_layout.tsx, __tests__/sync-db.test.ts
- **Test results**: 9 suites, 77 tests, ALL PASSING


## Iteration 74 — Chemistry Readings Unification (web-parity)
- **Commit**: 6e989bc4605637041ff990cd0fc34b931b4e465b
- **Date**: 2026-09-08
- **Changes**:
  - Added CC + water_temp to expandChemistryLabel map
  - Added required prop to ReadingChipRow (red * marker)
  - Exported canonicalReadingKey + ReadingInputRow from PoolChecklistForm
  - Added short-form abbreviations to _NAME_TO_CANONICAL
  - Replaced inline compact grid in service-report with canonical ReadingChipRow
  - Changed WaterBodyPanel from meta.short to meta.name (full-word labels)
  - Added combined_chlorine + water_temp to waterBodies READING_LABELS + READING_ALLOWLIST
  - Applied expandChemistryLabel to portal service-report for customer-facing labels
  - Added 9 regression tests (chemistry-unification.test.ts)
- **Files modified**: src/lib/expandChemistryLabel.ts, src/components/checklist/ReadingChipRow.tsx, src/components/checklist/PoolChecklistForm.tsx, src/components/checklist/WaterBodyPanel.tsx, src/lib/waterBodies.ts, app/(app)/service-report/[id].tsx, app/portal/service-report/[id].tsx
- **Files created**: __tests__/chemistry-unification.test.ts
- **Test results**: 9 new tests passing, 77+16 existing tests passing, 0 regressions


## Iteration 75 — OTA Auto-Update Configuration
- **Commit**: 6e989bc4605637041ff990cd0fc34b931b4e465b
- **Date**: 2026-09-08
- **Changes**:
  - Created useOtaUpdateListener hook (check on cold start + foreground, fetch in background, subtle alert with "Restart now" option, never auto-reload mid-session)
  - Mounted useOtaUpdateListener in _layout.tsx
  - Created /app/memory/OTA_AUTO_UPDATE_CONFIG.md documentation
  - Created __tests__/ota-config.test.ts (9 tests verifying config correctness)
  - Verified app.config.js already had correct updates config (no changes needed)
  - Verified eas.json already had correct channel wiring (no changes needed)
- **Files created**: src/hooks/useOtaUpdateListener.ts, __tests__/ota-config.test.ts, /app/memory/OTA_AUTO_UPDATE_CONFIG.md
- **Files modified**: app/_layout.tsx (import + mount useOtaUpdateListener)
- **Test results**: 9 OTA tests + 86 existing = 95 total, all passing, 0 regressions


## Iteration 76 — Task 4 (Account Chooser) + Task 6 (Send Service Records Link)
- **Commit**: 4e28bef9e809b63b771cc9352022f92043461c6c
- **Date**: 2026-09-08
- **Changes**:
  - Task 4: Multi-account chooser on login — detects multi_account_choice_required, renders card chooser, finalizeAccountChoice to POST /auth/login/select-account, "Not you? Log out." cancel
  - Task 6: Send Service Records Link modal — Email/SMS tabs, consent checks, throttle status, copy link, send button, success/error toasts
  - Task 6: Added "Service Records Link" to SendCreateSheet quick actions
  - Added 9 Task 4 tests + 13 Task 6 tests
- **Files created**: src/components/customers/SendServiceRecordsLinkModal.tsx, __tests__/task4-account-chooser.test.ts, __tests__/task6-send-service-records-link.test.ts
- **Files modified**: src/auth.tsx, app/login.tsx, src/components/customers/SendCreateSheet.tsx, app/customer/[id].tsx
- **Test results**: 13 suites, 116 tests, ALL passing, 0 regressions



## Iteration 77 — Expo Web Schedule Map + Header Layout Bugs
- **Commit**: 623467c4639607ef5cd4188ca9b5139e28a2a72f
- **Date**: 2026-09-09
- **Changes**:
  - Bug 1: Verified DailyRouteMap.web.tsx Leaflet/OSM iframe map was already complete from prior agent — renders real map tiles with colored circleMarkers
  - Bug 2: Fixed Header component in widgets.tsx — added minWidth: 0 + flexShrink: 1 to title column, numberOfLines={1} + ellipsizeMode="tail" to subtitle Text to prevent RN Web flexbox collapse
- **Files modified**: src/components/widgets.tsx
- **Web files referenced**: DailyRouteMap.web.tsx, OfflineBadge.tsx, calendar.tsx


## Iteration 78 — Trim Chemistry UI on Expo Web Checklist
- **Commit**: 284fc1f7f41657bdb78c40945b132f772f20e20f
- **Date**: 2026-09-09
- **Changes**:
  - WaterBodyPanel.tsx: Wrapped "Chemicals Used" block (label + chemical rows + "Add chemical") in Platform.OS !== "web" guard
  - PoolChecklistForm.tsx: Wrapped "Chemical Readings" heading in Platform.OS !== "web" guard (classify prompt untouched)
  - Added 6-test guard RTL test: chemistry-ui-trim.test.tsx
- **Files modified**: src/components/checklist/WaterBodyPanel.tsx, src/components/checklist/PoolChecklistForm.tsx
- **Files created**: __tests__/chemistry-ui-trim.test.tsx
- **Test results**: 6/6 new tests passing, no regressions


## Iteration 79 — Port Phase A line-item decline + schedule refresh + VIP inline
- **Commit**: dd808147a7bb6f644bb48b3e0d19b20c0a2f657c
- **Date**: 2026-09-09
- **Changes**:
  - ITEM 1: Full Phase A line-item decline + top-level approve/decline on estimate view
  - ITEM 2: Schedule refresh button in header toolbar (schedule-refresh testID)
  - ITEM 3: VIP pill + NavigateJobButton moved inline with customer name on schedule cards
- **Files modified**: estimate-view/[id].tsx, estimatesFull.ts, calendar.tsx
- **Files created**: __tests__/parity-phase-a.test.tsx
- **Test results**: 8/8 passing


## Iteration 80 — Solid red Decline button on estimate toolbar
- **Commit**: 4ed75b4838b2e5348d25ceb9dcdd9a60d00a660c
- **Date**: 2026-09-10
- **Changes**: Changed estimate-toolbar-customer-decline from outlined-red to solid-red (#DC2626) bg with white text/icon
- **Files modified**: app/estimate-view/[id].tsx, __tests__/parity-phase-a.test.tsx
- **Test results**: 9/9 passing (new assertion: backgroundColor === "#DC2626")


## Iteration 81 — P0 Tech Close Job 429 Fix
- **Commit**: 2fbda064fa88052cc386d90fa59cbe955e02303f
- **Date**: 2026-09-10
- **Changes**:
  - Created retryWithBackoff.ts: exponential backoff + jitter, honors Retry-After/X-Ratelimit-Source, max 5 retries
  - Extended ApiError with retryAfterSeconds + rateLimitSource on 429 responses
  - Created ChecklistSavePill.tsx: single unified pill (saving/retrying/exhausted/synced/offline)
  - Replaced dual checklist pills (autosave + network) with single unified pill
  - Wrapped close-job POST + autosave PATCH in retryWithBackoff
  - Added job-close-error-dialog modal on retry exhaustion
  - 429 exhaustion enqueues payload to writeQueue for offline safety
- **Files modified**: api.ts, checklist.tsx
- **Files created**: retryWithBackoff.ts, ChecklistSavePill.tsx, __tests__/p0-429-retry.test.tsx
- **Test results**: 12/12 passing


## Iteration 82 — Mobile Parity: Task 3 + Task 5 + Task 6 + PB2
- **Commit**: ec03b89b18006a6172e2460d858eaf91bc919621
- **Date**: 2026-04-16
- **Changes**:
  - Task 3: Created magic-link invoice screen at /app/i/[token].tsx (JWT decode, fetch, pay via system browser)
  - Task 5: Created portal payment-methods screen with card list, remove, set-default + save-card toggle on magic pay
  - Task 6: Added terms_and_conditions section to estimate-view with empty-state handling
  - PB2: Documented gap in MOBILE_PARITY_GAPS.md (no admin line-item editor on mobile)
  - Added "View all cards" link to existing payment-method screen
- **Files created**: app/i/[token].tsx, app/portal/payment-methods.tsx, memory/MOBILE_PARITY_GAPS.md
- **Files modified**: app/estimate-view/[id].tsx, src/api/estimatesFull.ts, app/portal/payment-method.tsx
- **Tests created**: task3-invoice-bypass-mobile.test.tsx (6), task5-save-card-mobile.test.tsx (4), task6-terms-mobile.test.tsx (6), pb2-line-item-overrides.test.tsx (4)
- **Test results**: 20/20 passing, all pre-existing tests still passing (27/27)

## Iteration 83 — P0 Fix: Close-Job silent no-op
- **Commit**: 5a1d5e7ec3dc92ac79165296488b563f8449d87f
- **Date**: 2026-04-16
- **Changes**:
  - Root cause: Alert.alert silently no-oping on iOS 17 + Hermes (detached UIScene)
  - Replaced 2 Alert.alert calls in closeJob with in-tree Modal components
  - Extracted doCloseJob from inner Alert callback
  - Added 3s hard cap on outlier check (fail-open advisory)
  - Fixed handleClose() ReferenceError → doCloseJob() in 429 retry handler
  - Added 2 new Modals: close-job-confirm-dialog, close-job-outlier-dialog
- **Files modified**: app/job/[id]/checklist.tsx
- **Files created**: __tests__/job-close-silent-noop.test.tsx
- **Test results**: 6/6 new tests passing, 47/47 pre-existing still passing (53 total)
- **Screenshot**: /tmp/close-job-fixed.png — in-tree confirm dialog renders after tap

## Iteration 84 — Offline Hardening: 3 Fixes
- **Commit**: 0e2aa4cd367c2dcddcfa8744b6fc75d45cce0db8
- **Date**: 2026-04-16
- **Changes**:
  - Fix 1: Replaced N+1 per-job GET calls in routeHydrator with single GET /mobile/offline-bundle
  - Fix 2: Created photoUrlCache.ts (URL builder, prefetch, base64 strip, lazy resolve via expo-image)
  - Fix 3: Honest sync status in HydrationMeta + OfflineBadge (partial/failed/synced)
  - Updated calendar.tsx freshness label to show honest partial/failed status
- **Files created**: src/services/photoUrlCache.ts, __tests__/route-hydrator-single-call.test.ts, __tests__/job-photo-url-cache.test.tsx, __tests__/sync-status-partial.test.tsx, memory/MOBILE_OFFLINE_HARDENING.md
- **Files rewritten**: src/services/routeHydrator.ts, src/components/OfflineBadge.tsx
- **Files modified**: src/hooks/useRouteHydration.ts, app/(app)/schedule/calendar.tsx
- **Test results**: 68/68 total (15 new + 53 existing), all passing

## Iteration 85 — Temp-Password + First-Access Parity
- **Commit**: cf0af6df5a05201a893ab31bda64b98933ebab25
- **Date**: 2026-04-16
- **Changes**:
  - Created /set-password screen with silent re-login after reset
  - Extended login() and finalizeAccountChoice() to return password_reset_required fork
  - Updated login.tsx submit() and pickAccount() to handle the fork
  - Added "Never logged in" filter to admin customers list (?first_access=never)
  - Token-expired handling with friendly Alert → back to login
- **Files created**: app/set-password.tsx, 3 test files, memory/MOBILE_TEMP_PASSWORD_PARITY.md
- **Files modified**: src/auth.tsx, app/login.tsx, app/(app)/customers.tsx
- **Test results**: 78/78 total (10 new + 68 existing), all passing
- **Screenshot**: /tmp/mobile-temp-password-reset.png

## Iteration 86 — Mobile parity: Business Settings + Decline-per-group + Theme Refresh
- **Commit**: 89edabbbebfae003d5ed916753a8f9be7f135e72
- **Date**: 2026-09-12
- **Changes**:
  - New Business Settings screen with company fields, logo upload/remove, brand colour pickers, live preview
  - Dual-total renderer on admin quote detail (Subtotal incl. declined / Effective excl. declined)
  - Grouped-view with Decline/Restore buttons on estimate customer view
  - Branded header/footer bands (dark-blue / brand_primary_hex) on estimates, invoices, and quotes
- **Files modified**: businessSettings.ts (new), useBusinessSettings.ts (new), settings/business.tsx (new), settings/index.tsx, estimatesFull.ts, quote/[id].tsx, estimate-view/[id].tsx, invoice/[id].tsx
- **Web files referenced**: BusinessSettings.jsx, BrandLogoSettings.jsx, EstimateView.jsx, DocDesktopShell.jsx, useTenantBranding.js, QuoteInvoiceDetail.jsx

## Iteration 87 — Duplicate Quote (P0) + UX polish: 403 vs offline label + Toast
- **Commit**: 09c5705f97224828950ed5e1d049e7825ab43c7d
- **Date**: 2026-09-13
- **Changes**:
  - Duplicate Quote: copy-outline button in quote header (admin/super_admin only), bottom-sheet modal with searchable customer picker + property picker, POST /api/quotes/{qid}/duplicate, success toast + navigate to new quote
  - mapApiError classifier: 403→forbidden (lock icon), 401→auth, 404→not_found, 500→server, network→offline (cloud icon). Fixed dashboard showing "You're offline" for 403 errors
  - ToastProvider: lightweight Animated toast context provider, 3 variants (success/error/info), globally available via useToast()
  - Swapped 4 quote success Alert.alert calls to showToast: payment received, reminder sent, estimate decision, quote duplicated
  - 10/10 mapApiError unit tests passing
- **Files created**: mapApiError.ts, ToastProvider.tsx, mapApiError.test.ts, duplicate-quote.test.tsx
- **Files modified**: quote/[id].tsx, _layout.tsx, (app)/index.tsx


## Iteration 87 — UX Polish: Broader Alert→Toast rollout + mapApiError expansion + Tests
- **Commit**: 4a8d044294a26b197150835840416b1856849018
- **Date**: 2026-09-13
- **Changes**:
  - **Phase 1 — Alert.alert → showToast**: Converted 40+ success/info/non-blocking-error Alert.alert calls to showToast across 25+ files
  - **Phase 2 — mapApiError expansion**: Retrofitted into 7 error surfaces (job detail, checklist, d2d, EbitTile, comms templates/sends/automations)
  - **Phase 3 — Tests**: 27 tests passing (mapApiError unit + toast conversion patterns + screen integration)
  - Fixed syntax errors in aeo/publish-config.tsx and aeo/response-draft.tsx
- **Files modified**: 25+ app screens, 5 components, 3 test files (2 new)



## Iteration 88 — Dispatch A Test Fix: Jest API mock hoisting + cleanup
- **Commit**: c792e05a
- **Date**: 2026-09-13
- **Changes**:
  - Fixed `TypeError: _api.api.get is not a function` in both Dispatch A test files. Root cause: `const mockGet = jest.fn()` was in the temporal dead zone when `jest.mock()` factory evaluated `api: { get: mockGet }` (babel hoists `jest.mock` above `const` initializers). Fix: use inline `jest.fn()` in factory, then cast `api.get as jest.Mock` after import.
  - Fixed ChaseStalledInvitesSheet mock in onboarding tile test to respond to `visible` prop (was returning null always, breaking the "opens sheet" test).
  - Removed 2 stray `console.log` statements from `PortalOnboardingHealthTile.tsx` (lines 180, 191).
  - Removed unused `formatCustomerName` import from `customers.tsx`.
  - Deleted debug sandbox file `__tests__/debug-tile.test.tsx`.
  - Updated `/app/memory/AUDIT_MOBILE_PARITY_TRIO.md` with Dispatch A final deliverable checklist.
  - **14/14 tests passing** (8 onboarding tile + 6 chase sheet).
- **Files modified**: `__tests__/onboarding-health-tile.test.tsx`, `__tests__/chase-stalled-invites.test.tsx`, `src/components/customers/PortalOnboardingHealthTile.tsx`, `app/(app)/customers.tsx`
- **Files deleted**: `__tests__/debug-tile.test.tsx`

## Iteration 89 — Dispatch B: Portal Access Panel (Feature 3)
- **Commit**: c792e05a
- **Date**: 2026-09-13
- **Changes**:
  - Created `src/components/customers/PortalAccessPanel.tsx` (515 LOC): admin-only portal management panel with status row, 5 action buttons (send invite, send reset link, copy reset link, reset password, revoke access), temp password card with clipboard copy, and activity feed.
  - Created `__tests__/portal-access-panel.test.tsx` (11 tests): full coverage of all actions, RBAC gating (super_admin copy link), Alert confirmations, clipboard, error handling via mapApiError.
  - Integrated into `app/customer/[id].tsx`: admin-gated render below login badge section.
  - Used inline `jest.fn()` in mock factory pattern (learned from Dispatch A TDZ fix) for expo-clipboard mock.
  - **11/11 Dispatch B tests passing**, **14/14 Dispatch A tests still green** = 25 total parity tests green.
- **Files created**: `src/components/customers/PortalAccessPanel.tsx`, `__tests__/portal-access-panel.test.tsx`
- **Files modified**: `app/customer/[id].tsx`
- **Web files referenced**: `frontend/src/pages/customers/CustomerDetail.jsx` (PortalAccessPanel, PortalResetModal, event labels)
- **Memo**: `/app/memory/FEATURE_MOBILE_PARITY_DISPATCH_B.md`


## Iteration 90 — Send Quote to Customer action mirror
- **Commit**: 68472567
- **Date**: 2026-09-13
- **Changes**:
  - Created `src/components/quotes/SendToCustomerSheet.tsx` (328 LOC): Bottom-sheet modal with recipient preview from `quote.customer_email`, override toggle + email input, note textarea (≤500 chars), Cancel/Send buttons. Uses `mapApiError` for errors, `showToast` for success. Sheet stays open on error.
  - Created `__tests__/send-to-customer-sheet.test.tsx` (6 tests): visibility, recipient pre-fill, override POST body, char cap, success toast + callbacks, error mapApiError.
  - Modified `app/quote/[id].tsx`: Added SendToCustomerSheet import + state, send icon button in header (admin + non-invoice gated), render sheet with quote data.
  - **6/6 new tests passing**, **31 prior parity tests still green** = 37 total.
  - Decision: Toast-only (no Alert) — modal is the confirmation.
- **Files created**: `src/components/quotes/SendToCustomerSheet.tsx`, `__tests__/send-to-customer-sheet.test.tsx`
- **Files modified**: `app/quote/[id].tsx`
- **Web files referenced**: `frontend/src/components/quotes/SendToCustomerModal.jsx`, `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx`
- **Memo**: `/app/memory/FEATURE_SEND_TO_CUSTOMER_MOBILE.md`


## Iteration 91 — Route-entry classifier gap fix
- **Commit**: 94bc9fdb
- **Date**: 2026-09-13
- **Changes**:
  - Audited all `[id].tsx` detail screens for route-entry classifier gap. Found 3 affected: quote, customer, invoice. Job was already fixed (reference pattern).
  - **quote/[id].tsx**: Added `loadError`/`rawLoadError` state, classified error render block with `mapApiError` + `errorKindIcon` + retry button. 403 now shows "Not authorized" instead of blank screen.
  - **customer/[id].tsx**: Same pattern applied. 403 now shows "Not authorized" instead of blank screen.
  - **invoice/[id].tsx**: Added `rawLoadError` to existing error handling, upgraded existing error block to use `mapApiError` classification. 403 now shows "Not authorized" instead of generic "Failed to load invoice".
  - Created `__tests__/route-entry-classifier.test.tsx` (6 tests): 403 → "Not authorized" + network → "You're offline" for all 3 screens.
  - **6/6 new tests passing**, **31 prior tests still green** = 37 total.
  - ~82 LOC total (under 100 LOC cap).
- **Files modified**: `app/quote/[id].tsx`, `app/customer/[id].tsx`, `app/invoice/[id].tsx`
- **Files created**: `__tests__/route-entry-classifier.test.tsx`
- **Memo**: `/app/memory/FEATURE_MOBILE_ROUTE_ENTRY_CLASSIFIER.md`


## Iteration 92 — Hide Checklist Chemical Readings (mobile mirror)
- **Commit**: e908e475
- **Date**: 2026-09-13
- **Changes**:
  - Created `src/config/featureFlags.ts` (9 LOC) — new feature flags module mirroring web pattern. `SHOW_CHECKLIST_CHEMICAL_READINGS: false`.
  - Gated the entire Chemical Readings section in `src/components/checklist/PoolChecklistForm.tsx` behind the flag (+8 LOC): heading, reclassify picker, reading inputs, analysis card, visible algae toggle.
  - Created `__tests__/hide-checklist-chemical-readings.test.tsx` (4 tests): flag OFF hides heading/inputs/algae; flag ON renders them (contract lock).
  - **4/4 new tests passing**, **37 prior tests still green** = 41 total.
  - 17 LOC change (well under 50 cap).
- **Files created**: `src/config/featureFlags.ts`, `__tests__/hide-checklist-chemical-readings.test.tsx`
- **Files modified**: `src/components/checklist/PoolChecklistForm.tsx`
- **Memo**: `/app/memory/FEATURE_HIDE_CHECKLIST_CHEMICAL_READINGS_MOBILE.md`


## Iteration 93 — Revert hide-all Chemical Readings + Remove Combined Chlorine
- **Commit**: d8109d22
- **Date**: 2026-09-13
- **Changes**:
  - **Step 1 (revert)**: Deleted `src/config/featureFlags.ts` + `__tests__/hide-checklist-chemical-readings.test.tsx`. Removed flag import + JSX gate from `PoolChecklistForm.tsx`. Section always renders again.
  - **Step 2 (legacy fix)**: Confirmed 10 previously-broken legacy tests (`chemistry-ui-trim` 6 + `checklist-service-type-picker` 4) all pass after revert with zero test-file changes.
  - **Step 3 (surgical CC removal)**: Filtered `combined_chlorine` from `readingFields` useMemo in `PoolChecklistForm.tsx`. Removed from `READING_ALLOWLIST.pool` and `READING_ALLOWLIST.other` in `waterBodies.ts`. Preserved canonical key mapping + labels for historic reads.
  - Created `__tests__/remove-combined-chlorine.test.tsx` (4 tests): section renders, CC absent, core 5 present, filter verified.
  - **51 tests all green** (37 parity + 10 recovered legacy + 4 new CC).
- **Files deleted**: `src/config/featureFlags.ts`, `__tests__/hide-checklist-chemical-readings.test.tsx`
- **Files modified**: `src/components/checklist/PoolChecklistForm.tsx`, `src/lib/waterBodies.ts`
- **Files created**: `__tests__/remove-combined-chlorine.test.tsx`
- **Memo**: `/app/memory/FEATURE_REMOVE_COMBINED_CHLORINE_MOBILE.md`


## Iteration 94 — Responsive Quote/Estimate Stacked Card Layout
- **Commit**: 71545ea3
- **Date**: 2026-09-14
- **Changes**:
  - Converted line items from horizontal row layout to vertically stacked cards across 4 screens: `estimate-view/[id].tsx`, `quote/[id].tsx`, `invoice/[id].tsx`, `i/[token].tsx`.
  - Each line item card: Description → qty detail → subtotal separator row → action button.
  - Decline/Undo Decline buttons now full-width with `minHeight: 44px` tap targets.
  - Wrapped Internal Margin table (admin only) in `<ScrollView horizontal>` in both `quote/[id].tsx` and `invoice/[id].tsx` with `minWidth: 480`.
  - Removed old `lineRow`/`groupRow` row-based styles; introduced `lineCard`, `lineCardSubtotalRow`, `lineCardSubtotalLabel`, `lineCardDeclined`, `lineCardLateFee`, `lineCardHeader`.
  - No new dependencies. No backend changes.
- **Files modified**: `app/estimate-view/[id].tsx`, `app/quote/[id].tsx`, `app/invoice/[id].tsx`, `app/i/[token].tsx`
- **Files created**: `memory/FEATURE_RESPONSIVE_QUOTE_ESTIMATE_MOBILE_PARITY.md`
- **Web files referenced**: None (mobile-only layout refactor)

## Iteration 95 — Chemistry Gate Mobile Fix: ref→report mirror + payload consistency
- **Commit**: 52e394cc
- **Date**: 2026-09-14
- **Changes**:
  - Added `flattenPoolReadings()` helper to `src/lib/waterBodies.ts` — rebuilds flat `chemical_readings` mirror from structured `water_bodies[]`.
  - Fixed `handleBodiesChange` in `checklist.tsx` to mirror `waterBodiesRef.current` back into `report.water_bodies` and `report.chemical_readings` via `patchReport()` on every edit.
  - Fixed `flushSave` PATCH payload: when bodies exist, `chemical_readings` is rebuilt from the authoritative ref at build time (no longer stale from `reportRef.current`).
  - Fixed `doCloseJob` offline path: enriches report with fresh water-body data from ref before passing to `submitOffline`.
  - Added 8 Jest test cases in `chemistry-gate-mobile.test.ts`.
- **Files modified**: `app/job/[id]/checklist.tsx`, `src/lib/waterBodies.ts`
- **Files created**: `__tests__/chemistry-gate-mobile.test.ts`, `memory/FEATURE_CHEMISTRY_GATE_MOBILE.md`
- **Web files referenced**: None (mobile-only behavior fix)

## Iteration 96 — Sync arrival radius to 75m (server parity)
- **Commit**: ad60be0c45
- **Date**: 2026-09-14
- **Changes**:
  - Changed `ARRIVE_RADIUS_M` in `JobTimerCard.tsx` from 150 → 75.
  - Changed `RADIUS_M` in `geofence.ts` from 150 → 75.
  - `jobGeofence.ts` `FALLBACK_RADIUS_M` already 75 — no change needed.
  - Added sync comments referencing `backend/routers/gps_auto_start.py`.
  - Added 3 Jest tests locking all three constants to 75m.
- **Files modified**: `src/components/job/JobTimerCard.tsx`, `src/geofence.ts`
- **Files created**: `__tests__/arrival-radius-sync.test.ts`, `memory/FEATURE_MOBILE_ARRIVAL_RADIUS_SYNC.md`

## Iteration 97 — Recurring Jobs: is_active toggle + hard-delete + inactive badge
- **Commit**: bfe012a1fb
- **Date**: 2026-09-14
- **Changes**:
  - Added `is_active` field to RecurringJob type + Active toggle (Switch) in create/edit form.
  - Active toggle disabled when start_date is empty; client-side validation blocks save if is_active=true without start_date.
  - Backend 422 `start_date_required_for_active` surfaced gracefully.
  - Added orange "INACTIVE" badge per row when `is_active === false`.
  - Added per-row Soft Delete button (DELETE /recurring-jobs/{id}).
  - Added per-row Hard Delete button → confirmation modal with destructive copy → DELETE ?hard=true → toast with future_jobs_cancelled count.
  - Renamed testID `recurring-start-date` → `recurring-job-start-date-input` (spec compliance).
  - 19 new Jest tests, 0 regressions.
- **Files modified**: `app/finance/recurring-jobs.tsx`, `__tests__/recurring-jobs-mobile-form.test.tsx`
- **Files created**: `__tests__/recurring-jobs-is-active-hard-delete.test.ts`, `memory/FEATURE_RECURRING_JOBS_MOBILE_PARITY.md`
- **Web files referenced**: `frontend/src/pages/admin/RecurringJobs.jsx`, `memory/FEATURE_RECURRING_JOBS_ACTIVE_AND_DELETE.md`

## Iteration 98 — Technician Check-In Flow (GPS + Photo + Two-Step Submit)
- **Commit**: 5b5df20f6c
- **Date**: 2026-09-14
- **Changes**:
  - Created `app/job/[id]/checkin.tsx` — full Check-In composer screen with GPS capture, multiline note (1–2000 chars), photo picker (1–5 via /api/files/upload with purpose='public_checkin'), upload progress per photo, retry on failure, two-step submission (POST /checkins → POST /checkins/{id}/submit-public).
  - Added "Log Check-In" button on Job Detail (`app/job/[id].tsx`) — green icon+label, gated on canManage.
  - 28 new Jest tests covering submit validation, two-step flow, photo upload failure blocking, testID map, job detail button.
- **Files modified**: `app/job/[id].tsx`
- **Files created**: `app/job/[id]/checkin.tsx`, `__tests__/tech-checkin-mobile.test.ts`, `memory/FEATURE_TECH_CHECKIN_MOBILE.md`
- **Web files referenced**: None (new mobile-only feature paired with backend)

## Iteration 95 — Phase M1: Sitewide Custom Teardrop Map Pin
- **Commit**: e82e90681b362d580f0e638eab4b112c3a4d50ad
- **Date**: 2026-09-15
- **Changes**:
  - Created `TeardropPin.tsx` — SVG teardrop pin with hollow center, 12-color palette, pulse halo
  - Updated `LiveTechPinsMap.tsx` — teardrop pins with per-tech colors + pulse for fresh GPS
  - Updated `DailyRouteMap.native.tsx` — teardrop pins with numbered overlay + status badges
  - Updated `ScheduleMap.native.tsx` — teardrop pins replacing native pinColor markers
- **Files modified**:
  - `/app/mobile/src/components/maps/TeardropPin.tsx` (NEW)
  - `/app/mobile/src/components/dispatch/LiveTechPinsMap.tsx`
  - `/app/mobile/src/components/schedule/DailyRouteMap.native.tsx`
  - `/app/mobile/src/components/schedule/ScheduleMap.native.tsx`
- **Web files referenced**:
  - `/app/frontend/src/pages/dispatch/LiveTechPinsLayer.jsx`

## Iteration 96 — Align mobile colorFromId to canonical palette v1
- **Commit**: (same session as iter 95)
- **Date**: 2026-09-15
- **Changes**:
  - Updated `colorFromId` in `TeardropPin.tsx` to canonical palette v1 (palette order + Java-style hashCode parity with web)
  - Added Jest test file `__tests__/teardrop-pin-parity.test.ts` (12 tests, all pass)
- **Files modified**:
  - `/app/mobile/src/components/maps/TeardropPin.tsx` (palette + hash updated)
  - `/app/mobile/__tests__/teardrop-pin-parity.test.ts` (NEW)
- **Web files referenced**:
  - `/app/memory/tech_color_palette.md` (canonical spec)

## Iteration 97 — Phase T1: Sitewide input theme (white bg + navy text)
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Added `inputColors` constants to `theme.ts` (bg=#FFFFFF, text=#000080, placeholder=rgba(0,0,128,0.55))
  - Created `AppTextInput` wrapper at `src/components/ui/AppTextInput.tsx`
  - Batch-replaced all 247 `<TextInput` → `<AppTextInput` across 154 files
  - Cleaned unused `TextInput` imports from react-native in 5 files
  - Added Jest test `__tests__/app-text-input-theme.test.tsx` (4 tests, all pass)
- **Files modified**:
  - `/app/mobile/src/theme.ts` (inputColors added)
  - `/app/mobile/src/components/ui/AppTextInput.tsx` (NEW)
  - `/app/mobile/__tests__/app-text-input-theme.test.tsx` (NEW)
  - 154 files across `src/` and `app/` (TextInput → AppTextInput)
- **Web files referenced**: None (mobile-only theme change)

## Iteration 98 — Bugfix: Address field missing from leads list + offline banner false positive
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Root cause**: The leads list page (`/leads`) used an inline Sheet form with NO address field. The `NewLeadForm` with `AddressAutocomplete` existed at separate routes (`/leads/new`, `/(app)/new-lead`), but testers always used the `+` button on the leads list which opened the inline form. Additionally, `mapApiError.ts` fallback classified all unknown errors as "You're offline".
- **Changes**:
  - Added `AddressAutocomplete` to inline form in `app/leads/index.tsx` with correct `onChange` prop
  - Fixed `mapApiError.ts` fallback to return "Something went wrong" (kind: "client") instead of "You're offline" (kind: "offline") for non-network errors
  - Fixed prop mismatch: `onSelect`/`onChangeText` → correct `onChange` callback with `sel.formatted`/`sel.latitude`/`sel.longitude`
- **Files modified**:
  - `/app/mobile/app/leads/index.tsx`
  - `/app/mobile/src/utils/mapApiError.ts`
- **Verified**: 3 screenshots on deployed preview confirming Address visible → 5 suggestions → populated + dismissed

## Iteration 99 — Phase C1 + C1.1: Dirty-close guard for checklist
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Added `usePreventRemove` from `@react-navigation/core` to intercept back navigation when dirty
  - Added `attemptClose()` function that checks `dirtyRef.current` before closing
  - Added three-button confirm dialog Modal: Save & close, Discard changes, Keep editing
  - Save & close: flushes save, shows spinner + "Saving…", handles success/failure
  - Discard: clears dirty, navigates back without saving
  - Keep editing: dismisses dialog only
  - Added "×" close button to Header for explicit close path
  - Added `isDirtyForGuard` state synced with `dirtyRef` via interval (for reactive `usePreventRemove`)
  - Fixed mapApiError.ts fallback from "You're offline" to "Something went wrong" (from iteration 98)
  - Added Jest test file with 5 tests (all pass)
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx`
  - `/app/mobile/__tests__/checklist-dirty-close-guard.test.tsx` (NEW)
- **Verified**: Screenshot of dirty-close dialog showing all three buttons on deployed preview

## Iteration 100 — Phase CHEM1: Remove Total Chlorine + relax non-required chemistry
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Removed `total_chlorine` from READING_ALLOWLIST (pool, other), READING_REQUIRED, READING_LABELS, DEFAULT_VALUES, DEFAULT_TESTED_KEYS, RULES, _NAME_TO_CANONICAL, _K60_LABEL_MAP, and REQUIRED_READING_KEYS
  - Updated READING_REQUIRED to enforce Required Four (free_chlorine, ph, alkalinity, cyanuric_acid) on pool, spa, AND other body types
  - Added 8 Jest tests — all pass
- **Files modified**:
  - `/app/mobile/src/lib/waterBodies.ts`
  - `/app/mobile/src/components/checklist/PoolChecklistForm.tsx`
  - `/app/mobile/src/components/checklist/ReadingChipRow.tsx`
  - `/app/mobile/src/lib/expandChemistryLabel.ts`
  - `/app/mobile/app/(app)/service-report/[id].tsx`
  - `/app/mobile/__tests__/chem1-required-four.test.ts` (NEW)
- **Before grep count**: 30 occurrences of total_chlorine/Total Chlorine
- **After grep count**: 0 (outside tests)

## Iteration 101 — Phase CHEM1.1: READING_REQUIRED only enforces on pool bodies
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Set spa, water_feature, fountain, other to `[]` in READING_REQUIRED (only pool keeps Required Four)
  - Updated tests: 13 tests (added spa/other/water_feature/fountain empty assertions + blank spa/other validation tests)
- **Files modified**:
  - `/app/mobile/src/lib/waterBodies.ts`
  - `/app/mobile/__tests__/chem1-required-four.test.ts`

## Iteration 102 — Phase CHEM2: Cyanuric alias dedupe on WaterBodyPanel
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - WaterBodyPanel read path: `readingsByKey` resolves `cyanuric` → `cyanuric_acid` via LEGACY_ALIAS; canonical key wins if both exist
  - WaterBodyPanel write path: `setReading` strips legacy `cyanuric` entries when writing `cyanuric_acid`
  - Added 7 Jest tests covering all 5 alias scenarios + write-path verification
- **Files modified**:
  - `/app/mobile/src/components/checklist/WaterBodyPanel.tsx`
  - `/app/mobile/__tests__/chem2-cyanuric-alias.test.ts` (NEW)

## Iteration 103 — Phase CHEM3: Reuse ChemicalDropdownStack inside WaterBodyPanel
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Replaced legacy CHEMICALS USED section in WaterBodyPanel with ChemicalDropdownStack
  - Added bodyType prop to ChemicalDropdownStack that filters catalog via CHEMICAL_ALLOWLIST
  - Read adapter: maps body.chemicals_used[*].product_slug → slug for the stack
  - Write adapter: maps stack slug → product_slug for persistence
  - Removed legacy chemical helpers (addChemical, updateChemical, removeChemical, allowedChemicals)
  - Removed unused styles (chemRow, chemInput, chemUnit, etc.)
  - Fixed missing useMemo import in ChemicalDropdownStack
  - Added 6 Jest tests (all pass) + all 26 chem tests green
- **Files modified**:
  - `/app/mobile/src/components/checklist/WaterBodyPanel.tsx`
  - `/app/mobile/src/components/checklist/ChemicalDropdownStack.tsx`
  - `/app/mobile/__tests__/chem3-chemical-dropdown-adapter.test.ts` (NEW)

## Iteration 104 — Phase CHEM4: isPrimary body suppression + additional-body header labels
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - WaterBodyPanel: Added `isPrimary` prop; gated Chemistry Readings + Chemicals sections behind `!isPrimary`
  - WaterBodyManager: Passes `isPrimary={idx === 0}` to body 0
  - Additional-body header: "ADDITIONAL BODY OF WATER CHEMICALS" + sub-header with body type label
  - Added `subHeader` style
  - 6 Jest tests, all pass; 32 total across chem suites
- **Files modified**:
  - `/app/mobile/src/components/checklist/WaterBodyPanel.tsx`
  - `/app/mobile/src/components/checklist/WaterBodyManager.tsx`
  - `/app/mobile/__tests__/chem4-isprimary-suppression.test.tsx` (NEW)

## Iteration 105 — Phase M2: Safe-area inset on Checklist screen footer
- **Commit**: (same session)
- **Date**: 2026-09-15
- **Changes**:
  - Imported `useSafeAreaInsets` from `react-native-safe-area-context`
  - Footer: `paddingBottom: insets.bottom + spacing.md` (mirrors check-in screen pattern)
  - ScrollView: `paddingBottom: 160 + insets.bottom` so last item scrolls above footer
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx`


## Iteration 96 — Phase CHEM5: Unify all water-body forms + remove duplicate
- **Commit**: 428713647
- **Date**: 2026-09-15
- **Changes**:
  - WaterBodyPanel: `!isPrimary` gates already removed (prior step); both Chemistry Readings + Chemicals render on all bodies
  - PoolChecklistForm: Removed standalone "Chemicals Added" block (section title, ChemicalDropdownStack, quick-add button, ChemicalPickerSheet)
  - Cleaned up orphaned imports (ChemicalPickerSheet) and state (pickerOpen)
  - Test file: Flipped assertions so isPrimary=true body now expects BOTH sections rendered; header = "Pool"
  - 6/6 Jest tests pass; testID-based screenshot verification confirms removal
- **Files modified**:
  - `/app/mobile/src/components/checklist/PoolChecklistForm.tsx`
  - `/app/mobile/__tests__/chem4-isprimary-suppression.test.tsx`
- **Web files referenced**: None (continuation of prior CHEM5 work)


## Iteration 97 — Phase M3: Relabel + relocate Internal Photos / Internal Videos
- **Commit**: 525a1bbcd
- **Date**: 2026-09-15
- **Changes**:
  - Reordered checklist sections: Visit Media → Internal Photos → Internal Videos → Template Form
  - Relabeled "Photos" card title → "Internal Photos"
  - Added "Internal Videos" `<Text>` title wrapping `VideoMediaUploader` (component itself untouched)
  - All props, state bindings, and handlers preserved — zero functional changes
  - 5 Jest source-structure tests pass (title assertions + ordering assertions)
  - Screenshot verification: all 3 cards present in correct order, titles correct
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx`
  - `/app/mobile/__tests__/m3-internal-media-relabel.test.tsx` (NEW)
- **Web files referenced**: None
- **VideoMediaUploader.tsx**: Confirmed untouched (empty git diff)


## Iteration 98 — Phase S1: Schedule per-tech filter + tech default to "My jobs only"
- **Commit**: ac688faed
- **Date**: 2026-09-15
- **Changes**:
  - Added `techFilter` state with AsyncStorage persistence (key: `schedule.tech_filter.{userId}`)
  - Tech role: defaults to own user ID (backend already scopes by `technician_id`); dropdown hidden
  - Admin/Manager/Owner: defaults to "All techs"; dropdown visible below Calendar/Grid toggle
  - Filter logic: `"all"` → all jobs; specific tech → that tech's jobs + unassigned
  - Downstream memos (`dayJobs`, `weekCounts`, `jobsByDay`) all use `filteredJobs`
  - Header subtitle shows filtered job count
  - Tech picker modal: "All techs" + alphabetically sorted tech entries, checkmark on active
  - 8 Jest source-structure tests pass
  - Screenshot: admin sees "All techs" dropdown, picker modal opens with options
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx`
  - `/app/mobile/__tests__/s1-schedule-tech-filter.test.tsx` (NEW)
- **Web files referenced**: None (parallel web work by e1_dev)

## Iteration 99 — Phase M4: Relocate Internal media to bottom + restyle PhotoUploader
- **Commit**: 49381ede6
- **Date**: 2026-09-15
- **Changes**:
  - Relocated Internal Photos + Internal Videos to very bottom of ScrollView content (after template form, before footer)
  - Restyled PhotoUploader buttons: Camera→"Photo", kept "Library"; horizontal pill row matching Visit Media's `uploadBtn` pattern (dashed border, brand-colored icons, semibold text, 1.5px border)
  - Added internal-only binding comments: `// Internal-only — bound to job.photos / job.videos, never surfaced to customer portal.`
  - Updated M3 test file → M4 assertions: 9 tests covering new bottom position, label restyle, style matching
  - Safe-area padding verified: `paddingBottom: 160 + insets.bottom` covers the new bottom blocks
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx` — block relocation + binding comments
  - `/app/mobile/src/components/checklist/PhotoUploader.tsx` — button restyle
  - `/app/mobile/__tests__/m3-internal-media-relabel.test.tsx` — updated to M4 assertions
- **VideoMediaUploader.tsx**: Confirmed untouched (empty git diff)


## Iteration 100 — Phase M5: Remove VisitRecapModal after job close
- **Commit**: 7930b0133
- **Date**: 2026-09-16
- **Changes**:
  - Removed `<VisitRecapModal>` render + import from checklist.tsx
  - Removed `recapOpen` and `recapCustomer` state hooks
  - Updated `doCloseJob` success branch: clears dirty guard → shows Alert("Job closed") → navigates to schedule
  - Removed `readCachedCustomer` + `writeThroughCustomer` orphaned imports (from recap customer-fetch)
  - Updated `usePreventRemove` guard: removed `!recapOpen` bypass, using dirty-state reset instead
  - Shared VisitRecapModal.tsx file untouched (confirmed empty git diff)
  - 8 Jest tests pass (m5-remove-recap-modal.test.tsx)
  - Pre-existing k61 test failure confirmed (K61.a.2 comment missing before M5 changes)
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx`
  - `/app/mobile/__tests__/m5-remove-recap-modal.test.tsx` (NEW)
- **Files NOT modified**:
  - `/app/mobile/src/components/checklist/VisitRecapModal.tsx` (shared file preserved)


## Iteration 101 — Phase MI1.1-mobile: Multi-industry checklist dispatcher parity
- **Commit**: e4e2ca140
- **Date**: 2026-09-16
- **Changes**:
  - Created `mobile/src/lib/deriveIndustry.ts` — client-side industry deriver with keyword-ordered resolution (solar>clean) matching backend + web
  - Created `mobile/src/components/checklist/IndustryChecklistForm.tsx` — RN renderer (fetches template, checkbox rows, required asterisks, notes)
  - Updated `mobile/app/job/[id]/checklist.tsx` — generic branch now routes through deriveIndustryForJob → IndustryChecklistForm for 5 new industries, handyman fallback with [MI1.1-mobile] console.warn
  - Pool and Landscaping branches: BYTE-IDENTICAL (not in diff)
  - 19 Jest tests pass (mi1-industry-dispatcher.test.ts)
- **Files created**:
  - `/app/mobile/src/lib/deriveIndustry.ts` (66 lines)
  - `/app/mobile/src/components/checklist/IndustryChecklistForm.tsx` (188 lines)
  - `/app/mobile/__tests__/mi1-industry-dispatcher.test.ts` (136 lines)
- **Files modified**:
  - `/app/mobile/app/job/[id]/checklist.tsx` (generic branch replaced, +2 imports, net -4 lines)


## Iteration 102 — Phase SRL: Sequential routing navigation lock
- **Commit**: 14be95e06
- **Date**: 2026-09-17
- **Changes**:
  - Created `mobile/src/lib/sequentialRouteLock.ts` — `isJobLockedByRoute()` helper with terminal status set (completed, canceled, cancelled, skipped, could_not_service)
  - GridView: `lockedIds` useMemo computes lock set per day's route order; passed to JobRow as `routeLocked` prop
  - JobRow: routeLocked → lock icon badge (Ionicons lock-closed), 55% opacity, Alert.alert("Route lock", ...) on tap
  - CalendarView: accepts `isAdmin` prop, sorts dayJ by route_index before lock computation, shows lock icon + opacity on locked event cards
  - Admin bypass: `isAdmin` → empty lockedIds set; CalendarView gates on `!isAdmin`
  - 22 Jest tests pass (12 helper, 10 schedule render)
  - Prior schedule tests still green (s1 tech filter: 8/8)
  - Inventory: route ordering = `route_index ?? route_order ?? 999` (server-provided); `skipped` status EXISTS; no emergency/urgent flag; entry point = `onOpenJob → router.push('/job/{id}/checklist')`
  - Follow-up: server-side enforcement (403 from GET /api/jobs/{id}/checklist if prior stop not terminal)
- **Files created**:
  - `/app/mobile/src/lib/sequentialRouteLock.ts` (48 lines)
  - `/app/mobile/__tests__/phase-sequential-route-lock-helper.test.ts` (93 lines)
  - `/app/mobile/__tests__/phase-sequential-route-lock-schedule-render.test.tsx` (86 lines)
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (import, GridView lockedIds, JobRow lock UI, CalendarView lock UI, gStyles)


## Iteration 103 — Bugfix: Schedule tech filter uses wrong ID
- **Commit**: 07b976b50
- **Date**: 2026-09-17
- **Changes**:
  - Switched allTechs data source from `GET /api/users?role=tech` → `GET /api/technicians` (returns technician record IDs that match `job.technician_id`)
  - Fixed tech self-scope default from `user?.id` → `user?.technician_id`
  - Added `user?.technician_id` to useEffect dependency array
  - Updated S1 test assertion to match new `technician_id` pattern
  - 7 new test assertions in `phase-schedule-tech-filter-technician-id.test.tsx`
  - All 37 schedule-related tests pass (S1: 8, SRL helper: 12, SRL render: 10, new fix: 7)
- **Root cause**: `job.technician_id` stores technician record IDs from `/api/technicians`, but the picker was using user account IDs from `/api/users?role=tech`. These are different entities.
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx`
  - `/app/mobile/__tests__/s1-schedule-tech-filter.test.tsx` (updated assertion)
  - `/app/mobile/__tests__/phase-schedule-tech-filter-technician-id.test.tsx` (NEW)



## Iteration 104 — P37c: GPS Job Timer wire-up (3 sub-tasks)
- **Commit**: 7b3f7248b
- **Date**: 2026-09-17
- **Changes**:
  - Sub-task 1: Mounted `<GpsConsentModal />` in `calendar.tsx` for technician-role users (gated by `isTech`). Component self-checks consent via `GET /tech-gps-consent/me` and auto-shows if not active.
  - Sub-task 2: Added `syncJobGeofencesP37c()` call in `_layout.tsx` boot useEffect — fire-and-forget inside try/catch, never blocks boot.
  - Sub-task 3: Added `POST /api/jobs/{id}/arrive` with `{ lat, lng, source: "manual" }` inside `OnMyWayButton.tsx` `send()` — fires alongside SMS, silently handles `already_arrived`/`already_running`, failure is swallowed.
  - 28 new Jest tests across 3 test files (6 + 15 + 7), all passing.
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (+1 import, +2 JSX lines: GpsConsentModal mount)
  - `/app/mobile/app/_layout.tsx` (+1 import, +2 lines: syncJobGeofencesP37c call in boot)
  - `/app/mobile/src/components/schedule/OnMyWayButton.tsx` (+10 lines: arrive POST block)
- **Files created**:
  - `/app/mobile/__tests__/phase-gps-consent-modal-mount.test.tsx` (136 lines)
  - `/app/mobile/__tests__/phase-syncjobgeofences-startup.test.tsx` (243 lines)
  - `/app/mobile/__tests__/phase-mobile-arrival-endpoint.test.tsx` (183 lines)
- **Web files referenced**:
  - `/app/frontend/src/pages/jobs/JobDetail.jsx` (line 107: `onArrive` pattern)


## Iteration 105 — Phase M1 finish: TeardropPin consumers + ColorPicker integration + tests
- **Commit**: 396b7b7be
- **Date**: 2026-09-17
- **Changes**:
  - LiveTechPinsMap.tsx: migrated from `<Text>` children to `label={initials}` prop. Removed unused `pinText` style.
  - Technician detail page (`app/technician/[id].tsx`): Full rewrite. Admin-only crew-color editor section using `<ColorPicker />`. PATCH `/api/users/{user_id}` with `{display_color_hex}`. Handles server 400 `color_contrast_too_low`. Fire-and-forget `POST /api/users/me/recent-colors`.
  - DailyRouteMap.native.tsx: cleaned up unused `pinNumber` style.
  - 3 test suites, 27 tests total (8 + 12 + 7), all passing.
- **Files created**:
  - `/app/mobile/__tests__/colorContrast.test.ts` (8 tests)
  - `/app/mobile/__tests__/TeardropPin.test.tsx` (12 tests)
  - `/app/mobile/__tests__/ColorPicker.test.tsx` (7 tests)
- **Files modified**:
  - `/app/mobile/src/components/dispatch/LiveTechPinsMap.tsx` (children→label, removed pinText style)
  - `/app/mobile/app/technician/[id].tsx` (full rewrite with ColorPicker section)
  - `/app/mobile/src/components/schedule/DailyRouteMap.native.tsx` (removed unused pinNumber style)
- **Dependencies added**:
  - `@react-native-community/slider` (pure-JS, no native module — used for HSL hue picker in ColorPicker)
- **Web files referenced**:
  - `frontend/src/components/ui/ColorPicker.jsx`
  - `frontend/src/components/maps/TeardropPin.jsx`
  - `frontend/src/lib/colorContrast.js`
  - `frontend/src/pages/ops/OpsHub.jsx` (crew color editor pattern)


## Iteration 106 — Bug fix: schedule tech filter techScope uses wrong ID
- **Commit**: ef0bb8dba
- **Date**: 2026-09-17
- **Changes**:
  - Fixed `calendar.tsx` line 408: `techScope` query parameter was using `user?.id` (user account ID) instead of `user?.technician_id` (technicians collection ID). Jobs store the technician ID in their `technician_id` field, so the user-account ID would never match, causing techs to see an empty schedule when the backend scoped by the wrong ID.
  - Added test assertion to `phase-schedule-tech-filter-technician-id.test.tsx` verifying the `techScope` line uses `user?.technician_id`.
- **Root cause**: Line 408 in calendar.tsx constructed the API query string `&technician_id=${user.id}` — but `user.id` is the users-collection ID, while `j.technician_id` on jobs stores the technicians-collection ID. These are different ID spaces.
- **Web predicate mirrored**: Web `CalendarSchedule.jsx` line 486: `if (_isTech) return user?.technician_id || ""` — the web always uses `user.technician_id`, never `user.id`, for tech scoping.
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (1 line changed: `user?.id` → `user?.technician_id`)
  - `/app/mobile/__tests__/phase-schedule-tech-filter-technician-id.test.tsx` (1 new test case added)


## Iteration 107 — Mirror web jobCategory classifier update
- **Commit**: 165b0c13e
- **Date**: 2026-09-18
- **Changes**:
  - Widened `_SERVICES_RX`: `landscape` → `landscap` stem + added `inspection|weekly|monthly` keywords
  - Added completed-job fallback (rule #4): unmatched completed jobs → `"service"`, non-completed stay `null`
  - Updated header docstring to match web's 5-rule block verbatim
  - 7 new Jest tests, all passing
- **Files modified**:
  - `/app/mobile/lib/jobCategory.ts` (3 changes: regex, fallback, docstring)
- **Files created**:
  - `/app/mobile/__tests__/jobCategory.test.ts` (7 tests)
- **Web files referenced**:
  - `/app/frontend/src/lib/jobCategory.js` (authoritative source of truth)


## Iteration 108 — Clickable Customer Data: PhoneLink + AddressLink + CustomerLink
- **Commit**: 8838452e7
- **Date**: 2026-09-19
- **Changes**:
  - Created 3 shared primitives in `/app/mobile/src/components/customer/`:
    - `PhoneLink.tsx` — normalizes to tel:+1XXXXXXXXXX, opens device dialer, plain text fallback for empty
    - `AddressLink.tsx` — iOS maps://, Android geo:, Web Google Maps HTTPS, AddressObject support
    - `CustomerLink.tsx` — navigates to /customer/{id} via expo-router, plain text fallback
    - `index.ts` — barrel export
  - Updated 6 callsites:
    1. `app/(app)/customers.tsx` — row subtitle: address → AddressLink, phone → PhoneLink
    2. `app/leads/index.tsx` — row subtitle: phone → PhoneLink
    3. `app/leads/[id].tsx` — contact card: phone → PhoneLink, address → AddressLink
    4. `app/job/[id].tsx` — hero: customer name → CustomerLink, address row → AddressLink, property address → AddressLink
    5. `app/(app)/schedule/calendar.tsx` — job card: address → AddressLink
    6. `app/customer/[id].tsx` — contact card: phone → PhoneLink, address → AddressLink, billing → AddressLink
  - Skipped callsites (justified): checklist hero (compact combined text), landscape picker (row tap conflict), admin debug screens
  - 18 Jest tests, all passing
- **Files created**:
  - `/app/mobile/src/components/customer/PhoneLink.tsx`
  - `/app/mobile/src/components/customer/AddressLink.tsx`
  - `/app/mobile/src/components/customer/CustomerLink.tsx`
  - `/app/mobile/src/components/customer/index.ts`
  - `/app/mobile/__tests__/clickable-customer-data.test.tsx` (18 tests)
- **Files modified**:
  - `app/(app)/customers.tsx`, `app/leads/index.tsx`, `app/leads/[id].tsx`
  - `app/job/[id].tsx`, `app/(app)/schedule/calendar.tsx`, `app/customer/[id].tsx`
- **New dependencies**: None


## Iteration 109 — K43: resolveTechnicianId fallback via /api/technicians/me
- **Commit**: c41487a85
- **Date**: 2026-09-19
- **Changes**:
  - Created `lib/technicianResolver.ts`: `resolveTechnicianId(user)` — fast-path when `user.technician_id` is truthy, slow-path via `GET /api/technicians/me`, module-level cache by user.id, 404 → null (not in roster), non-404 errors not cached (allow retry).
  - `calendar.tsx`: replaced all `user?.technician_id` direct reads with `resolvedTechId` state + useEffect resolver. `techScope` and `techFilter` default now use resolved value. Added empty-profile banner: "Your technician profile is not linked yet — contact your admin to get set up."
  - `checklist.tsx`: replaced `user.technician_id` ownership check with `myTechId` state + useEffect resolver.
  - `auth.tsx`: added `clearTechnicianIdCache()` call on logout.
  - 9 Jest tests, all passing.
- **Files created**:
  - `/app/mobile/lib/technicianResolver.ts`
  - `/app/mobile/__tests__/technicianResolver.test.ts` (9 tests)
- **Files modified**:
  - `/app/mobile/app/(app)/schedule/calendar.tsx` (resolver state, techScope, filter default, empty-profile banner + styles)
  - `/app/mobile/app/job/[id]/checklist.tsx` (ownership check uses resolved ID)
  - `/app/mobile/src/auth.tsx` (cache clear on logout)
- **Callsites migrated to resolveTechnicianId**:
  - `calendar.tsx` line 412: techScope query param
  - `calendar.tsx` line 321/324: techFilter default
  - `checklist.tsx` line 893: canEditServiceType ownership check
  - `auth.tsx` logout: cache invalidation


## Iteration 110 — A5: Smart Brief Card on job detail
- **Commit**: 7c9b1a883
- **Date**: 2026-09-20
- **Changes**:
  - Created `src/components/job/SmartBriefCard.tsx`: Fetches `GET /api/jobs/{id}/smart-brief`, renders customer header (name + PhoneLink + AddressLink), special access chips (gate code, key, dog 🐕), last 3 visits (accordion with chemistry + notes), intelligence alerts (top 3, severity dot). Loading skeleton, error banner with retry, 403/404 gracefully hides card.
  - Wired into `app/job/[id].tsx` at the top of the body (above property card, below hero).
  - 11 Jest tests, all passing.
- **Files created**:
  - `/app/mobile/src/components/job/SmartBriefCard.tsx` (295 lines)
  - `/app/mobile/__tests__/SmartBriefCard.test.tsx` (11 tests)
- **Files modified**:
  - `/app/mobile/app/job/[id].tsx` (+2 lines: import + render)
- **API contract consumed**:
  - `GET /api/jobs/{job_id}/smart-brief` — all documented fields consumed: customer, special_access, last_visits (chemistry_snapshot + notes), open_intelligence_alerts
  - 403 (`insufficient_role_for_brief`) → hidden
  - 404 (`job_not_found`) → hidden
- **Screenshot verified**: Job detail as mike@aquaterra.com shows customer header, recent visits with dates, accordion chevrons. Card renders above existing job body.



## Iteration 111 — E3: Mobile Bottom Navigation (5-Tab Persistent Bar)
- **Commit**: e0f69addaf6a5938542beb637165f58398b70f5a
- **Date**: 2026-09-20
- **Changes**:
  - Unhid the bottom tab bar (removed `display: "none"` from `tabBarStyle`)
  - Configured 5 persistent visible tabs in order: Schedule, Customers, Messages, Jobs/Pipeline, More/Profile
  - Role-gated slot 4: Techs see "Jobs" (`jobs` screen), Admins see "Pipeline" (`quotes` screen)
  - Role-gated slot 5 label: Techs see "Profile", Admins see "More"
  - Registered ALL 70 route files as `<Tabs.Screen>` — previously only 47 were registered, causing auto-generated phantom tabs
  - Fixed `name="assets"` → `name="assets/index"` to prevent extra tab leakage from directory-based routes
  - Fixed `name="onboarding"` (dead registration for non-existent file) → `name="onboarding/mine"` (actual file)
  - Added 22 previously-unregistered route files with `href: null` (before-after, chat, cfo/index, checks/register, directories, dunning/queue, handbook/*, inventory/*, landscape-time-clock, onboarding-checklist/index, profile, property-lookup, schedule/JobTrackerTiles, service-report/[id], settings/offline-diagnostics, tests/*, instaquote, instaschedule, assets/[id])
  - Added `tabBarTestID` to all 5 visible tabs: tab-schedule, tab-customers, tab-messages, tab-jobs/tab-pipeline, tab-more
  - Added `tabBarHideOnKeyboard: true` for better UX when keyboard is open
  - Added subtle shadow/elevation to tab bar for depth
  - Moved AI Dock FAB above the tab bar (dynamic `TAB_BAR_HEIGHT` constant)
  - GlobalMenu hamburger preserved — no changes to overflow navigation
- **Files modified**:
  - `/app/mobile/app/(app)/_layout.tsx` (full restructure: 329→208 lines, all tabs reordered + 22 new registrations)
- **Admin tab bar**: Schedule | Customers | Messages | Pipeline | More
- **Tech tab bar**: Schedule | Customers | Messages | Jobs | Profile
- **Screenshot verified**: Both admin (admin@aquaterra.com) and tech (mike@aquaterra.com) show correct 5-tab bars. Navigation to Schedule, Customers, Messages, Jobs tabs all confirmed working.


## Iteration 112 — G2: Messages Tab Unread Badge
- **Commit**: 3b3c771756b4baaf17a68d2e2452e4ab5ec4ced2
- **Date**: 2026-09-20
- **Changes**:
  - Created `src/hooks/useUnreadCount.ts`: fetches `GET /api/messages/unread-count` on mount, every 60s, and on AppState "active" (foreground resume). Returns formatted badge: undefined (0), numeric (1-99), or "99+" (>99). Auth errors silently swallowed.
  - Wired into `app/(app)/_layout.tsx`: Messages tab now shows `tabBarBadge: unreadBadge` + red badge style.
  - 8 Jest tests covering: numeric badge, "99+" cap, 0 hides badge, fetch failure no-crash, 60s poll, foreground refetch, cleanup on unmount, disabled state.
- **Files created**:
  - `/app/mobile/src/hooks/useUnreadCount.ts` (73 lines)
  - `/app/mobile/__tests__/useUnreadCount.test.ts` (8 tests, all passing)
- **Files modified**:
  - `/app/mobile/app/(app)/_layout.tsx` (+3 lines: import, hook call, tabBarBadge/tabBarBadgeStyle)
- **API contract consumed**: `GET /api/messages/unread-count` → `{ unread_count: N, by_channel: {...} }`
- **Screenshot verified**: mike@aquaterra.com shows red "2" badge on Messages tab; admin@aquaterra.com shows no badge (0 unread).


## Iteration 113 — D1: EAS Deployment Blocker — Corrupt Filename Cleanup
- **Commit**: e479751427223fd1fc8e3f16bfff427a07996f2d
- **Date**: 2026-09-21
- **Changes**:
  - Removed 1 corrupt zero-byte file at inode 142350 (raw bytes: `01 90 f8 40 40 d0 c3 39 40 38`) from `/app/mobile/` root
  - Created `/app/mobile/.easignore` with D1 hygiene entries to prevent future garbled/binary droppings from being packed into EAS tarballs
  - Corrupt file count: 1 → 0
- **Files created**: `/app/mobile/.easignore`
- **Files deleted**: 1 corrupt-named zero-byte file (inode 142350)
- **Files NOT touched**: package.json, eas.json, app.json, src/*, heresdk/*, backend/*, frontend/*


## Iteration 114 — P9-C: Technician Visibility Jail (Mobile)
- **Commit**: 5b132a1ee481841c48509ea48d13d0ac54e1da9e
- **Date**: 2026-09-21
- **Changes**:
  ### A) UI — Defense-in-depth guards
  - `calendar.tsx`: "All techs" option in picker modal wrapped in `{!isTech && (...)}` (was already unreachable since trigger button was hidden, now also guarded inside modal)
  - `calendar.tsx`: `techFilter` initial state for techs now defaults to `user.technician_id` instead of `"all"` (eliminates brief "all" window)
  - `calendar.tsx`: `filteredJobs` fail-closed guard: if `isTech && techFilter === "all"`, scopes to `resolvedTechId` instead of showing all
  - `CrewFilterBar.tsx`: Added `hideAllOption` prop; "All crews" row wrapped in `{!hideAllOption && (...)}`; passed from calendar
  ### B) Offline cache — belt-and-suspenders filter
  - `apiCache.ts`: `writeThroughJobs` gains optional `TechScope` param; when tech, filters jobs to `technician_id === self || !technician_id`; null tech_id → empty list (fail closed)
  - `routeHydrator.ts`: `hydrateToday` gains optional `HydrationTechScope`; filters job list before caching
  - `offlineStore.ts`: `downloadBundle` gains optional `BundleTechScope`; filters `data.jobs` before storing
  - `SyncManager.tsx`: now imports `useAuth`, computes `techScope`, passes to `downloadBundle`
  - `useRouteHydration.ts`: computes `techScope`, passes to `hydrateToday`
  - `calendar.tsx`: passes `isTech` scope to `writeThroughJobs` in load() callback
  - `offline-diagnostics.tsx`: passes tech scope to `hydrateToday` call
  ### C) One-shot purge migration
  - NEW: `src/lib/offline/p9cPurge.ts`: on first boot after deploy, iterates SQLite cached jobs for tech user, deletes any where `job.technician_id !== user.technician_id`; guards with `p9c_purged_v1` AsyncStorage flag
  - Wired in `useRouteHydration.ts` → runs on mount for tech users
- **Files created**:
  - `src/lib/offline/p9cPurge.ts`
  - `__tests__/p9cVisibilityJail.test.tsx` (10 tests, all passing)
- **Files modified**:
  - `app/(app)/schedule/calendar.tsx`
  - `src/components/schedule/CrewFilterBar.tsx`
  - `src/lib/offline/apiCache.ts`
  - `src/services/routeHydrator.ts`
  - `src/services/offlineStore.ts`
  - `src/services/SyncManager.tsx`
  - `src/hooks/useRouteHydration.ts`
  - `app/(app)/settings/offline-diagnostics.tsx`


## Iteration — Income by Category UUID Label Fix
- **Commit**: c043b131a133555794c182e82c2d3b06ab7e1125
- **Date**: 2026-09-23
- **Changes**:
  - Fixed Income by Category screen displaying raw UUIDs instead of human-readable labels
  - Changed render from `r.category` to `r.label || r.category` (fallback-safe)
  - Added `numberOfLines={1}` + `ellipsizeMode="tail"` to the category label Text
  - Added `numberOfLines={1}` to the amount Text to prevent wrapping
  - Added `flex: 1` to `rowCat` style so long labels truncate with ellipsis
  - Added `flexShrink: 0` + `marginRight` to `rowAmt` style so dollar amounts never compress
  - Updated React `key` to use `r.category_id || r.category` (stable key)
- **Files modified**: `app/income-by-category.tsx`
- **Web files referenced**: N/A (backend contract change only)
- **Verified**: Screenshot confirms labels show "Service Revenue (Demo)" and "Pool" (not UUIDs), amounts right-aligned on one line. Lint clean.

## Iteration — Task L · Photo visibility merge (SR + job.photos)
- **Commit**: a785a1ba89f1206128abe8947fe0fc63e36f6fce
- **Date**: 2026-09-24
- **Changes**:
  - Recreated `src/lib/absolutizeUrl.ts` (lost by intervening git stash)
  - Added parallel fire-and-forget `GET /jobs/{id}/detail` fetch in job detail `load()` to extract `service_report_photos`
  - Added `srPhotos` state + `allPhotos` useMemo that merges SR photos + job.photos (backend pre-deduplicates)
  - Each SR photo tagged with `_source: "service_report"` for conditional delete button + "SR" badge
  - PhotoCarousel.tsx updated: `source={{ uri: absolutizeUrl(p.url || p.data) }}` — handles both cloud URLs and base64 data URIs
  - Service images strip updated: uses `allPhotos` with `absolutizeUrl()`, SR photos show "SR" badge, delete restricted to job-source photos only
  - Display count header uses `displayPhotoCount` (all photos + pending), upload cap still based on `job.photos` only
  - Re-applied Task I fix to `before-after.tsx` (absolutizeUrl for generated_card_url, also stash-reverted)
- **Files added**: `src/lib/absolutizeUrl.ts` (recreated)
- **Files modified**: `app/job/[id].tsx`, `src/components/job/PhotoCarousel.tsx`, `app/(app)/before-after.tsx`
- **Verified**: App compiles + renders job detail with photo section showing "PHOTOS 0/10" for jobs with no photos. Metro bundle clean. No console errors.
- **Note**: `business.tsx` still has local `toAbsolute()` — dedup to shared helper is a low-priority follow-up (not breaking).


## Iteration — Schedule Card Redesign (NavigateJobButton removal, name+address map triggers)
- **Commit**: 6dcfc769bc0995f1799808f19fcc5094abc7c4e5
- **Date**: 2026-09-25
- **Changes**:
  - Extracted `resolveJobCoords()` into `src/utils/nativeNav.ts` (shared helper, canonical + legacy coord resolution)
  - Removed `NavigateJobButton` import + JSX usage from `calendar.tsx` (component file preserved)
  - Moved address block from after JobNotesCallout to immediately below customer name
  - Enlarged `gStyles.addr` from `fontSize.xs` → `fontSize.base`
  - Wrapped customer name in `<Pressable>` with `openNativeNavTo` + address-string fallback
  - Wrapped address in `<Pressable>` with same directional behavior
  - Both have `hitSlop`, `accessibilityLabel`, and unique testIDs (`job-card-name-nav-{id}`, `job-card-addr-nav-{id}`)
  - Added `Linking` import for address-string fallback
  - Added test: `__tests__/calendar-schedule-card-directions.test.tsx` (13/13 pass)
- **Files modified**: `app/(app)/schedule/calendar.tsx`, `src/utils/nativeNav.ts`
- **Files added**: `__tests__/calendar-schedule-card-directions.test.tsx`
- **Verified**: Screenshot confirms: (a) no NavigateJobButton, (b) address beneath name, (c) enlarged font, (d) 4 name-nav + 3 addr-nav pressables detected. Metro clean. Jest 13/13.

<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes

## Iteration 115 — Phase 25: mobile parity for web Phases 20 / 22 / 23 / 24
- **Commits**:
  - F2 `886f1c2b71f27ca190421edb687700828baacb35` — customer profile skeleton (CustomerProfileSkeleton.tsx + [id].tsx wiring + test)
  - F3+F4 `e873da16079cfe8ab4957d233a11baa894c8551b` — portal home: 3 sections on stat-tile chassis + accents; Past Due/Credit dynamic bgs + white text; Quick Action press glow
- **F1 (Phase 20 action row)**: FLAGGED no-op — mobile has no unified action row (Edit = header icon, Delete = inline admin button, Send/Create = FAB, Call = PhoneLink) and no tabs row.
- **Tests**: shard-run full suite 43 failed suites / 49 failed tests = identical to HEAD baseline (set-diff empty both ways).
- **BLOCKER (not mine, not touched)**: commit 6911174d9 (cron) landed unresolved stash conflict markers in `mobile/app/(app)/schedule/calendar.tsx` (~L1578+) and in this file just above → Metro 500s the whole bundle. Needs a manual resolution pass.

## Iteration 116 — Templates Library Phase 3 (Mobile) re-verification
- **Commit**: 77affb86c (feature) · verified at HEAD 2f65a39a6
- **Date**: 2026-10-11
- **Changes**: none to code — audit + E2E verification (Jest 45/45, curl contract, Expo-web offline/reconnect/finalize/PDF)
- **Files modified**: memory only (PRD.md, mobile/iteration_116.md, mobile/commit_log.md)
- **Web files referenced**: frontend/src/api/templates.js

## Iteration 117 — Phase 39B: mobile dashboard widget parity (7 widgets)
- **Commit**: 56864ac19
- **Date**: 2026-10-11
- **Changes**: MassMessagingCard (admin/super_admin → /marketing/broadcasts), DashboardActionCards (manager+, GET /dashboard/action-cards, 60s poll), SoshiePublishingTile, BulkOpsAuditTile (/dashboard fields), CrewProductivityTile (range tabs + table), RoutingCostTile (7/30/90d chips), WarrantiesExpiringTile — last 5 gated super_admin/admin/owner. Mounted in web section order.
- **Files modified**: app/(app)/index.tsx; added src/components/dashboard/{MassMessagingCard,DashboardActionCards,BulkOpsAuditTile,RoutingCostTile,WarrantiesExpiringTile,SoshiePublishingTile,CrewProductivityTile}.tsx, __tests__/phase39b-mobile-dashboard-widgets.test.tsx
- **Web files referenced**: pages/admin/Dashboard.jsx, components/mass-messaging/MassMessagingCard.jsx, components/dashboard/DashboardActionCards.jsx, components/admin/{BulkOps,RoutingCost,WarrantiesExpiring,SoshiePublishing,CrewProductivity}Tile.jsx

## Iteration 118 — Phase 39C: Team CPO Readiness + Recommendations Queue (write actions)
- **Commit**: see `git log --grep "phase 39C"`
- **Date**: 2026-10-11
- **Changes**: TeamCpoReadinessWidget (3 parallel GETs, bulk POST /training/nudge-non-starters, optimistic "Nudged" + rollback + toast); RecommendationsQueueWidget (GET ?older_than_days=7, POST /{id}/send + /{id}/discard w/ confirm, optimistic remove + index-preserving rollback + toast, silent reload). Mounted after Payments, before Revenue by Service, gated admin/super_admin (backend-effective; web mounts ungated).
- **Files modified**: app/(app)/index.tsx; added src/components/dashboard/{TeamCpoReadinessWidget,RecommendationsQueueWidget}.tsx, __tests__/phase39c-mobile-dashboard-write-actions.test.tsx
- **Web files referenced**: components/admin/TeamCpoReadinessWidget.jsx, components/admin/RecommendationsQueueWidget.jsx, pages/admin/Dashboard.jsx; backend routers recommendations_queue.py / training.py / training_nudge.py (read-only, role guards)

## Iteration 119 — Phase 40b: Issue Credit command-strip button
- **Commit**: see `git log --grep "phase 40b"`
- **Date**: 2026-10-11
- **Changes**: `customer-action-issue-credit` steel button in the customer action row (after View-as, before Delete) → `jumpTo("credits")`. Gated admin/super_admin (= mobile Credits section gate; web gate also includes manager/owner but Credits section is hidden for them on mobile). Credits + Equipment blocks byte-identical (sha1 match).
- **Files modified**: app/customer/[id].tsx (+14), __tests__/phase40-customer-profile-visual-grouping.test.tsx (+33, append-only)
- **Web files referenced**: pages/customers/CustomerDetail.jsx (canIssueCredit, cd-issue-credit-btn)

## Iteration 120 — Recurring Jobs "Next" date filter (web parity 52c3eb6fa)
- **Commits**: 664af4aca (src/lib/scheduleRangePresets.ts + test), 88e3938de (finance/recurring-jobs.tsx + test)
- **Date**: 2026-10-12
- **Changes**: 7-key preset helper (verified identical to web module, 21k anchors x 3 TZs); 5 pill chips + From/To DateField + Clear; inclusive upcoming[0] filter, AND with Active/Paused tab; "Next: YYYY-MM-DD|—" row meta.
- **Follow-up backlog**: mobile RecurringJobs search + service-category filter parity (web NavyFilterBar) — not on mobile yet.
- **Web files referenced**: frontend/src/lib/scheduleRangePresets.js, pages/admin/RecurringJobs.jsx, test/recurring-jobs-date-filter.test.jsx

## Iteration 121 — Schedule "completed" color #DC2626 → #ff4542 (web parity 85fd76f17 / dd1b9d0d9)
- **Commits**: c5482f90f (feat: src/lib/jobStatus.ts + src/utils/scheduleStatus.ts), 21d85e2a8 (test: k50-job-status-color + schedule-card-phase3-parity)
- **Date**: 2026-10-12
- **Changes**: K50 completed bg + left border → #ff4542; K50_BOLD_RED_BG now derives from K50_JOB_STATUS_BG.completed (closes silent white-text-flip drift). "Closed" green pill + map pins untouched.
- **Backlog**: MOBILE-MAP-PIN-COMPLETED-COLOR-DRIFT (ScheduleMap.native green #16A34A / DailyRouteMap.native gray #6B7280 / DailyRouteMap.web green #22C55E). Also: mobile Grid filters `scheduled_date === focusISO` (exact string) so jobs stored with full ISO timestamps (e.g. 15 completed seed jobs on 2026-09-15) never render while WeekStrip counts them.
- **Pre-existing failing suites (unrelated, mock both helpers or assert calendar.tsx strings)**: k32-tech-scoped-schedule (ExpoTaskManager), schedule-map-toggle (stale jobStatus mock), s1-schedule-tech-filter, phase-schedule-tech-filter-technician-id, schedule-select-all.

## Iteration 122 — RecurringJobs customer search + service-category filter (web parity R2 / P54)
- **Commits**: 30a6a0849 (feat: app/finance/recurring-jobs.tsx), 465d88bea (test: new recurring-jobs-search-category-filter.test.tsx + 1-line testID follow in recurring-jobs-date-filter.test.tsx)
- **Date**: 2026-10-12
- **Changes**: search (customer name/company/email/phone, 250ms debounce) + category Sheet picker (GET /service-categories, exact service_category_id) AND date AND tab; empty msg → web's "No recurring jobs match your search." (recurring-jobs-empty).
- **Notes**: test placed in mobile/__tests__/ (not app/finance/__tests__/ — expo-router would register it as a route). Seed data: 0 recurring jobs have service_category_id → any category pick = 0 rows on preview (accepted; not mutated).

## Iteration 123 — P2 #9 MOBILE-SCHEDULE-DAY-VIEW-TIMESTAMP-FILTER-BUG
- **Commit**: 342b55df7 (single atomic: scheduleDayKey.ts + calendar.tsx + 2 tests + TECH_DEBT TD-12..15)
- **Date**: 2026-10-12
- **Changes**: iso() → device-local localDateKey (11 call sites); dayJobs/weekCounts/jobsByDay → jobDayKey (web P13: scheduled_date prefix, else tenant-local scheduled_start).
- **Notes**: Jest sandboxes process.env → runtime TZ switch does NOT work in-worker; real 5-TZ matrix uses child Jest processes (P2_9_CHILD=1). schedule-hide-cancelled boundary regex updated (it locked the buggy expression text). Schedule sweep: 9 pre-existing failures identical pre/post (baseline @ac7f0ba00).

## Iteration 124 — Hotfix · Time Clock Gate (pool-tech bypass + punch `source`)
- **Commits**: 8d52ccb34 (Fix 2 · source) + the Fix 1 commit that includes this entry (`git log -1 -- mobile/src/utils/clockInGate.ts`)
- **Date**: 2026-10-12
- **Changes**:
  - Fix 2: `LandscapeTechClockInGate` POST `/timeclock/punch` sent `source: "mobile_gate"` → backend `PunchIn.source: Literal["mobile","web"]` 422 ("Input should be 'mobile' or 'web'"). Now `"mobile"`. Other punch sites (`LandscapingClockWidget`, `landscape-time-clock`) already sent `"mobile"`; `/workforce/clock-in|out` have no `source` field (untouched). No central wrapper → patched the call site.
  - Fix 1: discriminator = `users.role === "technician"` + `users.department` (returned by `/auth/login` + `/auth/me`; preview values: pool_tech, landscaping, north, south, null). Added `isPoolTech()` (pool, pools, pool_tech, pool_technician, pool_service; trimmed/lowercased/space+hyphen→_), which wins over `isLandscapeTech()`. `useClockInStatus(enabled)` skips the `/timeclock/mine-status` probe for non-gated users (was probing + 403ing for every user). `both` stays gated (web parity / default gate-ON).
- **Files modified**: mobile/src/components/LandscapeTechClockInGate.tsx, mobile/src/utils/clockInGate.ts, mobile/__tests__/LandscapeTechClockInGate.test.tsx
- **Web/backend files referenced (read-only)**: frontend/src/hooks/useClockInGate.jsx, backend/routers/timeclock_landscaping.py, backend/routers/workforce.py
- **Tests**: gate suite 15/15 (was 6). Clock-related sweep: 3 suites (schedule-map-toggle, k32-tech-scoped-schedule, dashboard-active-inactive-tiles) fail identically at pre-fix baseline ("Cannot read 'bg'" theme-mock drift) — pre-existing.
- **Note**: Templates Library Phase 3 brief re-dispatched again this turn — already shipped 2026-10-08 (PRD §5); not re-implemented. No external repo cloned.

## Iteration 125 — Schedule map parity: Live Tech GPS pins + Multi-Property pins
- **Commits**: a388d76eb (F1 live tech pins) + the F2 commit containing this entry (`git log -1 -- mobile/src/utils/jobPinCoordSource.ts`)
- **Date**: 2026-10-14
- **Web refs**: 6db3c4f57 (useLiveTechLocations.js + ScheduleMap.jsx), 723e28204 (ScheduleMap.jsx approximate + property chip); BE 89d77b370 / bf89d1b99 (read-only)
- **F1**: `src/hooks/useLiveTechLocations.ts` (GET /workforce/live-locations, 30s poll, AppState pause/resume, AbortController, AsyncStorage `live_tech_overlay.<user_id>` "1"/"0", role gate = BE `_GPS_READ_ROLES` admin/super_admin/owner/manager/dispatcher; non-gps roles: toggle hidden + never poll). `src/components/schedule/LiveTechOverlay.tsx` (toggle chip, staleness dots #22c55e/#eab308/#94a3b8 keyed by staleness so tracksViewChanges=false still recolors, info card). ScheduleMap.native: overlay wired; map frames live techs when no mapped jobs.
- **F2**: `src/utils/jobPinCoordSource.ts` (jobPinVariant / isApproximatePin = customer+property_id / propertyChipLabel / jobPinWrapStyle dashed+0.7). ScheduleMap.native: pin wrapper View, marker `description` = property_label, info-card "Property: <label>" chip + approximate note. ScheduleMapLazy Job type += coord_source/property_id/property_label.
- **Map lib**: react-native-maps 1.20.1 via `@/src/lib/maps` (Google adapter). No clustering on mobile Schedule map (nothing to preserve). ScheduleMap.web.tsx is a placeholder — unchanged.
- **Tests**: new live-tech-locations-mobile (12) + multi-property-map-pins-mobile (9); ScheduleMap + gate suites green. Pre-existing fails unchanged: teardrop-pin-parity (deriveDarker default 0.25 vs 0.28), schedule-map-toggle (inputColors.bg).

## Iteration 126 — P2 #11 Email Builder mobile parity (view + preview + test-send)
- **Commits**: 69ceb98e4 (C1 drawer wiring + gate + list fields + WebView preview) + the C2 commit containing this entry (`git log -1 -- mobile/src/components/comms/EmailTestSendPanel.tsx`)
- **Date**: 2026-10-14
- **Web/BE refs (read-only)**: 965fb3c69 (test-send endpoint), d34aec4e5 (CommsEmailBuilder), backend/routers/comms.py `_require_admin` / `_resolve_test_recipient` / `_rate_limit_comms_test_send`, frontend/src/App.js `AdminOnly`
- **C1**: drawer "Email Builder" + "Templates" → t1, `roles: ["super_admin","admin"]` (only those 2 rows in src/nav/adminNav.ts; SMS/Automations/Sends untouched); app/admin/comms/{email,templates}.tsx → `<Redirect href="/comms/templates">`; CommsAdminGate (admin+super_admin, wraps list + detail so non-admins never fetch); list rows show subject + CUSTOMER-FACING badge (+subject search); detail preview modal opens immediately with loader / in-modal error + Retry; EmailPreviewWebView (JS off, links → system browser, Expo-web text fallback).
- **C2**: EmailTestSendPanel on email detail. One-off direct `fetch` (`postTemplateTestSend`) for Retry-After header access — commented. 200 → toast "Sent to <recipient>" (+ delivery status e.g. suppressed_not_demo) + 2s cooldown; 400 → backend msg verbatim; 403 → "Admin access required" (body not echoed); 429 → ceil(Retry-After) countdown, button disabled. TD-48 filed (edit-on-mobile; rich-text dep + web Phase 2 schema; CORS expose_headers note).
- **Tests**: comms-email-templates-mobile (13) + comms-email-test-send-mobile (12). No prior comms/templates or comms/test-send suites existed.
- **Deps**: none.

## Iteration 127 — Parity sweep: Optimize Route modal + per-tech pins (+ Port 3 no-op, Port 4 audit)
- **Commits**: f001ff6ad (Port 1 — CRON-COMMITTED with a junk title "I have enough. Compiling the discovery report:"; content verified byte-identical to my 4 files), dc5690f80 (Port 2). Port 3 no-op. Port 4 read-only.
- **Port 1** (web 2f14a7ea5 + e5d6fa01e): src/utils/routeHaversine.ts (haversine/total/classifyMiles/formatRouteHeader port), src/components/schedule/OptimizeRouteModal.tsx (POST /schedule/optimize-route {date, technician_id}; header server-totals → haversine on drag/move/reverse; Reverse Order left of Save; dropped banner; save via existing POST /jobs/reorder), calendar Bulk Actions "Optimize Route" (adminOnly, isAdmin-gated modal). Real wire = ordered_job_ids/total_distance_m/total_duration_s (brief's optimized_order/miles names were wrong).
- **Port 2** (web 9eb08b5c1): src/utils/crewPalette.ts (crewHuedColor port + buildTechColorMap), src/utils/perTechSequence.ts, src/components/schedule/TechLegend.tsx; ScheduleMap.native pins fill by tech color + `label` = per-tech seq when `techs` passed (status colors otherwise); calendar passes allTechs + crews. No clustering on mobile.
- **Port 3**: no-op — server preview HTML carries the hidden preheader + nested column cells; mobile WebView passes html verbatim (asserted in comms-email-templates-mobile). Mobile list shows no snippet; list payload has no preview_text.
- **Port 4 (45b05e41e audit)**: commit has border + tests + snapshot only; jobStatus.ts bg (#ff4542) and calendar.tsx ✓ / text changes were LOST (never committed, worktree reverted). 14 tests red at HEAD (k50, phase3-parity, recede). Awaiting user follow-up dispatch.
- **Cron guard used for Port 2**: .git/info/exclude for new files + `git update-index --skip-worktree` for edited tracked files; both removed before `git commit --only`.
- **Deps**: none (lucide-react-native NOT installed → Ionicons).

## Iteration 128–130 — completed-card fix, iOS decimals, Form Builder P1+P2 read-only parity
- **284bfb114** completed-card recede completion (jobStatus #ECFDF5 + JobRow ✓) — fixed the 14 red tests from phantom 45b05e41e.
- **09b0bcb78** iOS decimal entry (locale "," → "." sanitizer) on ReadingChipRow / customer chemistry / calculators.
- **02061f835** Form Builder C1: /admin/marketing/forms list + [id] (Preview with PORTED formShowIf | Versions view-only, no revert, copy desktop link | Settings), drawer admin+super_admin, TD-59 filed (pool-volume comma decimal, OPEN).
- **C2 (this commit)**: /admin/marketing/forms/submissions inbox (form chips; "All forms" fans out ≤25 forms with submission_count>0 — no cross-form endpoint; date range all/7d/30d) + submissions/[sid] detail (labelled answers, pii_tag / is_customer_facing:false masked, metadata, lead/customer destination). Helpers in src/utils/formSubmissions.ts.
- Gate: CommsAdminGate (admin+super_admin); backend require_admin also admits owner — mobile stricter per brief.
- Cron lockout: .git/info/exclude for new paths + skip-worktree on edited tracked files; cleared before `git commit --only`.
- Deps: none. Edit-on-mobile still TD-48.

## Iteration 131 — Templates Library Phase 3 re-dispatch (verification only)
- **Commit**: the docs-only commit containing this entry (base f0f5bbe14)
- **Date**: 2026-10-15
- **Changes**: none to code. Phase 3 already shipped in 77affb86c; no frontend/backend/mobile templates diffs since. Re-verified Jest 45/45, live API contract (incl. 409 after finalize, PDF), Expo-web offline queue → reconnect flush. PRD §5 re-verification line added.
- **Files modified**: memory/PRD.md, memory/mobile/commit_log.md
- **Web files referenced**: none re-read (unchanged since 77affb86c). No external repo cloned.
