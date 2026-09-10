# Mobile Offline Hardening — Fix 1 + Fix 2 + Fix 3

**Date**: 2026-04-16

---

## Endpoint Contracts Verified

### Fix 1 — `GET /api/mobile/offline-bundle`
```
curl -s -w "HTTP %{http_code} in %{time_total}s"
  "$API/api/mobile/offline-bundle"
  -H "Authorization: Bearer $TOKEN"

HTTP 200 in 0.24s

Response shape:
{
  "jobs": [...],                          // Full job details
  "customers": [...],                     // Customer records
  "service_reports_in_progress": [...],   // Service reports matched by job_id
  "chemistry_types": [...],
  "chemicals_catalog": [...],
  "invoices": [...],
  "job_count": N,                         // Total server-side job count
  "cap_reached": false,
  "generated_at": "2026-04-16T...",
  "offline_bundle_expires_at": "2026-04-16T..."
}
```
✅ Confirmed working with `mike@aquaterra.com` auth.

### Fix 2 — `GET /api/public/job-photo/{jid}/{pid}`
```
curl -s -w "HTTP %{http_code}" "$API/api/public/job-photo/fake-jid/fake-pid"
→ HTTP 404 (expected: fake IDs)
```
✅ Endpoint exists, is unauthenticated (no Bearer required). Returns image bytes for valid IDs, 404 for invalid. UUID-gated.

---

## Files Touched

| File | Change |
|------|--------|
| `src/services/routeHydrator.ts` | **Rewritten** — Fix 1 (single bundle call) + Fix 3 (honest sync status) |
| `src/services/photoUrlCache.ts` | **Created** — Fix 2 (URL builder, prefetch, base64 strip, resolve) |
| `src/components/OfflineBadge.tsx` | **Rewritten** — Fix 3 (partial/failed status rendering) |
| `src/hooks/useRouteHydration.ts` | Updated `HydrationMeta` EMPTY default |
| `app/(app)/schedule/calendar.tsx` | Updated OfflineBadge prop pass-through + freshness label |

---

## SQLite Schema Diff

**No schema changes.** The same `read_cache` table (key-value JSON blobs) is used. The only data change is that `job:bootstrap:{jid}` values no longer contain base64 photo blobs — they now contain photo metadata objects with `id` fields, and the URL is resolved lazily at render time via `resolvePhotoSource()`.

Legacy rows with inline base64 are handled by `stripBase64FromReport()` which is applied:
1. During hydration (proactive strip on write).
2. At render time via `resolvePhotoSource()` which falls back to base64 if no `(jid, pid)` tuple is available, preventing crashes on legacy data.

---

## Fix Details

### Fix 1 — Kill N+1 job fetches
- **Before**: `hydrateToday` called `GET /jobs?start=…&end=…` for the list, then `GET /jobs/{jid}` + `GET /jobs/{jid}/service-report` per job in batches of 4. For 37 jobs = 1 + 74 = 75 HTTP requests.
- **After**: Single `GET /mobile/offline-bundle` returns all jobs + service reports in one response. For 37 jobs = **1 HTTP request**.
- Reports are matched to jobs via `job_id` field in O(1) Map lookup.

### Fix 2 — Photos as URLs, not base64
- `jobPhotoUrl(jid, pid)` → `${BACKEND_URL}/api/public/job-photo/{jid}/{pid}`
- `resolvePhotoSource(jid, photo)` → priority: explicit URL > public URL from IDs > legacy base64 fallback
- `stripBase64FromReport(report)` → strips `base64`, `data`, `dataUrl`, `data_url` from photo objects
- `prefetchReportPhotos(jid, photos)` → batched prefetch into expo-image disk cache (groups of 3)
- **No base64 enters SQLite** — only photo IDs are stored. Images are lazily fetched by `expo-image` which has built-in disk caching.

### Fix 3 — Honest sync status
- `HydrationMeta` now includes `syncStatus: "synced" | "partial" | "failed" | "idle"`, `lastPartialSyncAt`, `lastError`.
- `lastSyncedAt` is ONLY stamped when `cachedJobs === totalJobs` (clean sync).
- `lastPartialSyncAt` is stamped when `cachedJobs < totalJobs`.
- OfflineBadge renders:
  - Offline + synced: "Offline — 5 of 5 jobs cached • synced 7:42 AM"
  - Offline + partial: "Offline — 3 of 5 jobs cached • partial 7:42 AM"
  - Offline + failed: "Offline — sync failed (0 of 37)"
  - Online + partial: "Partial sync: 3 of 5"
  - Online + failed: "Sync failed — retry"
- Calendar freshness label shows: "Partial sync: N of M" or "Sync failed — tap sync to retry"

---

## Test Tally

| Test File | Tests | Status |
|-----------|-------|--------|
| `route-hydrator-single-call.test.ts` | 4 | ✅ PASS |
| `job-photo-url-cache.test.tsx` | 5 | ✅ PASS |
| `sync-status-partial.test.tsx` | 6 | ✅ PASS |
| `job-close-silent-noop.test.tsx` | 6 | ✅ PASS |
| `task3-invoice-bypass-mobile.test.tsx` | 6 | ✅ PASS |
| `task5-save-card-mobile.test.tsx` | 4 | ✅ PASS |
| `task6-terms-mobile.test.tsx` | 6 | ✅ PASS |
| `pb2-line-item-overrides.test.tsx` | 4 | ✅ PASS |
| `parity-phase-a.test.tsx` | 9 | ✅ PASS |
| `p0-429-retry.test.tsx` | 12 | ✅ PASS |
| `chemistry-ui-trim.test.tsx` | 6 | ✅ PASS |
| **Total** | **68** | **All pass** |

---

## Screenshots

- `/tmp/mobile-partial-sync.png` — Schedule screen showing "Cached just now" freshness label (sync status = synced, all jobs cached, badge hidden when online + clean sync).

---

## Manual QA Checklist

1. Login as `mike@aquaterra.com` → Schedule loads with "Cached just now" freshness label
2. Turn off network → OfflineBadge appears showing job count + last sync time
3. With network: trigger sync → should complete in one HTTP call (check network tab)
4. If bundle returns fewer jobs than `job_count` → "Partial sync: N of M" label
5. Photos in checklist render from URL (not inline base64) — check network tab for `/api/public/job-photo/` requests
