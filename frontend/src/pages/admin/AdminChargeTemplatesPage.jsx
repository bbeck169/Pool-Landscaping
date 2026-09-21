/**
 * Phase F2 · Feb-2026 — Charge Template Bundles admin CRUD.
 *
 * Route: /admin/charge-templates (admin+ only)
 *
 * Lets admins create reusable "bundles" of 3-4 line items so techs can
 * append the whole bundle onto a job in a single click from the schedule
 * job-edit modal.
 *
 * Design notes:
 *   • The template editor uses a compact inline row editor (name /
 *     price / qty / category / description). The F7 LineItemsSection
 *     (jobs) is intentionally NOT reused here — it's tightly coupled
 *     to the pricebook picker + per-row REST calls. Extracting a
 *     shared LineItemsEditor primitive (TD-F7-1) is deferred.
 *   • Soft-delete via ArmToDelete (existing primitive).
 *   • Sonner toasts on save/delete for parity with AdminTagsList.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Pencil, X as XIcon, Search } from "lucide-react";
import { api } from "../../api";
import { colors, money } from "../../theme";
import { Button, PageHeader } from "../../components/ui-kit";
import ArmToDelete from "../../components/ui/ArmToDelete";

const CATEGORIES = [
  { value: "chemicals", label: "Chemicals" },
  { value: "maintenance", label: "Maintenance" },
  { value: "repair", label: "Repair" },
  { value: "custom", label: "Custom" },
];

function _emptyLineItem() {
  return {
    _key: Math.random().toString(36).slice(2, 10),
    name: "",
    unit_price: "",
    quantity: "1",
    category: "",
    description: "",
  };
}

function _templateTotal(items) {
  let sub = 0;
  for (const li of items || []) {
    const p = parseFloat(li.unit_price || 0) || 0;
    const q = parseFloat(li.quantity || 0) || 0;
    sub += p * q;
  }
  return Math.round(sub * 100) / 100;
}

function TemplateEditorModal({ open, mode, initial, onClose, onSubmit, busy }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0].value);
  const [lineItems, setLineItems] = useState([_emptyLineItem()]);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    setName(initial?.name || "");
    setDescription(initial?.description || "");
    setCategory(initial?.category || CATEGORIES[0].value);
    if (initial?.line_items?.length) {
      setLineItems(initial.line_items.map((li) => ({
        _key: Math.random().toString(36).slice(2, 10),
        name: li.name || "",
        unit_price: String(li.unit_price ?? ""),
        quantity: String(li.quantity ?? "1"),
        category: li.category || "",
        description: li.description || "",
      })));
    } else {
      setLineItems([_emptyLineItem()]);
    }
  }, [open, initial]);

  if (!open) return null;
  const isEdit = mode === "edit";

  const patchRow = (key, patch) =>
    setLineItems((rows) => rows.map((r) => (r._key === key ? { ...r, ...patch } : r)));
  const removeRow = (key) =>
    setLineItems((rows) => (rows.length > 1
      ? rows.filter((r) => r._key !== key)
      : rows));
  const addRow = () =>
    setLineItems((rows) => (rows.length >= 20
      ? rows
      : [...rows, _emptyLineItem()]));

  const submit = () => {
    setErr("");
    const trimmedName = (name || "").trim();
    if (!trimmedName) { setErr("Name is required"); return; }
    if (lineItems.length < 1) { setErr("Add at least one line item"); return; }
    for (const li of lineItems) {
      if (!(li.name || "").trim()) {
        setErr("Every line item needs a name"); return;
      }
      const up = parseFloat(li.unit_price);
      if (!Number.isFinite(up) || up < 0) {
        setErr(`Line "${li.name}" needs a valid unit price >= 0`); return;
      }
      const q = parseFloat(li.quantity);
      if (!Number.isFinite(q) || q <= 0) {
        setErr(`Line "${li.name}" needs a quantity > 0`); return;
      }
    }
    onSubmit({
      name: trimmedName,
      description: (description || "").trim() || null,
      category,
      line_items: lineItems.map((li) => ({
        name: (li.name || "").trim(),
        unit_price: parseFloat(li.unit_price),
        quantity: parseFloat(li.quantity),
        category: (li.category || "").trim() || null,
        description: (li.description || "").trim() || null,
      })),
    });
  };

  const total = _templateTotal(lineItems);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="charge-template-editor"
    >
      <div
        className="w-full max-w-3xl rounded-2xl p-6 shadow-2xl overflow-y-auto"
        style={{ backgroundColor: colors.surface,
                 border: `1px solid ${colors.border}`,
                 maxHeight: "90vh" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}
              data-testid="charge-template-editor-title">
            {isEdit ? "Edit template" : "New template"}
          </h2>
          <button type="button" onClick={onClose} className="p-1"
                  style={{ color: colors.muted }}
                  aria-label="Close"
                  data-testid="charge-template-editor-close">
            <XIcon size={18} />
          </button>
        </div>

        <label className="block text-xs font-semibold mb-1"
               style={{ color: colors.onSurfaceSecondary }}>
          Name
        </label>
        <input
          type="text" value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Chlorine Shock Combo"
          autoFocus
          maxLength={120}
          className="w-full px-3 py-2 text-sm rounded-lg outline-none"
          style={{ border: `1px solid ${colors.border}`,
                   color: colors.onSurface, backgroundColor: colors.surface }}
          data-testid="charge-template-name"
        />

        <label className="block text-xs font-semibold mt-4 mb-1"
               style={{ color: colors.onSurfaceSecondary }}>
          Description (optional)
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 text-sm rounded-lg outline-none"
          style={{ border: `1px solid ${colors.border}`,
                   color: colors.onSurface, backgroundColor: colors.surface,
                   resize: "vertical" }}
          data-testid="charge-template-description"
        />

        <label className="block text-xs font-semibold mt-4 mb-1"
               style={{ color: colors.onSurfaceSecondary }}>
          Category
        </label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full px-3 py-2 text-sm rounded-lg outline-none"
          style={{ border: `1px solid ${colors.border}`,
                   color: colors.onSurface, backgroundColor: colors.surface }}
          data-testid="charge-template-category"
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>

        <div className="flex items-center justify-between mt-5 mb-2">
          <label className="text-xs font-semibold"
                 style={{ color: colors.onSurfaceSecondary }}>
            Line items ({lineItems.length})
          </label>
          <button
            type="button"
            onClick={addRow}
            disabled={lineItems.length >= 20}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-lg"
            style={{ background: colors.surfaceSecondary,
                     border: `1px solid ${colors.border}`,
                     color: colors.onSurface }}
            data-testid="charge-template-add-row"
          >
            <Plus size={12} /> Add line
          </button>
        </div>

        <div className="flex flex-col gap-2"
             data-testid="charge-template-lineitems">
          {lineItems.map((row, idx) => (
            <div
              key={row._key}
              className="grid grid-cols-12 gap-2 items-start px-2 py-2 rounded-lg"
              style={{ background: colors.surfaceSecondary,
                       border: `1px solid ${colors.border}` }}
              data-testid={`charge-template-row-${idx}`}
            >
              <input
                type="text"
                value={row.name}
                onChange={(e) => patchRow(row._key, { name: e.target.value })}
                placeholder="Item name"
                className="col-span-4 px-2 py-1 text-sm rounded-md outline-none"
                style={{ border: `1px solid ${colors.border}`,
                         color: colors.onSurface,
                         backgroundColor: colors.surface }}
                data-testid={`charge-template-row-${idx}-name`}
              />
              <input
                type="number" step="0.01" min="0"
                value={row.unit_price}
                onChange={(e) => patchRow(row._key, { unit_price: e.target.value })}
                placeholder="Unit $"
                className="col-span-2 px-2 py-1 text-sm rounded-md outline-none"
                style={{ border: `1px solid ${colors.border}`,
                         color: colors.onSurface,
                         backgroundColor: colors.surface }}
                data-testid={`charge-template-row-${idx}-price`}
              />
              <input
                type="number" step="0.01" min="0.01"
                value={row.quantity}
                onChange={(e) => patchRow(row._key, { quantity: e.target.value })}
                placeholder="Qty"
                className="col-span-1 px-2 py-1 text-sm rounded-md outline-none"
                style={{ border: `1px solid ${colors.border}`,
                         color: colors.onSurface,
                         backgroundColor: colors.surface }}
                data-testid={`charge-template-row-${idx}-qty`}
              />
              <input
                type="text"
                value={row.category}
                onChange={(e) => patchRow(row._key, { category: e.target.value })}
                placeholder="Category"
                className="col-span-3 px-2 py-1 text-sm rounded-md outline-none"
                style={{ border: `1px solid ${colors.border}`,
                         color: colors.onSurface,
                         backgroundColor: colors.surface }}
                data-testid={`charge-template-row-${idx}-category`}
              />
              <div className="col-span-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => removeRow(row._key)}
                  disabled={lineItems.length <= 1}
                  className="p-1 rounded-md"
                  style={{ color: lineItems.length <= 1
                           ? colors.muted : colors.error }}
                  aria-label="Remove line"
                  data-testid={`charge-template-row-${idx}-remove`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 flex items-center justify-between text-sm">
          <span style={{ color: colors.muted }}>
            Total (sum of line items):
          </span>
          <span className="font-bold"
                style={{ color: colors.onSurface }}
                data-testid="charge-template-total">
            {money(total)}
          </span>
        </div>

        {err ? (
          <div className="mt-3 text-sm font-semibold"
               style={{ color: colors.error }}
               data-testid="charge-template-editor-error">
            {err}
          </div>
        ) : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} testid="charge-template-cancel">
            Cancel
          </Button>
          <Button
            onClick={submit} disabled={busy}
            testid="charge-template-save"
          >
            {busy ? "Saving…" : (isEdit ? "Save changes" : "Create template")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function AdminChargeTemplatesPage() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [editor, setEditor] = useState({ open: false, mode: "create",
                                          initial: null });
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  const load = async () => {
    setLoading(true); setError("");
    try {
      const res = await api.get("/charge-templates");
      setTemplates(res?.templates || []);
    } catch (e) {
      setError(e?.message || "Failed to load templates");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const needle = (q || "").trim().toLowerCase();
    if (!needle) return templates;
    return templates.filter((t) =>
      (t.name || "").toLowerCase().includes(needle) ||
      (t.description || "").toLowerCase().includes(needle),
    );
  }, [templates, q]);

  const openCreate = () =>
    setEditor({ open: true, mode: "create", initial: null });
  const openEdit = (tpl) =>
    setEditor({ open: true, mode: "edit", initial: tpl });
  const closeEditor = () =>
    setEditor({ open: false, mode: "create", initial: null });

  const saveTemplate = async (payload) => {
    setBusy(true);
    try {
      if (editor.mode === "edit" && editor.initial?.id) {
        await api.put(`/charge-templates/${editor.initial.id}`, payload);
        toast.success(`Template "${payload.name}" updated`);
      } else {
        await api.post("/charge-templates", payload);
        toast.success(`Template "${payload.name}" created`);
      }
      closeEditor();
      await load();
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const deleteTemplate = async (tpl) => {
    setDeletingId(tpl.id);
    try {
      await api.del(`/charge-templates/${tpl.id}`);
      toast.success(`Template "${tpl.name}" deleted`);
      await load();
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="p-6" data-testid="charge-templates-page">
      <PageHeader
        title="Charge Templates"
        subtitle="Bundles of line items techs can drop onto a job in one click."
        right={(
          <Button onClick={openCreate} testid="charge-template-new-btn">
            <Plus size={14} /> Add template
          </Button>
        )}
      />

      <div className="mt-4 flex items-center gap-2">
        <div
          className="flex items-center gap-2 flex-1 px-3 py-2 rounded-lg"
          style={{ background: colors.surfaceSecondary,
                   border: `1px solid ${colors.border}` }}
        >
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name or description…"
            className="bg-transparent outline-none flex-1 text-sm"
            style={{ color: colors.onSurface }}
            data-testid="charge-templates-search"
          />
        </div>
      </div>

      {error ? (
        <div
          className="mt-4 p-3 rounded-lg text-sm"
          style={{ background: "#FEE2E2", color: colors.error,
                   border: `1px solid #FCA5A5` }}
          data-testid="charge-templates-error"
        >
          {error}
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto rounded-2xl"
           style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface }}>
        <table className="w-full text-sm" data-testid="charge-templates-table">
          <thead>
            <tr style={{ background: colors.surfaceSecondary }}>
              {["Name", "Category", "Items", "Total", "Last used", "Actions"]
                .map((c) => (
                <th key={c}
                    className="text-left text-[10px] uppercase font-bold px-3 py-2"
                    style={{ color: colors.muted,
                             borderBottom: `1px solid ${colors.border}` }}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && filtered.length === 0 ? (
              <tr><td colSpan={6}
                      className="text-center py-8 text-sm"
                      style={{ color: colors.muted }}
                      data-testid="charge-templates-loading">
                Loading…
              </td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={6}
                      className="text-center py-8 text-sm"
                      style={{ color: colors.muted }}
                      data-testid="charge-templates-empty">
                No charge templates yet.
                Click <b>Add template</b> above to build your first bundle.
              </td></tr>
            ) : filtered.map((tpl) => {
              const total = _templateTotal(
                (tpl.line_items || []).map((li) => ({
                  unit_price: li.unit_price, quantity: li.quantity,
                })),
              );
              return (
                <tr key={tpl.id}
                    style={{ borderBottom: `1px solid ${colors.border}` }}
                    data-testid={`charge-template-row-${tpl.id}`}>
                  <td className="px-3 py-2 font-semibold"
                      style={{ color: colors.onSurface }}>
                    {tpl.name}
                    {tpl.description ? (
                      <div className="text-[11px] font-normal"
                           style={{ color: colors.muted }}>
                        {tpl.description}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-xs"
                      style={{ color: colors.onSurface }}
                      data-testid={`charge-template-cat-${tpl.id}`}>
                    {tpl.category}
                  </td>
                  <td className="px-3 py-2 text-xs"
                      style={{ color: colors.onSurface }}>
                    {(tpl.line_items || []).length}
                  </td>
                  <td className="px-3 py-2 text-xs"
                      style={{ color: colors.onSurface }}>
                    {money(total)}
                  </td>
                  <td className="px-3 py-2 text-xs"
                      style={{ color: colors.muted }}>
                    {tpl.last_used_at
                      ? new Date(tpl.last_used_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        type="button"
                        onClick={() => openEdit(tpl)}
                        className="p-1 rounded-md"
                        style={{ color: colors.brand }}
                        aria-label="Edit template"
                        data-testid={`charge-template-edit-${tpl.id}`}
                      >
                        <Pencil size={14} />
                      </button>
                      <ArmToDelete
                        count={1}
                        catastrophicThreshold={9999}
                        disabled={deletingId === tpl.id}
                        onConfirm={() => deleteTemplate(tpl)}
                        label="Delete"
                        testIdPrefix={`charge-template-delete-${tpl.id}`}
                        size="sm"
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <TemplateEditorModal
        open={editor.open}
        mode={editor.mode}
        initial={editor.initial}
        busy={busy}
        onClose={closeEditor}
        onSubmit={saveTemplate}
      />
    </div>
  );
}

// Named export for tests that want to exercise the modal in isolation.
export { TemplateEditorModal };
