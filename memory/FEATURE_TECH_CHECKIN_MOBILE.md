# Feature: Technician Check-In Flow (Mobile)

## Summary
New "Log Check-In" button on Job Detail → opens a Check-In composer with GPS, note, and photo capture → two-step submission to backend (`POST /checkins` then `POST /checkins/{id}/submit-public`).

## Files Touched

| File | Changes |
|------|---------|
| `app/job/[id].tsx` | Added "Log Check-In" button (`job-detail-log-checkin-btn`), navigates to `/job/{id}/checkin` |
| `app/job/[id]/checkin.tsx` | **NEW** — Full Check-In composer screen |
| `__tests__/tech-checkin-mobile.test.ts` | **NEW** — 28 test cases |

## Route
`/job/{id}/checkin` — file-based Expo Router route via `app/job/[id]/checkin.tsx`

## TestID Map

### Job Detail
| Element | testID |
|---------|--------|
| Log Check-In button | `job-detail-log-checkin-btn` |

### Check-In Composer
| Element | testID |
|---------|--------|
| Back button | `checkin-back-btn` |
| GPS section | `checkin-gps-section` |
| GPS loading indicator | `checkin-gps-loading` |
| GPS status text | `checkin-gps-status` |
| GPS recapture button | `checkin-gps-recapture-btn` |
| Note section | `checkin-note-section` |
| Note input (multiline) | `checkin-note-input` |
| Photo section | `checkin-photo-section` |
| Photo picker container | `checkin-photo-picker` |
| Photo thumbnail (per-index) | `checkin-photo-thumb-{i}` |
| Photo remove button (per-index) | `checkin-photo-remove-{i}` |
| Photo retry button (per-index) | `checkin-photo-retry-{i}` |
| Camera button | `checkin-photo-camera-btn` |
| Library button | `checkin-photo-library-btn` |
| Photo error message | `checkin-photo-error` |
| Submit button | `checkin-submit-btn` |
| Scroll container | `checkin-scroll` |

## Two-Step Submission Sequence

### Step 1: Create Check-In
```
POST /api/checkins
{
  job_id: string,
  latitude: number,
  longitude: number,
  note: string,           // 1..2000 chars
  photo_file_ids: string[] // 1..5, uploaded via /api/files/upload
}
→ { id: string, ... }
```
**On failure**: Error toast, stay on composer with input intact.

### Step 2: Submit for Public Review
```
POST /api/checkins/{checkin_id}/submit-public
{}
→ 200 OK
```
**On success**: Toast "Check-in submitted for review", navigate back.
**On failure**: Warning toast "Check-in saved but not submitted for review — retry later", navigate back (check-in in draft state).

## Photo Upload Flow
- Reuses `uploadFile` from `@/src/api/files` (same S3 pipeline as other attachments)
- Each photo uploaded with `purpose: "public_checkin"`
- Upload progress tracked per-photo (0–100%)
- Failed uploads show retry overlay
- Submit blocked until all photos successfully uploaded
- Min 1, max 5 photos

## GPS Capture
- Uses `geolocate()` from `@/src/utils/geolocate` (same as arrival detection)
- Auto-captures on mount with 6s timeout
- "Recapture" button for re-acquisition
- GPS lock required before Submit enabled

## Validation (Submit disabled until all met)
1. GPS locked (lat + lng non-null)
2. Note non-empty and ≤ 2000 chars
3. ≥ 1 photo uploaded successfully (no pending uploads, no errors)

## Coupling with Backend
- Backend contract from `FEATURE_TECH_CHECKIN_BACKEND.md`
- `POST /api/checkins` expects `photo_file_ids[]` (1–5 IDs from `/api/files/upload`)
- `POST /api/checkins/{id}/submit-public` resolves lat_public/lng_public on backend side
- Photo files stored in S3 with `purpose='public_checkin'`
