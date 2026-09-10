/**
 * Phase K71 · Feb-2026 — Line-items editor with inline pencil edit,
 * bold Item + secondary muted long_description, and Service + Income
 * category dropdowns.
 *
 * Phase K80.a · Feb-2026 — Add + Delete line item affordances.
 *   • "+ Add line" button below the table (visible only when canEdit).
 *     Clicking appends an empty draft line and enters inline-edit mode
 *     on it immediately. Cancelling a NEW line discards it entirely.
 *   • Trash icon on each row (visible only when canEdit). Clicking hides
 *     the row locally and surfaces an in-component Undo toast for 5s.
 *     If not undone, onLinesUpdated fires with the deleted row removed.
 *   • Only one pending delete at a time. While a delete is pending the
 *     Add-line and other trash buttons are disabled to keep state simple.
 *   • Category-required validation is unchanged: an added line still has
 *     to pass the same Service + Income picker rule as any legacy row
 *     switching into edit mode. Rows added and then Cancelled/Undone
 *     never round-trip to the server.
 *
 * Contract:
 *   - Renders the line-items table for /quotes/:id and /invoices/:id.
 *   - Column header renamed from "Description" → "Item" (spec K71).
 *   - Pencil icon appears on each row when ``canEdit`` is true (draft
 *     doc AND admin/super role). Clicking swaps the row into an inline
 *     form with fields: Item (description), Qty, Unit price, Description
 *     (multi-line, 500-char cap), Service Category, Income Category.
 *   - Save = onLinesUpdated(fullMutatedArray) — parent PUTs the whole
 *     array to /api/quotes/:id (server recomputes totals). Cancel reverts.
 *     Enter = Save, Esc = Cancel.
 *   - Legacy line items (neither service_category_id nor
 *     income_category_id present) show a subtle "Uncategorized" badge.
 *   - PDF/portal never render this component (staff-only surface).
 */
import React, { useEffect, useRef, useState } from "react";
import { Pencil, X, Check, Plus, Trash2, Undo2 } from "lucide-react";
import { colors, money } from "@/theme";
import CategoryPicker from "@/components/income/CategoryPicker";

const MAX_LONG_DESC = 500;
const UNDO_WINDOW_MS = 5000;

function LegacyBadge() {
  return (
    <span
      className="px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
      data-testid="k71-uncategorized-badge"
    >
      Uncategorized
    </span>
  );
}

function isLegacyLine(li) {
  // Phase K71 · Feb-2026 — K71-touched iff either category field is
  // a string (matches backend routers/income_categories.py rule).
  const hasSvc = typeof li.service_category_id === "string";
  const hasInc = typeof li.income_category_id === "string";
  return !hasSvc && !hasInc;
}

