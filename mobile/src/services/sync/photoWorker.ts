/**
 * Phase O3 · Photo pipeline worker.
 *
 * Manages the full lifecycle:
 *   1. Capture → downscale via expo-image-manipulator (2048px, 0.85 JPEG)
 *   2. Stage to `documentDirectory/photos/pending/{uuid}.jpg`
 *   3. Insert row into SQLite `photos_pending` table
 *   4. Upload to `POST /jobs/{jid}/photos` with client_uuid + X-Idempotency-Key
 *   5. On success: delete local file
 *   6. On 3+ failures: mark `stalled`
 *   7. Orphan cleanup: purge photos whose parent entity was deleted
 */
import * as FileSystem from "expo-file-system/legacy";
import { manipulateAsync, SaveFormat } from "expo-image-manipulator";
import { getSyncDb } from "./db";
import { clientUuid } from "../ids/clientUuid";
import { isOnlineNow, on } from "./netBus";
import { api } from "@/src/api";

// ─── constants ─────────────────────────────────────────────────────
const MAX_SIDE = 2048;
const JPEG_QUALITY = 0.85;
const MAX_UPLOAD_ATTEMPTS = 3;
const PHOTOS_DIR = `${FileSystem.documentDirectory}photos/pending/`;

// ─── types ─────────────────────────────────────────────────────────
export type PendingPhoto = {
  id: string;
  local_uri: string;
  entity_type: string;
  entity_id: string;
  upload_status: "pending" | "uploading" | "uploaded" | "stalled";
  upload_attempts: number;
  last_error: string | null;
  created_at: string;
};

// ─── listeners ─────────────────────────────────────────────────────
type PhotoListener = () => void;
const _listeners = new Set<PhotoListener>();
function _notify() {
  _listeners.forEach((l) => { try { l(); } catch { /* ignore */ } });
}
export function subscribePhotos(listener: PhotoListener): () => void {
  _listeners.add(listener);
  return () => { _listeners.delete(listener); };
}

// ─── auto-upload on reconnect ──────────────────────────────────────
let _autoWired = false;
export function wirePhotoAutoUpload(): void {
  if (_autoWired) return;
  _autoWired = true;
  on("network:online", () => {
    setTimeout(() => { flushPhotos().catch(() => {}); }, 2000);
  });
}

// ─── ensure dir ────────────────────────────────────────────────────
async function ensureDir(): Promise<void> {
  const info = await FileSystem.getInfoAsync(PHOTOS_DIR);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(PHOTOS_DIR, { intermediates: true });
  }
}

// ─── 1. Capture + downscale ────────────────────────────────────────
/**
 * Given a raw image URI (from camera/picker), downscale to 2048px
 * longest side, save as JPEG 0.85, return the staged local path.
 */
export async function downscaleAndStage(rawUri: string): Promise<{
  stagedUri: string;
  photoId: string;
}> {
  await ensureDir();
  const photoId = clientUuid();
  const destPath = `${PHOTOS_DIR}${photoId}.jpg`;

  const result = await manipulateAsync(
    rawUri,
    [{ resize: { width: MAX_SIDE } }],
    { compress: JPEG_QUALITY, format: SaveFormat.JPEG },
  );

  // Move from tmp to persistent staging directory.
  await FileSystem.moveAsync({ from: result.uri, to: destPath });

  return { stagedUri: destPath, photoId };
}

// ─── 2. Insert into photos_pending ─────────────────────────────────
export async function insertPendingPhoto(
  photoId: string,
  localUri: string,
  entityType: string,
  entityId: string,
): Promise<void> {
  const db = await getSyncDb();
  const now = new Date().toISOString();
  await db.runAsync(
    `INSERT INTO photos_pending
       (id, local_uri, entity_type, entity_id, upload_status, upload_attempts, created_at)
     VALUES (?, ?, ?, ?, 'pending', 0, ?)`,
    [photoId, localUri, entityType, entityId, now],
  );
  _notify();
}

// ─── 3. Full capture pipeline ──────────────────────────────────────
/**
 * Single entry point: downscale → stage → insert → trigger upload.
 * Returns the photo's client UUID for UI attachment.
 */
export async function capturePhoto(
  rawUri: string,
  entityType: string,
  entityId: string,
): Promise<string> {
  const { stagedUri, photoId } = await downscaleAndStage(rawUri);
  await insertPendingPhoto(photoId, stagedUri, entityType, entityId);

  // If online, immediately try uploading.
  if (isOnlineNow()) {
    flushPhotos().catch(() => {});
  }

  return photoId;
}

// ─── 4. Upload worker ──────────────────────────────────────────────
let _photoFlushing = false;

