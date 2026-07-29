/**
 * Income Categories settings page · Feb-2026.
 *
 * Admin CRUD for the income category picklist. Categories are
 * referenced by invoice line items; enforcement lives in the backend
 * (routers/income_categories.py::validate_line_item_categories).
 */
import React, { useEffect, useState } from "react";
import { Plus, Archive, ArchiveRestore, Pencil, X } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import { Button } from "@/components/ui-kit";
import { invalidateCategoryCache } from "@/components/income/CategoryPicker";

function CategoryFormModal({ initial, onClose, onSaved }) {
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [color, setColor] = useState(initial?.color || "#94A3B8");
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
        ? await api.patch(`/income-categories/${initial.id}`, payload)
        : await api.post("/income-categories", payload);
      invalidateCategoryCache();
      onSaved?.(res);
    } catch (e) {
      setErr(e?.data?.detail?.error === "duplicate_name"
              ? "A category with that name already exists."
              : (e?.message || "Save failed"));
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="income-cat-form-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="income-cat-form"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold"
                style={{ color: colors.onSurface }}>
            {editing ? "Edit category" : "New category"}
          </div>
          <button onClick={onClose} data-testid="income-cat-form-close"
                  style={{ color: colors.muted }}><X size={18} /></button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="income-cat-form-name"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="income-cat-form-desc"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.muted }}>Color</label>
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="w-full h-9 rounded-lg cursor-pointer"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="income-cat-form-color"
              />
            </div>
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.muted }}>Sort order</label>
              <input
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="income-cat-form-sort"
              />
            </div>
          </div>
          {err ? (
            <div className="rounded-xl p-2 text-xs"
                  style={{ background: "#FEE2E2", color: "#7F1D1D",
                            border: "1px solid #FCA5A5" }}
                  data-testid="income-cat-form-error">{err}</div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`,
                    background: colors.surfaceSecondary }}
        >
          <Button variant="ghost" onClick={onClose}
                  testid="income-cat-form-cancel">Cancel</Button>
          <Button onClick={save} disabled={busy}
                  testid="income-cat-form-save">
            {busy ? "Saving…" : "Save"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

export default function IncomeCategoriesPage() {
  const [items, setItems] = useState(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editing, setEditing] = useState(null);   // {} for new, doc for edit
  const [busyId, setBusyId] = useState("");

  const load = async () => {
    try {
      const url = includeArchived
        ? "/income-categories?include_archived=true"
        : "/income-categories";
      const r = await api.get(url);
      setItems(r?.items || []);
    } catch {
      setItems([]);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [includeArchived]);

  const archive = async (id) => {
    setBusyId(id);
    await api.post(`/income-categories/${id}/archive`, {});
    invalidateCategoryCache();
    await load();
    setBusyId("");
  };
  const restore = async (id) => {
    setBusyId(id);
    await api.post(`/income-categories/${id}/restore`, {});
    invalidateCategoryCache();
    await load();
    setBusyId("");
  };

  return (
    <div className="max-w-4xl mx-auto p-4" data-testid="income-categories-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-black"
              style={{ color: colors.onSurface }}>Income Categories</h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Manage the picklist that categorizes invoice line items and
            direct income entries.
          </p>
        </div>
        <Button onClick={() => setEditing({})} testid="income-cat-new">
          <Plus size={14} /> New category
        </Button>
      </div>

      <label className="flex items-center gap-2 mb-3 text-sm">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => setIncludeArchived(e.target.checked)}
          data-testid="income-cat-show-archived"
        />
        <span style={{ color: colors.muted }}>Show archived</span>
      </label>

      <div className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm"
                data-testid="income-cat-table">
          <thead style={{ background: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Color</th>
              <th className="text-left px-3 py-2 font-semibold">Name</th>
              <th className="text-left px-3 py-2 font-semibold">Description</th>
              <th className="text-right px-3 py-2 font-semibold">Sort</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="w-20 px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr><td colSpan="6" className="px-3 py-4 text-center"
                        style={{ color: colors.muted }}>Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan="6" className="px-3 py-4 text-center"
                        style={{ color: colors.muted }}>
                No categories yet — create your first one.
              </td></tr>
            ) : items.map((c) => (
              <tr key={c.id}
                  style={{ borderTop: `1px solid ${colors.border}`,
                            opacity: c.is_archived ? 0.55 : 1 }}
                  data-testid={`income-cat-row-${c.id}`}>
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
                  <button
                    onClick={() => setEditing(c)}
                    disabled={busyId === c.id}
                    className="p-1 mr-1"
                    style={{ color: colors.brand }}
                    data-testid={`income-cat-edit-${c.id}`}
                    title="Edit"
                  ><Pencil size={13} /></button>
                  {c.is_archived ? (
                    <button
                      onClick={() => restore(c.id)}
                      disabled={busyId === c.id}
                      className="p-1"
                      style={{ color: "#0891B2" }}
                      data-testid={`income-cat-restore-${c.id}`}
                      title="Restore"
                    ><ArchiveRestore size={13} /></button>
                  ) : (
                    <button
                      onClick={() => archive(c.id)}
                      disabled={busyId === c.id}
                      className="p-1"
                      style={{ color: colors.error }}
                      data-testid={`income-cat-archive-${c.id}`}
                      title="Archive"
                    ><Archive size={13} /></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing ? (
        <CategoryFormModal
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      ) : null}
    </div>
  );
}
