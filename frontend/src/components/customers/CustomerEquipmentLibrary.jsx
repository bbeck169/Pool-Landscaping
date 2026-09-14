/**
 * Phase Feb-2026 — Customer Equipment Library (web, canonical).
 *
 * Card-per-unit UI. Each customer_equipment record shows
 * equipment_type + brand/model/serial/install_date + a strip of
 * S3-backed photos uploaded via /api/files/upload. Legacy
 * /customers/{id}/equipment-photos endpoints stay untouched for
 * back-compat with the mobile client and any historical photo
 * blobs — new units render here on the new pipeline only.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Camera, Pencil, Plus, Trash2 } from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import {
  buildAuthedDownloadUrl,
  deleteFile,
  uploadFile,
} from "@/api/files";
import { compressImageIfNeeded } from "../../lib/imageCompress";

const c = {
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#F8FAFC",
  onSurface: "#0F172A",
  danger: "#DC2626",
  brand: "#0EA5E9",
};

function currentToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function canWrite(user) {
  const role = (user?.role || "").toLowerCase();
  return ["admin", "super_admin", "technician"].includes(role);
}

const EMPTY_FORM = {
  equipment_type: "",
  brand: "",
  model: "",
  serial_number: "",
  install_date: "",
  notes: "",
};

// ─── Equipment form modal ─────────────────────────────────────────
function EquipmentFormModal({
  open,
  initial,
  equipmentTypes,
  onSubmit,
  onClose,
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setForm({
        equipment_type: initial.equipment_type || "",
        brand: initial.brand || "",
        model: initial.model || "",
        serial_number: initial.serial_number || "",
        install_date: initial.install_date || "",
        notes: initial.notes || "",
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setErr("");
  }, [open, initial]);

  if (!open) return null;

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      if (!form.equipment_type) {
        throw new Error("Equipment type is required");
      }
      await onSubmit(form);
      onClose();
    } catch (e) {
      setErr(e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const isEdit = Boolean(initial);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onClick={onClose}
      data-testid="equipment-form-modal"
    >
      <div
        className="w-full max-w-lg rounded-xl overflow-hidden shadow-2xl"
        style={{ background: "#fff" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-4 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${c.border}` }}
        >
          <div className="text-sm font-bold" style={{ color: c.onSurface }}>
            {isEdit ? "Edit Equipment" : "Add Equipment"}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-lg px-2"
            style={{ color: c.muted, background: "transparent", border: 0, cursor: "pointer" }}
            data-testid="equipment-form-close"
          >
            ×
          </button>
        </div>

        <div className="p-4 space-y-3 text-sm" style={{ color: c.onSurface }}>
          {err ? (
            <div
              className="text-xs px-2 py-1 rounded"
              style={{ background: "#FEE2E2", color: "#991B1B" }}
              data-testid="equipment-form-error"
            >
              {err}
            </div>
          ) : null}

          <div>
            <label className="text-xs font-semibold" style={{ color: c.muted }}>
              Equipment Type *
            </label>
            <select
              value={form.equipment_type}
              onChange={(e) => update("equipment_type", e.target.value)}
              className="w-full mt-1 px-3 py-2 rounded-md text-sm"
              style={{ border: `1px solid ${c.border}`, background: "#fff" }}
              data-testid="equipment-type-select"
            >
              <option value="">— Select —</option>
              {equipmentTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Brand
              </label>
              <input
                type="text"
                value={form.brand}
                onChange={(e) => update("brand", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}` }}
                data-testid="equipment-brand-input"
              />
            </div>
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Model
              </label>
              <input
                type="text"
                value={form.model}
                onChange={(e) => update("model", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}` }}
                data-testid="equipment-model-input"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Serial Number
              </label>
              <input
                type="text"
                value={form.serial_number}
                onChange={(e) => update("serial_number", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}` }}
                data-testid="equipment-serial-input"
              />
            </div>
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Install Date
              </label>
              <input
                type="date"
                value={form.install_date}
                onChange={(e) => update("install_date", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}` }}
                data-testid="equipment-install-date-input"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold" style={{ color: c.muted }}>
              Notes
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => update("notes", e.target.value)}
              rows={2}
              className="w-full mt-1 px-3 py-2 rounded-md text-sm"
              style={{ border: `1px solid ${c.border}` }}
              data-testid="equipment-notes-input"
            />
          </div>
        </div>

        <div
          className="px-4 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${c.border}`, background: c.surface }}
        >
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: "transparent",
              border: `1px solid ${c.border}`,
              cursor: "pointer",
            }}
            data-testid="equipment-form-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: c.brand,
              color: "#fff",
              border: 0,
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
            data-testid="equipment-form-submit"
          >
            {busy ? "Saving…" : isEdit ? "Save" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Photo strip on each card ─────────────────────────────────────
function PhotoStrip({ unit, canEdit, onUploaded, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const inputRef = useRef(null);
  const token = currentToken();

  const upload = useCallback(
    async (files) => {
      if (!files || !files.length) return;
      setBusy(true);
      setErr("");
      try {
        const compressed = await compressImageIfNeeded(files[0]);
        await uploadFile({
          file: compressed,
          purpose: "customer_equipment",
          linkedEntityType: "customer_equipment",
          linkedEntityId: unit.id,
        });
        await onUploaded();
      } catch (e) {
        setErr(e?.message || "Upload failed");
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [unit.id, onUploaded]
  );

  const removePhoto = useCallback(
    async (photoId) => {
      if (!window.confirm("Delete this photo?")) return;
      try {
        await deleteFile(photoId);
        await onDeleted();
      } catch (e) {
        setErr(e?.message || "Delete failed");
      }
    },
    [onDeleted]
  );

  const photos = unit.photos || [];

  return (
    <div className="mt-2">
      {err ? (
        <div
          className="text-[11px] px-2 py-1 mb-2 rounded"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid={`equipment-photo-error-${unit.id}`}
        >
          {err}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {photos.map((p, i) => {
          const url = buildAuthedDownloadUrl(p.id, token);
          const isImage = (p.content_type || "").startsWith("image/");
          return (
            <div
              key={p.id}
              className="relative"
              style={{
                width: 64,
                height: 64,
                border: `1px solid ${c.border}`,
                borderRadius: 8,
                overflow: "hidden",
                background: c.surface,
              }}
              data-testid={`equipment-photo-thumb-${i}`}
            >
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: "block",
                  width: "100%",
                  height: "100%",
                }}
              >
                {isImage ? (
                  <img
                    src={url}
                    alt={p.filename || "Equipment photo"}
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                  />
                ) : (
                  <div
                    className="w-full h-full flex flex-col items-center justify-center text-[9px] font-bold"
                    style={{ color: c.muted, padding: 4, textAlign: "center" }}
                  >
                    <span>FILE</span>
                    <span
                      style={{
                        maxWidth: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {(p.filename || "").slice(0, 10)}
                    </span>
                  </div>
                )}
              </a>
              {canEdit ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    removePhoto(p.id);
                  }}
                  className="absolute top-0 right-0"
                  style={{
                    background: "rgba(15,23,42,0.65)",
                    color: "#fff",
                    border: 0,
                    borderBottomLeftRadius: 6,
                    padding: "2px 4px",
                    cursor: "pointer",
                    lineHeight: 1,
                  }}
                  data-testid={`equipment-photo-thumb-${i}-delete`}
                  aria-label="Delete photo"
                >
                  <Trash2 size={10} />
                </button>
              ) : null}
            </div>
          );
        })}

        {canEdit ? (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="flex flex-col items-center justify-center gap-1"
            style={{
              width: 64,
              height: 64,
              background: c.surface,
              border: `2px dashed ${c.border}`,
              borderRadius: 8,
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
            data-testid={`equipment-photo-upload-${unit.id}`}
          >
            <Camera size={16} color={c.muted} />
            <span
              className="text-[9px] font-bold uppercase"
              style={{ color: c.muted }}
            >
              {busy ? "Uploading…" : "Add"}
            </span>
          </button>
        ) : null}
        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf"
          style={{ display: "none" }}
          onChange={(e) => upload(e.target.files)}
          data-testid={`equipment-photo-input-${unit.id}`}
        />
      </div>
    </div>
  );
}

// ─── Individual equipment card ─────────────────────────────────────
function EquipmentCard({ unit, canEdit, onEdit, onDelete, onRefresh }) {
  const fields = [
    ["Brand", unit.brand],
    ["Model", unit.model],
    ["Serial", unit.serial_number],
    ["Installed", unit.install_date],
  ].filter(([, v]) => v && String(v).trim());

  return (
    <div
      className="rounded-lg p-3"
      style={{
        border: `1px solid ${c.border}`,
        background: "#fff",
      }}
      data-testid={`equipment-card-${unit.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div
            className="text-sm font-bold"
            style={{ color: c.onSurface }}
            data-testid={`equipment-card-type-${unit.id}`}
          >
            {unit.equipment_type}
          </div>
          {fields.length ? (
            <div
              className="mt-1 text-xs space-y-0.5"
              style={{ color: c.muted }}
              data-testid={`equipment-card-fields-${unit.id}`}
            >
              {fields.map(([label, value]) => (
                <div key={label}>
                  <span className="font-semibold">{label}:</span> {value}
                </div>
              ))}
            </div>
          ) : null}
          {unit.notes ? (
            <div
              className="mt-2 text-xs"
              style={{ color: c.onSurface, whiteSpace: "pre-wrap" }}
              data-testid={`equipment-card-notes-${unit.id}`}
            >
              {unit.notes}
            </div>
          ) : null}
        </div>

        {canEdit ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={() => onEdit(unit)}
              className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-1 rounded-md"
              style={{
                background: c.surface,
                border: `1px solid ${c.border}`,
                color: c.onSurface,
                cursor: "pointer",
              }}
              data-testid={`equipment-card-edit-${unit.id}`}
            >
              <Pencil size={11} /> Edit
            </button>
            <button
              type="button"
              onClick={() => onDelete(unit)}
              className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-1 rounded-md"
              style={{
                background: "#FEE2E2",
                color: c.danger,
                border: `1px solid #FCA5A5`,
                cursor: "pointer",
              }}
              data-testid={`equipment-card-delete-${unit.id}`}
            >
              <Trash2 size={11} /> Delete
            </button>
          </div>
        ) : null}
      </div>

      <PhotoStrip
        unit={unit}
        canEdit={canEdit}
        onUploaded={onRefresh}
        onDeleted={onRefresh}
      />
    </div>
  );
}

// ─── Root component ─────────────────────────────────────────────────
export default function CustomerEquipmentLibrary({ customerId, currentUser }) {
  const [state, setState] = useState({
    items: [],
    loading: true,
    error: "",
  });
  const [equipmentTypes, setEquipmentTypes] = useState([]);
  const [modal, setModal] = useState({ open: false, initial: null });

  const canEdit = useMemo(() => canWrite(currentUser), [currentUser]);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const res = await api.get(
        `/customer-equipment?customer_id=${encodeURIComponent(customerId)}`
      );
      setState({
        items: res.items || [],
        loading: false,
        error: "",
      });
    } catch (e) {
      setState((s) => ({
        ...s,
        loading: false,
        error: e?.message || "Failed to load equipment",
      }));
    }
  }, [customerId]);

  const loadTypes = useCallback(async () => {
    try {
      const res = await api.get(`/equipment-types`);
      setEquipmentTypes(res.types || []);
    } catch {
      setEquipmentTypes([]);
    }
  }, []);

  useEffect(() => {
    load();
    loadTypes();
  }, [load, loadTypes]);

  const openAdd = () => setModal({ open: true, initial: null });
  const openEdit = (unit) => setModal({ open: true, initial: unit });
  const closeModal = () => setModal({ open: false, initial: null });

  const submitForm = useCallback(
    async (form) => {
      const payload = {
        equipment_type: form.equipment_type,
        brand: form.brand || null,
        model: form.model || null,
        serial_number: form.serial_number || null,
        install_date: form.install_date || null,
        notes: form.notes || null,
      };
      if (modal.initial) {
        await api.patch(`/customer-equipment/${modal.initial.id}`, payload);
      } else {
        await api.post(`/customer-equipment`, {
          ...payload,
          customer_id: customerId,
        });
      }
      await load();
    },
    [modal.initial, customerId, load]
  );

  const removeUnit = useCallback(
    async (unit) => {
      if (
        !window.confirm(
          `Delete ${unit.equipment_type}${unit.brand ? " (" + unit.brand + ")" : ""}?`
        )
      )
        return;
      try {
        await api.delete(`/customer-equipment/${unit.id}`);
        await load();
      } catch (e) {
        setState((s) => ({
          ...s,
          error: e?.message || "Delete failed",
        }));
      }
    },
    [load]
  );

  return (
    <div className="space-y-3" data-testid="customer-equipment-library">
      <div className="flex items-center justify-between">
        <div className="text-sm" style={{ color: c.muted }}>
          One card per equipment unit. Admins &amp; techs can add / edit;
          customers are read-only.
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={openAdd}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: c.brand,
              color: "#fff",
              border: 0,
              cursor: "pointer",
            }}
            data-testid="equipment-add-btn"
          >
            <Plus size={12} /> Add Equipment
          </button>
        ) : null}
      </div>

      {state.loading ? (
        <div
          className="text-sm"
          style={{ color: c.muted }}
          data-testid="equipment-loading"
        >
          Loading…
        </div>
      ) : state.error ? (
        <div
          className="text-sm"
          style={{ color: c.danger }}
          data-testid="equipment-error"
        >
          {state.error}
        </div>
      ) : state.items.length === 0 ? (
        <div
          className="text-sm p-4 rounded-lg text-center"
          style={{
            color: c.muted,
            background: c.surface,
            border: `1px dashed ${c.border}`,
          }}
          data-testid="equipment-empty"
        >
          No equipment recorded yet.
        </div>
      ) : (
        <div className="space-y-2" data-testid="equipment-list">
          {state.items.map((u) => (
            <EquipmentCard
              key={u.id}
              unit={u}
              canEdit={canEdit}
              onEdit={openEdit}
              onDelete={removeUnit}
              onRefresh={load}
            />
          ))}
        </div>
      )}

      <EquipmentFormModal
        open={modal.open}
        initial={modal.initial}
        equipmentTypes={equipmentTypes}
        onSubmit={submitForm}
        onClose={closeModal}
      />
    </div>
  );
}
