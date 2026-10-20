# TD-88e · Mobile multi-select pre-flight audit

2026-10-19 · read-only · HEAD `45b952f12` · English

## 1. Call-site locations vs the handoff — all 6 match
| # | Handoff | Confirmed at HEAD | Function | Current options |
|---|---|---|---|---|
| 1 | `src/components/checklist/PhotoUploader.tsx:55` | ✅ L55 | `pick(false)` | `{ quality: 0.7, allowsEditing: true }` |
| 2 | `src/components/checklist/ServiceReportMediaUploader.tsx:72` | ✅ L72 | `pickPhoto(false)` | `{ quality: 0.7, mediaTypes: ["images"] }` |
| 3 | `…ServiceReportMediaUploader.tsx:120` (video, **SKIP**) | ✅ L120 | `pickVideo(false)` | `{ mediaTypes: ["videos"], allowsEditing: false, quality: 1 }` |
| 4 | `src/components/checklist/PoolChecklistForm.tsx:302` | ✅ L302 | **`analyzeWater()`** | `{ quality: 0.6, base64: true }` — ⚠ see §4 |
| 5 | `app/job/[id].tsx:303` | ✅ L303 | `pickPhoto("library")` | shared `opts = { quality: 0.7, allowsEditing: true }` (L298) |
| 6 | `app/job/[id]/checkin.tsx:92` | ✅ L92 | `pickPhoto("library")` | shared `opts = { quality: 0.7, allowsEditing: false }` (L89) |

## 2. Cap source + count accessor per surface
| Surface | Cap source | Count accessor | Behaviour at cap today | Upload pipeline |
|---|---|---|---|---|
| PhotoUploader (landscaping/pool checklist "Internal Photos") | `max` prop, default 10 (L40). Mounted with `max={PHOTO_CAP}`, where `PHOTO_CAP = 10` is local to `app/job/[id]/checklist.tsx:81`. | `photos.length` → `remaining` (L43) | Library/Photo buttons hidden (`remaining > 0`, L106); `pick` returns silently (L47). **No error text exists.** | `capturePhoto(uri,"job",jobId)` (photoWorker), then refresh via `getPhotosForEntity` |
| ServiceReportMediaUploader (Visit Media, photos) | `PHOTO_CAP = 10` — `src/api/serviceReportMedia.ts:25` | `photos.length` (`photoCount`, L54) | `Alert "Limit reached" / "Maximum 10 photos per visit."` (L60-62) ✅ existing error | Per-asset MIME check → `uploadServiceReportMedia` (progress) → `onPhotosChange([...photos, new])` |
| PoolChecklistForm `analyzeWater` | none — single photo by design | n/a | n/a | base64 → `POST /jobs/{id}/photos` → `POST /service-report/analyze-water-photo` → one `analysis` result |
| Job detail (`app/job/[id].tsx`) | `MAX_PHOTOS = 10` — local const, L271 | `photoCount = job.photos.length + pendingPhotos.length` (L273). Note: the header shows `displayPhotoCount`, which also includes SR photos (L284). | Add button replaced by `photo-cap-reached` "10/10 limit" text (L676-684) ✅ existing indicator | `capturePhoto` per asset, then `setPendingPhotos(getPhotosForEntity)` |
| Check-in (`app/job/[id]/checkin.tsx`) | `MAX_PHOTOS = 5` — L29 | `photos.length` (PhotoSlot[]) | Add button hidden (L415); `pickPhoto` returns silently (L80) | Per-slot `uploadFile(purpose:"public_checkin")` with progress keyed by slot index. **Needs care:** `idx = photos.length` is a stale closure (L106); a loop must use `base + i` |

No surface lacks a cap, so the default hard cap of 10 isn't needed anywhere.

## 3. expo-image-picker API check (installed 17.0.11 = `~17.0.11`)
- `launchImageLibraryAsync(options?: ImagePickerOptions): Promise<ImagePickerResult>`, with `allowsMultipleSelection?: boolean`, `selectionLimit?: number` (0 = unlimited) and `orderedSelection?` (iOS 15+).
- `MediaType = 'images' | 'videos' | 'livePhotos'`, so `mediaTypes?: ImagePicker.MediaType[]` is valid. `quality` and `base64` pass through.
- `allowsEditing` is ignored or mutually exclusive when `allowsMultipleSelection` is on (types L380-381), so the proposed helper that drops it is correct.
- **Caveat:** `ExponentImagePicker.web` destructures only `{ mediaTypes, allowsMultipleSelection, base64 }`, so **`selectionLimit` is ignored on web**, and older Android pickers don't enforce it either. The helper must also `slice(0, remainingCap)` the returned assets.
- `requestMediaLibraryPermissionsAsync()` → `{ granted, canAskAgain }`. The helper returns `null` when not granted, but callers own the UX: `job/[id]` opens a settings sheet when `!canAskAgain`, and `checkin` shows a toast. **Proposal:** the helper returns `null` for denial, and callers that need `canAskAgain` keep their own permission prompt before calling it. Alternatively the helper can expose an optional `onDenied(perm)` callback (decision below).
- The signature matches the handoff as proposed.