function EditableRow({ line, index, onSave, onCancel }) {
  const [description, setDescription] = useState(line.description || "");
  const [longDesc, setLongDesc] = useState(line.long_description || "");
  const [quantity, setQuantity] = useState(String(line.quantity ?? 1));
  const [unitPrice, setUnitPrice] = useState(String(line.unit_price ?? 0));
  const [serviceCategoryId, setServiceCategoryId] = useState(
    line.service_category_id || ""
  );
  const [incomeCategoryId, setIncomeCategoryId] = useState(
    line.income_category_id || ""
  );
  // Feb-2026 · Pricebook × Profit-Reporting Phase 2 — per-line
  // admin overrides. Empty string in state = "no override, use
  // the snapshot at read". Serialised as null on save.
  const [wholesaleOverride, setWholesaleOverride] = useState(
    line.wholesale_cost_override == null ? "" : String(line.wholesale_cost_override)
  );
  const [laborOverride, setLaborOverride] = useState(
    line.labor_cost_override == null ? "" : String(line.labor_cost_override)
  );
  const [serviceCategoryOverride, setServiceCategoryOverride] = useState(
    line.service_category_id_override || ""
  );
  const [incomeCategoryOverride, setIncomeCategoryOverride] = useState(
    line.income_category_id_override || ""
  );
  const [attempted, setAttempted] = useState(false);
  const nameRef = useRef(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  // Feb-2026 · Phase 2 — Live margin display. Uses OVERRIDE-first
  // resolution to match backend ``effective_*`` semantics so admins
  // see the margin they'll actually book at the reporting layer.
  const wholesaleSnap = Number(line.wholesale_price_snapshot ?? 0);
  const laborSnap = Number(line.labor_cost_snapshot ?? 0);
  const effWholesale = wholesaleOverride === "" ? wholesaleSnap : Number(wholesaleOverride) || 0;
  const effLabor = laborOverride === "" ? laborSnap : Number(laborOverride) || 0;
  const retailPerUnit = Number(unitPrice) || 0;
  const qtyN = Number(quantity) || 0;
  const lineRevenue = retailPerUnit * qtyN;
  const lineCost = (effWholesale + effLabor) * qtyN;
  const marginDollar = lineRevenue - lineCost;
  const marginPct = lineRevenue > 0 ? (marginDollar / lineRevenue) * 100 : 0;

  const commit = () => {
    setAttempted(true);
    if (!description.trim()) return;
    if (!serviceCategoryId || !incomeCategoryId) return;
    if ((longDesc || "").length > MAX_LONG_DESC) return;
    // Validate override numeric fields are non-negative when set.
    if (wholesaleOverride !== "" && (Number.isNaN(Number(wholesaleOverride)) || Number(wholesaleOverride) < 0)) return;
    if (laborOverride !== "" && (Number.isNaN(Number(laborOverride)) || Number(laborOverride) < 0)) return;
    onSave({
      ...line,
      description: description.trim(),
      long_description: longDesc || null,
      quantity: Number(quantity) || 0,
      unit_price: Number(unitPrice) || 0,
      service_category_id: serviceCategoryId,
      income_category_id: incomeCategoryId,
      // Feb-2026 · Phase 2 — carry override fields through the save.
      // Empty-string in state maps to explicit null so the backend
      // treats it as "no override" (revert to snapshot).
      wholesale_cost_override: wholesaleOverride === "" ? null : Number(wholesaleOverride),
      labor_cost_override: laborOverride === "" ? null : Number(laborOverride),
      service_category_id_override: serviceCategoryOverride || null,
      income_category_id_override: incomeCategoryOverride || null,
    });
  };

  const handleKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); onCancel(); }
    if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "TEXTAREA") {
      e.preventDefault();
      commit();
    }
  };

  return (
    <tr
      style={{ borderBottom: `1px solid ${colors.divider}`,
                background: colors.surfaceSecondary }}
      data-testid={`k71-row-edit-${index}`}
      onKeyDown={handleKey}
    >
      <td colSpan={5} className="px-2 py-3">
        <div className="grid grid-cols-12 gap-2">
          <div className="col-span-12 sm:col-span-5">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>Item</label>
            <input
              ref={nameRef}
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-2 py-1 text-sm rounded"
              style={{ background: colors.surface,
                        border: `1px solid ${
                          attempted && !description.trim()
                            ? "#DC2626" : colors.border}` }}
              data-testid={`k71-input-item-${index}`}
            />
          </div>
          <div className="col-span-4 sm:col-span-2">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>Qty</label>
            <input
              type="number"
              step="0.01"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full px-2 py-1 text-sm rounded text-right"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid={`k71-input-qty-${index}`}
            />
          </div>
          <div className="col-span-8 sm:col-span-3">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>Unit price</label>
            <input
              type="number"
              step="0.01"
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
              className="w-full px-2 py-1 text-sm rounded text-right"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid={`k71-input-price-${index}`}
            />
          </div>
          <div className="col-span-12 sm:col-span-2 flex items-end justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="px-2 py-1 text-xs rounded"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid={`k71-cancel-${index}`}
            >
              <X size={12} className="inline" /> Cancel
            </button>
            <button
              type="button"
              onClick={commit}
              className="px-2 py-1 text-xs rounded font-semibold"
              style={{ background: colors.brand,
                        color: colors.onBrand || "#fff" }}
              data-testid={`k71-save-${index}`}
            >
              <Check size={12} className="inline" /> Save
            </button>
          </div>
          <div className="col-span-12">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>
              Description
              <span className="ml-2 font-normal normal-case">
                {(longDesc || "").length}/{MAX_LONG_DESC}
              </span>
            </label>
            <textarea
              rows={2}
              value={longDesc}
              maxLength={MAX_LONG_DESC}
              onChange={(e) => setLongDesc(e.target.value)}
              placeholder="Optional multi-line detail shown internally only."
              className="w-full px-2 py-1 text-sm rounded"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        resize: "vertical" }}
              data-testid={`k71-input-longdesc-${index}`}
            />
          </div>
          <div className="col-span-12 sm:col-span-6">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>
              Service category <span style={{ color: "#DC2626" }}>*</span>
            </label>
            <CategoryPicker
              source="service"
              value={serviceCategoryId}
              onChange={setServiceCategoryId}
              required
              testid={`k71-service-picker-${index}`}
              placeholder="Choose service category"
            />
            {attempted && !serviceCategoryId ? (
              <div className="text-[11px] mt-1"
                    style={{ color: "#DC2626" }}
                    data-testid={`k71-error-service-${index}`}>
                Service category is required.
              </div>
            ) : null}
          </div>
          <div className="col-span-12 sm:col-span-6">
            <label className="text-[10px] uppercase font-bold block mb-1"
                    style={{ color: colors.muted }}>
              Income category <span style={{ color: "#DC2626" }}>*</span>
            </label>
            <CategoryPicker
              source="income"
              value={incomeCategoryId}
              onChange={setIncomeCategoryId}
              required
              testid={`k71-income-picker-${index}`}
              placeholder="Choose income category"
            />
            {attempted && !incomeCategoryId ? (
              <div className="text-[11px] mt-1"
                    style={{ color: "#DC2626" }}
                    data-testid={`k71-error-income-${index}`}>
                Income category is required.
              </div>
            ) : null}
          </div>
          {/* Feb-2026 · Phase 2 — Cost & Category Overrides.
              Admin-only surface; never rendered on customer views. */}
          <div className="col-span-12 mt-3 p-3 rounded-lg"
               style={{ background: colors.surface, border: `1px dashed ${colors.border}` }}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[10px] uppercase font-bold tracking-wide"
                   style={{ color: colors.muted }}>
                Cost &amp; Category Overrides (admin-only)
              </div>
              <div
                className="text-xs font-bold"
                style={{ color: marginDollar >= 0 ? colors.brand : "#DC2626" }}
                data-testid={`line-item-margin-display-${index}`}
              >
                Margin: {marginPct.toFixed(1)}% ({money(marginDollar)})
              </div>
            </div>
            <div className="grid grid-cols-12 gap-2">
              <div className="col-span-6 sm:col-span-3">
                <label className="text-[10px] uppercase font-bold flex items-center justify-between mb-1"
                       style={{ color: colors.muted }}>
                  <span>Wholesale $</span>
                  {wholesaleOverride !== "" ? (
                    <button
                      type="button"
                      onClick={() => setWholesaleOverride("")}
                      className="text-[10px] normal-case font-semibold hover:underline"
                      style={{ color: colors.brand }}
                      data-testid={`line-item-reset-wholesale-${index}`}
                    >
                      reset
                    </button>
                  ) : null}
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={wholesaleOverride}
                  onChange={(e) => setWholesaleOverride(e.target.value)}
                  placeholder={wholesaleSnap ? String(wholesaleSnap) : "0.00"}
                  className="w-full px-2 py-1 text-sm rounded text-right"
                  style={{ background: colors.surfaceSecondary,
                           border: `1px solid ${colors.border}` }}
                  data-testid={`line-item-wholesale-override-${index}`}
                />
              </div>
              <div className="col-span-6 sm:col-span-3">
                <label className="text-[10px] uppercase font-bold flex items-center justify-between mb-1"
                       style={{ color: colors.muted }}>
                  <span>Labor $</span>
                  {laborOverride !== "" ? (
                    <button
                      type="button"
                      onClick={() => setLaborOverride("")}
                      className="text-[10px] normal-case font-semibold hover:underline"
                      style={{ color: colors.brand }}
                      data-testid={`line-item-reset-labor-${index}`}
                    >
                      reset
                    </button>
                  ) : null}
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={laborOverride}
                  onChange={(e) => setLaborOverride(e.target.value)}
                  placeholder={laborSnap ? String(laborSnap) : "0.00"}
                  className="w-full px-2 py-1 text-sm rounded text-right"
                  style={{ background: colors.surfaceSecondary,
                           border: `1px solid ${colors.border}` }}
                  data-testid={`line-item-labor-override-${index}`}
                />
              </div>
              <div className="col-span-12 sm:col-span-3">
                <label className="text-[10px] uppercase font-bold flex items-center justify-between mb-1"
                       style={{ color: colors.muted }}>
                  <span>Service cat.</span>
                  {serviceCategoryOverride ? (
                    <button
                      type="button"
                      onClick={() => setServiceCategoryOverride("")}
                      className="text-[10px] normal-case font-semibold hover:underline"
                      style={{ color: colors.brand }}
                      data-testid={`line-item-reset-service-category-${index}`}
                    >
                      reset
                    </button>
                  ) : null}
                </label>
                <CategoryPicker
                  source="service"
                  value={serviceCategoryOverride}
                  onChange={setServiceCategoryOverride}
                  testid={`line-item-service-category-select-${index}`}
                  placeholder="No override"
                />
              </div>
              <div className="col-span-12 sm:col-span-3">
                <label className="text-[10px] uppercase font-bold flex items-center justify-between mb-1"
                       style={{ color: colors.muted }}>
                  <span>Income cat.</span>
                  {incomeCategoryOverride ? (
                    <button
                      type="button"
                      onClick={() => setIncomeCategoryOverride("")}
                      className="text-[10px] normal-case font-semibold hover:underline"
                      style={{ color: colors.brand }}
                      data-testid={`line-item-reset-income-category-${index}`}
                    >
                      reset
                    </button>
                  ) : null}
                </label>
                <CategoryPicker
                  source="income"
                  value={incomeCategoryOverride}
                  onChange={setIncomeCategoryOverride}
                  testid={`line-item-income-category-select-${index}`}
                  placeholder="No override"
                />
              </div>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

