/**
 * Phase 56.11 — Customer Equipment Photo Library (web).
 *
 * Renders 11 equipment-type accordion sections for a customer. Each
 * section has a 2x2 photo grid with up to 4 slots. Empty slots show a
 * dashed "+ Add photo" placeholder; the placeholder disappears once
 * the cap is reached. Admins/super_admins can delete via lightbox.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Camera, X, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { api } from "@/api";

const c = {
  border: "#E2E8F0", muted: "#64748B", surface: "#F8FAFC",
  onSurface: "#0F172A", danger: "#DC2626", brand: "#0EA5E9",
};

const PHOTO_CAP = 4;

async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

function isAdmin(user) {
  return ["admin", "super_admin"].includes((user?.role || "").toLowerCase());
}

function LightBox({ photo, canDelete, onClose, onDelete }) {
  if (!photo) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.85)" }}
      onClick={onClose}
      data-testid="equipment-photo-lightbox"
    >
      <div
        className="rounded-lg overflow-hidden max-w-3xl w-full"
        style={{ background: "#fff" }}
        onClick={(e) => e.stopPropagation()}
      >
        <img src={photo.photo_url} alt={photo.caption || "Equipment"}
             className="w-full max-h-[70vh] object-contain" />
        <div className="p-3 space-y-1 text-sm" style={{ color: c.onSurface }}>
          {photo.caption ? (
            <div className="font-semibold">{photo.caption}</div>
          ) : null}
          <div className="text-xs" style={{ color: c.muted }}>
            Uploaded by {photo.uploaded_by_name || "Unknown"} · {(photo.uploaded_at || "").slice(0, 10)}
            {photo.tags && photo.tags.length > 0 ? (
              <span> · Tags: {photo.tags.join(", ")}</span>
            ) : null}
          </div>
          <div className="flex justify-end gap-2 pt-2">
            {canDelete ? (
              <button
                type="button"
                onClick={() => onDelete(photo)}
                className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
                style={{ background: c.danger, color: "#fff", border: 0, cursor: "pointer" }}
                data-testid="equipment-photo-delete-btn"
              >
                <Trash2 size={12} /> Delete
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="text-xs font-bold px-3 py-1.5 rounded-md"
              style={{ background: "transparent", border: `1px solid ${c.border}`, cursor: "pointer" }}
              data-testid="equipment-photo-close-btn"
            >Close</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function EquipmentSection({ customerId, type, photos, currentUser, onChange }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [lightbox, setLightbox] = useState(null);
  const inputRef = useRef(null);
  const remaining = Math.max(0, PHOTO_CAP - photos.length);
  const canDelete = isAdmin(currentUser);

  const upload = useCallback(async (files) => {
    if (!files || !files.length) return;
    setBusy(true); setErr("");
    try {
      const f = files[0];
      const data = await fileToDataUrl(f);
      await api.post(`/customers/${customerId}/equipment-photos`, {
        equipment_type: type,
        photo: data,
        tags: ["general"],
      });
      await onChange();
    } catch (e) {
      setErr(e?.message || "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }, [customerId, type, onChange]);

  const handleDelete = useCallback(async (photo) => {
    if (!window.confirm("Delete this photo?")) return;
    try {
      await api.del(`/customers/${customerId}/equipment-photos/${photo.id}`);
      setLightbox(null);
      await onChange();
    } catch (e) {
      setErr(e?.message || "Delete failed");
    }
  }, [customerId, onChange]);

  return (
    <div className="rounded-lg overflow-hidden"
         style={{ border: `1px solid ${c.border}`, background: "#fff" }}
         data-testid={`equipment-section-${type.replace(/\s+/g, "-").toLowerCase()}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-sm font-semibold text-left"
        style={{ background: c.surface, border: 0, cursor: "pointer", color: c.onSurface }}
        data-testid={`equipment-section-toggle-${type.replace(/\s+/g, "-").toLowerCase()}`}
      >
        <span className="inline-flex items-center gap-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {type}
        </span>
        <span className="text-xs font-bold" style={{ color: c.muted }}>
          {photos.length} / {PHOTO_CAP}
        </span>
      </button>
      {open ? (
        <div className="p-3">
          {err ? (
            <div className="text-xs px-2 py-1 mb-2 rounded"
                 style={{ background: "#FEE2E2", color: "#991B1B" }}
                 data-testid={`equipment-section-error-${type.replace(/\s+/g, "-").toLowerCase()}`}>{err}</div>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            {photos.map((p) => (
              <div key={p.id}
                   className="relative aspect-square rounded-md overflow-hidden cursor-pointer"
                   style={{ border: `1px solid ${c.border}`, background: c.surface }}
                   onClick={() => setLightbox(p)}
                   data-testid={`equipment-photo-${p.id}`}>
                <img src={p.photo_url} alt={p.caption || "Equipment"}
                     className="w-full h-full object-cover" />
                {(p.tags || []).includes("algae_before") ? (
                  <span className="absolute top-1 left-1 text-[10px] font-bold px-1.5 py-0.5 rounded"
                        style={{ background: "#B91C1C", color: "#fff" }}>ALGAE</span>
                ) : null}
              </div>
            ))}
            {remaining > 0 ? (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={busy}
                className="aspect-square rounded-md flex flex-col items-center justify-center gap-1"
                style={{
                  background: c.surface, border: `2px dashed ${c.border}`,
                  cursor: busy ? "wait" : "pointer",
                  opacity: busy ? 0.6 : 1,
                }}
                data-testid={`equipment-photo-add-${type.replace(/\s+/g, "-").toLowerCase()}`}
              >
                <Camera size={20} color={c.muted} />
                <span className="text-[10px] font-bold uppercase" style={{ color: c.muted }}>
                  {busy ? "Uploading…" : "Add photo"}
                </span>
              </button>
            ) : null}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => upload(e.target.files)}
            data-testid={`equipment-photo-input-${type.replace(/\s+/g, "-").toLowerCase()}`}
          />
        </div>
      ) : null}
      <LightBox
        photo={lightbox}
        canDelete={canDelete}
        onClose={() => setLightbox(null)}
        onDelete={handleDelete}
      />
    </div>
  );
}

export default function CustomerEquipmentLibrary({ customerId, currentUser }) {
  const [state, setState] = useState({ types: [], grouped: {}, loading: true, error: "" });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const res = await api.get(`/customers/${customerId}/equipment-photos`);
      setState({ types: res.types || [], grouped: res.grouped || {}, loading: false, error: "" });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e?.message || "Failed to load" }));
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-2" data-testid="customer-equipment-library">
      <div className="text-sm" style={{ color: c.muted }}>
        Up to {PHOTO_CAP} photos per equipment type. Techs upload, admins delete.
      </div>
      {state.loading ? (
        <div className="text-sm" style={{ color: c.muted }}>Loading…</div>
      ) : state.error ? (
        <div className="text-sm" style={{ color: c.danger }}>{state.error}</div>
      ) : (
        state.types.map((t) => (
          <EquipmentSection
            key={t}
            customerId={customerId}
            type={t}
            photos={state.grouped[t] || []}
            currentUser={currentUser}
            onChange={load}
          />
        ))
      )}
    </div>
  );
}
