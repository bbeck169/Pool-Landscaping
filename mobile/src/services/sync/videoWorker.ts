/**
 * Phase 2 · Video pipeline worker.
 *
 * Mirrors photoWorker.ts for video attachments:
 *   1. Pick/record → enforce 30-second cap (keep audio)
 *   2. Stage to `documentDirectory/videos/pending/{uuid}.mp4`
 *   3. Insert row into SQLite `videos_pending` table
 *   4. Upload to `POST /jobs/{jid}/videos` with client_uuid + X-Idempotency-Key
 *   5. On success: delete local file
 *   6. On 3+ failures: mark `stalled`
 */
import * as FileSystem from "expo-file-system/legacy";
import { getSyncDb } from "./db";
import { clientUuid } from "../ids/clientUuid";
import { isOnlineNow, on } from "./netBus";
import { api } from "@/src/api";

// ─── constants ─────────────────────────────────────────────────────
const MAX_DURATION_SEC = 30;
const MAX_UPLOAD_ATTEMPTS = 3;
const VIDEOS_DIR = `${FileSystem.documentDirectory}videos/pending/`;

// ─── types ─────────────────────────────────────────────────────────
export type PendingVideo = {
  id: string;
  local_uri: string;
  entity_type: string;
  entity_id: string;
  duration_sec: number;
  upload_status: "pending" | "uploading" | "uploaded" | "stalled";
  upload_attempts: number;
  last_error: string | null;
  created_at: string;
};

// ─── listeners ─────────────────────────────────────────────────────
type VideoListener = () => void;
const _listeners = new Set<VideoListener>();
function _notify() {
  _listeners.forEach((l) => { try { l(); } catch { /* ignore */ } });
}
export function subscribeVideos(listener: VideoListener): () => void {
  _listeners.add(listener);
  return () => { _listeners.delete(listener); };
}

// ─── auto-upload on reconnect ──────────────────────────────────────
let _autoWired = false;
export function wireVideoAutoUpload(): void {
  if (_autoWired) return;
  _autoWired = true;
  on("network:online", () => {
    setTimeout(() => { flushVideos().catch(() => {}); }, 3000);
  });
}

// ─── ensure dir ────────────────────────────────────────────────────
async function ensureDir(): Promise<void> {
  const info = await FileSystem.getInfoAsync(VIDEOS_DIR);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(VIDEOS_DIR, { intermediates: true });
  }
}

// ─── constants for consumers ────────────────────────────────────────
export const VIDEO_MAX_DURATION_SEC = MAX_DURATION_SEC;

// ─── stage video ───────────────────────────────────────────────────
/**
 * Given a raw video URI (from camera/picker), copy to staging directory.
 * The caller is responsible for enforcing the 30s cap via picker config.
 */
export async function stageVideo(rawUri: string, durationSec: number = 0): Promise<{
  stagedUri: string;
  videoId: string;
}> {
  await ensureDir();
  const videoId = clientUuid();
  const ext = rawUri.toLowerCase().includes(".mov") ? "mov" : "mp4";
  const destPath = `${VIDEOS_DIR}${videoId}.${ext}`;

  await FileSystem.copyAsync({ from: rawUri, to: destPath });

  return { stagedUri: destPath, videoId };
}

// ─── insert into videos_pending ────────────────────────────────────
export async function insertPendingVideo(
  videoId: string,
  localUri: string,
  entityType: string,
  entityId: string,
  durationSec: number = 0,
): Promise<void> {
  const db = await getSyncDb();
  const now = new Date().toISOString();
  await db.runAsync(
    `INSERT INTO videos_pending
       (id, local_uri, entity_type, entity_id, duration_sec,
        upload_status, upload_attempts, created_at)
     VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)`,
    [videoId, localUri, entityType, entityId, Math.min(durationSec, MAX_DURATION_SEC), now],
  );
  _notify();
}

// ─── full capture pipeline ─────────────────────────────────────────
/**
 * Single entry point: stage → insert → trigger upload.
 * Returns the video's client UUID for UI attachment.
 */
export async function captureVideo(
  rawUri: string,
  entityType: string,
  entityId: string,
  durationSec: number = 0,
): Promise<string> {
  // Enforce 30s cap at capture level
  const cappedDuration = Math.min(durationSec, MAX_DURATION_SEC);
  const { stagedUri, videoId } = await stageVideo(rawUri, cappedDuration);
  await insertPendingVideo(videoId, stagedUri, entityType, entityId, cappedDuration);

  if (isOnlineNow()) {
    flushVideos().catch(() => {});
  }

  return videoId;
}

// ─── upload worker ─────────────────────────────────────────────────
let _videoFlushing = false;

