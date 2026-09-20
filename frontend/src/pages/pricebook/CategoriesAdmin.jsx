/**
 * Pricebook × Profit-Reporting Phase 1 · Feb-2026.
 *
 * Consolidated Categories admin page — two tabs surface CRUD for
 * both category axes side-by-side. Ships alongside (not replacing)
 * the legacy standalone ``IncomeCategoriesPage`` / ``ServiceCategoriesPage``
 * so any bookmarked deep-links keep working, but this becomes the
 * canonical admin surface reached from the Pricebook toolbar.
 *
 * Route: ``/pricebook/categories``.
 *
 * Phase 1 required testids (locked by human):
 *   - income-categories-table
 *   - service-categories-table
 *   - income-category-create-btn
 *   - service-category-create-btn
 *   - category-delete-warn-dialog
 *   - category-active-toggle-{id}
 *
 * Endpoints used (all pre-existing except ``/references``):
 *   GET   /api/{axis}-categories?include_archived=1
 *   POST  /api/{axis}-categories
 *   PATCH /api/{axis}-categories/{id}
 *   POST  /api/{axis}-categories/{id}/archive     ← soft-delete
 *   POST  /api/{axis}-categories/{id}/restore
 *   GET   /api/{axis}-categories/{id}/references  ← NEW (Phase 1)
 *
 * Delete posture: **soft** via the ``archive`` endpoint. We never
 * hard-delete. Historical docs that reference an archived category
 * surface an "Archived category" badge on the admin doc view.
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Archive, ArchiveRestore, Plus, Pencil, GripVertical } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, useSortable,
  arrayMove, sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";


const AXIS = {
  income:  { path: "income-categories",  label: "Income Categories" },
  service: { path: "service-categories", label: "Service Categories" },
};


// ─── Create / Edit modal ─────────────────────────────────────────
function CategoryFormDialog({
  open, onOpenChange, axis, initial, onSaved,
}) {
  const editing = Boolean(initial?.id);
  const [name, setName]       = useState("");
  const [description, setDesc] = useState("");
  const [color, setColor]     = useState("#94A3B8");
  const [sortOrder, setSort]  = useState(0);
  const [saving, setSaving]   = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(initial?.name || "");
    setDesc(initial?.description || "");
    setColor(initial?.color || "#94A3B8");
    setSort(Number(initial?.sort_order || 0));
  }, [open, initial]);

  const save = async () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    setSaving(true);
    try {
      const body = {
        name: name.trim(), description, color,
        sort_order: Number(sortOrder) || 0,
      };
      const path = AXIS[axis].path;
      const res = editing
        ? await api.patch(`/${path}/${initial.id}`, body)
        : await api.post(`/${path}`, body);
      onSaved?.(res);
      onOpenChange(false);
    } catch (e) {
      toast.error(e?.data?.detail?.error === "duplicate_name"
        ? "A category with that name already exists."
        : e?.message || "Save failed");
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={`category-form-dialog-${axis}`}
                       className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {editing ? "Edit category" : `New ${AXIS[axis].label.replace(" Categories", "").toLowerCase()} category`}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div>
            <Label className="text-xs uppercase">Name *</Label>
            <Input value={name}
                    autoFocus
                    onChange={(e) => setName(e.target.value)}
                    data-testid={`category-form-name-${axis}`} />
          </div>
          <div>
            <Label className="text-xs uppercase">Description</Label>
            <Input value={description}
                    onChange={(e) => setDesc(e.target.value)}
                    data-testid={`category-form-desc-${axis}`} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs uppercase">Color</Label>
              <input type="color" value={color}
                        onChange={(e) => setColor(e.target.value)}
                        className="w-full h-9 rounded border"
                        data-testid={`category-form-color-${axis}`} />
            </div>
            <div>
              <Label className="text-xs uppercase">Sort order</Label>
              <Input type="number" value={sortOrder}
                      onChange={(e) => setSort(e.target.value)}
                      data-testid={`category-form-sort-${axis}`} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}
                     data-testid={`category-form-cancel-${axis}`}>Cancel</Button>
          <Button onClick={save} disabled={saving}
                     data-testid={`category-form-save-${axis}`}>
            {saving ? "Saving…" : (editing ? "Save" : "Create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


// ─── Archive-with-warn dialog (Phase 1 §7.2) ─────────────────────
function ArchiveWarnDialog({
  open, onOpenChange, axis, category, onConfirm,
}) {
  const [refs, setRefs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !category?.id) { setRefs(null); return; }
    setLoading(true);
    const path = AXIS[axis].path;
    api.get(`/${path}/${category.id}/references`)
      .then((r) => setRefs(r))
      .catch(() => setRefs({ pricebook_item_count: 0, line_item_count: 0 }))
      .finally(() => setLoading(false));
  }, [open, axis, category]);

  const confirm = async () => {
    setBusy(true);
    try { await onConfirm(category); onOpenChange(false); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="category-delete-warn-dialog"
                       className="max-w-md">
        <DialogHeader>
          <DialogTitle>Archive &ldquo;{category?.name}&rdquo;?</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2 text-sm"
              style={{ color: colors.onSurface }}>
          {loading ? (
            <div data-testid="category-refs-loading"
                    style={{ color: colors.muted }}>
              Checking references…
            </div>
          ) : (
            <>
              <div data-testid="category-refs-summary">
                <div>
                  <strong data-testid="category-refs-pricebook-count">
                    {refs?.pricebook_item_count ?? 0}
                  </strong>{" "}
                  active pricebook item{refs?.pricebook_item_count === 1 ? "" : "s"} reference this category.
                </div>
                <div>
                  <strong data-testid="category-refs-line-count">
                    {refs?.line_item_count ?? 0}
                  </strong>{" "}
                  historical document{refs?.line_item_count === 1 ? "" : "s"} contain line items in this category.
                </div>
              </div>
              {(refs?.pricebook_item_count || 0) + (refs?.line_item_count || 0) > 0 ? (
                <div className="rounded-md p-3 text-xs"
                        style={{ background: "#FEF3C7",
                                  color: "#78350F",
                                  border: "1px solid #FCD34D" }}
                        data-testid="category-refs-warn-banner">
                  Archiving will surface an{" "}
                  <span className="font-semibold">&ldquo;Archived category&rdquo;</span>
                  {" "}badge on affected historical line items. Existing
                  data is preserved — this is a soft-delete.
                </div>
              ) : (
                <div className="text-xs" style={{ color: colors.muted }}>
                  No references — safe to archive.
                </div>
              )}
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}
                     data-testid="category-delete-warn-cancel">Cancel</Button>
          <Button onClick={confirm} disabled={busy}
                     data-testid="category-delete-warn-confirm"
                     style={{ background: "#DC2626", color: "#FFF" }}>
            {busy ? "Archiving…" : "Archive"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


// ─── Sortable row (F1.5 · Feb-2026 — drag-drop reorder wiring) ──
function SortableCategoryRow({
  category, axis, onEdit, onArchive, onRestore, busyId,
}) {
  const c = category;
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: c.id });
  const isSeed = c.created_by_user_id === "system:seed";
  const rowStyle = {
    borderTop: `1px solid ${colors.border}`,
    opacity: c.is_archived ? 0.55 : 1,
    transform: CSS.Transform.toString(transform),
    transition,
    background: isDragging ? colors.surfaceSecondary : "transparent",
  };
  return (
    <tr ref={setNodeRef} style={rowStyle}
        data-testid={`${axis}-category-row-${c.id}`}>
      <td className="px-2 py-2 w-6">
        <button
          type="button"
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing p-1"
          style={{ color: colors.muted }}
          data-testid={`${axis}-category-drag-${c.id}`}
          aria-label="Drag to reorder"
        ><GripVertical size={14} /></button>
      </td>
      <td className="px-3 py-2">
        <span className="inline-block w-5 h-5 rounded"
              style={{ background: c.color || "#94A3B8" }} />
      </td>
      <td className="px-3 py-2 font-semibold"
          style={{ color: colors.onSurface }}>
        <span>{c.name}</span>
        {isSeed ? (
          <span
            className="ml-2 inline-block text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase align-middle"
            style={{ background: "#E0F2FE", color: "#075985",
                      border: "1px solid #7DD3FC" }}
            data-testid={`${axis}-category-seed-badge-${c.id}`}
            title="Seeded default — created automatically"
          >Default</span>
        ) : null}
      </td>
      <td className="px-3 py-2" style={{ color: colors.muted }}>
        {c.description || "—"}
      </td>
      <td className="px-3 py-2 text-right font-mono text-xs">
        {c.sort_order || 0}
      </td>
      <td className="px-3 py-2 text-center text-xs">
        <button
          onClick={() => c.is_archived ? onRestore(c) : onArchive(c)}
          disabled={busyId === c.id}
          className="px-2 py-0.5 rounded-full text-[11px] font-semibold"
          style={{
            background: c.is_archived ? "#FEE2E2" : "#DCFCE7",
            color: c.is_archived ? "#7F1D1D" : "#166534",
            cursor: "pointer",
          }}
          data-testid={`category-active-toggle-${c.id}`}
          data-axis={axis}
          data-archived={c.is_archived ? "true" : "false"}
        >
          {c.is_archived ? "Archived" : "Active"}
        </button>
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        <button
          onClick={() => onEdit(c)}
          disabled={busyId === c.id}
          className="p-1 mr-1"
          style={{ color: colors.brand }}
          data-testid={`${axis}-category-edit-${c.id}`}
          title="Edit"
        ><Pencil size={13} /></button>
        {c.is_archived ? (
          <button
            onClick={() => onRestore(c)}
            disabled={busyId === c.id}
            className="p-1"
            style={{ color: "#0891B2" }}
            data-testid={`${axis}-category-restore-${c.id}`}
            title="Restore"
          ><ArchiveRestore size={13} /></button>
        ) : (
          <button
            onClick={() => onArchive(c)}
            disabled={busyId === c.id}
            className="p-1"
            style={{ color: "#DC2626" }}
            data-testid={`${axis}-category-archive-${c.id}`}
            title="Archive"
          ><Archive size={13} /></button>
        )}
      </td>
    </tr>
  );
}


// ─── Table per axis ──────────────────────────────────────────────
function CategoriesTable({ axis }) {
  const [items, setItems]        = useState(null);
  const [includeArchived, setIA] = useState(false);
  const [editing, setEditing]    = useState(null);      // {id?, ...}
  const [archiving, setArchive]  = useState(null);
  const [busyId, setBusyId]      = useState("");

  const load = useCallback(async () => {
    try {
      const path = AXIS[axis].path;
      const r = await api.get(
        `/${path}?include_archived=${includeArchived ? 1 : 0}`);
      const rows = Array.isArray(r) ? r : (r?.items || []);
      setItems(rows);
    } catch { setItems([]); }
  }, [axis, includeArchived]);

  useEffect(() => { load(); }, [load]);

  const archive = async (c) => {
    setBusyId(c.id);
    try {
      await api.post(`/${AXIS[axis].path}/${c.id}/archive`, {});
      toast.success("Archived");
      await load();
    } catch (e) {
      toast.error(e?.message || "Archive failed");
    } finally { setBusyId(""); }
  };

  const restore = async (c) => {
    setBusyId(c.id);
    try {
      await api.post(`/${AXIS[axis].path}/${c.id}/restore`, {});
      toast.success("Restored");
      await load();
    } catch (e) {
      toast.error(e?.message || "Restore failed");
    } finally { setBusyId(""); }
  };

  const createTestid = `${axis === "income" ? "income" : "service"}-category-create-btn`;
  const tableTestid  = `${axis === "income" ? "income" : "service"}-categories-table`;

  // F1.5 · Feb-2026 — drag-drop reorder wiring.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = async (ev) => {
    const { active, over } = ev;
    if (!over || active.id === over.id || !items) return;
    const oldIdx = items.findIndex((it) => it.id === active.id);
    const newIdx = items.findIndex((it) => it.id === over.id);
    if (oldIdx < 0 || newIdx < 0) return;
    const next = arrayMove(items, oldIdx, newIdx);
    const orderedIds = next.map((it) => it.id);
    // Optimistic update.
    setItems(next);
    try {
      await api.post(`/${AXIS[axis].path}/reorder`,
                       { ordered_ids: orderedIds });
    } catch (e) {
      // Revert on failure.
      setItems(items);
      toast.error(e?.message || "Reorder failed");
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={includeArchived}
                    onChange={(e) => setIA(e.target.checked)}
                    data-testid={`${axis}-categories-show-archived`} />
          <span style={{ color: colors.muted }}>Show archived</span>
        </label>
        <Button onClick={() => setEditing({})}
                   data-testid={createTestid}
                   size="sm">
          <Plus size={14} className="mr-1" /> New category
        </Button>
      </div>

      <div className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={(items || []).map((c) => c.id)}
            strategy={verticalListSortingStrategy}
          >
            <table className="w-full text-sm" data-testid={tableTestid}>
              <thead style={{ background: colors.surfaceSecondary }}>
                <tr>
                  <th className="w-6"></th>
                  <th className="text-left px-3 py-2 font-semibold">Color</th>
                  <th className="text-left px-3 py-2 font-semibold">Name</th>
                  <th className="text-left px-3 py-2 font-semibold">Description</th>
                  <th className="text-right px-3 py-2 font-semibold">Sort</th>
                  <th className="text-center px-3 py-2 font-semibold">Status</th>
                  <th className="w-32 px-3 py-2"></th>
                </tr>
              </thead>
              <tbody data-testid={`${axis}-categories-tbody`}>
                {items === null ? (
                  <tr><td colSpan="7" className="px-3 py-4 text-center"
                            style={{ color: colors.muted }}>Loading…</td></tr>
                ) : items.length === 0 ? (
                  <tr><td colSpan="7" className="px-3 py-4 text-center"
                            style={{ color: colors.muted }}
                            data-testid={`${axis}-categories-empty`}>
                    No categories yet — create your first one.
                  </td></tr>
                ) : items.map((c) => (
                  <SortableCategoryRow
                    key={c.id}
                    category={c}
                    axis={axis}
                    onEdit={setEditing}
                    onArchive={setArchive}
                    onRestore={restore}
                    busyId={busyId}
                  />
                ))}
              </tbody>
            </table>
          </SortableContext>
        </DndContext>
      </div>

      <CategoryFormDialog
        open={Boolean(editing)}
        onOpenChange={(v) => { if (!v) setEditing(null); }}
        axis={axis}
        initial={editing}
        onSaved={() => { setEditing(null); load(); }}
      />
      <ArchiveWarnDialog
        open={Boolean(archiving)}
        onOpenChange={(v) => { if (!v) setArchive(null); }}
        axis={axis}
        category={archiving}
        onConfirm={archive}
      />
    </div>
  );
}


// ─── Page shell ──────────────────────────────────────────────────
export default function CategoriesAdmin() {
  const [tab, setTab] = useState("income");
  return (
    <div className="max-w-5xl mx-auto p-4"
          data-testid="categories-admin-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-black"
              style={{ color: colors.onSurface }}>Categories</h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Manage the two picklists that slice the pricebook and every
            estimate / invoice line item. Both use soft-delete —
            archived rows keep historical references intact.
          </p>
        </div>
        <Link to="/price-book"
                className="text-sm underline"
                style={{ color: colors.brand }}
                data-testid="categories-admin-back-to-pricebook">
          ← Back to Pricebook
        </Link>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList className="grid grid-cols-2 w-full max-w-md"
                     data-testid="categories-admin-tabs">
          <TabsTrigger value="income"
                          data-testid="categories-admin-tab-income">
            Income Categories
          </TabsTrigger>
          <TabsTrigger value="service"
                          data-testid="categories-admin-tab-service">
            Service Categories
          </TabsTrigger>
        </TabsList>
        <TabsContent value="income" className="mt-4"
                        data-testid="categories-admin-panel-income">
          <CategoriesTable axis="income" />
        </TabsContent>
        <TabsContent value="service" className="mt-4"
                        data-testid="categories-admin-panel-service">
          <CategoriesTable axis="service" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
