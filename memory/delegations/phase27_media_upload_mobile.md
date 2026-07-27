# Delegation Brief · e1_expo_frontend_dev · Phase 27

**From:** Web team (Phase 27 · Feb 2026)
**To:** Expo mobile frontend
**Priority:** P1
**Status:** Web slice shipped. Mobile parity blocked on your side.

## Context
We just shipped service-report media upload (photos + videos) end-to-end on the web:

- **Backend endpoints (all live on preview, ready for prod after redeploy):**
  - `POST /api/service-reports/{report_id}/media` — multipart upload of a photo OR video. Form fields: `file` (required), `kind` = `photo|video` (optional — inferred from mime), `poster_url` (optional — video only). Header `X-Video-Duration` (seconds, float) required for videos.
  - `PATCH /api/service-reports/{report_id}/media/reorder` — JSON `{photo_order: [url, ...], video_order: [url, ...]}` — persists the array order verbatim; entries not referenced are appended so nothing is lost.
  - `GET /api/public/service/{uuid}` — now returns `videos: [{url, poster_url, duration_seconds, content_type}]` alongside `images`.
  - `GET /api/public/service/{uuid}/video/{video_id}` — public streaming (no auth) — the URL emitted by the upload endpoint on video rows.

- **Caps enforced server-side:**
  - Photos: max **10 per report**
  - Videos: max **3 per report**
  - Video duration: max **60 seconds** (rejected 400 if `X-Video-Duration` > 60)
  - File size: max 100 MB videos, 20 MB photos
  - Mime allowlist:
    - Photos: `image/jpeg`, `image/png`, `image/webp`, `image/heic`, `image/heif`
    - Videos: `video/mp4`, `video/quicktime`, `video/webm`, `video/x-m4v`, `video/avi`, `video/x-msvideo`

## Ask
Add video capture / picker + drag-reorder + upload to the Expo tech checkout screen.

## Behavior spec
1. **Video picker** — add a "Record video" or "Pick video" action alongside the existing photo picker in the service report screen. Use `expo-image-picker` (`ImagePicker.launchCameraAsync({ mediaTypes: MediaTypeOptions.Videos, videoMaxDuration: 60, allowsEditing: true })`).
2. **Client-side duration validation** — reject > 60s before uploading. Read duration via `expo-av`'s `Video.createAsync(...)` or use the `duration` field returned by `expo-image-picker` (available in SDK 49+).
3. **Client-side cap check** — before upload, count existing photos + videos on the current report and refuse when the corresponding cap would be exceeded. Show a toast: "Maximum 3 videos per visit — delete one first."
4. **Upload** — POST multipart to `${EXPO_PUBLIC_BACKEND_URL}/api/service-reports/{id}/media` with header `X-Video-Duration: {seconds}`. Include `kind=video` in the form so ambiguous mimes are handled correctly.
5. **Poster generation** — try `expo-video-thumbnails` (`VideoThumbnails.getThumbnailAsync(uri, { time: 500 })`) to grab a first-frame image, upload it to your usual image endpoint, and pass its URL as `poster_url` form field. If the module isn't installed or the call fails, skip — the backend accepts null poster and the web portal renders a solid dark tile with a play icon.
6. **Drag-reorder** — provide reorder handles on the media pool. On save, POST to `PATCH /api/service-reports/{id}/media/reorder` with `photo_order` + `video_order` (arrays of URLs).
7. **Playback preview** — in the tech's own review view, tap a video thumbnail → open native `<Video>` playback. In production the customer will see the same media via the public portal (`/portal/service/{public_uuid}`) that the web team just shipped.

## Sharing (from Phase 22.b)
The "Share visit" button that copies `${origin}/portal/service/{public_uuid}` to clipboard is still relevant — the same public portal now renders videos with a play-icon overlay + native `<video>` lightbox. No change on your side except that shared links will now include videos.

## data-testid
Use these test IDs for parity with the web contract:
- `svc-report-photo-picker`, `svc-report-video-picker`
- `svc-report-media-tile-{index}`
- `svc-report-media-reorder-handle-{index}`
- `svc-report-video-duration-error` (toast for > 60s rejects)

## Guardrails
- Do NOT hardcode URLs — use `EXPO_PUBLIC_BACKEND_URL` (already in your `.env` alias set).
- Do NOT touch backend endpoints; they are stable.
- Do NOT install ffmpeg or shell out — use `expo-video-thumbnails` for poster generation.
- If `expo-video-thumbnails` requires a native module rebuild that would break your OTA flow, DEFER poster generation to a follow-up and ship without it.

## Web references
- Backend endpoint source: `/app/backend/routers/service_report_media.py`
- Public portal page (video lightbox + play-icon overlay): `/app/frontend/src/pages/public/ServiceImagesPortalPage.jsx`
- Merge tag renderer including video posters: `/app/backend/services/marketing/merge_tags.py::_service_record_images`
- Vitest coverage: `/app/frontend/src/test/phase27-portal-sections.test.jsx`

## Deployment
No prod redeploy needed on the mobile side until this ships as part of a normal mobile release cadence. Backend is live on preview and will be live on prod after the next web deploy (user handles).
