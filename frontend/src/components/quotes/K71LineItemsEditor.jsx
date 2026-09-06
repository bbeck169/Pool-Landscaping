/**
 * Phase K71 · Feb-2026 — Line-items editor with inline pencil edit,
 * bold Item + secondary muted long_description, and Service + Income
 * category dropdowns.
 *
 * Contract:
 *   - Renders the line-items table for /quotes/:id and /invoices/:id.
 *   - Column header renamed from "Description" → "Item" (spec K71).
 *   - Pencil icon appears on each row when ``canEdit`` is true (draft
 *     doc AND admin/super role). Clicking swaps the row into an inline
 *     form with fields: Item (description), Qty, Unit price, Description
 *     (multi-line, 500-char cap), Service Category, Income Category.
 *   - Save = PUT /api/quotes/:id with the full mutated line_items[]
 *     array (server recomputes totals). Cancel reverts. Enter = Save,
 *     Esc = Cancel.
 *   - Legacy line items (neither service_category_id nor
 *     income_category_id present) show a subtle "Uncategorized" badge.
 *   - PDF/portal never render this component (staff-only surface).
 */
import React, { useEffect, useRef, useState } from "react";
import { Pencil, X, Check } from "lucide-react";
import { colors, money } from "@/theme";
import CategoryPicker from "@/components/income/CategoryPicker";

const MAX_LONG_DESC = 500;

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
  // Pydantic model returns ``null`` on legacy Mongo docs, so the
  // presence-in-object check is unreliable — string-type check
  // aligns frontend + backend exactly.
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
  const [attempted, setAttempted] = useState(false);
  const nameRef = useRef(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  const commit = () => {
    setAttempted(true);
    if (!description.trim()) return;
    if (!serviceCategoryId || !incomeCategoryId) return;
    if ((longDesc || "").length > MAX_LONG_DESC) return;
    onSave({
      ...line,
      description: description.trim(),
      long_description: longDesc || null,
      quantity: Number(quantity) || 0,
      unit_price: Number(unitPrice) || 0,
      service_category_id: serviceCategoryId,
      income_category_id: incomeCategoryId,
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
        </div>
      </td>
    </tr>
  );
}

function ReadRow({ line, index, canEdit, onEdit }) {
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
      <td className="px-2 py-2 text-right w-12">
        {canEdit ? (
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
        ) : null}
      </td>
    </tr>
  );
}

export default function K71LineItemsEditor({
  doc, canEdit, onLinesUpdated, onError,
}) {
  const [editIndex, setEditIndex] = useState(null);
  const items = doc.line_items || [];

  const saveLine = async (idx, updatedLine) => {
    const next = items.slice();
    next[idx] = updatedLine;
    try {
      // Server recomputes subtotal/tax/total from the new array.
      const res = await onLinesUpdated(next);
      if (res !== false) setEditIndex(null);
    } catch (e) {
      onError?.(e?.data?.detail || e?.message || "Save failed");
    }
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
            <th className="px-2 py-2 w-12"></th>
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
                onCancel={() => setEditIndex(null)}
              />
            ) : (
              <ReadRow
                key={i}
                line={li}
                index={i}
                canEdit={canEdit && editIndex === null}
                onEdit={setEditIndex}
              />
            )
          ))}
        </tbody>
      </table>
    </div>
  );
}
