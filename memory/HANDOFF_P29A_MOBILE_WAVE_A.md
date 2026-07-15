# Handoff — Phase 29A · Mobile Wave A Parity (Feb 15 2026)

Mobile port of Phase 26 Wave A. Backend unchanged; no schema, no endpoint,
no test additions. Web is untouched.

## Aggregate
- **New Expo screens: 3** (Dispatch Board, Weather Reschedule, Batch/Payroll CSV).
- **Mobile-only** — no `/app/frontend/` or `/app/backend/` changes.
- **Backend regression: 42/42 green** across `test_phase26_wave_a`,
  `test_phase26_polish_p21_audit`, `test_phase27_wave_b`, `test_phase28_warranties`,
  `test_checks`, `test_inventory`.
- **All 7 endpoints hit by the new screens return 200** as `admin@aquaterra.com`
  (curl-verified against the external ingress URL).

## Screens shipped

### 29A.1 · Dispatch Board — `/(app)/dispatch/board`
Mobile port of `/admin/dispatch`. Admin-only (backend enforces; UI hard-gates).
- View unassigned jobs (today or later) as vertical cards
- View every active technician (deduped by `user_id || id` to work around the
  known cosmetic dup in `GET /dispatch/technician-skills` — HANDOFF_P26_POLISH.md#40)
- One-tap "Auto-assign" per job → shows the winning tech + insertion cost
- Bulk "Auto-assign all" iterates unassigned jobs
- Toggle for `settings.dispatch.auto_assign_on_create`
- Deep-link tile to the Weather Reschedule screen

Endpoints hit: `GET /jobs?limit=500`, `GET /dispatch/settings`,
`GET /dispatch/technician-skills`, `POST /dispatch/auto-assign`,
`PUT /dispatch/settings`.

### 29A.2 · Weather Reschedule — `/(app)/dispatch/weather`
Mobile port of `/admin/dispatch/weather`. Admin-only.
- Mode picker: `manual` (propose only) vs `auto` (move immediately)
- Threshold summary (rain % / wind mph) — full editor stays on desktop
- "Run weather scan" button hits `POST /dispatch/weather-scan {}` → surfaces
  `{scanned, affected, mode}` in an inline toast
- Proposed-events list with rain %, wind mph, mode
- Per-event **Accept** (with optional YYYY-MM-DD override date input), **Reject**
- Decided-events list (last 20, read-only)

Endpoints hit: `GET /dispatch/weather-events`, `GET /dispatch/settings`,
`POST /dispatch/weather-scan`, `POST /dispatch/weather-events/{id}/accept`,
`POST /dispatch/weather-events/{id}/reject`, `PUT /dispatch/settings`.

### 29A.3 · Batch Checks + Payroll CSV — `/(app)/payroll/batch`
Mobile port of `/admin/checks/batch/new` and `/admin/checks/payroll`. Admin-only.
Two tabs in one screen so techs can flip without leaving the flow:

**Tab A · Manual batch**
- Horizontal chip picker for bank accounts (shows nickname + last 4 digits)
- Add-line cards — payee chip picker, amount, date (YYYY-MM-DD), memo
- Live "Batch total" tile
- Submit → `POST /checks/batch` → shows batch id + total → **Open PDF in browser**
  button opens `/checks/batch/{id}/print` via `Linking.openURL()`
- Fails fast with an honest error message if any line is missing payee or amount

**Tab B · Payroll CSV**
- Prominent "Template" button opens `GET /checks/payroll/template.csv`
- Pick a `.csv` via `expo-document-picker` → shows file name
- **Preview** — `POST /checks/payroll/import-csv?bank_account_id=X` (no `execute`)
- **Execute** — same endpoint with `execute=true`, only enabled after preview
- Preview card shows up to 20 rows with per-row `status` / `error` pills;
  warnings count called out honestly ("+N more on execute" for large batches)
- After execute → **Open PDF in browser** button

Endpoints hit: `GET /checks/bank-accounts`, `GET /checks/payees`,
`POST /checks/batch`, `POST /checks/batch/{id}/print` (opened via browser),
`GET /checks/payroll/template.csv`, `POST /checks/payroll/import-csv`.

## Navigation wiring
- **Mobile Tools Hub** (`/(app)/tools.tsx`) admin sections got two new groups:
  **Dispatch** (Dispatch Board, Weather Reschedule) and **Payroll**
  (Batch Checks & Payroll CSV).
- **`/(app)/more.tsx`** admin `Management` list now points the pre-existing
  **Dispatch** entry at `/(app)/dispatch/board` (was linking to the web
  `/dispatch` route) and adds **Weather Reschedule** + **Batch Checks & Payroll CSV**.
- **`/(app)/_layout.tsx`** — three new hidden `<Tabs.Screen>` registrations
  with `href: null` so the routes exist for `router.push()` but never render
  as tab-bar entries.

Tech Tools Hub gets nothing new (Phase 26 Wave A is admin-only by design).

## Honest-mocking / degradation
- `GET /jobs?limit=500` — accepts both list and paginated object shapes
  (`.items` / `.data`) — no silent fail.
- Every screen shows an "Admins only" lock state if a non-admin somehow lands
  on it (defense-in-depth; backend already enforces).
- Weather scan surfaces the raw `{scanned, affected, mode}` from the API
  instead of pretending "success" — matches the honest-mocking rule.
- CSV upload uses `multipart/form-data` via RN `FormData`; if `getAuthToken()`
  returns empty (never happens for a logged-in session, but guarded anyway),
  the request goes without an Authorization header and gets a 401 from the
  backend — the error message is bubbled up to the toast, not swallowed.
- Batch PDF is opened via `Linking.openURL()` (device browser). If the
  platform refuses the URL, the toast shows the exact URL so the admin can
  copy it — no silent no-op.

## Files touched

### New (3 screens)
- `mobile/app/(app)/dispatch/board.tsx`
- `mobile/app/(app)/dispatch/weather.tsx`
- `mobile/app/(app)/payroll/batch.tsx`

### Edited (4 files)
- `mobile/app/(app)/_layout.tsx` — three new hidden `<Tabs.Screen>` entries.
- `mobile/app/(app)/tools.tsx` — Dispatch + Payroll sections added to
  `ADMIN_SECTIONS`.
- `mobile/app/(app)/more.tsx` — retarget Dispatch link + add Weather /
  Batch entries under admin `Management`.
- `mobile/src/api.ts` — export `api_base()` + async `getAuthToken()` so the
  CSV multipart flow can attach the bearer without going through the JSON
  wrapper.

### Backend / DB / web
**Untouched.** As per the phase brief.

## Endpoint → Screen mapping (verified 200 as admin)

| Screen | Endpoint | Method | Status |
|---|---|---|---|
| Dispatch Board | `/api/jobs?limit=500` | GET | 200 (list of 29) |
| Dispatch Board | `/api/dispatch/settings` | GET / PUT | 200 |
| Dispatch Board | `/api/dispatch/technician-skills` | GET | 200 (3 items, deduped to 2 client-side) |
| Dispatch Board | `/api/dispatch/auto-assign` | POST | 200 (per job) |
| Weather | `/api/dispatch/weather-events` | GET | 200 (1 seeded proposal) |
| Weather | `/api/dispatch/weather-scan` | POST | 200 |
| Weather | `/api/dispatch/weather-events/{id}/accept` | POST | 200 |
| Weather | `/api/dispatch/weather-events/{id}/reject` | POST | 200 |
| Payroll | `/api/checks/bank-accounts` | GET | 200 (1 bank seeded) |
| Payroll | `/api/checks/payees` | GET | 200 (1 payee seeded) |
| Payroll | `/api/checks/batch` | POST | 200 |
| Payroll | `/api/checks/batch/{id}/print` | POST | Opened via `Linking` |
| Payroll | `/api/checks/payroll/template.csv` | GET | 200 |
| Payroll | `/api/checks/payroll/import-csv` | POST (multipart) | Preview or execute |

## Credentials for testing
No new accounts. Existing demo creds (all password `password123`):
- `admin@aquaterra.com` — full access to all three screens
- `mike@aquaterra.com` — tech; sees "Admins only" lock state on each
- `customer@aquaterra.com` — customer; can't reach the routes (Tools Hub
  hides them and each screen re-verifies role client-side)

`/app/memory/test_credentials.md` already lists these — no update needed.

## Known follow-ups (deferred, non-blocking)
- **Native date picker on Weather override input.** Currently a plain
  YYYY-MM-DD text field. `@react-native-community/datetimepicker` isn't in the
  package.json; adding it is a small polish PR.
- **Deep-link the PDF into `expo-sharing` instead of `Linking`.** Works today
  because `Linking.openURL()` picks up the device browser and the browser
  handles auth via the same cookie/token session, but a `Sharing.shareAsync()`
  path would let admins airdrop the PDF straight to a printer. Requires
  streaming the PDF into `FileSystem.cacheDirectory` first.
- **CSV column-mapper UI.** The desktop preview shows a full row-by-row
  table with per-column diagnostics. On mobile we cap at 20 rows and lean
  on the backend's row-level `status` / `error` fields. Full parity would
  need a horizontally-scrollable data-grid component.

## Not touched in this phase (per hard rules)
- Phase 29B / 29C — Wave B + Wave C mobile parity. **Stopped after 29A**
  as instructed.
- Backend endpoints, DB collections, cron jobs.
- Web pages under `/app/frontend/`.
- External GitHub repo — **never cloned or fetched.**
