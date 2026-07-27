# Iteration 24 — Phase 33, 34, 32 Implementation

## What was implemented

### Phase 33 (10 items — ALL COMPLETE)
1. **BrandLogo component** — `src/components/BrandLogo.tsx` with sm/md/lg sizes, integrated into login
2. **Forgot Password** — `app/forgot-password.tsx` UI stub with email form and confirmation
3. **Portal Home: Hero to Top** — Greeting tile removed, hero card immediately after CTA row
4. **Portal Home: Top CTA Row** — "Call Now" (teal) + "Request Service" (gradient) side-by-side; stacks on narrow
5. **Portal Home: Concierge Highlight** — teal→cyan→emerald gradient card with sparkles + AI employee list
6. **Portal Home: Concierge above Refer a Friend** — Section order: Quick Actions → Last Visit → Concierge → Referral → Business Card
7. **Portal Home: Last Visit Card** — Shows last service date + title above concierge section
8. **Portal Home: Refer a Friend Highlight** — purple→magenta gradient card with $55 credit copy
9. **Portal: Media Date Grouping** — photos.tsx, videos.tsx, service-reports.tsx all rewritten with SectionList grouped by date
10. **Portal: Request Service Simplify** — Removed service type picker, free-text form with character counter; Book Service redirects to Request Service

### Phase 34 (8 items — ALL COMPLETE)
1. **Business Card Website Row** — `card.tsx` now shows website URL row between action icons and Save to Contacts
2. **Remove ToS Banner** — No ToS banner existed on mobile; confirmed removed
3. **Referral $25→$55** — Updated in portal home ($55 gradient card) and referrals.tsx share message + fallback text
4. **Portal Tour v2** — `src/components/Tour.tsx` lightweight 12-step tooltip engine; integrated in portal home with AsyncStorage persistence
5. **Auto-send Completion Notify** — `job/[id].tsx` now shows info banner below "Mark Complete": "A completion summary will be sent to the customer automatically."
6. **Password Reset Flows** — `app/reset-password.tsx` (deep link), `app/settings/change-password.tsx` (in-app), forgot-password already done in Phase 33
7. **Leads Status Enum** — Updated to 5 canonical values (new, contacted, qualified, won, lost) with backwards-compat for legacy values
8. **AI Employees Dedupe** — Stable key props using `emp.id || emp.key` in portal home

### Phase 34 Skipped (Admin-only)
- Admin Edit Any Job, CRM-wide Bulk-select, Invoices/Estimates Bulk-select, Leads Bulk Status Change, Task LL UI Wrapup

### Phase 34 Deferred (Backend not shipped)
- Digest Attention Tracker (explicitly deferred)
- Portal Profile Editable (backend not shipped)
- Review Gating (backend not shipped)

### Phase 32 (Foundation — COMPLETE)
1. **offlineStore.ts** — AsyncStorage-backed bundle cache + outbox queue (enqueue, flush, clear)
2. **SyncManager.tsx** — React context provider with NetInfo listener, auto-flush on reconnect, periodic outbox poll
3. **SyncStatusPill.tsx** — Header pill showing sync state (Synced/Syncing/Pending/Offline)
4. Integrated SyncManagerProvider in root `_layout.tsx`
5. SyncStatusPill visible in admin dashboard header

## Web-to-Mobile Mapping
- Web portal home → `app/portal/home.tsx` (complete rewrite with gradient sections)
- Web forgot-password → `app/forgot-password.tsx` (UI stub)
- Web reset-password → `app/reset-password.tsx` (deep link with token)
- Web change-password → `app/settings/change-password.tsx` (in-app)
- Web tour → `src/components/Tour.tsx` (lightweight modal-based)
- Web offline → `src/services/offlineStore.ts` + `SyncManager.tsx` (foundation)

## Dependencies Installed
- `@react-native-community/netinfo@12.0.1` (Phase 32 offline)

## Known Issues / Deferred
- Forgot password endpoint (`POST /api/auth/forgot-password`) not shipped — UI stub only
- Reset password endpoint (`POST /api/auth/reset-password`) may not be shipped — wired but untested
- Change password endpoint (`POST /api/auth/change-password`) may not be shipped — wired but untested
- Offline bundle endpoint (`GET /api/mobile/offline-bundle`) may not be shipped — SyncManager handles gracefully
- Full outbox conflict resolution deferred (basic replay only)
