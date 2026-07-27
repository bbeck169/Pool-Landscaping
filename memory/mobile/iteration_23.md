# Iteration 23 — Phase 27: Photo + Video Upload on Service Report

## Files Created (2)
- `src/api/serviceReportMedia.ts` — API helpers for upload + reorder endpoints, cap/limit constants, mime allowlists
- `src/components/checklist/ServiceReportMediaUploader.tsx` — Unified media grid component

## Files Modified (1)
- `app/job/[id]/checklist.tsx` — Imports, srPhotos/srVideos state, seed from report.media, renders ServiceReportMediaUploader card

## Dependencies Added
- `expo-video-thumbnails@57.0.1` — poster frame generation for video uploads

## Feature Details
- **Photo upload**: Camera + Library pickers, cap 10, validates PHOTO_MIMES (jpg/png/webp/heic), max 20MB
- **Video upload**: Record + Library pickers, cap 3, validates VIDEO_MIMES (mp4/mov/webm/m4v/avi), max 100MB, 60s duration
- **Duration validation**: Client-side check on `asset.duration` before upload, shows error message
- **Poster generation**: `VideoThumbnails.getThumbnailAsync(uri, { time: 500 })` — passes poster_url in form field
- **Upload**: XHR to `POST /api/service-reports/{reportId}/media` with progress callback
- **Reorder**: Long-press tile → enter reorder mode → up/down arrows → "Save order" calls `PATCH /api/service-reports/{reportId}/media/reorder`
- **Video playback**: Tap video tile → VideoPlayerModal

## testIDs (per delegation brief)
- `svc-report-media-uploader`, `svc-report-photo-picker`, `svc-report-photo-library`
- `svc-report-video-picker`, `svc-report-video-library`
- `svc-report-media-tile-{idx}`, `svc-report-media-reorder-handle-{idx}`
- `svc-report-video-duration-error`

## Deferred
- No delete-before-resubmit (per spec: "no delete-before-resubmit")
- No captions (per spec)
- Poster upload as separate form field (base64 or URI) — depends on backend handling the poster_url field