export async function flushVideos(): Promise<{
  uploaded: number;
  stalled: number;
}> {
  if (_videoFlushing) return { uploaded: 0, stalled: 0 };
  _videoFlushing = true;
  _notify();

  const result = { uploaded: 0, stalled: 0 };

  try {
    const db = await getSyncDb();
    const pending = await db.getAllAsync<PendingVideo>(
      `SELECT * FROM videos_pending
       WHERE upload_status = 'pending'
       ORDER BY created_at ASC`,
    );

    for (const video of pending) {
      if (!isOnlineNow()) break;

      // Mark uploading.
      await db.runAsync(
        `UPDATE videos_pending SET upload_status = 'uploading' WHERE id = ?`,
        [video.id],
      );
      _notify();

      try {
        // Read file as base64.
        const base64 = await FileSystem.readAsStringAsync(video.local_uri, {
          encoding: FileSystem.EncodingType.Base64,
        });
        const mimeType = video.local_uri.toLowerCase().includes(".mov")
          ? "video/quicktime"
          : "video/mp4";
        const dataUrl = `data:${mimeType};base64,${base64}`;

        // Upload to server.
        await api.post(
          `/jobs/${video.entity_id}/videos`,
          {
            data: dataUrl,
            label: `video-${video.id}`,
            client_uuid: video.id,
            duration_sec: video.duration_sec,
          },
          120000, // 2 min timeout for video upload
          { "X-Idempotency-Key": `video:${video.id}` },
        );

        // Mark uploaded.
        await db.runAsync(
          `UPDATE videos_pending SET upload_status = 'uploaded' WHERE id = ?`,
          [video.id],
        );
        result.uploaded++;

        // Cleanup local file.
        try {
          await FileSystem.deleteAsync(video.local_uri, { idempotent: true });
        } catch { /* non-fatal */ }
      } catch (e: any) {
        const attempts = video.upload_attempts + 1;
        const errMsg = (e?.message || "Upload failed").slice(0, 500);

        if (attempts >= MAX_UPLOAD_ATTEMPTS) {
          await db.runAsync(
            `UPDATE videos_pending SET upload_status = 'stalled',
               upload_attempts = ?, last_error = ?
             WHERE id = ?`,
            [attempts, errMsg, video.id],
          );
          result.stalled++;
        } else {
          await db.runAsync(
            `UPDATE videos_pending SET upload_status = 'pending',
               upload_attempts = ?, last_error = ?
             WHERE id = ?`,
            [attempts, errMsg, video.id],
          );
        }
      }
      _notify();
    }
  } finally {
    _videoFlushing = false;
    _notify();
  }

  return result;
}

// ─── retry stalled ─────────────────────────────────────────────────
export async function retryStalled(videoId: string): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE videos_pending SET upload_status = 'pending',
       upload_attempts = 0, last_error = NULL
     WHERE id = ? AND upload_status = 'stalled'`,
    [videoId],
  );
  _notify();
  flushVideos().catch(() => {});
}

export async function retryAllStalledVideos(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE videos_pending SET upload_status = 'pending',
       upload_attempts = 0, last_error = NULL
     WHERE upload_status = 'stalled'`,
  );
  _notify();
  flushVideos().catch(() => {});
}

// ─── query helpers ─────────────────────────────────────────────────
export async function getPendingVideos(): Promise<PendingVideo[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingVideo>(
    `SELECT * FROM videos_pending WHERE upload_status IN ('pending', 'uploading')
     ORDER BY created_at ASC`,
  );
}

export async function getStalledVideos(): Promise<PendingVideo[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingVideo>(
    `SELECT * FROM videos_pending WHERE upload_status = 'stalled'
     ORDER BY created_at ASC`,
  );
}

export async function getVideosForEntity(entityId: string): Promise<PendingVideo[]> {
  const db = await getSyncDb();
  return db.getAllAsync<PendingVideo>(
    `SELECT * FROM videos_pending WHERE entity_id = ?
     ORDER BY created_at ASC`,
    [entityId],
  );
}

// ─── orphan cleanup ────────────────────────────────────────────────
export async function purgeVideosForEntity(entityId: string): Promise<void> {
  const db = await getSyncDb();
  const videos = await db.getAllAsync<PendingVideo>(
    `SELECT * FROM videos_pending WHERE entity_id = ?`,
    [entityId],
  );

  for (const video of videos) {
    try {
      await FileSystem.deleteAsync(video.local_uri, { idempotent: true });
    } catch { /* file may already be gone */ }
  }

  await db.runAsync(
    `DELETE FROM videos_pending WHERE entity_id = ?`,
    [entityId],
  );
  _notify();
}

// ─── cleanup uploaded ──────────────────────────────────────────────
export async function cleanupUploadedVideos(): Promise<number> {
  const db = await getSyncDb();
  const uploaded = await db.getAllAsync<PendingVideo>(
    `SELECT * FROM videos_pending WHERE upload_status = 'uploaded'`,
  );
  for (const video of uploaded) {
    try {
      await FileSystem.deleteAsync(video.local_uri, { idempotent: true });
    } catch { /* already gone */ }
  }
  await db.runAsync(
    `DELETE FROM videos_pending WHERE upload_status = 'uploaded'`,
  );
  _notify();
  return uploaded.length;
}

// ─── test helpers ──────────────────────────────────────────────────
export async function __clearForTests(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync("DELETE FROM videos_pending");
  _videoFlushing = false;
  _notify();
}
