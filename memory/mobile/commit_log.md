## Iteration 85 — Per-endpoint timeouts + Retry wall-clock cap + Retry-After UI
- **Commit**: 3ad46a32
- **Date**: 2026-09-11
- **Changes**:
  - `api.ts`: Per-endpoint timeout classification (GET→8s, standard write→20s, uploads/multipart→60s). `ApiNetworkError.reason` field distinguishes "timeout" vs "cancelled" vs "network". `classifyTimeout()` heuristic: checks Content-Type header + path regex + HTTP method.
  - `retryWithBackoff.ts`: Full rewrite — added `maxTotalWaitMs` (default 30s) wall-clock budget, Retry-After honored on ALL retries (not just first), enhanced `onRetryAttempt({attempt, nextDelayMs, retryAfterMs, totalElapsedMs, willStop})` callback. Cancelled requests NOT retried.
  - `ChecklistSavePill.tsx`: Enhanced state types — `retrying` now has `nextDelayMs`/`totalElapsedMs`, `exhausted` has `totalElapsedMs`. Toast copy: "Save error — retrying in Xs" and "Save failed after Xs — tap to retry".
  - `checklist.tsx`: Switched both retry call sites from `onRetry` to `onRetryAttempt` with `maxTotalWaitMs: 30000`.
  - `api-timeout-retry.test.ts`: 11 tests — 7 timeout classification + 4 retry behavior (Retry-After, wall-clock cap, onRetryAttempt payload, cancelled-not-retried). All pass.
- **Timeout thresholds**: Read 8s, Write 20s, Upload 60s
- **maxTotalWaitMs default**: 30s — matches existing max backoff + gives time for ~2-3 retries with exponential backoff
- **Retry state pattern**: Callback (`onRetryAttempt`) — matches existing `onRetry` pattern, no new store/subject needed
- **Files modified**: `mobile/src/api.ts`, `mobile/src/services/retryWithBackoff.ts`, `mobile/src/components/sync/ChecklistSavePill.tsx`, `mobile/app/job/[id]/checklist.tsx`, `mobile/__tests__/api-timeout-retry.test.ts`



## Iteration 84 — Dashboard /dashboard fetch loop guard
- **Commit**: 9abac25a
- **Date**: 2026-09-11
- **Changes**:
  - `useOfflineQuery.ts`: (2a) Added staleTime enforcement via `readCacheWithAge` — returns cached value immediately if `Date.now() - cachedAt < staleTime`, skipping network fetch. Legacy entries without `cachedAt` are treated as stale. (2b) Strategy A — ref-latched `fetcher` via `useRef` + `useEffect`, removed `fetcher` from `execute`'s dep array. `execute` is now stable regardless of fetcher identity. `refetch()` bypasses staleTime via `force=true`.
  - `(app)/index.tsx`: Wrapped dashboard fetcher in `useCallback([], [])`. Destructured `refetch` from `dashQ` to satisfy exhaustive-deps. Removed wrapper `load` function; `onRefresh` now calls stable `refetch` directly.
  - Created `use-offline-query-stale.test.ts` — 5 tests: fresh cache skips fetch, stale cache re-fetches, refetch() bypasses staleTime, unstable fetcher identity absorbed, legacy entry treated as stale. All pass.
- **Strategy chosen**: A (ref-latch) — stronger guarantee than B (ESLint suppress). The hook protects itself; callers don't need to remember `useCallback`.
- **Cache timestamp shape**: Existing `readCacheWithAge` in `readCache.ts` already returns `{data, cachedAt}` from SQLite `cached_at` column. No schema change needed.
- **Files modified**: `mobile/src/hooks/useOfflineQuery.ts`, `mobile/app/(app)/index.tsx`, `mobile/__tests__/use-offline-query-stale.test.ts`



