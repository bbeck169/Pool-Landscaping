/**
 * Phase 31 · Step 2b — PhotoUploader (web).
 *
 * Web mirror of the mobile PhotoUploader. Uses the same job-photo
 * endpoints verified in Step 1 discovery:
 *   POST   /api/jobs/{jid}/photos
 *   DELETE /api/jobs/{jid}/photos/{pid}
 *
 * Photos are uploaded as base64 data-URLs (matches the existing
 * JobDetail upload contract on web + mobile).
 *
 * Feb-2026 · Thumbnails + upload guardrails
 *   * List thumbnails render via ``/api/public/job-photo/{jid}/{pid}/thumb``
 *     with ``loading="lazy"`` so the full base64 blob never lands
 *     in the DOM.
 *   * Client-side canvas compression fires via ``compressImageIfNeeded``.
 *     Post-compression, we assert the encoded size is under
 *     ``MAX_UPLOAD_BYTES`` (5 MB) so uploads that STILL can't get
 *     small are rejected inline (no POST wasted).
 *   * MIME allowlist mirrors the backend guardrail so obvious
 *     non-images never hit the wire.
 */
import React, { useRef, useState } from "react";
import { Camera, X, Loader2 } from 'lucide-react';
import { api } from "@/api";
import { compressImageIfNeeded } from "../../lib/imageCompress";

const colors = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#F8FAFC",
  danger: "#DC2626",
};

// Mirrors the backend ``PHOTOS_MAX_UPLOAD_BYTES`` default (5 MB
// post-decode). If the compression pass can't get under this,
// we reject inline — no POST fires.
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const ALLOWED_MIMES = new Set([
  "image/jpeg", "image/jpg", "image/png", "image/webp",
  "image/heic", "image/heif",
]);

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.readAsDataURL(file);
  });
}

function decodedByteLen(dataUrl) {
  // A base64 data-URL's decoded size is (b64.length * 3) / 4 minus
  // one byte per '=' pad. Estimate without decoding the blob so we
  // don't double the memory footprint on iOS Safari.
  const idx = dataUrl.indexOf(",");
  if (idx < 0) return 0;
  const b64 = dataUrl.slice(idx + 1);
  const pad = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  return Math.floor((b64.length * 3) / 4) - pad;
}

export default function PhotoUploader({
  jobId, photos = [], onPhotosChange, max = 10, disabled = false,
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const inputRef = useRef(null);
  const remaining = Math.max(0, max - photos.length);

  const upload = async (files) => {
    if (!files?.length || disabled) return;
    setBusy(true); setErr("");
    let updated = { photos };
    try {
      for (const f0 of Array.from(files).slice(0, remaining)) {
        // Guardrail 1 — MIME allowlist BEFORE compression.
        const rawType = (f0.type || "").toLowerCase();
        if (rawType && !ALLOWED_MIMES.has(rawType)) {
          throw new Error(
            "Unsupported file type. Only JPG, PNG, WebP, or HEIC.",
          );
        }
        // Compress if the source is bigger than 1 MB (canvas-backed
        // via ``browser-image-compression``, capped at 2560px).
        const f = await compressImageIfNeeded(f0);
        const dataUrl = await fileToDataUrl(f);
        // Guardrail 2 — post-compression size cap. Reject inline.
        const decoded = decodedByteLen(dataUrl);
        if (decoded > MAX_UPLOAD_BYTES) {
          throw new Error(
            "This photo is too large after resizing. Try a smaller image.",
          );
        }
        updated = await api.post(`/jobs/${jobId}/photos`, {
          data: dataUrl,
          label: `checklist-${new Date().toISOString()}`,
        });
      }
      onPhotosChange(updated.photos || []);
    } catch (e) {
      setErr(e?.message || "Upload failed.");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async (pid) => {
    if (disabled) return;
    setErr("");
    try {
      const updated = await api.del(`/jobs/${jobId}/photos/${pid}`);
      onPhotosChange(updated.photos || []);
    } catch (e) {
      setErr(e?.message || "Delete failed.");
    }
  };

  return (
    <div data-testid="checklist-photo-uploader">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold uppercase" style={{ color: colors.muted }}>
          {photos.length} of {max}
        </span>
        {busy && <Loader2 size={14} className="animate-spin" color={colors.brand} />}
      </div>

      {err ? (
        <div className="text-xs px-2 py-1 rounded mb-2"
             style={{ color: "#991B1B", background: "#FEE2E2" }}
             data-testid="checklist-photo-error">
          {err}
        </div>
      ) : null}

      <div className="grid grid-cols-4 gap-2">
        {photos.map((p) => {
          // Feb-2026 · Thumbnails ship — prefer the public thumb
          // route over the embedded base64 blob so list-view DOM
          // stays tiny. Falls back to the base64 payload only when
          // the caller didn't hand us a jobId (rare).
          const thumbSrc = jobId
            ? `/api/public/job-photo/${jobId}/${p.id}/thumb`
            : (p.data || p.url);
          return (
            <div key={p.id} className="relative aspect-square rounded-lg overflow-hidden"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                 data-testid={`checklist-photo-${p.id}`}>
              <img
                src={thumbSrc}
                loading="lazy"
                alt={p.label || "photo"}
                className="w-full h-full object-cover"
                data-testid={`checklist-photo-img-${p.id}`}
              />
              {!disabled && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); remove(p.id); }}
                  className="absolute top-1 right-1 rounded-full p-1"
                  style={{ background: "rgba(0,0,0,0.65)", cursor: "pointer", border: 0 }}
                  data-testid={`checklist-photo-del-${p.id}`}
                  aria-label="Remove photo"
                >
                  <X size={11} color="#fff" />
                </button>
              )}
            </div>
          );
        })}
        {!disabled && remaining > 0 && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="aspect-square rounded-lg flex flex-col items-center justify-center gap-1 cursor-pointer"
            style={{ background: colors.surface, border: `2px dashed ${colors.border}` }}
            data-testid="checklist-photo-add"
          >
            <Camera size={20} color={colors.muted} />
            <span className="text-[10px] font-bold uppercase" style={{ color: colors.muted }}>
              Add photo
            </span>
          </button>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
        multiple
        style={{ display: "none" }}
        onChange={(e) => upload(e.target.files)}
        data-testid="checklist-photo-input"
      />
    </div>
  );
}