export async function flushPhotos(): Promise<{
  uploaded: number;
  stalled: number;
}> {
  if (_photoFlushing) return { uploaded: 0, stalled: 0 };
  _photoFlushing = true;
  _notify();

  const result = { uploaded: 0, stalled: 0 };

  try {
    const db = await getSyncDb();
    const pending = await db.getAllAsync<PendingPhoto>(
      `SELECT * FROM photos_pending
       WHERE upload_status = 'pending'
       ORDER BY created_at ASC`,
    );

    for (const photo of pending) {
      if (!isOnlineNow()) break;

      // Mark uploading.
      await db.runAsync(
        `UPDATE photos_pending SET upload_status = 'uploading' WHERE id = ?`,
        [photo.id],
      );
      _notify();

      try {
        // Read file as base64.
        const base64 = await FileSystem.readAsStringAsync(photo.local_uri, {
          encoding: FileSystem.EncodingType.Base64,
        });
        const dataUrl = `data:image/jpeg;base64,${base64}`;

        // Upload to server.
        await api.post(
          `/jobs/${photo.entity_id}/photos`,
          {
            data: dataUrl,
            label: `photo-${photo.id}`,
            client_uuid: photo.id,
          },
          60000,
          { "X-Idempotency-Key": `photo:${photo.id}` },
        );

        // Mark uploaded.
        await db.runAsync(
          `UPDATE photos_pending SET upload_status = 'uploaded' WHERE id = ?`,
          [photo.id],
        );
        result.uploaded++;

        // Cleanup local file.
        try {
          await FileSystem.deleteAsync(photo.local_uri, { idempotent: true });
        } catch { /* non-fatal */ }
      } catch (e: any) {
        const attempts = photo.upload_attempts + 1;
        const errMsg = (e?.message || "Upload failed").slice(0, 500);

        if (attempts >= MAX_UPLOAD_ATTEMPTS) {
          await db.runAsync(
            `UPDATE photos_pending SET upload_status = 'stalled',
               upload_attempts = ?, last_error = ?
             WHERE id = ?`,
            [attempts, errMsg, photo.id],
          );
          result.stalled++;
        } else {
          await db.runAsync(
            `UPDATE photos_pending SET upload_status = 'pending',
               upload_attempts = ?, last_error = ?
             WHERE id = ?`,
            [attempts, errMsg, photo.id],
          );
        }
      }
      _notify();
    }
  } finally {
    _photoFlushing = false;
    _notify();
  }

  return result;
}

// ─── 5. Retry stalled ──────────────────────────────────────────────
export async function retryStalled(photoId: string): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE photos_pending SET upload_status = 'pending',
       upload_attempts = 0, last_error = NULL
     WHERE id = ? AND upload_status = 'stalled'`,
    [photoId],
  );
  _notify();
  flushPhotos().catch(() => {});
}

export async function retryAllStalled(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE photos_pending SET upload_status = 'pending',
       upload_attempts = 0, last_error = NULL
     WHERE upload_status = 'stalled'`,
  );
  _notify();
  flushPhotos().catch(() => {});
}

// ─── 6. Query helpers ──────────────────────────────────────────────
export async function getPendingPhotos(): Promise<PendingPhoto[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingPhoto>(
    `SELECT * FROM photos_pending WHERE upload_status IN ('pending', 'uploading')
     ORDER BY created_at ASC`,
  );
}

export async function getStalledPhotos(): Promise<PendingPhoto[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingPhoto>(
    `SELECT * FROM photos_pending WHERE upload_status = 'stalled'
     ORDER BY created_at ASC`,
  );
}

export async function getPhotosForEntity(
  entityId: string,
): Promise<PendingPhoto[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingPhoto>(
    `SELECT * FROM photos_pending WHERE entity_id = ?
     ORDER BY created_at ASC`,
    [entityId],
  );
}

// ─── 7. Orphan cleanup ────────────────────────────────────────────
/**
 * Purge all pending photos for an entity.  Call this when a service
 * report is deleted locally before its photos were uploaded.
 */
export async function purgePhotosForEntity(entityId: string): Promise<void> {
  const db = await getSyncDb();
  const photos = await db.getAllAsync<PendingPhoto>(
    `SELECT * FROM photos_pending WHERE entity_id = ?`,
    [entityId],
  );

  for (const photo of photos) {
    try {
      await FileSystem.deleteAsync(photo.local_uri, { idempotent: true });
    } catch { /* file may already be gone */ }
  }

  await db.runAsync(
    `DELETE FROM photos_pending WHERE entity_id = ?`,
    [entityId],
  );
  _notify();
}

// ─── 8. Cleanup uploaded ──────────────────────────────────────────
export async function cleanupUploaded(): Promise<number> {
  const db = await getSyncDb();
  const uploaded = await db.getAllAsync<PendingPhoto>(
    `SELECT * FROM photos_pending WHERE upload_status = 'uploaded'`,
  );
  for (const photo of uploaded) {
    try {
      await FileSystem.deleteAsync(photo.local_uri, { idempotent: true });
    } catch { /* already gone */ }
  }
  await db.runAsync(
    `DELETE FROM photos_pending WHERE upload_status = 'uploaded'`,
  );
  _notify();
  return uploaded.length;
}

// ─── test helpers ──────────────────────────────────────────────────
export async function __clearForTests(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync("DELETE FROM photos_pending");
  _photoFlushing = false;
  _notify();
}
