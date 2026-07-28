/**
 * Phase F1 · File Upload API client (mobile).
 *
 * Mirrors /app/frontend/src/api/files.js but adapted for React Native:
 *   - Uses FormData with {uri,name,type} for uploads (RN convention)
 *   - XHR for upload progress (same pattern as src/api/media.ts)
 *   - Auth token via getAuthToken() (SecureStore / AsyncStorage)
 *   - downloadToLocalCache via expo-file-system instead of fetchAsBlob
 *
 * Backend contract (F0):
 *   POST   /api/files/upload        — multipart (file + optional form fields)
 *   GET    /api/files/{id}/download  — bearer OR ?auth= query
 *   POST   /api/files/{id}/delete    — 204
 *   GET    /api/files?linked_entity_type=&linked_entity_id=
 */
import * as FileSystem from "expo-file-system/legacy";
import { api_base, getAuthToken } from "@/src/api";

const MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024;

// ── Types ──────────────────────────────────────────────────────────
export type FileRecord = {
  id: string;
  url: string;
  size: number;
  content_type: string;
  original_filename: string;
  storage_path: string;
  purpose?: string;
  linked_entity_type?: string;
  linked_entity_id?: string;
  created_at?: string;
};

export type UploadOpts = {
  uri: string;
  name: string;
  type: string;
  purpose?: string;
  linkedEntityType?: string;
  linkedEntityId?: string;
  onProgress?: (pct: number) => void;
};

// ── Helpers ────────────────────────────────────────────────────────
export function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function mimeAllowed(ct: string, accept: string): boolean {
  const acc = (accept || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (acc.length === 0) return true;
  const type = (ct || "").toLowerCase();
  return acc.some((rule) => {
    if (rule === "*/*") return true;
    if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
    return type === rule.toLowerCase();
  });
}

// ── uploadFile ─────────────────────────────────────────────────────
export async function uploadFile(opts: UploadOpts): Promise<FileRecord> {
  const { uri, name, type, purpose, linkedEntityType, linkedEntityId, onProgress } = opts;

  const token = await getAuthToken();
  const url = `${api_base()}/files/upload`;

  const form = new FormData();
  form.append("file", { uri, name: name || "file", type: type || "application/octet-stream" } as any);
  if (purpose) form.append("purpose", purpose);
  if (linkedEntityType) form.append("linked_entity_type", linkedEntityType);
  if (linkedEntityId) form.append("linked_entity_id", linkedEntityId);

  return new Promise<FileRecord>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    if (typeof onProgress === "function") {
      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) {
          onProgress(Math.round((evt.loaded / evt.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      let parsed: any = null;
      try { parsed = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed || ({} as FileRecord));
      } else {
        let msg = `Upload failed (${xhr.status})`;
        const d = parsed?.detail;
        if (d && typeof d === "string") msg = d;
        else if (d?.message) msg = d.message;
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(form);
  });
}

// ── deleteFile ─────────────────────────────────────────────────────
export async function deleteFile(id: string): Promise<boolean> {
  const token = await getAuthToken();
  const res = await fetch(`${api_base()}/files/${id}/delete`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  if (!res.ok && res.status !== 204) {
    let msg = `Delete failed (${res.status})`;
    try {
      const j = await res.json();
      if (j?.detail) msg = typeof j.detail === "string" ? j.detail : j.detail.message || msg;
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return true;
}

// ── listFilesByEntity ──────────────────────────────────────────────
export async function listFilesByEntity(
  entityType: string,
  entityId: string,
  purpose?: string,
): Promise<FileRecord[]> {
  const token = await getAuthToken();
  const q = new URLSearchParams();
  if (entityType) q.set("linked_entity_type", entityType);
  if (entityId) q.set("linked_entity_id", entityId);
  if (purpose) q.set("purpose", purpose);

  const res = await fetch(`${api_base()}/files?${q.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let msg = `Failed to load files (${res.status})`;
    try { const j = await res.json(); if (j?.detail) msg = j.detail; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const body = await res.json();
  return body?.items || [];
}

// ── buildAuthedDownloadUrl ─────────────────────────────────────────
export function buildAuthedDownloadUrl(id: string, token: string): string {
  return `${api_base()}/files/${encodeURIComponent(id)}/download?auth=${encodeURIComponent(token)}`;
}

// ── downloadToLocalCache ───────────────────────────────────────────
export async function downloadToLocalCache(id: string, token?: string): Promise<string> {
  const t = token || await getAuthToken();
  const url = buildAuthedDownloadUrl(id, t);
  const localUri = `${FileSystem.cacheDirectory}files_${id}`;
  const result = await FileSystem.downloadAsync(url, localUri);
  if (result.status < 200 || result.status >= 300) {
    throw new Error(`Download failed (${result.status})`);
  }
  return result.uri;
}

export { MAX_UPLOAD_SIZE_BYTES };
