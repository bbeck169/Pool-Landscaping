/**
 * Phase F1 · Feb 2026 — /api/files/* client wrapper (web).
 *
 * Contract mirrors the F0 backend router:
 *   POST   /api/files/upload             (multipart form; `file` +
 *                                          optional `purpose`,
 *                                          `linked_entity_type`,
 *                                          `linked_entity_id` — ALL as
 *                                          FORM fields, not query params).
 *   GET    /api/files/{id}/download      (bearer header OR ?auth= query)
 *   POST   /api/files/{id}/delete        (bearer header; soft delete → 204)
 *   GET    /api/files?linked_entity_type=&linked_entity_id=&purpose=
 *
 * Uses XMLHttpRequest for upload so we can wire an ``onUploadProgress``
 * callback (fetch() streams have no per-request progress event yet on
 * every browser matrix). Everything else uses fetch().
 */
import { TOKEN_KEY } from "@/api";

const BASE = process.env.REACT_APP_BACKEND_URL;

function tokenNow() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function tenantSlugNow() {
  try {
    return localStorage.getItem("tenant_slug") || "";
  } catch {
    return "";
  }
}

function authedHeaders(extra = {}) {
  const h = { ...extra };
  const t = tokenNow();
  const s = tenantSlugNow();
  if (t) h["Authorization"] = `Bearer ${t}`;
  if (s) h["X-Tenant-Slug"] = s;
  return h;
}

async function _parseErr(res) {
  let text = "";
  try {
    text = await res.text();
  } catch { /* ignore */ }
  let msg = null;
  try {
    const j = JSON.parse(text);
    const d = j?.detail;
    msg = (d && typeof d === "object") ? (d.message || d.code) : d;
  } catch { /* not JSON */ }
  if (!msg) msg = `Request failed (${res.status})`;
  const err = new Error(msg);
  err.status = res.status;
  return err;
}

// ── uploadFile — XHR for progress support ─────────────────────────
export function uploadFile({
  file, purpose, linkedEntityType, linkedEntityId, onProgress,
} = {}) {
  return new Promise((resolve, reject) => {
    if (!file) { reject(new Error("file is required")); return; }
    const fd = new FormData();
    fd.append("file", file, file.name);
    if (purpose) fd.append("purpose", purpose);
    if (linkedEntityType) fd.append("linked_entity_type", linkedEntityType);
    if (linkedEntityId) fd.append("linked_entity_id", linkedEntityId);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/api/files/upload`, true);
    const headers = authedHeaders();
    // Do NOT set Content-Type — the browser sets the multipart boundary.
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);

    if (typeof onProgress === "function") {
      xhr.upload.addEventListener("progress", (ev) => {
        if (ev.lengthComputable) {
          onProgress(Math.round((ev.loaded / ev.total) * 100));
        }
      });
    }
    xhr.addEventListener("load", () => {
      const body = xhr.responseText || "";
      let parsed = null;
      try { parsed = JSON.parse(body); } catch { parsed = null; }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed || {});
      } else {
        let msg = null;
        const d = parsed?.detail;
        if (d && typeof d === "object") msg = d.message || d.code;
        else if (d) msg = d;
        if (!msg) msg = `Upload failed (${xhr.status})`;
        const err = new Error(msg);
        err.status = xhr.status;
        reject(err);
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")));
    xhr.addEventListener("abort", () => reject(new Error("Upload aborted")));
    xhr.send(fd);
  });
}

// ── uploadKnowledgeFile — POST /api/ai/knowledge/file ─────────────
// Phase KB3 · Feb-2026 — same XHR-with-progress shape as
// ``uploadFile`` but targets the AI Brain ingestion endpoint.  The
// backend performs S3 upload + text extraction + KB row insertion
// in one call and returns ``{kb, file}``.
export function uploadKnowledgeFile({
  file, title, kind, tags, onProgress,
} = {}) {
  return new Promise((resolve, reject) => {
    if (!file) { reject(new Error("file is required")); return; }
    const fd = new FormData();
    fd.append("file", file, file.name);
    if (title) fd.append("title", title);
    if (kind) fd.append("kind", kind);
    if (tags) fd.append("tags", tags);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/api/ai/knowledge/file`, true);
    const headers = authedHeaders();
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);

    if (typeof onProgress === "function") {
      xhr.upload.addEventListener("progress", (ev) => {
        if (ev.lengthComputable) {
          onProgress(Math.round((ev.loaded / ev.total) * 100));
        }
      });
    }
    xhr.addEventListener("load", () => {
      const body = xhr.responseText || "";
      let parsed = null;
      try { parsed = JSON.parse(body); } catch { parsed = null; }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed || {});
      } else {
        let msg = null;
        const d = parsed?.detail;
        if (d && typeof d === "object") msg = d.message || d.code;
        else if (d) msg = d;
        if (!msg) msg = `Upload failed (${xhr.status})`;
        const err = new Error(msg);
        err.status = xhr.status;
        err.data = parsed;
        reject(err);
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")));
    xhr.addEventListener("abort", () => reject(new Error("Upload aborted")));
    xhr.send(fd);
  });
}

// ── deleteFile — soft delete ────────────────────────────────────
export async function deleteFile(id) {
  const res = await fetch(`${BASE}/api/files/${id}/delete`, {
    method: "POST",
    headers: authedHeaders({ "Content-Type": "application/json" }),
  });
  if (!res.ok && res.status !== 204) throw await _parseErr(res);
  return true;
}

// ── listFilesByEntity ────────────────────────────────────────────
export async function listFilesByEntity(entityType, entityId, purpose) {
  const q = new URLSearchParams();
  if (entityType) q.set("linked_entity_type", entityType);
  if (entityId) q.set("linked_entity_id", entityId);
  if (purpose) q.set("purpose", purpose);
  const res = await fetch(
    `${BASE}/api/files?${q.toString()}`,
    { headers: authedHeaders() },
  );
  if (!res.ok) throw await _parseErr(res);
  const body = await res.json();
  return (body?.items) || [];
}

// ── buildAuthedDownloadUrl ──────────────────────────────────────
// For <img src> where headers can't be attached. Trade-off: token
// appears in the URL and may leak into referrer / server access logs.
// Prefer fetchAsBlob() when possible.
export function buildAuthedDownloadUrl(id, token) {
  const t = token || tokenNow();
  return `${BASE}/api/files/${encodeURIComponent(id)}/download?auth=${encodeURIComponent(t)}`;
}

// ── fetchAsBlob / revokeBlobUrl ─────────────────────────────────
export async function fetchAsBlob(id, token) {
  const t = token || tokenNow();
  const res = await fetch(`${BASE}/api/files/${encodeURIComponent(id)}/download`, {
    headers: { Authorization: `Bearer ${t}` },
  });
  if (!res.ok) throw await _parseErr(res);
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), contentType: blob.type };
}

export function revokeBlobUrl(url) {
  if (url && url.startsWith("blob:")) URL.revokeObjectURL(url);
}
