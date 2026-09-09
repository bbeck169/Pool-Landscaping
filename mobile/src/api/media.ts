/**
 * Phase 5B · Video uploads — thin API client for mobile.
 *
 * Uses XMLHttpRequest for upload progress (fetch on RN doesn't expose
 * upload.onprogress reliably). PATCH / DELETE / stream-URL use the
 * normal api helpers.
 */
import { api, api_base, getAuthToken } from "@/src/api";
import NetInfo from "@react-native-community/netinfo";

export type VideoEntity = "job" | "estimate";

export type VideoRecord = {
  id: string;
  storage_path: string;
  mime: string;
  size_bytes: number;
  duration_seconds: number | null;
  original_filename: string;
  uploaded_by_user_id: string;
  uploaded_by_name: string;
  uploaded_at: string;
  visibility: "internal" | "customer";
  caption: string;
  is_deleted: boolean;
};

const MAX_BYTES = 100 * 1024 * 1024;

function entityPath(kind: VideoEntity, id: string): string {
  return kind === "estimate" ? `/quotes/${id}/videos` : `/jobs/${id}/videos`;
}

/**
 * Build authenticated streaming URL for a video.
 * expo-video will send Range requests automatically.
 */
export async function buildStreamUrl(storagePath: string): Promise<string> {
  const token = await getAuthToken();
  return `${api_base()}/media/videos/${storagePath}?auth=${encodeURIComponent(token)}`;
}

/**
 * Upload a video file via multipart/form-data with progress callback.
 * Uses XHR for upload.onprogress support.
 */
export async function uploadVideo(opts: {
  kind: VideoEntity;
  entityId: string;
  fileUri: string;
  fileName: string;
  mimeType: string;
  fileSize: number;
  durationSeconds?: number | null;
  caption?: string;
  visibility?: string;
  onProgress?: (pct: number) => void;
}): Promise<{ video: VideoRecord }> {
  // Offline guard
  const netState = await NetInfo.fetch();
  if (!netState.isConnected || netState.isInternetReachable === false) {
    throw new OfflineError("Video uploads require an internet connection. Try again when connected.");
  }

  if (opts.fileSize > MAX_BYTES) {
    throw new Error(`Video is ${Math.round(opts.fileSize / 1024 / 1024)} MB — max 100 MB.`);
  }

  const token = await getAuthToken();
  const url = `${api_base()}${entityPath(opts.kind, opts.entityId)}`;

  const form = new FormData();
  form.append("file", {
    uri: opts.fileUri,
    name: opts.fileName || "video.mp4",
    type: opts.mimeType || "video/mp4",
  } as any);
  form.append("visibility", opts.visibility || "internal");
  if (opts.caption) form.append("caption", opts.caption);

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (opts.durationSeconds != null) {
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
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error("Malformed server response."));
        }
      } else {
        let msg = `Upload failed (${xhr.status})`;
        try {
          msg = JSON.parse(xhr.responseText).detail || msg;
        } catch { /* ignore */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.send(form);
  });
}

/** Toggle visibility between internal ↔ customer. */
export async function patchVideoVisibility(
  kind: VideoEntity,
  entityId: string,
  videoId: string,
  newVisibility: "internal" | "customer",
): Promise<{ video: VideoRecord }> {
  const token = await getAuthToken();
  const url = `${api_base()}${entityPath(kind, entityId)}/${videoId}`;
  const form = new FormData();
  form.append("visibility", newVisibility);
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!resp.ok) throw new Error((await resp.text()) || `Update failed (${resp.status})`);
  return resp.json();
}

/** Soft-delete a video. */
export async function deleteVideo(
  kind: VideoEntity,
  entityId: string,
  videoId: string,
): Promise<void> {
  const token = await getAuthToken();
  const url = `${api_base()}${entityPath(kind, entityId)}/${videoId}`;
  const resp = await fetch(url, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error((await resp.text()) || `Delete failed (${resp.status})`);
}

/** Fetch portal videos. */
export async function fetchPortalVideos(): Promise<any> {
  return api.get("/portal/videos");
}

// Custom error for offline guard
export class OfflineError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "OfflineError";
  }
}

// Helpers
export function bytesToLabel(n: number): string {
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function durationLabel(s: number | null | undefined): string {
  if (s == null) return "";
  const total = Math.max(0, Math.round(Number(s)));
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export function relativeTime(iso: string): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.floor(ms / 60000);
  if (min < 1) return "Just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}
