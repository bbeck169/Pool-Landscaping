/**
 * Task D · Feb-2026 — Employee Benefits page.
 *
 * Tenant-managed catalog of external-URL perks for the whole
 * workforce. Reads open to every authenticated user; CRUD
 * controls self-gate on ``admin`` / ``super_admin`` via
 * ``usePermissions()``. Backend enforcement lives on
 * ``/api/benefits`` (see ``routers/benefits.py``).
 *
 * UX shape mirrors ``pages/settings/MasterServicesSettings.jsx``
 * (modal-based CRUD, role-gated buttons, sonner toasts) with a
 * responsive tile grid instead of a table (each tile = one
 * benefit, whole tile is a clickable ``<a target="_blank">``).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Book,
  Briefcase,
  Building,
  Coffee,
  Dumbbell,
  Gift,
  GraduationCap,
  Heart,
  Pencil,
  PiggyBank,
  Plus,
  Shield,
  Smile,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";


// 12 curated Lucide icon names — kept in sync with the backend
// allowlist in ``backend/routers/benefits.py::BENEFIT_ICON_ALLOWLIST``.
// Order matches the preset picker's visual order in the admin
// modal.
export const ICON_ALLOWLIST = [
  "gift", "heart", "building", "briefcase", "coffee",
  "graduation-cap", "shield", "smile", "sparkles",
  "book", "dumbbell", "piggy-bank",
];

const ICON_MAP = {
  gift: Gift,
  heart: Heart,
  building: Building,
  briefcase: Briefcase,
  coffee: Coffee,
  "graduation-cap": GraduationCap,
  shield: Shield,
  smile: Smile,
  sparkles: Sparkles,
  book: Book,
  dumbbell: Dumbbell,
  "piggy-bank": PiggyBank,
};

function IconFor({ name, size = 28 }) {
  // Defensive fallback: if a persisted icon name isn't in the map
  // (future removal, typo in a hand-edited row), render Gift. Log
  // a dev-mode warning so the drift is loud, not silent.
  const Comp = ICON_MAP[name] || Gift;
  if (!ICON_MAP[name] && typeof console !== "undefined"
      && process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.warn(`[EmployeeBenefits] Unknown icon "${name}"; falling back to Gift.`);
  }
  return <Comp size={size} aria-hidden />;
}


function BenefitModal({ initial, onClose, onSaved }) {
  const editing = Boolean(initial?.id);
  const [title, setTitle] = useState(initial?.title || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [externalUrl, setExternalUrl] = useState(initial?.external_url || "");
  const [icon, setIcon] = useState(initial?.icon || "gift");
  const [isActive, setIsActive] = useState(
    typeof initial?.is_active === "boolean" ? initial.is_active : true,
  );
  const [sortOrder, setSortOrder] = useState(
    Number.isFinite(initial?.sort_order) ? String(initial.sort_order) : "0",
  );
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const save = useCallback(async () => {
    setErr("");
    const t = (title || "").trim();
    const u = (externalUrl || "").trim();
    if (!t) { setErr("Title is required."); return; }
    if (!u) { setErr("External URL is required."); return; }
    if (!/^https?:\/\//i.test(u)) {
      setErr("External URL must start with http:// or https://.");
      return;
    }
    const nSort = Number(sortOrder);
    if (sortOrder !== "" && !Number.isFinite(nSort)) {
      setErr("Sort order must be a number.");
      return;
    }
    const payload = {
      title: t,
      description: (description || "").trim(),
      external_url: u,
      icon,
      is_active: !!isActive,
      sort_order: sortOrder === "" ? 0 : nSort,
    };
    setBusy(true);
    try {
      const res = editing
        ? await api.patch(`/benefits/${initial.id}`, payload)
        : await api.post("/benefits", payload);
      onSaved?.(res);
    } catch (e) {
      const detail = e?.data?.detail;
      if (typeof detail === "string") setErr(detail);
      else if (Array.isArray(detail) && detail[0]?.msg) setErr(detail[0].msg);
      else setErr(e?.message || "Save failed.");
    } finally { setBusy(false); }
  }, [editing, initial?.id, title, description, externalUrl, icon,
       isActive, sortOrder]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(15, 23, 42, 0.55)" }}
          data-testid="benefit-modal-backdrop">
      <div className="w-full max-w-lg rounded-lg shadow-2xl"
            style={{ background: colors.surface, color: colors.text }}
            data-testid="benefit-modal">
        <div className="flex items-center justify-between px-5 py-4"
              style={{ borderBottom: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-semibold">
            {editing ? "Edit benefit" : "New benefit"}
          </h2>
          <button type="button" onClick={onClose}
                   className="p-1 rounded hover:opacity-70"
                   data-testid="benefit-modal-close">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <label className="block text-sm">
            <span className="block mb-1" style={{ color: colors.muted }}>
              Title <span style={{ color: "#ef4444" }}>*</span>
            </span>
            <input type="text" value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full px-3 py-2 rounded"
                    style={{ background: colors.bg, color: colors.text,
                              border: `1px solid ${colors.border}` }}
                    data-testid="benefit-modal-title"
                    maxLength={120} />
          </label>

          <label className="block text-sm">
            <span className="block mb-1" style={{ color: colors.muted }}>
              Description
            </span>
            <textarea value={description} rows={3}
                       onChange={(e) => setDescription(e.target.value)}
                       className="w-full px-3 py-2 rounded"
                       style={{ background: colors.bg, color: colors.text,
                                 border: `1px solid ${colors.border}` }}
                       data-testid="benefit-modal-description"
                       maxLength={1000} />
          </label>

          <label className="block text-sm">
            <span className="block mb-1" style={{ color: colors.muted }}>
              External URL <span style={{ color: "#ef4444" }}>*</span>
            </span>
            <input type="url" value={externalUrl}
                    onChange={(e) => setExternalUrl(e.target.value)}
                    placeholder="https://example.com"
                    className="w-full px-3 py-2 rounded"
                    style={{ background: colors.bg, color: colors.text,
                              border: `1px solid ${colors.border}` }}
                    data-testid="benefit-modal-url" />
          </label>

          <div className="block text-sm">
            <span className="block mb-1" style={{ color: colors.muted }}>
              Icon
            </span>
            <div className="grid grid-cols-6 gap-2"
                  data-testid="benefit-modal-icon-picker">
              {ICON_ALLOWLIST.map((name) => {
                const Comp = ICON_MAP[name];
                const selected = icon === name;
                return (
                  <button type="button" key={name}
                           onClick={() => setIcon(name)}
                           className="flex flex-col items-center justify-center py-2 rounded transition"
                           style={{
                             background: selected ? colors.accent : colors.bg,
                             color: selected ? "#fff" : colors.text,
                             border: `1px solid ${selected ? colors.accent : colors.border}`,
                           }}
                           data-testid={`benefit-modal-icon-${name}`}
                           aria-pressed={selected}
                           title={name}>
                    <Comp size={20} aria-hidden />
                    <span className="text-[10px] mt-1 leading-tight">
                      {name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={isActive}
                      onChange={(e) => setIsActive(e.target.checked)}
                      data-testid="benefit-modal-active" />
              <span>Active</span>
            </label>
            <label className="flex items-center gap-2">
              <span style={{ color: colors.muted }}>Sort order</span>
              <input type="number" value={sortOrder}
                      onChange={(e) => setSortOrder(e.target.value)}
                      className="w-20 px-2 py-1 rounded"
                      style={{ background: colors.bg, color: colors.text,
                                border: `1px solid ${colors.border}` }}
                      data-testid="benefit-modal-sort-order" />
            </label>
          </div>

          {err ? (
            <div className="text-sm px-3 py-2 rounded"
                  style={{ background: "#fee2e2", color: "#b91c1c" }}
                  data-testid="benefit-modal-error">
              {err}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3"
              style={{ borderTop: `1px solid ${colors.border}` }}>
          <button type="button" onClick={onClose} disabled={busy}
                   className="px-3 py-2 rounded text-sm"
                   style={{ background: colors.bg, color: colors.text,
                             border: `1px solid ${colors.border}` }}
                   data-testid="benefit-modal-cancel">
            Cancel
          </button>
          <button type="button" onClick={save} disabled={busy}
                   className="px-3 py-2 rounded text-sm font-medium"
                   style={{ background: colors.accent, color: "#fff" }}
                   data-testid="benefit-modal-save">
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


function DeleteConfirm({ benefit, onClose, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const runDelete = useCallback(async () => {
    setBusy(true);
    try {
      await api.delete(`/benefits/${benefit.id}`);
      onDeleted?.();
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    } finally { setBusy(false); }
  }, [benefit?.id, onDeleted]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(15, 23, 42, 0.55)" }}
          data-testid="benefit-delete-backdrop">
      <div className="w-full max-w-md rounded-lg shadow-2xl"
            style={{ background: colors.surface, color: colors.text }}
            data-testid="benefit-delete-modal">
        <div className="px-5 py-4"
              style={{ borderBottom: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-semibold">Delete benefit?</h2>
        </div>
        <div className="px-5 py-4 text-sm">
          <p>
            Are you sure you want to delete{" "}
            <strong>{benefit?.title}</strong>? This is a soft-delete and
            can be reversed by a super-admin.
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3"
              style={{ borderTop: `1px solid ${colors.border}` }}>
          <button type="button" onClick={onClose} disabled={busy}
                   className="px-3 py-2 rounded text-sm"
                   style={{ background: colors.bg, color: colors.text,
                             border: `1px solid ${colors.border}` }}
                   data-testid="benefit-delete-cancel">
            Cancel
          </button>
          <button type="button" onClick={runDelete} disabled={busy}
                   className="px-3 py-2 rounded text-sm font-medium"
                   style={{ background: "#dc2626", color: "#fff" }}
                   data-testid="benefit-delete-confirm">
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function EmployeeBenefits() {
  const { effectiveRole } = usePermissions();
  const canManage = useMemo(
    () => effectiveRole === "admin" || effectiveRole === "super_admin",
    [effectiveRole],
  );
  const [rows, setRows] = useState(null);      // null = loading
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get("/benefits");
      setRows(Array.isArray(r?.items) ? r.items : []);
    } catch (e) {
      toast.error(e?.message || "Failed to load benefits");
      setRows([]);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6"
          data-testid="employee-benefits-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold"
               style={{ color: colors.text }}>
            Employee Benefits
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Perks and resources available to every teammate.
          </p>
        </div>
        {canManage ? (
          <button type="button"
                   onClick={() => setCreating(true)}
                   className="flex items-center gap-2 px-3 py-2 rounded text-sm font-medium"
                   style={{ background: colors.accent, color: "#fff" }}
                   data-testid="benefits-new-btn">
            <Plus size={16} /> New benefit
          </button>
        ) : null}
      </div>

      {rows === null ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="benefits-loading">
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="text-sm py-16 text-center rounded"
              style={{ color: colors.muted, background: colors.surface,
                        border: `1px dashed ${colors.border}` }}
              data-testid="benefits-empty">
          No benefits published yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
              data-testid="benefits-grid">
          {rows.map((b) => (
            <div key={b.id}
                  className="relative rounded-lg shadow-sm hover:shadow-md transition"
                  style={{ background: colors.surface,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`benefit-tile-${b.id}`}>
              <a href={b.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block px-4 py-4 h-full"
                  data-testid={`benefit-link-${b.id}`}>
                <div className="flex items-start gap-3">
                  <div className="flex items-center justify-center rounded"
                        style={{ background: colors.bg, padding: 10,
                                  color: colors.accent }}
                        data-testid={`benefit-icon-${b.id}`}>
                    <IconFor name={b.icon} size={22} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium truncate"
                          style={{ color: colors.text }}
                          data-testid={`benefit-title-${b.id}`}>
                      {b.title}
                    </div>
                    {b.description ? (
                      <div className="text-xs mt-1 line-clamp-3"
                            style={{ color: colors.muted }}
                            data-testid={`benefit-desc-${b.id}`}>
                        {b.description}
                      </div>
                    ) : null}
                  </div>
                </div>
              </a>
              {canManage ? (
                <div className="absolute top-2 right-2 flex gap-1"
                      data-testid={`benefit-controls-${b.id}`}>
                  <button type="button"
                           onClick={(e) => { e.preventDefault(); setEditing(b); }}
                           className="p-1.5 rounded hover:opacity-80"
                           style={{ background: colors.bg,
                                     border: `1px solid ${colors.border}`,
                                     color: colors.text }}
                           data-testid={`benefit-edit-${b.id}`}
                           aria-label={`Edit ${b.title}`}>
                    <Pencil size={14} />
                  </button>
                  <button type="button"
                           onClick={(e) => { e.preventDefault(); setDeleting(b); }}
                           className="p-1.5 rounded hover:opacity-80"
                           style={{ background: colors.bg,
                                     border: `1px solid ${colors.border}`,
                                     color: "#dc2626" }}
                           data-testid={`benefit-delete-${b.id}`}
                           aria-label={`Delete ${b.title}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {creating ? (
        <BenefitModal
          initial={null}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            toast.success("Benefit created");
            refresh();
          }}
        />
      ) : null}
      {editing ? (
        <BenefitModal
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            toast.success("Benefit updated");
            refresh();
          }}
        />
      ) : null}
      {deleting ? (
        <DeleteConfirm
          benefit={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            toast.success("Benefit deleted");
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}
