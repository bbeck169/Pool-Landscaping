/**
 * Phase F2e · Feb 2026 — Persona avatar upload modal (web).
 *
 * Opens over the ``AiPersonasScopePage`` row. Uploads a single image
 * via the F0 files pipeline, then PATCHes the persona's ``avatar_url``
 * to the F0 download path. "Reset to default" writes the built-in
 * ``/avatars/personas/{key}.jpg`` back to the row.
 *
 * Upload limits are tighter than F0's default (5 MB, image-only) —
 * persona avatars are 40-64px circles, no reason to allow a 25MB PNG.
 */
import React, { useState } from "react";
import { X as XIcon } from "lucide-react";
import { toast } from "sonner";
import { FileUpload } from "@/components/files/FileUpload";
import { PersonaAvatar } from "@/components/personas/PersonaAvatar";
import { api } from "@/api";

const ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_BYTES = 5 * 1024 * 1024;   // 5 MB — client-side gate

// Exported for Vitest — builds the avatar_url value we persist on
// the persona row after a successful F0 upload. Tests assert on the
// exact shape.
export function buildPersonaAvatarUrl(fileId) {
  if (!fileId) return "";
  return `/api/files/${fileId}/download`;
}

// Exported for Vitest — the default persona avatar path per key.
export function defaultPersonaAvatarUrl(personaKey) {
  if (!personaKey) return "";
  return `/avatars/personas/${personaKey}.jpg`;
}

export function PersonaAvatarUploadModal({ persona, onClose, onSaved }) {
  const [saving, setSaving] = useState(false);
  const key = persona?.key;
  const eid = persona?.id || persona?.employee_id || persona?.eid || key;

  const patchAvatar = async (avatar_url) => {
    setSaving(true);
    try {
      await api.patch(`/ai-employees/${eid}`, { avatar_url });
      toast.success("Avatar updated.");
      onSaved?.({ ...persona, avatar_url });
      onClose?.();
    } catch (e) {
      toast.error(e?.message || "Failed to update avatar.");
    } finally { setSaving(false); }
  };

  const onUploaded = (payload) => {
    // FileUpload emits ``{id, ...}`` on success.
    const id = payload?.id || payload?.file_id;
    if (!id) {
      toast.error("Upload succeeded but no file id was returned.");
      return;
    }
    patchAvatar(buildPersonaAvatarUrl(id));
  };

  const onReset = () => patchAvatar(defaultPersonaAvatarUrl(key));

  if (!persona) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
      data-testid="persona-avatar-upload-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <PersonaAvatar persona={persona} size={56} />
            <div>
              <h2 className="text-lg font-bold">{persona.name || key}</h2>
              <p className="text-xs text-zinc-500">Upload a new avatar image</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 text-zinc-500 hover:text-zinc-900"
          >
            <XIcon size={18} />
          </button>
        </div>

        <FileUpload
          purpose="persona_avatar"
          linkedEntityType="persona"
          linkedEntityId={key}
          accept={ACCEPT}
          multiple={false}
          maxFiles={1}
          onUploaded={onUploaded}
          buttonLabel="Upload image (PNG/JPG/WebP, max 5MB)"
          disabled={saving}
        />

        <p className="text-xs text-zinc-500 mt-2">
          Recommended: 200×200px square, under 5 MB.
        </p>

        <div className="mt-5 flex items-center justify-between">
          <button
            type="button"
            onClick={onReset}
            disabled={saving}
            className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 disabled:opacity-50"
            data-testid="persona-avatar-reset"
          >
            Reset to default
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-zinc-100 text-zinc-900"
            data-testid="persona-avatar-close"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default PersonaAvatarUploadModal;
export { MAX_BYTES as PERSONA_AVATAR_MAX_BYTES, ACCEPT as PERSONA_AVATAR_ACCEPT };
