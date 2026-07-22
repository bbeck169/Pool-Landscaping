# Iteration 8 — Phase 5A + 5A.2 Mobile Mirror

## Scope Implemented

### 1. Tech UX Cleanup
- **sections.ts**: Removed `estimator` (Field Estimator) and `property-lookup` (Property Lookup) tiles from TECH_SECTIONS
- **estimator/index.tsx**: Added role-gate — techs see "Not available on your role" screen with Go Home button. Hooks ordered correctly (before conditional return).
- **property-lookup.tsx**: Added role-gate — techs see "Not available on your role" screen with Go Home button. Imported `useAuth` + `useRouter`.
- **card.tsx**: Already handles techs correctly — company card only, no "My Card" toggle. No changes needed.
- **more.tsx**: 
  - Removed "Field Estimator" from techLinks
  - Moved "Work Stream" from generic links to adminLinks (admin/super_admin only)
  - Push notifications toggle retained

### 2. Daily Checklist — Backend-Driven
- **FieldReport.tsx**: Added `useEffect` that fetches `GET /api/checklists/daily` (no query — backend resolves service line from user). Falls back to `?service_line=<job.service_type>` if needed.
- Merges backend items (source-of-truth for labels + ordering) with per-job completion state from `job.checklist`.
- Falls back to `job.checklist` if API fails.
- **No hardcoded fallback arrays** — all items come from the backend.
- Pool jobs: 7 items (Skimmed Pool, Brush Pool, etc.) + Chemical Readings + Chemicals Added
- Landscape jobs: 10 items + Chemical sections hidden entirely

### 3. Workstream — Admin-Only + Service Log Detail
- **workstream.tsx**: Complete rewrite
  - Role gate: only `admin` + `super_admin` allowed
  - Title: "Workstream — Completed Jobs"
  - No status filter pills — only completed status (backend default)
  - Sort pills: Newest, Oldest, Tech A-Z, Customer A-Z
  - Card tap navigates to `/workstream/[id]` (Service Log detail)
  - API response handles both `{jobs: [...]}` wrapper and raw array

- **NEW: workstream/[id].tsx** — Service Log Detail screen
  - Fetches `GET /api/jobs/{jid}/service-log`
  - **Section 1 — Log Details**: Customer → Property (with arrow), service date/time, time spent, employee avatar + name, checklist with checkmarks, previous service with VIEW pill buttons, EMAIL DOOR HANGER CTA
  - **Section 2 — Water Test Results** (pool only): rows for each test with value
  - **Section 3 — Chemicals Used** (pool only): header with red cost pill, chemical rows. For landscape: shows Service Notes + Materials Used instead.
  - **Section 4 — Service Images carousel**: horizontal FlatList with left/right chevron nav, dot pagination, play badge on videos, empty state card
  - EMAIL DOOR HANGER: calls `POST /api/jobs/{jid}/email-door-hanger`, handles 200/429/error with appropriate alerts
  - Role gate for non-admins with "Not authorized" screen

### 4. Role-Gates + Navigation Cleanup
- Workstream route (`/workstream`, `/workstream/[id]`): role-gate in component for non-admins
- Field Estimator route: role-gate for techs
- Property Lookup route: role-gate for techs
- Work Stream link hidden from techs in More screen
- All gates show clear "Not available" / "Not authorized" UI with Go Home button

## API Endpoints Used
- `GET /api/checklists/daily[?service_line=pool|landscape]` — checklist source-of-truth
- `GET /api/workstream/jobs[?sort=newest&limit=100]` — completed jobs list
- `GET /api/jobs/{jid}/service-log` — full service log detail
- `POST /api/jobs/{jid}/email-door-hanger` — send door hanger email

## Files Created
- `src/api/serviceLog.ts` — Service log, door hanger, daily checklist API
- `app/workstream/[id].tsx` — Service Log detail screen

## Files Modified
- `app/workstream.tsx` — Complete rewrite (admin-only, completed-only)
- `src/components/tools/sections.ts` — Removed estimator + property-lookup from TECH_SECTIONS
- `src/components/job/FieldReport.tsx` — Backend-driven checklist fetch
- `app/(app)/more.tsx` — Moved Work Stream to adminLinks, removed Field Estimator from techLinks
- `app/(app)/estimator/index.tsx` — Added role-gate for techs
- `app/(app)/property-lookup.tsx` — Added role-gate for techs

## No Regressions
- Invoice viewer + Stripe Pay Now: untouched
- Estimate viewer + Accept/Decline: untouched
- Job Detail (line items, media caps, tech guardrail): untouched
- Push notifications: untouched
- AI Dock: untouched

## Dependencies
- No new dependencies installed
