/**
 * Phase 31 · Step 2b — PhotoUploader (web).
 *
 * Web mirror of the mobile PhotoUploader. Uses the same job-photo
 * endpoints verified in Step 1 discovery:
 *   POST   /api/jobs/{jid}/photos
 *   DELETE /api/jobs/{jid}/photos/{pid}
 *
 * Photos are uploaded as base64 data-URLs (matches the existing
 * JobDetail upload contract on web + mobile). No new endpoints.
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

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.readAsDataURL(file);
  });
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
        // Feb 2026 · iOS field-upload timeout fix — shrink before the
        // base64 blowup so /api/jobs/{jid}/photos gets a manageable
        // payload. Non-image + small images pass through unchanged.
        const f = await compressImageIfNeeded(f0);
        const dataUrl = await fileToDataUrl(f);
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
        {photos.map((p) => (
          <div key={p.id} className="relative aspect-square rounded-lg overflow-hidden"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`checklist-photo-${p.id}`}>
            <img src={p.data || p.url} alt={p.label || "photo"}
                 className="w-full h-full object-cover" />
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
        ))}
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
        accept="image/*"
        multiple
        style={{ display: "none" }}
        onChange={(e) => upload(e.target.files)}
        data-testid="checklist-photo-input"
      />
    </div>
  );
}