function ReadRow({ line, index, canEdit, deleteDisabled, onEdit, onDelete }) {
  const q = Number(line.quantity || 0);
  const u = Number(line.unit_price || 0);
  const legacy = isLegacyLine(line);
  return (
    <tr
      style={{ borderBottom: `1px solid ${colors.divider}`,
                backgroundColor: line.is_late_fee ? "#FFF7ED" : undefined }}
      data-testid={`k71-row-${index}`}
    >
      <td className="px-2 py-2" style={{ color: colors.onSurface }}>
        <div className="flex items-center gap-2">
          <span className="font-semibold">{line.description}</span>
          {line.is_late_fee ? (
            <span
              className="px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide"
              style={{ backgroundColor: "#FEE2E2", color: "#B91C1C" }}
              data-testid="late-fee-chip"
            >
              Late fee
            </span>
          ) : null}
          {legacy ? <LegacyBadge /> : null}
        </div>
        {line.long_description ? (
          <div className="text-xs mt-0.5"
                style={{ color: colors.muted }}
                data-testid={`k71-longdesc-${index}`}>
            {line.long_description}
          </div>
        ) : null}
      </td>
      <td className="px-2 py-2 text-right"
          style={{ color: colors.onSurfaceSecondary }}>{q}</td>
      <td className="px-2 py-2 text-right"
          style={{ color: colors.onSurfaceSecondary }}>{money(u)}</td>
      <td className="px-2 py-2 text-right font-semibold"
          style={{ color: colors.onSurface }}>{money(q * u)}</td>
      <td className="px-2 py-2 text-right w-20">
        {canEdit ? (
          <div className="flex items-center justify-end gap-1">
            <button
              type="button"
              onClick={() => onEdit(index)}
              className="p-1 rounded hover:bg-black/5"
              style={{ color: colors.brand }}
              title="Edit line"
              data-testid={`k71-edit-btn-${index}`}
            >
              <Pencil size={13} />
            </button>
            <button
              type="button"
              onClick={() => onDelete(index)}
              disabled={deleteDisabled}
              className="p-1 rounded hover:bg-black/5 disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ color: "#DC2626" }}
              title={deleteDisabled
                ? "Finish the pending delete first"
                : "Delete line"}
              data-testid={`k71-delete-btn-${index}`}
            >
              <Trash2 size={13} />
            </button>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function UndoToast({ onUndo, testid }) {
  return (
    <div
      className="rounded-xl p-3 mt-3 text-sm flex items-center justify-between gap-3"
      style={{ background: "#1F2937", color: "#F9FAFB",
                border: "1px solid #111827" }}
      data-testid={testid}
    >
      <div className="flex items-center gap-2">
        <Trash2 size={14} />
        <span>Line item removed.</span>
      </div>
      <button
        type="button"
        onClick={onUndo}
        className="px-2 py-1 rounded text-xs font-semibold flex items-center gap-1"
        style={{ background: "#F9FAFB", color: "#111827" }}
        data-testid="k71-undo-btn"
      >
        <Undo2 size={12} /> Undo
      </button>
    </div>
  );
}

export default function K71LineItemsEditor({
  doc, canEdit, onLinesUpdated, onError,
}) {
  const [localItems, setLocalItems] = useState(doc.line_items || []);
  const [editIndex, setEditIndex] = useState(null);
  // Track the index of a locally-added-but-not-yet-saved line so
  // Cancel discards it entirely (vs reverting an existing row).
  const [newLineIndex, setNewLineIndex] = useState(null);
  // Single-slot pending delete with 5s undo window.
  //   { line, originalIndex, timeoutId }
  const [pendingDelete, setPendingDelete] = useState(null);

  // Ref so the delayed onLinesUpdated call captures the LATEST
  // localItems (in case the user adds another line during the window).
  const localItemsRef = useRef(localItems);
  useEffect(() => { localItemsRef.current = localItems; }, [localItems]);

  // Sync when parent doc changes (after a save or full reload).
  // Only re-sync when nothing is in flight locally — otherwise we'd
  // wipe an unsaved add or an active undo window.
  useEffect(() => {
    if (editIndex === null && pendingDelete === null && newLineIndex === null) {
      setLocalItems(doc.line_items || []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.line_items]);

  // Clear any lingering timeout on unmount so we don't fire a save
  // against a stale parent after the page navigates away.
  useEffect(() => {
    return () => {
      if (pendingDelete?.timeoutId) {
        clearTimeout(pendingDelete.timeoutId);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = localItems;
  const canAdd = canEdit && editIndex === null && pendingDelete === null;

  const saveLine = async (idx, updatedLine) => {
    const next = items.slice();
    next[idx] = updatedLine;
    try {
      // Optimistic: reflect in local state immediately so the
      // "Cancel" of a subsequent add doesn't wipe the fresh save.
      setLocalItems(next);
      const res = await onLinesUpdated(next);
      if (res !== false) {
        setEditIndex(null);
        // Clear new-line marker — the row is now persisted.
        if (newLineIndex === idx) setNewLineIndex(null);
      } else {
        // Save rejected — leave the row in edit mode so the user
        // can fix the error and retry.
      }
    } catch (e) {
      onError?.(e?.data?.detail || e?.message || "Save failed");
    }
  };

  const cancelLine = (idx) => {
    if (newLineIndex === idx) {
      // Discard the never-saved draft entirely.
      setLocalItems((prev) => prev.filter((_, i) => i !== idx));
      setNewLineIndex(null);
    }
    setEditIndex(null);
  };

  const handleAddLine = () => {
    if (!canAdd) return;
    const empty = {
      description: "",
      quantity: 1,
      unit_price: 0,
      service_category_id: "",
      income_category_id: "",
      long_description: "",
    };
    setLocalItems((prev) => {
      const next = [...prev, empty];
      const newIdx = next.length - 1;
      setNewLineIndex(newIdx);
      setEditIndex(newIdx);
      return next;
    });
  };

  const handleDelete = (idx) => {
    if (!canEdit || pendingDelete !== null) return;
    const line = items[idx];
    const nextLocal = items.filter((_, i) => i !== idx);
    setLocalItems(nextLocal);
    const timeoutId = setTimeout(async () => {
      setPendingDelete(null);
      try {
        // Use the ref so any add/edit that happened during the
        // window is included.
        await onLinesUpdated(localItemsRef.current);
      } catch (e) {
        onError?.(e?.data?.detail || e?.message || "Delete failed");
      }
    }, UNDO_WINDOW_MS);
    setPendingDelete({ line, originalIndex: idx, timeoutId });
  };

  const handleUndo = () => {
    if (!pendingDelete) return;
    clearTimeout(pendingDelete.timeoutId);
    setLocalItems((prev) => {
      const restored = prev.slice();
      const at = Math.min(pendingDelete.originalIndex, restored.length);
      restored.splice(at, 0, pendingDelete.line);
      return restored;
    });
    setPendingDelete(null);
  };

  // K71 gap detection for the banner + inline row highlighting.
  // Uses the same string-type rule as the backend so a legacy line
  // returned as ``service_category_id: null`` doesn't spuriously
  // enter the banner count.
  const gaps = items
    .map((li, i) => {
      const hasSvc = typeof li.service_category_id === "string";
      const hasInc = typeof li.income_category_id === "string";
      if (!hasSvc && !hasInc) return null;
      const svcVal = hasSvc ? li.service_category_id.trim() : "";
      const incVal = hasInc ? li.income_category_id.trim() : "";
      return (!svcVal || !incVal) ? i : null;
    })
    .filter((v) => v !== null);

  return (
    <div>
      {gaps.length && canEdit ? (
        <div
          className="rounded-xl p-3 mb-3 text-sm flex items-start gap-2"
          style={{ background: "#FEE2E2", color: "#7F1D1D",
                    border: "1px solid #FCA5A5" }}
          data-testid="k71-gap-banner"
        >
          <span className="font-semibold">Missing categories:</span>
          <span>
            {gaps.length === 1
              ? "1 line item is missing a Service or Income category."
              : `${gaps.length} line items are missing a Service or Income category.`}{" "}
            You must set them before sending, approving or converting.
          </span>
        </div>
      ) : null}
      <table className="w-full text-sm" data-testid="k71-line-items-table">
        <thead>
          <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
            <th className="text-left px-2 py-2 font-semibold"
                style={{ color: colors.onSurfaceSecondary }}
                data-testid="k71-th-item">Item</th>
            <th className="text-right px-2 py-2 font-semibold"
                style={{ color: colors.onSurfaceSecondary }}>Qty</th>
            <th className="text-right px-2 py-2 font-semibold"
                style={{ color: colors.onSurfaceSecondary }}>Unit</th>
            <th className="text-right px-2 py-2 font-semibold"
                style={{ color: colors.onSurfaceSecondary }}>Total</th>
            <th className="px-2 py-2 w-20"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((li, i) => (
            editIndex === i ? (
              <EditableRow
                key={i}
                line={li}
                index={i}
                onSave={(updated) => saveLine(i, updated)}
                onCancel={() => cancelLine(i)}
              />
            ) : (
              <ReadRow
                key={i}
                line={li}
                index={i}
                canEdit={canEdit && editIndex === null}
                deleteDisabled={pendingDelete !== null}
                onEdit={setEditIndex}
                onDelete={handleDelete}
              />
            )
          ))}
        </tbody>
      </table>

      {canEdit ? (
        <div className="mt-3 flex justify-start">
          <button
            type="button"
            onClick={handleAddLine}
            disabled={!canAdd}
            className="text-xs font-semibold flex items-center gap-1 px-2 py-1 rounded disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ color: colors.brand,
                      border: `1px dashed ${colors.brand}` }}
            data-testid="k71-add-line-btn"
            title={pendingDelete !== null
              ? "Finish the pending delete first"
              : editIndex !== null
                ? "Save or cancel the current row first"
                : "Add a new line item"}
          >
            <Plus size={12} /> Add line
          </button>
        </div>
      ) : null}

      {pendingDelete ? (
        <UndoToast onUndo={handleUndo} testid="k71-undo-toast" />
      ) : null}
    </div>
  );
}