## Iteration 83 — Multi-Contact Editor + Automations Mute Toggle
- **Commit**: a4644eb9
- **Date**: 2026-09-11
- **Changes**:
  - Created `CustomerMultiContactEditor.tsx` — admin-only inline editor for customer.emails[] and customer.mobiles[]. Max 4 cap, duplicate detection, email/phone validation, save via PATCH endpoints
  - Created `AutomationsMuteSection.tsx` — admin-only toggle for automations_muted. Reason modal on mute, amber banner when muted, info modal on banner tap/long-press
  - Updated `customer/[id].tsx` — imported new components, admin-gated editor vs read-only, primaryEmail/primaryPhone derivation from arrays with scalar fallback
  - Created `automations-mute-toggle.test.tsx` — 4 Jest tests for mute toggle happy path (all pass)
- **Files modified**: `mobile/app/customer/[id].tsx`, `mobile/src/components/customers/CustomerMultiContactEditor.tsx`, `mobile/src/components/customers/AutomationsMuteSection.tsx`, `mobile/__tests__/automations-mute-toggle.test.tsx`
- **Web files referenced**: `frontend/src/components/customers/CustomerMultiContactEditor.jsx`
- **Feature memo**: `/app/memory/FEATURE_MULTI_CONTACT_MOBILE_PARITY.md`



## Iteration 82 — P0 Fix: Job detail 20s timeout + error/retry UI
- **Commit**: 18a60892
- **Date**: 2026-09-10
- **Changes**:
  - Added `LOAD_TIMEOUT_MS = 20_000` constant to `[id].tsx`
  - Added `loadError` state for user-visible error messages
  - Made `flushPendingMutations()` and `flushPendingPhotos()` fire-and-forget (removed `await`, kept `.catch(() => {})`)
  - Wrapped `api.get(/jobs/${id})` in `Promise.race` with 20s timeout — rejects with `__LOAD_TIMEOUT__` error
  - On timeout/failure with no cache: renders "Couldn't load job. Retry?" UI with `job-detail-error`, `job-detail-error-message`, `job-detail-retry-btn` testIDs
  - On timeout with cache: falls back to cached job (existing behavior preserved)
  - Fixed `job-detail-spinner-timeout.test.tsx` — rewrote with 6 tests (4 logic + 2 UI render)
    - Tests 1-4: Pure async logic tests (fake timers for timeout simulation)
    - Tests 5-6: Static UI render tests for error/retry and cached-banner states
  - All 6 tests pass, 0 lint issues, Metro 2308 modules clean
- **Files modified**: `mobile/app/job/[id].tsx` (load timeout + error UI)
- **Files modified (tests)**: `mobile/__tests__/job-detail-spinner-timeout.test.tsx` (rewritten)
- **Root cause**: `load()` sequentially awaited `flushPendingMutations()` and `flushPendingPhotos()` which made blocking API calls. On slow/failing networks, these blocked indefinitely, preventing the job fetch from ever starting.
- **Fix approach**: Fire-and-forget flushes + Promise.race timeout on main fetch + graceful error UI



## Iteration 81 — Outcome C: /estimates/* → /quotes/* URL rename
- **Commit**: b114a901
- **Date**: 2026-09-09
- **Changes**:
  - `src/api/estimatesFull.ts` lines 48/51/54/57: `/estimates/${eid}/*` → `/quotes/${eid}/*` (4 paths)
  - `src/api/media.ts` line 31: `/estimates/${id}/videos` → `/quotes/${id}/videos` (1 path)
  - `app/estimate-view/[id].tsx` line 4: docstring updated to reference `/quotes/*` canonical
  - Zero remaining old `/estimates/` paths outside estimator/ (confirmed via grep)
  - No test file changes needed (no mocks referenced old paths)
- **Files modified**: `mobile/src/api/estimatesFull.ts`, `mobile/src/api/media.ts`, `mobile/app/estimate-view/[id].tsx`