## 4. ⚠ Invariant break — STOP
- **`PoolChecklistForm.tsx:302` `analyzeWater` is a single-photo AI action, not a gallery.** One test-strip photo is uploaded, one `analyze-water-photo` call is made, and one `analysis` state is rendered. Multi-select would mean either N billable AI calls with only the last result kept, or a silent drop of every photo but the first.
- Options:
  - **A (recommended default):** exclude it — keep its single-pick and ship 4 migrated sites.
  - **B:** route it through `pickImagesMulti({ remainingCap: 1, quality: 0.6, base64: true })`. Same behaviour, but uses the shared helper. Small risk: some iOS/Android pickers still show a multi-select UI with a "1 max" badge.
  - **C:** multi-analyze. Not recommended (AI cost, needs a UX design).

## 5. Other notes
- **Silent at-cap surfaces:** PhotoUploader and checkin have no "max reached" error text; they hide the button. The ship keeps hiding it, plus a defensive `remainingCap < 1` guard (no picker opens). It does not add new error copy unless you ask.
- **Other gallery-type library pickers NOT in the handoff** (flagged, not migrated):
  - `app/(app)/service-report/[id].tsx:154` — SR photos, cap 10, `Alert "Photo cap"`; a natural candidate.
  - `src/components/files/FileUpload.tsx:175`
  - `app/(app)/chat.tsx:208`
  - `app/portal/chats/[id].tsx:300`
  - `app/(app)/estimator/new.tsx:51`
  - `app/(app)/before-after.tsx:39`
  - `app/equipment.tsx:74` already uses multi-select (limit 5).
- **Single-photo by design** (correctly out of scope): avatars or logos (`customer/new`, `portal/profile`, `card`, `settings/business`), `landscape.tsx:128` (yard visualizer), `ServiceIssues`, `MaintenanceLog`, the equipment unit photo.
- **Camera paths:** untouched, as instructed.
- **Video (`ServiceReportMediaUploader.tsx:120`):** skipped, as instructed. Opting in later means switching it to `pickImagesMulti({ remainingCap: VIDEO_CAP - videoCount, mediaTypes: ["videos"], quality: 1 })` plus a loop.
- **Existing tests to extend:** `tech-checkin-mobile.test.ts` (checkin), `m3-internal-media-relabel` / `f2a-job-photos` (job detail / uploader). The helper gets a new unit suite.

## 6. Ship receipt (2026-10-20)
- **Decision:** the operator's reply was "Assume default and continue", so per the TD-61 auto-ack addendum the posted defaults apply:
  - `analyzeWater` stays single-pick (option A).
  - The helper returns `null` on denial; callers keep their own permission UX.
  - No new "max reached" copy.
  - `service-report/[id].tsx:154` stays excluded.
- **Commits:**
  - `4f80f138f` m-td88e-helper: `src/lib/pickImages.ts` + `__tests__/td88e-pick-images-multi.test.ts` (7 tests)
  - `305335a67` m-td88e-migrate: 4 sites + `__tests__/td88e-multiselect-surfaces.test.tsx` (9 tests)
- **Migrated:** `PhotoUploader.tsx` (L55), `ServiceReportMediaUploader.tsx` photo (L72), `app/job/[id].tsx` (L303), `app/job/[id]/checkin.tsx` (L92). Library picks go through `pickImagesMulti`, with `remainingCap = cap - count`, a per-asset loop through the existing pipeline, and `allowsEditing` dropped.
- **Unchanged:**
  - Camera paths: single-shot.
  - `PoolChecklistForm.tsx:302` `analyzeWater`: single photo by design.
  - SR video (`ServiceReportMediaUploader.tsx` ~L135): opting in is a 1-line switch to `pickImagesMulti({ remainingCap: VIDEO_CAP - videoCount, mediaTypes: ["videos"], quality: 1 })` plus a loop.
- **Per-surface behaviour notes:**
  - SR media: the list is accumulated locally, so every upload lands. Unsupported MIME types are skipped with the existing error, and `OfflineError` stops the batch.
  - Check-in: slot index = `base + i`, which fixes the stale-closure risk.
  - PhotoUploader: per-asset failures are counted and reported once.
- **Verification:**
  - Jest: full suite 42 failed suites / 48 failed tests = baseline (2529 passed, +16 new).
  - tsc: 651 = baseline.
  - eslint: clean (one pre-existing unused-var warning in PhotoUploader).
- **Live preview (Expo web, admin, job `ebb84565…` "LL-timer" checklist):**
  - The Library tap opens a file chooser with `multiple = true`, and picking 3 files gives 3 pipeline runs: 3× `POST /service-reports/{id}/media`.
  - **No end-to-end upload on web — an existing web-only limitation, not caused by this ship.**
    - `serviceReportMedia.ts` and `files.ts` append the React Native `{uri,name,type}` FormData object, which a browser serialises as a string. The backend answers 422 "Expected UploadFile, received str", and single-pick at HEAD fails the same way.
    - `PhotoUploader` and job detail go through photoWorker, whose SQLite layer is a no-op stub on web (`db.web.ts`).
  - So "3 photos appear", "at cap" and "cancel" were checked by Jest render tests, plus the live picker-level check above. **Device reproduction (iOS simulator / Android) is still the operator's step;** no simulator is available in this pod.
- **Possible follow-up:** make the mobile upload clients web-capable (fetch the uri → Blob → `form.append("file", blob, name)` when `Platform.OS === "web"`). Needs a TD number.
