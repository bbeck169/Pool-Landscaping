# Iteration 81 — P0 Tech Close Job 429 Fix

## What was implemented

### 1) Exponential backoff + jitter for 429s
- Created `src/services/retryWithBackoff.ts` — generic async retry with:
  - Base delay 2s, cap 30s, max 5 retries
  - ±25% jitter on each backoff step
  - Honors `Retry-After` header (from `ApiError.retryAfterSeconds`) on the first retry
  - Honors `detail.retry_after_seconds` from JSON body (app-minted 429s)
  - `onRetry(attempt, delayMs)` callback for pill state updates
  - Only retries 429 and `ApiNetworkError` — non-retryable errors (400, 401, etc.) throw immediately
- Updated `api.ts` `ApiError` class with `retryAfterSeconds` and `rateLimitSource` fields, populated from `Retry-After` and `X-Ratelimit-Source` response headers on 429

### 2) Fixed contradictory pill state
- Created `src/components/sync/ChecklistSavePill.tsx` — single unified pill with 5 mutually-exclusive states:
  - "Saving…" (blue, spinner)
  - "Save error — retrying 2/5" (amber)
  - "Save error — tap to retry" (red)
  - "Online · Synced" (green)
  - "Offline · Queued (N)" (orange)
- Removed the old dual-pill system (checklist-autosave-pill + checklist-network-pill) from `checklist.tsx`
- Added `useEffect` derivation: priority = saving > retrying > exhausted > syncing > offline > synced

### 3) Offline queue for close-job
- When 429 retries exhaust on close-job, the payload is enqueued to `writeQueue` so it's not lost
- When offline at close time, existing `submitOffline()` flow is preserved
- `retryWithBackoff` is used for both the autosave PATCH and the close-job POST

### 4) Error dialog
- Added `job-close-error-dialog` modal after 5 retries fail with "Try again" and "Dismiss" buttons
- testIDs: `job-close-error-dialog`, `job-close-error-retry`, `job-close-error-dismiss`

## Files modified
- `src/api.ts` — Extended ApiError with retryAfterSeconds, rateLimitSource
- `src/services/retryWithBackoff.ts` — New file
- `src/components/sync/ChecklistSavePill.tsx` — New file
- `app/job/[id]/checklist.tsx` — Replaced dual pills, added retryWithBackoff to close/autosave, added error dialog
- `__tests__/p0-429-retry.test.tsx` — 12 tests

## Test results
- 12/12 tests passing:
  - retryWithBackoff: honors Retry-After, throws after 5 retries, no retry on 400, retries on network error, succeeds first try
  - ChecklistSavePill: all 5 states render correctly, exactly one pill at a time
  - ApiError: 429 metadata fields present

## Existing infrastructure reused
- `writeQueue.ts` (AsyncStorage queue) — reused for offline enqueue on exhausted retries
- `offlineWrite.ts` — wrap autosave with retryWithBackoff inside the onlineFn
- `submitOffline()` — preserved for offline close-job path
- `useOnline()` hook — drives offline detection for pill state