## Iteration 80 — P45 "More filters" bottom sheet + Add card row polish
- **Commit**: ffa2ce23
- **Date**: 2026-09-09
- **Changes**:
  - Consolidated 9 filter chips into a single "More filters" bottom sheet (Modal)
  - Trigger: `customers-more-filters-dropdown` with summary text ("All", first label, "first +N")
  - Sheet has 4 groups: Contact info missing (No email, No phone, Missing address), Payment (No payment on file), Portal status (Any/Signed in/Never signed in radio), Administrative (Show deleted, Show merged, Pending merge)
  - All 11 old testIDs preserved inside the sheet + 1 new `customers-more-filters-clear`
  - Portal status: `accessibilityRole="radio"` + `accessibilityState={{ selected }}` inside `radiogroup`
  - New filters wired: `missing_email`, `missing_phone`, `include_merged`, `pending_merge_candidates`
  - New count fetches: missing email (12), missing phone (12), pending merge (3) in parallel on mount
  - Add card pill moved to right actions cluster, restyled navy #1E293B / white #FFFFFF / border #0F172A
  - Missing card dot stays before name (left column), Add card pill in right column
  - 19 Jest tests (all pass): trigger rendering, sheet testIDs, filter toggles, composition, clear all, portal radio a11y, row actions, row order
- **Files modified**: `mobile/app/(app)/customers.tsx`, `mobile/__tests__/customer-list-filters.test.tsx`



## Iteration 79 — P44 row polish: name leftmost, label → "Add card"
- **Commit**: a1031a02
- **Date**: 2026-09-09
- **Changes**:
  - Row order: customer name is now leftmost, missing-card dot + "Add card" pill trail after name
  - Label rename: "Send payment link" → "Add card" everywhere (button, testID, alert, accessibility)
  - testID: `send-payment-link-btn-{id}` → `add-card-btn-{id}`
  - Alert copy: "Payment link sent to…" → "Add-card link sent to…"
  - Icon: `send-outline` → `card-outline`
  - Added `testID="customer-row-name-{id}"` on name Text for order assertions
  - 18 Jest tests pass (16 original + 2 new: name-before-pill order, label text verification)
- **Files modified**: `mobile/app/(app)/customers.tsx`, `mobile/__tests__/customer-list-filters.test.tsx`



## Iteration 78 — P43b + P43c + P44 Customer list filter chips
- **Commit**: 8b2e34a3
- **Date**: 2026-09-09
- **Changes**:
  - P43b: "Missing address (25)" filter chip, queries `missing_address=true`
  - P43c corrected: Portal tri-state "Any | Signed in (5) | Never signed in (23)", queries `portal_activated=true/false` (replaces old "Activated/Not activated" + `portal_status` param)
  - P44: "No payment on file (28)" filter chip, queries `has_payment_method=false`
  - P44: "Send payment link" row action pill (admin-only, amber badge) + POST `/customers/{id}/send-card-add-link`
  - P44: Missing card dot indicator (amber ●) on rows without payment methods
  - All four count badges fetched in parallel on mount (stable, not composed)
  - Filter chips compose: multi-filter = ANDed backend query
  - 16 Jest tests (all pass): chip rendering, toggle API calls, composition, row action, alerts
- **Files modified**: `mobile/app/(app)/customers.tsx`
- **Files created**: `mobile/__tests__/customer-list-filters.test.tsx`
- **Web files referenced**: `frontend/src/pages/customers/CustomersList.jsx`
- **UX compromise**: Info banners (P43b "can't appear on maps" + P44 "can't be auto-charged") skipped for mobile viewport space



