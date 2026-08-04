/**
 * Service Categories settings page · Feb-2026.
 *
 * Mirror of IncomeCategoriesPage but scoped to the pricebook
 * ``service_categories`` collection. Two independent taxonomies —
 * do NOT reuse the income cache here.
 */
import React, { useEffect, useState } from "react";
import { Plus, Archive, ArchiveRestore, Pencil, Trash2, X } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import { Button } from "@/components/ui-kit";

function FormModal({ initial, onClose, onSaved }) {
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [color, setColor] = useState(initial?.color || "#0EA5E9");
  const [sortOrder, setSortOrder] = useState(initial?.sort_order || 0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const editing = Boolean(initial?.id);

  const save = async () => {
    if (!name.trim()) { setErr("Name is required."); return; }
    setBusy(true); setErr("");
    try {
      const payload = { name: name.trim(), description, color,
                         sort_order: Number(sortOrder) || 0 };
      const res = editing
        ? await api.patch(`/service-categories/${initial.id}`, payload)
        : await api.post("/service-categories", payload);
      onSaved?.(res);
    } catch (e) {
      setErr(e?.data?.detail?.error === "duplicate_name"
              ? "That name is already used."
              : (e?.message || "Save failed"));
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.55)" }} onClick={onClose}
          data-testid="svc-cat-form-backdrop">
      <div className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
            style={{ background: colors.surface }}
            onClick={(e) => e.stopPropagation()}
            data-testid="svc-cat-form">
        <header className="px-5 py-3 flex items-center justify-between"
                 style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="text-base font-bold"
                style={{ color: colors.onSurface }}>
            {editing ? "Edit service category" : "New service category"}
          </div>
          <button onClick={onClose} data-testid="svc-cat-form-close"
                  style={{ color: colors.muted }}><X size={18} /></button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Name *</label>
            <input type="text" value={name}
                    onChange={(e) => setName(e.target.value)}
                    autoFocus
                    className="w-full px-3 py-2 text-sm rounded-lg"
                    style={{ background: colors.surface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="svc-cat-form-name" />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Description</label>
            <input type="text" value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg"
                    style={{ background: colors.surface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="svc-cat-form-desc" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.muted }}>Color</label>
              <input type="color" value={color}
                      onChange={(e) => setColor(e.target.value)}
                      className="w-full h-9 rounded-lg cursor-pointer"
                      style={{ background: colors.surface,
                                border: `1px solid ${colors.border}` }}
                      data-testid="svc-cat-form-color" />
            </div>
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.muted }}>Sort</label>
              <input type="number" value={sortOrder}
                      onChange={(e) => setSortOrder(e.target.value)}
                      className="w-full px-3 py-2 text-sm rounded-lg"
                      style={{ background: colors.surface,
                                border: `1px solid ${colors.border}` }}
                      data-testid="svc-cat-form-sort" />
            </div>
          </div>
          {err ? (
            <div className="rounded-xl p-2 text-xs"
                  style={{ background: "#FEE2E2", color: "#7F1D1D",
                            border: "1px solid #FCA5A5" }}
                  data-testid="svc-cat-form-error">{err}</div>
          ) : null}
        </div>
        <footer className="px-5 py-3 flex justify-end gap-2"
                 style={{ borderTop: `1px solid ${colors.border}`,
                            background: colors.surfaceSecondary }}>
          <Button variant="ghost" onClick={onClose}
                  testid="svc-cat-form-cancel">Cancel</Button>
          <Button onClick={save} disabled={busy}
                  testid="svc-cat-form-save">
            {busy ? "Saving…" : "Save"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

export default function ServiceCategoriesPage() {
  const [items, setItems] = useState(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [toast, setToast] = useState("");

  const load = async () => {
    try {
      const url = includeArchived
        ? "/service-categories?include_archived=true"
        : "/service-categories";
      const r = await api.get(url);
      setItems(r?.items || []);
    } catch { setItems([]); }
  };

  useEffect(() => { load(); }, [includeArchived]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const archive = async (id) => {
    setBusyId(id);
    try { await api.post(`/service-categories/${id}/archive`, {}); await load(); }
    finally { setBusyId(""); }
  };
  const restore = async (id) => {
    setBusyId(id);
    try { await api.post(`/service-categories/${id}/restore`, {}); await load(); }
    finally { setBusyId(""); }
  };
  const hardDelete = async (id) => {
    if (!window.confirm("Permanently delete this service category? "
                         + "Only allowed if no pricebook items reference it.")) return;
    setBusyId(id);
    try {
      await api.del(`/service-categories/${id}`);
      await load();
      setToast("Category deleted.");
    } catch (e) {
      if (e?.data?.detail?.error === "category_in_use") {
        setToast(`Blocked — used by ${e.data.detail.linked_pricebook_items} pricebook item(s).`);
      } else {
        setToast(e?.message || "Delete failed.");
      }
    } finally { setBusyId(""); }
  };

  return (
    <div className="max-w-4xl mx-auto p-4" data-testid="service-categories-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-black"
              style={{ color: colors.onSurface }}>Service Categories</h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Higher-level business-unit taxonomy attached to pricebook items.
            (See Income Categories for the accounting-level picklist.)
          </p>
        </div>
        <Button onClick={() => setEditing({})} testid="svc-cat-new">
          <Plus size={14} /> New category
        </Button>
      </div>

      <label className="flex items-center gap-2 mb-3 text-sm">
        <input type="checkbox" checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                data-testid="svc-cat-show-archived" />
        <span style={{ color: colors.muted }}>Show archived</span>
      </label>

      {toast ? (
        <div className="rounded-xl p-2 mb-3 text-xs"
              style={{ background: "#FEF3C7", color: "#78350F",
                        border: "1px solid #FCD34D" }}
              data-testid="svc-cat-toast">{toast}</div>
      ) : null}

      <div className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="svc-cat-table">
          <thead style={{ background: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Color</th>
              <th className="text-left px-3 py-2 font-semibold">Name</th>
              <th className="text-left px-3 py-2 font-semibold">Description</th>
              <th className="text-right px-3 py-2 font-semibold">Sort</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="w-28 px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr><td colSpan="6" className="px-3 py-4 text-center"
                        style={{ color: colors.muted }}>Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="6" className="px-3 py-4 text-center"
                        style={{ color: colors.muted }}>
                No categories yet.
              </td></tr>
            ) : items.map((c) => (
              <tr key={c.id}
                  style={{ borderTop: `1px solid ${colors.border}`,
                            opacity: c.is_archived ? 0.55 : 1 }}
                  data-testid={`svc-cat-row-${c.id}`}>
                <td className="px-3 py-2">
                  <span className="inline-block w-5 h-5 rounded"
                        style={{ background: c.color || "#94A3B8" }} />
                </td>
                <td className="px-3 py-2 font-semibold"
                    style={{ color: colors.onSurface }}>{c.name}</td>
                <td className="px-3 py-2" style={{ color: colors.muted }}>
                  {c.description || "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs">
                  {c.sort_order || 0}
                </td>
                <td className="px-3 py-2 text-center text-xs">
                  {c.is_archived ? (
                    <span className="px-2 py-0.5 rounded-full"
                          style={{ background: "#FEE2E2", color: "#7F1D1D" }}>
                      Archived
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full"
                          style={{ background: "#DCFCE7", color: "#166534" }}>
                      Active
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button onClick={() => setEditing(c)}
                          disabled={busyId === c.id}
                          className="p-1 mr-1"
                          style={{ color: colors.brand }}
                          data-testid={`svc-cat-edit-${c.id}`}
                          title="Edit"><Pencil size={13} /></button>
                  {c.is_archived ? (
                    <button onClick={() => restore(c.id)}
                            disabled={busyId === c.id}
                            className="p-1 mr-1"
                            style={{ color: "#0891B2" }}
                            data-testid={`svc-cat-restore-${c.id}`}
                            title="Restore"><ArchiveRestore size={13} /></button>
                  ) : (
                    <button onClick={() => archive(c.id)}
                            disabled={busyId === c.id}
                            className="p-1 mr-1"
                            style={{ color: colors.warn || "#B45309" }}
                            data-testid={`svc-cat-archive-${c.id}`}
                            title="Archive"><Archive size={13} /></button>
                  )}
                  <button onClick={() => hardDelete(c.id)}
                          disabled={busyId === c.id}
                          className="p-1"
                          style={{ color: colors.error }}
                          data-testid={`svc-cat-delete-${c.id}`}
                          title="Delete permanently">
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing ? (
        <FormModal initial={editing}
                    onClose={() => setEditing(null)}
                    onSaved={() => { setEditing(null); load(); }} />
      ) : null}
    </div>
  );
}
