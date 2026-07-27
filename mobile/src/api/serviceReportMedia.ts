/**
 * Phase 27 · Service-Report Media API helpers.
 *
 * Endpoints:
 *   POST  /api/service-reports/{id}/media          — multipart upload (photo or video)
 *   PATCH /api/service-reports/{id}/media/reorder   — JSON {photo_order, video_order}
 *
 * Uses XHR for upload progress (fetch on RN lacks upload.onprogress).
 */
import { api, api_base, getAuthToken } from "@/src/api";
import NetInfo from "@react-native-community/netinfo";

/* ── Types ──────────────────────────────────────────────────────── */
export type SRMedia = {
  id?: string;
  url: string;
  kind: "photo" | "video";
  poster_url?: string | null;
  duration_seconds?: number | null;
  content_type?: string;
  size_bytes?: number;
};

/* ── Caps & limits ──────────────────────────────────────────────── */
export const PHOTO_CAP = 10;
export const VIDEO_CAP = 3;
export const VIDEO_MAX_DURATION_S = 60;
export const VIDEO_MAX_BYTES = 100 * 1024 * 1024;
export const PHOTO_MAX_BYTES = 20 * 1024 * 1024;

export const PHOTO_MIMES = new Set([
  "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
]);
export const VIDEO_MIMES = new Set([
  "video/mp4", "video/quicktime", "video/webm", "video/x-m4v",
  "video/avi", "video/x-msvideo",
]);

export class OfflineError extends Error {
  constructor(msg: string) { super(msg); this.name = "OfflineError"; }
}

/* ── Upload ─────────────────────────────────────────────────────── */
export async function uploadServiceReportMedia(opts: {
  reportId: string;
  fileUri: string;
  fileName: string;
  mimeType: string;
  fileSize: number;
  kind: "photo" | "video";
  durationSeconds?: number | null;
  posterUrl?: string | null;
  onProgress?: (pct: number) => void;
}): Promise<any> {
  const net = await NetInfo.fetch();
  if (!net.isConnected || net.isInternetReachable === false) {
    throw new OfflineError("Media uploads require an internet connection.");
  }

  const maxBytes = opts.kind === "video" ? VIDEO_MAX_BYTES : PHOTO_MAX_BYTES;
  if (opts.fileSize > maxBytes) {
    throw new Error(
      `File is ${Math.round(opts.fileSize / 1024 / 1024)} MB — max ${Math.round(maxBytes / 1024 / 1024)} MB.`,
    );
  }

  const token = await getAuthToken();
  const url = `${api_base()}/service-reports/${opts.reportId}/media`;

  const form = new FormData();
  form.append("file", {
    uri: opts.fileUri,
    name: opts.fileName || (opts.kind === "video" ? "video.mp4" : "photo.jpg"),
    type: opts.mimeType,
  } as any);
  form.append("kind", opts.kind);
  if (opts.posterUrl) form.append("poster_url", opts.posterUrl);

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (opts.kind === "video" && opts.durationSeconds != null) {
    headers["X-Video-Duration"] = String(opts.durationSeconds);
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (evt) => {
      if (evt.lengthComputable) {
        opts.onProgress?.(Math.round((evt.loaded / evt.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch { reject(new Error("Malformed server response.")); }
      } else {
        let msg = `Upload failed (${xhr.status})`;
        try { msg = JSON.parse(xhr.responseText).detail || msg; }
        catch { /* ignore */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.send(form);
  });
}

/* ── Reorder ────────────────────────────────────────────────────── */
export async function reorderServiceReportMedia(
  reportId: string,
  photoOrder: string[],
  videoOrder: string[],
): Promise<any> {
  return api.patch(`/service-reports/${reportId}/media/reorder`, {
    photo_order: photoOrder,
    video_order: videoOrder,
  });
}
