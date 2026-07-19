/**
 * MediaUploader — Phase 5A · Video Uploads on Jobs + Estimates (Feb 2026)
 *
 * First blob-storage UI in this codebase. Handles picking, pre-flight
 * (size + duration), multipart upload with progress, inline HTML5
 * playback via the auth-gated ``/api/media/videos/{path}?auth=token``
 * proxy, and per-video actions (visibility toggle + delete).
 *
 * Sits below the existing PhotoUploader on job/estimate detail pages —
 * photos and videos are peer citizens of the "Media" section, not a
 * replacement.
 */
import React, { useMemo, useRef, useState } from "react";
import { Film, Trash2, Eye, EyeOff, Loader2, Play, X as XIcon } from "lucide-react";
import { api_base, TOKEN_KEY } from "@/api";
import { colors } from "@/theme";

const MAX_BYTES = 100 * 1024 * 1024;
const MAX_DURATION_S = 180;
const ALLOWED_MIMES = new Set([
  "video/mp4", "video/quicktime", "video/webm", "video/x-m4v",
]);
const ACCEPT_ATTR = "video/mp4,video/quicktime,video/webm,video/x-m4v";

function bytesToLabel(n) {
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function durationLabel(s) {
  if (s == null) return "";
  const total = Math.max(0, Math.round(Number(s)));
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

function inspectClientVideo(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const el = document.createElement("video");
    el.preload = "metadata";
    el.src = url;
    el.onloadedmetadata = () => {
      const duration = Number.isFinite(el.duration) ? Number(el.duration) : null;
      URL.revokeObjectURL(url);
      resolve({ duration });
    };
    el.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read the video file — is it corrupt or an unsupported codec?"));
    };
  });
}

export default function MediaUploader({
  entityKind,        // "job" | "estimate"
  entityId,
  existingVideos = [],
  onUploaded,
  onDeleted,
  onPatched,
  readonly = false,
}) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState("");
  const [lightboxSrc, setLightboxSrc] = useState(null);
  const inputRef = useRef(null);

  const visibleVideos = useMemo(
    () => (existingVideos || []).filter((v) => !v?.is_deleted),
    [existingVideos],
  );
  const remaining = Math.max(0, 10 - visibleVideos.length);

  const uploadPath = `/api/${entityKind === "estimate" ? "estimates" : "jobs"}/${entityId}/videos`;

  const runUpload = async (file) => {
    setErr("");
    if (!file) return;

    if (!ALLOWED_MIMES.has(file.type)) {
      setErr("Unsupported format — use MP4, MOV, WebM, or M4V.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setErr(`File is ${bytesToLabel(file.size)} — max 100 MB.`);
      return;
    }

    // Client-side duration inspection.
    let inspected = { duration: null };
    try {
      inspected = await inspectClientVideo(file);
    } catch (e) {
      setErr(e.message || "Could not read the video file.");
      return;
    }
    if (inspected.duration != null && inspected.duration > MAX_DURATION_S) {
      setErr(`Video is ${durationLabel(inspected.duration)} — max 3:00.`);
      return;
    }

    setBusy(true);
    setProgress(0);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const url = `${api_base()}${uploadPath.replace("/api", "")}`;
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("visibility", "internal");

      // XHR-based so we get a real onprogress event. fetch/axios can be
      // used but XHR is the least-dependency path.
      const body = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url, true);
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        if (inspected.duration != null) {
          xhr.setRequestHeader("X-Video-Duration", String(inspected.duration));
        }
        const tenantSlug = localStorage.getItem("tenant_slug") || "";
        if (tenantSlug) xhr.setRequestHeader("X-Tenant-Slug", tenantSlug);
        xhr.upload.onprogress = (evt) => {
          if (evt.lengthComputable) {
            setProgress(Math.round((evt.loaded / evt.total) * 100));
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText)); }
            catch { reject(new Error("Malformed server response.")); }
          } else {
            let msg = `Upload failed (${xhr.status})`;
            try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
            reject(new Error(msg));
          }
        };
        xhr.onerror = () => reject(new Error("Network error during upload."));
        xhr.send(form);
      });

      onUploaded?.(body.video);
    } catch (e) {
      setErr(e.message || "Upload failed.");
    } finally {
      setBusy(false);
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handlePick = (e) => runUpload(e.target.files?.[0]);

  const streamSrc = (v) => {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    return `${api_base()}/media/videos/${v.storage_path}?auth=${encodeURIComponent(token)}`;
  };

  const toggleVisibility = async (v) => {
    if (readonly) return;
    const nextVis = v.visibility === "customer" ? "internal" : "customer";
    setErr("");
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const url = `${api_base()}${uploadPath}/${v.id}`;
      const form = new FormData();
      form.append("visibility", nextVis);
      const resp = await fetch(url, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!resp.ok) throw new Error((await resp.text()) || `Update failed (${resp.status})`);
      const body = await resp.json();
      onPatched?.(body.video);
    } catch (e) {
      setErr(e.message || "Could not update visibility.");
    }
  };

  const removeVideo = async (v) => {
    if (readonly) return;
    if (!window.confirm("Delete this video from the record?")) return;
    setErr("");
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const url = `${api_base()}${uploadPath}/${v.id}`;
      const resp = await fetch(url, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error((await resp.text()) || `Delete failed (${resp.status})`);
      onDeleted?.(v.id);
    } catch (e) {
      setErr(e.message || "Delete failed.");
    }
  };

  return (
    <div data-testid={`media-uploader-${entityKind}-${entityId}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Film size={14} style={{ color: colors.muted }} />
          <span className="text-xs font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}>
            Videos · {visibleVideos.length} of 10
          </span>
        </div>
        {busy ? (
          <div className="flex items-center gap-1 text-xs" style={{ color: colors.muted }}>
            <Loader2 size={12} className="animate-spin" />
            <span data-testid="media-upload-progress">{progress}%</span>
          </div>
        ) : null}
      </div>

      {err ? (
        <div className="text-xs px-3 py-2 rounded mb-3"
             style={{ color: "#991B1B", background: "#FEE2E2" }}
             data-testid="media-uploader-error">
          {err}
        </div>
      ) : null}

      {visibleVideos.length ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-3"
             data-testid="media-uploader-grid">
          {visibleVideos.map((v) => (
            <VideoTile
              key={v.id}
              video={v}
              src={streamSrc(v)}
              readonly={readonly}
              onPlay={() => setLightboxSrc(streamSrc(v))}
              onToggleVisibility={() => toggleVisibility(v)}
              onDelete={() => removeVideo(v)}
            />
          ))}
        </div>
      ) : null}

      {!readonly && remaining > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold cursor-pointer disabled:opacity-50"
            style={{
              background: colors.surfaceSecondary,
              border: `1.5px dashed ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="media-upload-add"
          >
            <Film size={14} />
            {busy ? "Uploading…" : `Upload video · up to ${remaining} more`}
          </button>
          <p className="text-[11px] mt-1.5" style={{ color: colors.muted }}>
            MP4 / MOV / WebM · up to 100 MB · up to 3 min
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_ATTR}
            style={{ display: "none" }}
            onChange={handlePick}
            data-testid="media-upload-input"
          />
        </div>
      ) : null}

      {lightboxSrc ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
             style={{ backgroundColor: "rgba(0,0,0,0.9)" }}
             onClick={() => setLightboxSrc(null)}
             data-testid="media-lightbox">
          <button className="absolute top-4 right-4 text-white"
                  onClick={() => setLightboxSrc(null)}>
            <XIcon size={28} />
          </button>
          <video
            controls
            autoPlay
            src={lightboxSrc}
            className="max-h-[85vh] max-w-full rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}
    </div>
  );
}

