/**
 * Phase 56-a.5 · Aug-2026 — Pricebook Suppliers admin page.
 *
 * Admin CRUD surface for the ``pricebook_suppliers`` collection landed
 * in Phase 56-a. Mirrors ``AutobillingRuns.jsx`` (Fix #5) for
 * soft-delete UX + confirmation modal patterns.
 *
 * Endpoints (all under ``/api/pricebook/suppliers/*``):
 *   GET    ?income_category_id=&include_deleted=
 *   POST                                — create (slug immutable after)
 *   PATCH  /{id}                        — display_name + is_active only
 *   DELETE /{id}                        — soft delete
 *   POST   /{id}/restore                — restore
 *
 * Write-once fields (preflight §5): ``slug`` + ``income_category_id``
 * are set at create and cannot be edited. The Edit modal shows both
 * read-only with an "Immutable after creation" helper. Bulk actions
 * are deferred to Phase 56-b+ — the checkbox column is present but
 * inert (only used for future selection UX).
 *
 * Role gate: admin + super_admin only (preflight lock — manager does
 * NOT see this page). Route guard is ``<AdminOnly>`` at the
 * ``App.js`` layer. Client-side ``canSee`` mirror avoids flash-of-UI
 * for non-admins who somehow bypass the guard.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Store, Plus, Pencil, Trash2, RotateCcw, X } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";


// Category → pill colour map. Only "Pool" and "Landscaping" are
// canonically supported at Phase 56 — everything else falls back to
// a neutral slate pill so the surface stays honest instead of dumping
// unstyled text.
const CATEGORY_PILLS = {
  Pool:        { bg: "#DBEAFE", fg: "#1E40AF" },
  Landscaping: { bg: "#DCFCE7", fg: "#166534" },
};

function CategoryPill({ name }) {
  const s = CATEGORY_PILLS[name] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: s.bg, color: s.fg }}
      data-testid={`pricebook-supplier-cat-pill-${name}`}
    >
      {name || "—"}
    </span>
  );
}


// Slug generator — matches the server's `.strip().lower()`
// normalisation. Kept dumb: whitespace → underscore, strip anything
// that's not `[a-z0-9_]`.
function slugify(s) {
  return String(s || "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_]+/g, "");
}


function CreateSupplierModal({ categories, onClose, onCreated }) {
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugDirty, setSlugDirty] = useState(false);
  const [categoryId, setCategoryId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // Auto-derive slug from displayName until the user edits it once.
  useEffect(() => {
    if (!slugDirty) setSlug(slugify(displayName));
  }, [displayName, slugDirty]);

  const canSave = displayName.trim() && slug.trim() && categoryId;

  const save = async () => {
    if (!canSave || busy) return;
    setBusy(true); setErr("");
    try {
      const row = await api.post("/pricebook/suppliers", {
        slug: slug.trim(),
        display_name: displayName.trim(),
        income_category_id: categoryId,
      });
      onCreated?.(row);
    } catch (e) {
      const code = e?.data?.detail?.error;
      if (code === "slug_taken") {
        setErr(`A supplier with slug "${slug}" already exists.`);
      } else {
        setErr(e?.message || "Save failed");
      }
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="pricebook-supplier-create-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ background: "#fff", border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            New pricebook supplier
          </h2>
          <button onClick={onClose} data-testid="pricebook-supplier-create-close"
                  style={{ color: colors.muted }} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Display name *</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              placeholder="e.g. Home Depot"
              data-testid="pricebook-supplier-create-name"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Slug *</label>
            <input
              type="text"
              value={slug}
              onChange={(e) => { setSlug(slugify(e.target.value));
                                   setSlugDirty(true); }}
              className="w-full px-3 py-2 rounded-lg text-sm font-mono"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              placeholder="home_depot"
              data-testid="pricebook-supplier-create-slug"
            />
            <p className="text-[10px] mt-1" style={{ color: colors.muted }}>
              Immutable after creation — auto-derived from the display
              name; edit once to override.
            </p>
          </div>

          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Income category *</label>
            <select
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="pricebook-supplier-create-category"
            >
              <option value="">Select a category…</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <p className="text-[10px] mt-1" style={{ color: colors.muted }}>
              Immutable after creation — a supplier belongs to one
              category for the life of its pricebook rows.
            </p>
          </div>

          {err ? (
            <div className="rounded-lg p-2 text-xs"
                  style={{ background: "#FEE2E2", color: "#7F1D1D",
                            border: "1px solid #FCA5A5" }}
                  data-testid="pricebook-supplier-create-error">{err}</div>
          ) : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface,
                      opacity: busy ? 0.5 : 1 }}
            data-testid="pricebook-supplier-create-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!canSave || busy}
            className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="pricebook-supplier-create-save"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


function EditSupplierModal({ row, categoryName, onClose, onSaved }) {
  const [displayName, setDisplayName] = useState(row?.display_name || "");
  const [isActive, setIsActive] = useState(Boolean(row?.is_active));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    if (!displayName.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      const updated = await api.patch(`/pricebook/suppliers/${row.id}`, {
        display_name: displayName.trim(),
        is_active: isActive,
      });
      onSaved?.(updated);
    } catch (e) {
      setErr(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="pricebook-supplier-edit-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ background: "#fff", border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Edit supplier
          </h2>
          <button onClick={onClose} data-testid="pricebook-supplier-edit-close"
                  style={{ color: colors.muted }} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Display name *</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="pricebook-supplier-edit-name"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Slug</label>
            <input
              type="text"
              value={row?.slug || ""}
              readOnly
              disabled
              className="w-full px-3 py-2 rounded-lg text-sm font-mono"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid="pricebook-supplier-edit-slug-readonly"
            />
            <p className="text-[10px] mt-1" style={{ color: colors.muted }}>
              Immutable after creation.
            </p>
          </div>

          <div>
            <label className="block text-[10px] uppercase font-bold mb-1"
                    style={{ color: colors.muted }}>Income category</label>
            <input
              type="text"
              value={categoryName || "—"}
              readOnly
              disabled
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid="pricebook-supplier-edit-category-readonly"
            />
            <p className="text-[10px] mt-1" style={{ color: colors.muted }}>
              Immutable after creation.
            </p>
          </div>

          <label className="inline-flex items-center gap-2 text-sm font-semibold cursor-pointer"
                  style={{ color: colors.onSurface }}>
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              data-testid="pricebook-supplier-edit-active"
              className="cursor-pointer"
            />
            Active
          </label>

          {err ? (
            <div className="rounded-lg p-2 text-xs"
                  style={{ background: "#FEE2E2", color: "#7F1D1D",
                            border: "1px solid #FCA5A5" }}
                  data-testid="pricebook-supplier-edit-error">{err}</div>
          ) : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface,
                      opacity: busy ? 0.5 : 1 }}
            data-testid="pricebook-supplier-edit-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!displayName.trim() || busy}
            className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="pricebook-supplier-edit-save"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function PricebookSuppliersAdmin() {
  const { user } = useAuth();
  const canManage = ["admin", "super_admin"].includes(user?.role);

  const [rows, setRows] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");   // "" = All
  const [showDeleted, setShowDeleted] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [editRow, setEditRow] = useState(null);

  const [deleteTarget, setDeleteTarget] = useState(null);   // {id, display_name}
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState(null); // {id, display_name}
  const [restoreBusy, setRestoreBusy] = useState(false);

  const [selectedIds, setSelectedIds] = useState(() => new Set());

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const qs = new URLSearchParams();
      if (categoryFilter) qs.set("income_category_id", categoryFilter);
      if (showDeleted) qs.set("include_deleted", "true");
      const url = `/pricebook/suppliers${qs.toString() ? `?${qs}` : ""}`;
      const r = await api.get(url);
      setRows(Array.isArray(r) ? r : []);
    } catch (e) {
      setError(e?.message || "Failed to load pricebook suppliers.");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, showDeleted]);

  useEffect(() => { if (canManage) load(); }, [load, canManage]);

  useEffect(() => {
    if (!canManage) return;
    // Load categories once — Pool + Landscaping are the two the seed
    // ships against. The dropdown filters to those two client-side
    // so a stray custom category (e.g., "Retail") doesn't leak into
    // this admin view.
    (async () => {
      try {
        const r = await api.get("/income-categories");
        const items = (r?.items || r || []).filter(
          (c) => c.name === "Pool" || c.name === "Landscaping",
        );
        setCategories(items);
      } catch {
        setCategories([]);
      }
    })();
  }, [canManage]);

  const categoryById = useMemo(() => {
    const m = new Map();
    for (const c of categories) m.set(c.id, c);
    return m;
  }, [categories]);

  const canManageRow = canManage;

  const visible = rows;

  const openDelete = (row) => setDeleteTarget(row);
  const closeDelete = () => { if (!deleteBusy) setDeleteTarget(null); };
  const doDelete = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await api.del(`/pricebook/suppliers/${deleteTarget.id}`);
      sonnerToast.success("Supplier deleted");
      setRows((prev) => showDeleted
        ? prev.map((r) => (r.id === deleteTarget.id
            ? { ...r, deleted_at: new Date().toISOString() }
            : r))
        : prev.filter((r) => r.id !== deleteTarget.id),
      );
      setDeleteTarget(null);
    } catch (e) {
      sonnerToast.error(e?.message || "Delete failed");
    } finally {
      setDeleteBusy(false);
    }
  };

  const openRestore = (row) => setRestoreTarget(row);
  const closeRestore = () => { if (!restoreBusy) setRestoreTarget(null); };
  const doRestore = async () => {
    if (!restoreTarget) return;
    setRestoreBusy(true);
    try {
      await api.post(`/pricebook/suppliers/${restoreTarget.id}/restore`, {});
      sonnerToast.success("Supplier restored");
      setRows((prev) => prev.map((r) => (r.id === restoreTarget.id
        ? { ...r, deleted_at: null, restored_at: new Date().toISOString() }
        : r)));
      setRestoreTarget(null);
    } catch (e) {
      sonnerToast.error(e?.message || "Restore failed");
    } finally {
      setRestoreBusy(false);
    }
  };

  const toggleOne = (id) => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAllVisible = () => setSelectedIds((prev) => {
    const next = new Set(prev);
    const ids = visible.map((r) => r.id);
    const allSelected = ids.length > 0 && ids.every((id) => next.has(id));
    if (allSelected) ids.forEach((id) => next.delete(id));
    else ids.forEach((id) => next.add(id));
    return next;
  });
  const allVisibleSelected =
    visible.length > 0 && visible.every((r) => selectedIds.has(r.id));

  if (!canManage) {
    // Route guard already redirects, but this covers the edge case
    // where a manager somehow lands here mid-refresh (auth still
    // resolving). Zero data leaks — plain gate message + no fetch.
    return (
      <div className="max-w-6xl mx-auto py-6 px-4"
            data-testid="pricebook-suppliers-page">
        <div className="rounded-lg p-4 text-sm"
              style={{ background: "#FEF3C7", color: "#92400E",
                        border: "1px solid #FCD34D" }}
              data-testid="pricebook-suppliers-no-permission">
          You don't have permission to view pricebook suppliers.
          Contact an admin.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4"
          data-testid="pricebook-suppliers-page">
      <PageHeader
        icon={Store}
        title="Pricebook Suppliers"
        subtitle="Manage the list of vendors that appear on Ops Hub Price Book grids. Each supplier is scoped to one income category (Pool or Landscaping)."
      />

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Category</div>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[180px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="pricebook-suppliers-filter-category"
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        <div className="flex-1" />

        <label
          className="inline-flex items-center gap-2 text-xs font-semibold cursor-pointer"
          style={{ color: colors.onSurface }}
          data-testid="pricebook-suppliers-show-deleted-label"
        >
          <input
            type="checkbox"
            checked={showDeleted}
            onChange={(e) => setShowDeleted(e.target.checked)}
            data-testid="pricebook-suppliers-show-deleted-toggle"
            className="cursor-pointer"
          />
          Show deleted
        </label>

        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0 }}
          data-testid="pricebook-suppliers-add-button"
        >
          <Plus size={12} /> Add new supplier
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="pricebook-suppliers-loading">Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
              data-testid="pricebook-suppliers-error">{error}</div>
      ) : (
        <div className="rounded-lg overflow-hidden"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="pricebook-suppliers-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="px-3 py-2 w-8" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    disabled={visible.length === 0}
                    aria-label="Select all visible suppliers"
                    data-testid="pricebook-suppliers-select-all"
                    className="cursor-pointer"
                  />
                </th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Display name</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Slug</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Category</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Origin</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Active</th>
                <th className="text-right px-3 py-2 w-24" style={{ color: colors.muted }}>&nbsp;</th>
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center"
                        style={{ color: colors.muted }}
                        data-testid="pricebook-suppliers-empty">
                    No suppliers yet — click "Add new supplier" to
                    create your first one.
                  </td>
                </tr>
              ) : visible.map((r) => {
                const isDeleted = Boolean(r.deleted_at);
                const catName = categoryById.get(r.income_category_id)?.name;
                const rowBg = selectedIds.has(r.id)
                  ? "#EFF6FF"
                  : (isDeleted ? "#F9FAFB" : "transparent");
                const mutedFg = isDeleted ? "#9CA3AF" : colors.onSurface;
                const mutedSub = isDeleted ? "#B0B7C0" : colors.muted;
                const strike = isDeleted ? { textDecoration: "line-through" } : {};
                return (
                  <tr key={r.id}
                       data-testid={`pricebook-supplier-row-${r.id}`}
                       data-deleted={isDeleted ? "true" : "false"}
                       style={{ backgroundColor: rowBg }}>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(r.id)}
                        onChange={() => toggleOne(r.id)}
                        aria-label={`Select supplier ${r.display_name}`}
                        data-testid={`pricebook-supplier-row-select-${r.id}`}
                        className="cursor-pointer"
                      />
                    </td>
                    <td className="px-3 py-2 font-bold"
                        style={{ color: mutedFg, ...strike }}>
                      {r.display_name}
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px]"
                        style={{ color: mutedSub }}
                        data-testid={`pricebook-supplier-slug-${r.id}`}>
                      {r.slug}
                    </td>
                    <td className="px-3 py-2">
                      <CategoryPill name={catName} />
                    </td>
                    <td className="px-3 py-2">
                      {r.is_seed ? (
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                          style={{ backgroundColor: "#E0E7FF", color: "#3730A3" }}
                          data-testid={`pricebook-supplier-seeded-pill-${r.id}`}
                        >
                          Seeded
                        </span>
                      ) : (
                        <span style={{ color: colors.muted }}>Custom</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {isDeleted ? (
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                          style={{ backgroundColor: "#E5E7EB", color: "#6B7280" }}
                          data-testid={`pricebook-supplier-deleted-pill-${r.id}`}
                        >
                          Deleted
                        </span>
                      ) : r.is_active ? (
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                          style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                          data-testid={`pricebook-supplier-active-pill-${r.id}`}
                        >
                          Active
                        </span>
                      ) : (
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                          style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                          data-testid={`pricebook-supplier-inactive-pill-${r.id}`}
                        >
                          Inactive
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}>
                      {canManageRow && !isDeleted ? (
                        <>
                          <button
                            type="button"
                            onClick={() => setEditRow(r)}
                            aria-label={`Edit ${r.display_name}`}
                            title="Edit"
                            className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-slate-100"
                            style={{ color: colors.brand }}
                            data-testid={`pricebook-supplier-row-edit-${r.id}`}
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            type="button"
                            onClick={() => openDelete(r)}
                            aria-label={`Delete ${r.display_name}`}
                            title="Delete"
                            className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-red-50 ml-1"
                            style={{ color: "#DC2626" }}
                            data-testid={`pricebook-supplier-row-delete-${r.id}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </>
                      ) : canManageRow && isDeleted ? (
                        <button
                          type="button"
                          onClick={() => openRestore(r)}
                          aria-label={`Restore ${r.display_name}`}
                          title="Restore"
                          className="inline-flex items-center justify-center p-1.5 rounded-md hover:bg-slate-100"
                          style={{ color: "#0F766E" }}
                          data-testid={`pricebook-supplier-row-restore-${r.id}`}
                        >
                          <RotateCcw size={14} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Create modal ──────────────────────────────────────── */}
      {createOpen ? (
        <CreateSupplierModal
          categories={categories}
          onClose={() => setCreateOpen(false)}
          onCreated={(row) => {
            sonnerToast.success(`Supplier "${row.display_name}" created`);
            setRows((prev) => [row, ...prev]);
            setCreateOpen(false);
          }}
        />
      ) : null}

      {/* ── Edit modal ────────────────────────────────────────── */}
      {editRow ? (
        <EditSupplierModal
          row={editRow}
          categoryName={categoryById.get(editRow.income_category_id)?.name}
          onClose={() => setEditRow(null)}
          onSaved={(updated) => {
            sonnerToast.success("Supplier updated");
            setRows((prev) => prev.map((r) => (
              r.id === updated.id ? { ...r, ...updated } : r
            )));
            setEditRow(null);
          }}
        />
      ) : null}

      {/* ── Delete confirmation modal ─────────────────────────── */}
      {deleteTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeDelete(); }}
          data-testid="pricebook-supplier-delete-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff",
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}
                data-testid="pricebook-supplier-delete-confirm-title">
              Delete supplier "{deleteTarget.display_name}"?
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              It will be soft-deleted and hidden from pricebook grids
              by default. Existing pricebook items referencing this
              supplier keep their prices.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeDelete}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: deleteBusy ? 0.5 : 1 }}
                data-testid="pricebook-supplier-delete-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doDelete}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="pricebook-supplier-delete-confirm-btn"
              >
                {deleteBusy ? "Deleting…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ── Restore confirmation modal ────────────────────────── */}
      {restoreTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeRestore(); }}
          data-testid="pricebook-supplier-restore-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ background: "#fff",
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}>
              Restore supplier "{restoreTarget.display_name}"?
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              It will reappear in pricebook grids for its category.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeRestore}
                disabled={restoreBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface,
                          opacity: restoreBusy ? 0.5 : 1 }}
                data-testid="pricebook-supplier-restore-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doRestore}
                disabled={restoreBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#0F766E" }}
                data-testid="pricebook-supplier-restore-confirm-btn"
              >
                {restoreBusy ? "Restoring…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