## Iteration 77 — Navigate arrow button: top-right + orange restyle
- **Commit**: 1b08cb2a
- **Date**: 2026-09-09
- **Changes**:
  - Moved NavigateJobButton from bottom of content column to top-right of card's right column
  - Restyled: navy (#1B1F5C) → orange (#F97316), 44px → 36px visual (48px effective with hitSlop), added shadow/elevation
  - Card layout changed from `alignItems: "center"` to `"flex-start"` with new `cardRight` column wrapper
  - Accessibility preserved: dynamic `accessibilityLabel="Navigate to {customer}"`, `accessibilityRole="button"`, hint
  - 8 Jest tests covering: testID, orange color, accessibility, press handler, disabled state, size
- **Files modified**: `mobile/src/components/schedule/NavigateJobButton.tsx`, `mobile/app/(app)/schedule/calendar.tsx`
- **Files modified (tests)**: `mobile/__tests__/navigate-job-button.test.tsx`



## Iteration 76 — Schedule map show/hide toggle
- **Commit**: 453db872
- **Date**: 2026-09-08
- **Changes**:
  - Added collapsible map toggle bar in Schedule Grid view
  - "Hide map" / "Show map" toggle hides DailyRouteMap + List|Map segmented control
  - Preference persisted via `storage.setItem("schedule.mapVisible", boolean)` (AsyncStorage)
  - Proper accessibility: `accessibilityLabel`, `accessibilityRole="button"`, dynamic label
  - 8 Jest tests covering: default state, toggle flip, persistence across mount/unmount, accessibility
- **Files modified**: `mobile/app/(app)/schedule/calendar.tsx`
- **Files created**: `mobile/__tests__/schedule-map-toggle.test.tsx`
- **Web files referenced**: None (mobile-only feature)



## Iteration 75 — Task 6b E2E Verification (Testing Agent)
- **Commit**: a9f5f483 (code unchanged; E2E test added)
- **Date**: 2026-09-08
- **Changes**:
  - Verified Task 6b (Revoke service-records link) via E2E Playwright tests
  - 8/8 Playwright tests pass: banner visibility/copy/dismiss, modal open/recent sends/tabs/buttons, login form
  - 17/17 Jest unit tests pass, 12/12 Task 6 tests pass, 9/9 Task 4 tests pass — 0 regressions
  - Fixed /root/.expo/state.json empty JSON error
- **Files created**: `tests/test_task6b_mobile_revoke.py`
- **Files modified**: None (code was already complete)



## Iteration 66 — Phase K28: Workstream completed_at column + LRU investigation
- **Commit**: 4851ac251c72dddad77d4b23d7a20effbc5c16cd
- **Date**: 2026-09-02
- **Changes**:
  - Part B: Added `completed_at` per-row on workstream list cards (+7 lines)
  - Part J: LRU recent tabs — DEFERRED (web-only ResponsiveTabs feature, no mobile equivalent, exceeds scope)
- **Files modified**: `app/workstream.tsx`



## Iteration 65 — Phase K27: Soshie API shape + Set-default payment method
- **Commit**: 7d68485e8b713bc31dca244dbd40334d4c25d4f3
- **Date**: 2026-09-02
- **Changes**:
  - Part E: Fixed `soshieModeration.ts` type + `soshie-moderation.tsx` read from `res?.posts` → `res?.items`
  - Part F: Added "Set default" affordance to `PaymentMethodRow.tsx` + wired in `customer/[id]/payment-methods.tsx`
  - Tests: 7 new (5 PaymentMethodRow + 2 Soshie), all passing
- **Files modified**: `soshieModeration.ts`, `soshie-moderation.tsx`, `PaymentMethodRow.tsx`, `customer/[id]/payment-methods.tsx`
- **Files created**: `__tests__/k27_setDefault.test.tsx`



## Iteration 64 — Phase K26: Portal Activation filter + Waitlist tab (Investigation only)
- **Commit**: N/A — no code changes; mobile already at full parity
- **Date**: 2026-09-02
- **Findings**: Status filter (Active/Inactive/Waitlist/All), portal activation filter (All/Activated/Not activated), and all API params (`is_active`, `waitlisted`, `portal_status`) already match web exactly. AsyncStorage persistence present. Nothing to ship.



## Iteration 63 — Phase K25: Schedule Crew filter + Active/Inactive customer filter
- **Commit**: 3db719aa9ac644e648795c72c3fcca26e69efb4f
- **Date**: 2026-09-02
- **Changes**:
  - Schedule crew filter: already implemented — K25 added AsyncStorage persistence
  - Customers active/inactive filter: already fully implemented with persistence — no changes needed
  - CrewFilterBar.tsx was already available and in use ✅
  - Tests: 17 new (7 crew filter + 10 customers filter), all passing
- **Files modified**: `calendar.tsx` (+9 lines)
- **Files created**: `scheduleCrewFilter.test.tsx`, `customersActiveFilter.test.tsx`



## Iteration 62 — Phase K24: Mobile parity for K11 payment-method prompts
- **Commit**: 4f982098f5a2299084bb1b1d28a7cb4c6661580d
- **Date**: 2026-09-02
- **Changes**:
  - Created `PaymentMethodPromptModal.tsx` (modal on portal home, missing/expiring)
  - Created `PaymentMethodPromptBanner.tsx` (persistent light-blue strip, original_prompt_kind)
  - Updated `portal/_layout.tsx` — banner in layout wrapper (route-aware exclusion)
  - Updated `portal/home.tsx` — modal in render tree
  - K13 impersonation interlock on both components
  - Tests: 12 new (paymentMethodPrompt.test.tsx), all passing
  - Metro clean, all files lint clean
- **Files created**: `PaymentMethodPromptModal.tsx`, `PaymentMethodPromptBanner.tsx`, `paymentMethodPrompt.test.tsx`
- **Files modified**: `portal/_layout.tsx`, `portal/home.tsx`



## Iteration 61 — Phase K23: Mobile parity for K1 Stripe-not-configured fallback
- **Commit**: 99b1e82a9d222de3aea91e1215dbe5972fc5f6a0
- **Date**: 2026-09-02
- **Changes**:
  - Created `src/lib/stripeConfig.tsx` — `StripeUnconfiguredNotice` + `StripeUnconfiguredBanner`
  - Updated `src/config/stripe.tsx` — added `stripeConfigured` boolean (fail-closed)
  - Guarded 6 surfaces: customer payment-methods, invoice Pay Now, payments/methods, portal payment-method, quote Pay Now, PaymentMethodTiles
  - Tests: 6 new (stripeConfig.test.tsx), all passing
  - Metro clean, all 8 files lint clean
- **Files created**: `src/lib/stripeConfig.tsx`, `__tests__/stripeConfig.test.tsx`
- **Files modified**: `src/config/stripe.tsx`, 5 payment screens, `PaymentMethodTiles.tsx`



## Iteration 60 — Phase K22: Port K16 formatCompletedAt to Expo Mobile
- **Commit**: 07d7e8ec3e06070e2ab7af14ab90e42edbce4546
- **Date**: 2026-09-02
- **Changes**:
  - Created `src/lib/dateTimeFormat.ts` — TS port of web K16 `formatCompletedAt`
  - Updated `workstream.tsx` — `relTime()` >30d fallback → `formatCompletedAt`
  - Updated `workstream/[id].tsx` — replaced `fmtDate()` at `service_at` + `completed_at` call sites
  - Updated `portal/service-report/[id].tsx` — replaced `fmtDate()` at `submitted_at` call site
  - Grep-final: 0 bare completion-context toLocale* remaining (116 non-completion untouched)
  - Tests: 11 new (dateTimeFormat.test.ts), all passing + empirical proof 7/7
  - Metro 2178 modules clean
- **Files created**: `src/lib/dateTimeFormat.ts`, `__tests__/dateTimeFormat.test.ts`, `scripts/empirical-proof-k22-dateTimeFormat.cjs`
- **Files modified**: `workstream.tsx`, `workstream/[id].tsx`, `portal/service-report/[id].tsx`



## Iteration 59 — Phase K20: Google Maps Config + Safety Guards on All Map Components
- **Commit**: 33c886f660ab6b951b239fa9f2fc655b47aa7326
- **Date**: 2026-09-02
- **Changes**:
  - Created `src/utils/mapsKey.tsx` — `hasGoogleMapsKey()`, `hasMapboxToken()`, `MapUnavailablePlaceholder`
  - Wired `android.config.googleMaps.apiKey` and `ios.config.googleMaps.apiKey` in `app.json` via `$EXPO_PUBLIC_GOOGLE_MAPS_*_KEY` EAS env refs
  - Added `EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY` + `EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY` to `.env`
  - Guarded `MeasureMap.native.tsx` with `hasGoogleMapsKey()` → `MapUnavailablePlaceholder`
  - Guarded `ScheduleMap.native.tsx` — replaced inline `_hasAndroidGoogleMapsKey()` with centralized util
  - Guarded `MapCanvas.native.tsx` with `hasGoogleMapsKey()` → `MapUnavailablePlaceholder`
  - Guarded `DailyRouteMap.native.tsx` — `hasMapboxToken()` replaces inline token check
  - Guarded `LiveTechPinsMap.tsx` — `hasMapboxToken()` after hooks (rules-of-hooks compliant)
  - Tests: 14 new (11 mapsKey + 3 MeasureMap), all passing
  - README.md rewritten with EAS secrets setup guide + safety guards table
  - Metro 2077 modules clean
- **Files created**: `src/utils/mapsKey.tsx`, `__tests__/mapsKey.test.ts`, `__tests__/MeasureMap.native.test.tsx`
- **Files modified**: `app.json`, `.env`, `README.md`, `MeasureMap.native.tsx`, `ScheduleMap.native.tsx`, `MapCanvas.native.tsx`, `DailyRouteMap.native.tsx`, `LiveTechPinsMap.tsx`



## Iteration 58 — Phase K15.mobile: Schedule Error UI + AbortController + Timeout Race
- **Commit**: 92c8bcdce8f93c3a0d55ce5e2a6979d7b57f2475
- **Date**: 2026-09-02
- **Changes**:
  - **api.ts** (+16 lines): Added optional `signal` (AbortSignal) to `request()` and `api.get()`; external abort wired to internal controller.
  - **apiCache.ts** (+3/-1): `cachedGet()` now accepts and forwards `signal` to `api.get()`.
  - **calendar.tsx** (+81/-25): Per-request AbortController ref; abort stale loads; 25s `Promise.race` timeout on `cachedGet`; upgraded error bar → full error card with Retry button + testIDs; passes `listError` to tiles; aborted requests don't clobber state.
  - **JobTrackerTiles.tsx** (+28/-7): New `listError` prop; renders "⚠ Schedule list failed to load" hint below tiles when list fetch errored.
  - Metro 2225 modules clean, 0 lint issues (1 pre-existing unused-disable warning)
- **Files modified**: `api.ts`, `apiCache.ts`, `calendar.tsx`, `JobTrackerTiles.tsx`



## Iteration 57 — Phase K17: Android Crash Defensive Fix (runtimeVersion fingerprint)
- **Commit**: 801cfde8b0b72446df9bf41cd1fabb88ad96ba51
- **Date**: 2026-09-02
- **Changes**:
  - CHANGED: `runtimeVersion.policy` from `"appVersion"` to `"fingerprint"` in `app.json` (line 17)
  - ADDED: `android.versionCode: 2` in `app.json` (was unset/default 1)
  - BUMPED: `ios.buildNumber` from `"1"` to `"2"` in `app.json` (line 28)
  - UPDATED: `validate_eas_update_config.mjs` — now rejects `appVersion` as UNSAFE, requires `fingerprint` or `nativeVersion`
  - Validator passes ✓ (1 non-blocking warning about update branch alias)
  - Metro 2236 modules clean
- **Files modified**: `app.json` (+3/-2 lines), `validate_eas_update_config.mjs` (+18/-5 lines)
- **Root cause**: `appVersion` policy pinned at "1.0.0" allowed any OTA JS bundle to apply to any native binary regardless of native module availability → crash-on-open when JS referenced a native module the binary didn't have



## Iteration 56 — Phase K18: Remove Apple Pay Entitlement + K17 OTA Analysis
- **Commit**: a5d3bf6f31d0afdf3a4424a08df5d7b46768185d
- **Date**: 2026-09-02
- **Changes**:
  - REMOVED: `merchantIdentifier: "merchant.com.poolscape.crm"` from Stripe plugin config in `app.json` (line 181)
  - REMOVED: `merchantIdentifier="merchant.com.poolscape.crm"` from `<StripeProvider>` prop in `payment-methods.tsx` (line 244)
  - Confirmed ZERO Apple Pay runtime usage (no useApplePay/presentApplePay/PlatformPay calls)
  - Stripe card payment flow preserved — only Apple Pay entitlement removed
  - K17 OTA analysis: `runtimeVersion.policy: "appVersion"` pinned at "1.0.0", EAS CLI not available in container
- **Files modified**: `app.json` (-1 line), `payment-methods.tsx` (-1 line)
- **Web files referenced**: None



## Iteration 55 — Phase J2: Mobile Parity Sweep (4 features)
- **Commit**: ee518a6865f57d4f6d317d0b3ad5d02e88160ac7
- **Date**: 2026-09-01
- **Changes**:
  - H4 Waitlist tab: added 4th segment to customer list (customers.tsx)
  - H10 Revenue Forecast tile: 5-tab quick-view on dashboard (RevenueForecastTile.tsx NEW)
  - I5 Payment Method tiles: green on-file + red empty + typed-delete + set-default + expiry chips (PaymentMethodTiles.tsx NEW)
  - I7 Communication Timeline: vertical timeline with SMS/Email pills + cursor pagination (CommunicationTimeline.tsx NEW)
  - Mounted I5 + I7 on customer profile ([id].tsx), I7 on portal messages (messages.tsx)
  - Metro 2166 modules clean, 0 lint issues, 7 files changed, +971 LOC
- **Files modified**: `customers.tsx`, `index.tsx`, `[id].tsx`, `messages.tsx`
- **Files created**: `RevenueForecastTile.tsx`, `PaymentMethodTiles.tsx`, `CommunicationTimeline.tsx`
- **Web files referenced**: `RevenueForecastTile.jsx`, `PaymentMethodTiles.jsx`, `CommunicationTimeline.jsx`, `CustomersList.jsx`



## Iteration 54 — Phase H8: Charge Templates + Soshie Moderation Queue (Mobile Parity)
- **Commit**: 433c9373277841f1388d1567462b34e3b7e03dc0
- **Date**: 2026-09-01
- **Changes**:
  - NEW: chargeTemplates.ts API layer (27 LOC) — getChargeTemplates + applyChargeTemplate
  - NEW: ChargeTemplatePickerModal.tsx (280 LOC) — searchable bottom-sheet modal for picking templates
  - MODIFIED: LineItemsSection.tsx — added "Template" button (admin-only), opened picker, refreshes on apply
  - NEW: soshieModeration.ts API layer (43 LOC) — getModerationQueue + approve/reject/markPosted
  - NEW: soshie-moderation.tsx screen (480 LOC) — full admin moderation queue with 3 tabs, actions (Approve/Reject/Copy/Mark posted), expo-clipboard, pull-to-refresh
  - MODIFIED: _layout.tsx — registered soshie-moderation hidden tab
  - MODIFIED: sections.ts — added Soshie Moderation tile to admin Marketing section
  - Metro 2159 modules clean, 0 lint issues
- **Files modified**: `LineItemsSection.tsx` (mod), `_layout.tsx` (mod), `sections.ts` (mod)
- **Files created**: `chargeTemplates.ts`, `ChargeTemplatePickerModal.tsx`, `soshieModeration.ts`, `soshie-moderation.tsx`
- **Web files referenced**: `ApplyChargeTemplateButton.jsx`, `SoshieModerationQueue.jsx`, `ReviewQueueTab.jsx`



## Iteration 53 — Phase G4b: Portal Activation Filter (Expo Mobile)
- **Commit**: 6b29c626468c1e1107525b6d3b2071bee738eb28
- **Date**: 2026-08-31
- **Changes**:
  - MODIFIED: customers.tsx — portal filter state + AsyncStorage persistence + portal_status URL param + chip UI
  - NEW: mobile-portal-filter.test.tsx (178 LOC, 7 tests)
  - All 7 tests pass, 43 regression tests pass, Metro 2134 modules clean
- **Files modified**: `customers.tsx` (mod), 1 test file (new)


## Iteration 52 — Phase F6b: Mobile Filter Bundle (Crew + Customer Status)
- **Commit**: 7946eea26c01e474fe9aa357e91066ec53181d5c
- **Date**: 2026-08-31
- **Changes**:
  - NEW: CrewFilterBar.tsx (222 LOC) — crew dropdown + member chips for schedule
  - MODIFIED: calendar.tsx — crew state + fetch + load crew_id + mount CrewFilterBar in filter row
  - MODIFIED: customers.tsx — Active/Inactive/All segmented control, AsyncStorage persistence, is_active param
  - NEW: 2 test files (298 LOC) — crew filter (7), customer status (5)
  - All 12 Phase F6b tests pass, 43 regression tests pass, Metro 2279 modules
- **Files modified**: `CrewFilterBar.tsx` (new), `calendar.tsx` (mod), `customers.tsx` (mod), 2 test files (new)
- **Web files referenced**: F6a crew filter spec (backend contracts)


## Iteration 51 — Phase E: Mobile Parity Sweep (Navigate + Line Items + Reorder)
- **Commit**: 2219688798243acb0fbea61051fd2e7b28dd71fb
- **Date**: 2026-08-31
- **Changes**:
  - NEW: NavigateRouteButton.tsx (135 LOC) — multi-stop Google Maps deep-link from schedule day header
  - MODIFIED: ScheduleJobEditSheet.tsx — mounted LineItemsSection for F7 line items in schedule edit
  - MODIFIED: calendar.tsx — drag handle moved right, green position badge, reorder header/save/cancel bar, fixed payload (ordered_job_ids + tech_user_id + date)
  - NEW: 3 test files (269 LOC) — navigate route (7), schedule line items (2), reorder route (5)
  - All 30 Phase E tests pass, 15 regression tests pass, Metro bundled 2226 modules
- **Files modified**: `NavigateRouteButton.tsx` (new), `ScheduleJobEditSheet.tsx` (mod), `calendar.tsx` (mod), 3 test files (new)
- **Web files referenced**: `ReorderRouteModal.jsx`, `LineItemsSection.jsx`, schedule navigate logic


## Iteration 50 — F7 Line Items Editor (Mobile Parity)
- **Commit**: 3fc78ffb0ca3af63944469300b8f65dff2bac9a3
- **Date**: 2026-08-31
- **Changes**:
  - Created LineItemsSection.tsx (1152 LOC) — full CRUD line-items editor with list, add/edit sheet, pricebook picker, category chips, writeback toggle, inline error highlighting, offline banner, totals footer
  - Created lineItems.ts API layer (108 LOC) — 6 API helpers matching web endpoints
  - Created 5 test files (536 LOC) — 16 tests covering list/add/edit/error/offline
  - Modified app/job/[id].tsx — replaced inline read-only line items with new LineItemsSection component
  - All 16 tests passing, 0 lint warnings, Metro bundled 2212 modules, no regressions
- **Files modified**: `src/components/jobs/LineItemsSection.tsx` (new), `src/api/lineItems.ts` (new), `app/job/[id].tsx` (modified), 5 test files (new)
- **Web files referenced**: `frontend/src/pages/jobs/LineItemsSection.jsx` (643 LOC)


## Iteration 49 — Subscriptions CRUD (B4) Validation & Test Fix
- **Commit**: eca77790c19181a2a0559651d39d1a2b9b86e7fb
- **Date**: 2026-08-31
- **Changes**:
  - Validated fully implemented SubscriptionsSection (List, Create/Edit/Cancel modals, offline handling)
  - Fixed failing test in subscriptions-mobile-create.test.tsx (timing: waited for price load before submit)
  - Removed 2 unused imports (ActivityIndicator, api) from SubscriptionsSection.tsx
  - All 15 subscription tests passing, 0 lint warnings
- **Files modified**: `__tests__/subscriptions-mobile-create.test.tsx`, `src/components/subscriptions/SubscriptionsSection.tsx`
- **Web files referenced**: `frontend/src/pages/customers/SubscriptionsPanel.jsx` (confirmed feature parity)


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