function VideoTile({ video, src, readonly, onPlay, onToggleVisibility, onDelete }) {
  const isCustomer = video.visibility === "customer";
  return (
    <div className="rounded-xl overflow-hidden"
         style={{ background: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}` }}
         data-testid={`media-tile-${video.id}`}>
      <div className="relative aspect-video bg-black">
        <video
          preload="metadata"
          src={src}
          className="w-full h-full object-cover"
          data-testid={`media-video-${video.id}`}
        />
        <button type="button"
                onClick={onPlay}
                className="absolute inset-0 flex items-center justify-center cursor-pointer"
                style={{ background: "rgba(0,0,0,0.15)" }}
                aria-label="Play video"
                data-testid={`media-play-${video.id}`}>
          <span className="rounded-full p-3"
                style={{ background: "rgba(0,0,0,0.65)" }}>
            <Play size={20} color="#fff" />
          </span>
        </button>
      </div>
      <div className="p-2.5">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                style={{
                  background: isCustomer ? "#DCFCE7" : colors.surface,
                  color: isCustomer ? "#166534" : colors.muted,
                  border: `1px solid ${isCustomer ? "#86EFAC" : colors.border}`,
                }}
                data-testid={`media-visibility-${video.id}`}>
            {isCustomer ? "Shareable" : "Internal"}
          </span>
          <span className="text-[11px]" style={{ color: colors.muted }}>
            {bytesToLabel(video.size_bytes)}
            {video.duration_seconds ? ` · ${durationLabel(video.duration_seconds)}` : ""}
          </span>
        </div>
        {video.caption ? (
          <p className="text-xs mb-1.5" style={{ color: colors.onSurface }}>
            {video.caption}
          </p>
        ) : null}
        <p className="text-[10px]" style={{ color: colors.muted }}>
          {video.uploaded_by_name || "Uploaded"} · {new Date(video.uploaded_at).toLocaleDateString()}
        </p>
        {!readonly ? (
          <div className="flex items-center gap-2 mt-2">
            <button type="button"
                    onClick={onToggleVisibility}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded"
                    style={{ background: colors.surface, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid={`media-toggle-vis-${video.id}`}>
              {isCustomer ? <EyeOff size={11} /> : <Eye size={11} />}
              {isCustomer ? "Make internal" : "Share to portal"}
            </button>
            <button type="button"
                    onClick={onDelete}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded"
                    style={{ background: "#FEF2F2", color: "#991B1B",
                             border: "1px solid #FECACA" }}
                    data-testid={`media-delete-${video.id}`}>
              <Trash2 size={11} />
              Delete
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
