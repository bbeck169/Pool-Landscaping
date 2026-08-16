/**
 * Task OO · Feb 2026 — Admin Customer Tags list.
 *
 * Feb-2026 Queue Item 2 upgrade:
 *   • "New Tag" button + modal (name + color picker)
 *   • Inline rename / recolor via edit modal
 *   • Delete with hard-confirm showing live usage count
 *   • Search box (visible once tag count > 10)
 *   • Usage-count column
 *   • System tags (is_system:true) locked with icon + disabled actions +
 *     tooltip ("System tags cannot be modified")
 *   • Preserves bulk-select toolbar shipped in the previous phase.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Tag as TagIcon, RefreshCw, Plus, Lock, Pencil, Trash2, X as XIcon, Search,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  useBulkSelect, BulkSelectAll, BulkSelectRow,
  BulkActionBar, BulkConfirmModal, LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";

// Palette matches backend routers/customer_tags.py::_PALETTE — same set of
// accessibility-tested pastels the auto-picker draws from.
const PALETTE = [
  "#DBEAFE", "#FEE2E2", "#DCFCE7", "#FEF3C7", "#EDE9FE",
  "#CFFAFE", "#FCE7F3", "#FEDCBB", "#E0E7FF", "#D1FAE5",
  // System-tag colors — surfaced so admins can match/re-use if they want
  "#22C55E", "#94A3B8",
];

// Threshold: only render the search input if there are > 10 tags.
const SEARCH_VISIBILITY_THRESHOLD = 10;

const SYSTEM_LOCK_TOOLTIP = "System tags cannot be modified";

function normalizeRows(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.tags || [];
}

// ═════════════════════════════════════════════════════════════════
// Reusable tag-editor modal (create + edit share the same UI).
// ═════════════════════════════════════════════════════════════════
function TagEditorModal({ open, mode, initial, onClose, onSubmit, busy }) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  useEffect(() => {
    if (!open) return;
    setName(initial?.name || "");
    setColor(initial?.color || PALETTE[0]);
  }, [open, initial]);
  if (!open) return null;

  const isEdit = mode === "edit";
  const title = isEdit ? "Edit tag" : "New tag";
  const cta = isEdit ? "Save changes" : "Create tag";
  const trimmed = (name || "").trim();
  const canSubmit = trimmed.length > 0 && trimmed.length <= 40 && !busy && (
    !isEdit || trimmed !== (initial?.name || "") || color !== (initial?.color || "")
  );

  const submit = () => {
    if (!canSubmit) return;
    const payload = {};
    if (!isEdit || trimmed !== (initial?.name || "")) payload.name = trimmed;
    if (!isEdit || color !== (initial?.color || "")) payload.color = color;
    onSubmit(payload);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="tag-editor-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            {title}
          </h2>
          <button type="button" onClick={onClose} className="p-1"
                    style={{ color: colors.muted }}
                    aria-label="Close" data-testid="tag-editor-close">
            <XIcon size={18} />
          </button>
        </div>
        <label className="block text-xs font-semibold mb-1"
                 style={{ color: colors.onSurfaceSecondary }}>
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder="e.g. VIP"
          autoFocus
          maxLength={40}
          className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
          style={{
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            backgroundColor: colors.surface,
          }}
          data-testid="tag-editor-name-input"
        />
        <p className="text-[11px] mt-1"
             style={{ color: colors.muted }}>
          1–40 characters, no leading/trailing whitespace.
        </p>

        <label className="block text-xs font-semibold mt-4 mb-2"
                 style={{ color: colors.onSurfaceSecondary }}>
          Color
        </label>
        <div className="flex flex-wrap gap-2" data-testid="tag-editor-palette">
          {PALETTE.map((c) => {
            const active = c.toLowerCase() === color.toLowerCase();
            return (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                className="w-8 h-8 rounded-full transition-transform"
                style={{
                  backgroundColor: c,
                  border: active ? `2px solid ${colors.brandPrimary}` : `1px solid ${colors.border}`,
                  transform: active ? "scale(1.1)" : "scale(1)",
                }}
                aria-label={`Pick color ${c}`}
                data-testid={`tag-editor-palette-swatch-${c.replace("#", "").toLowerCase()}`}
              />
            );
          })}
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-semibold"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            data-testid="tag-editor-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brandPrimary }}
            data-testid="tag-editor-submit"
          >
            {busy ? "Saving…" : cta}
          </button>
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// Main page.
// ═════════════════════════════════════════════════════════════════
export default function AdminTagsList() {
  const [rows, setRows] = useState(null);
  const [query, setQuery] = useState("");

  // Bulk-select confirm modal (delete-selected)
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});

  // Single-tag editor modal (create + edit)
  const [editor, setEditor] = useState({ open: false, mode: "create", tag: null });
  const [editorBusy, setEditorBusy] = useState(false);

  // Single-tag delete confirm modal
  const [delModal, setDelModal] = useState({ open: false, tag: null });
  const [delBusy, setDelBusy] = useState(false);

  const load = () =>
    api.get("/customer-tags")
      .then((r) => setRows(normalizeRows(r)))
      .catch(() => setRows([]));

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Filter view (system tags always visible + search).
  const filtered = useMemo(() => {
    const q = (query || "").trim().toLowerCase();
    const all = rows || [];
    if (!q) return all;
    return all.filter((r) => (r.name || r.label || "").toLowerCase().includes(q));
  }, [rows, query]);

  const totalCount = (rows || []).length;
  const showSearch = totalCount > SEARCH_VISIBILITY_THRESHOLD;

  const visibleIds = useMemo(() => filtered.map((r) => r.id), [filtered]);
  const { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);

  const applyFailures = (failed) => {
    if (!failed?.length) return;
    const map = {}; failed.forEach((f) => { map[f.id] = f.reason; });
    setLockedFailures(map);
    setTimeout(() => setLockedFailures({}), 10000);
  };

  // ── Bulk delete (existing behaviour, preserved) ────────────────
  const doBulkDelete = async () => {
    setBulkBusy(true);
    try {
      const res = await api.post("/customer-tags/bulk-delete", { ids: Array.from(selected) });
      applyFailures(res.failed);
      toast.success(`${res.deleted_count || 0} tag${(res.deleted_count || 0) === 1 ? "" : "s"} deleted`);
      clear();
      setBulkConfirmOpen(false);
      load();
    } catch (e) { toast.error(e?.message || "Bulk delete failed"); }
    finally { setBulkBusy(false); }
  };
  const doBulkArchive = async (state) => {
    try {
      const res = await api.post("/customer-tags/bulk-update", {
        ids: Array.from(selected),
        patch: { is_archived: state === "archived" },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${state}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Archive update failed"); }
  };

  // ── Single-tag CRUD ───────────────────────────────────────────
  const openCreate = () => setEditor({ open: true, mode: "create", tag: null });
  const openEdit = (tag) => setEditor({ open: true, mode: "edit", tag });
  const closeEditor = () => { if (!editorBusy) setEditor({ open: false, mode: "create", tag: null }); };

  const submitEditor = async (payload) => {
    setEditorBusy(true);
    try {
      if (editor.mode === "create") {
        await api.post("/customer-tags", payload);
        toast.success(`Tag "${payload.name}" created`);
      } else if (editor.tag) {
        await api.patch(`/customer-tags/${editor.tag.id}`, payload);
        toast.success("Tag updated");
      }
      setEditor({ open: false, mode: "create", tag: null });
      load();
    } catch (e) {
      const msg = e?.message || "";
      if (msg.includes("duplicate_tag_name")) {
        toast.error("A tag with that name already exists");
      } else if (msg.includes("system_tag_readonly")) {
        toast.error(SYSTEM_LOCK_TOOLTIP);
      } else {
        toast.error(msg || "Tag save failed");
      }
    } finally { setEditorBusy(false); }
  };

  const openDelete = (tag) => setDelModal({ open: true, tag });
  const closeDelete = () => { if (!delBusy) setDelModal({ open: false, tag: null }); };
  const submitDelete = async () => {
    if (!delModal.tag) return;
    setDelBusy(true);
    try {
      await api.del(`/customer-tags/${delModal.tag.id}`);
      toast.success(`Tag "${delModal.tag.name}" deleted`);
      setDelModal({ open: false, tag: null });
      load();
    } catch (e) {
      const msg = e?.message || "";
      toast.error(msg.includes("system_tag_readonly") ? SYSTEM_LOCK_TOOLTIP : (msg || "Delete failed"));
    } finally { setDelBusy(false); }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-tags-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <TagIcon size={20} className="inline mr-2" /> Customer Tags
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Manage the tenant tag registry. Assignment lives on the customer detail page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="admin-tags-refresh-btn"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          <button
            onClick={openCreate}
            className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5 text-white"
            style={{ backgroundColor: colors.brandPrimary }}
            data-testid="admin-tags-new-btn"
          >
            <Plus size={14} /> New tag
          </button>
        </div>
      </div>

      {/* Search (only when >10 tags) */}
      {showSearch ? (
        <div className="mb-3 relative max-w-sm">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: colors.muted }}
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${totalCount} tags…`}
            className="w-full pl-8 pr-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
              backgroundColor: colors.surface,
            }}
            data-testid="admin-tags-search-input"
          />
        </div>
      ) : null}

      {/* Table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <table className="w-full text-sm" data-testid="admin-tags-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll
                  checked={allVisibleSelected}
                  indeterminate={indeterminate}
                  onChange={toggleAll}
                />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Name</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Color</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Usage</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Archived</th>
              <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(rows !== null && filtered.length === 0) ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm"
                     style={{ color: colors.muted }}
                     data-testid="admin-tags-empty">
                  {rows.length === 0 ? "No tags yet." : "No tags match your search."}
                </td>
              </tr>
            ) : null}
            {filtered.map((r) => {
              const isSystem = !!r.is_system;
              const displayName = r.name || r.label || "—";
              const usage = Number(r.usage_count || 0);
              return (
                <tr
                  key={r.id}
                  style={{
                    borderTop: `1px solid ${colors.divider}`,
                    backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent",
                  }}
                  data-testid={`admin-tag-row-${r.id}`}
                >
                  <td className="px-3 py-3">
                    <BulkSelectRow
                      id={r.id}
                      checked={selected.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                    />
                  </td>
                  <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>
                    <span className="inline-flex items-center gap-1.5">
                      {isSystem ? (
                        <span
                          title={SYSTEM_LOCK_TOOLTIP}
                          aria-label={SYSTEM_LOCK_TOOLTIP}
                          className="inline-flex items-center"
                          data-testid={`admin-tag-system-lock-${r.id}`}
                        >
                          <Lock size={12} style={{ color: colors.muted }} />
                        </span>
                      ) : null}
                      {displayName}
                      {isSystem ? (
                        <span
                          className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: colors.surfaceTertiary, color: colors.onSurfaceSecondary }}
                          title={SYSTEM_LOCK_TOOLTIP}
                        >
                          System
                        </span>
                      ) : null}
                    </span>
                    {lockedFailures[r.id] ? (
                      <LockedPill
                        reason={lockedFailures[r.id]}
                        testid={`bulk-locked-pill-${r.id}`}
                      />
                    ) : null}
                  </td>
                  <td className="px-3 py-3">
                    <span
                      className="inline-block w-6 h-6 rounded-full"
                      style={{
                        backgroundColor: r.color || "#94A3B8",
                        border: `1px solid ${colors.border}`,
                      }}
                    />
                  </td>
                  <td className="px-3 py-3 text-xs" style={{ color: colors.onSurfaceSecondary }}
                       data-testid={`admin-tag-usage-${r.id}`}>
                    {usage}
                  </td>
                  <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>
                    {r.is_archived ? "Archived" : "Active"}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => !isSystem && openEdit(r)}
                        disabled={isSystem}
                        title={isSystem ? SYSTEM_LOCK_TOOLTIP : "Edit"}
                        className="p-1.5 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
                        style={{
                          color: colors.onSurfaceSecondary,
                          backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}`,
                        }}
                        data-testid={`admin-tag-edit-btn-${r.id}`}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => !isSystem && openDelete(r)}
                        disabled={isSystem}
                        title={isSystem ? SYSTEM_LOCK_TOOLTIP : "Delete"}
                        className="p-1.5 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
                        style={{
                          color: colors.error,
                          backgroundColor: "#FEF2F2",
                          border: `1px solid #FECACA`,
                        }}
                        data-testid={`admin-tag-delete-btn-${r.id}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Bulk toolbar (existing) */}
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          {
            key: "archive", label: "Set archive state",
            dropdown: [{ value: "archived", label: "Archived" }, { value: "active", label: "Active" }],
            onClick: (v) => doBulkArchive(v),
          },
          {
            key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setBulkConfirmOpen(true),
          },
        ]}
      />
      <BulkConfirmModal
        open={bulkConfirmOpen}
        onClose={() => setBulkConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} tag${selectedCount === 1 ? "" : "s"}?`}
        description="Tags assigned to customers will be unassigned. System tags will be skipped. This action cannot be undone."
        confirmLabel={bulkBusy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={bulkBusy}
      />

      {/* Single-tag editor */}
      <TagEditorModal
        open={editor.open}
        mode={editor.mode}
        initial={editor.tag}
        onClose={closeEditor}
        onSubmit={submitEditor}
        busy={editorBusy}
      />

      {/* Single-tag delete confirm */}
      {delModal.open && delModal.tag ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeDelete(); }}
          data-testid="admin-tag-delete-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Delete tag “{delModal.tag.name}”?
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  {Number(delModal.tag.usage_count || 0) > 0 ? (
                    <>
                      This tag is applied to{" "}
                      <b style={{ color: colors.onSurface }}
                          data-testid="admin-tag-delete-usage-count">
                        {delModal.tag.usage_count} customer
                        {delModal.tag.usage_count === 1 ? "" : "s"}
                      </b>
                      . Deleting will remove it from all of them.
                      This action cannot be undone.
                    </>
                  ) : (
                    <>This tag is not applied to any customer. Deleting is safe.</>
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={closeDelete}
                className="p-1"
                style={{ color: colors.muted }}
                aria-label="Close"
                data-testid="admin-tag-delete-close"
              >
                <XIcon size={18} />
              </button>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeDelete}
                className="px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                data-testid="admin-tag-delete-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitDelete}
                disabled={delBusy}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: colors.error }}
                data-testid="admin-tag-delete-confirm"
              >
                {delBusy ? "Deleting…" : "Delete tag"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
