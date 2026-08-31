/**
 * Slice K2 · Job Line Items panel.
 *
 * Renders a pricebook-backed line-item table on the Job Detail page.
 * Server projection is the security boundary — technicians never
 * receive unit_price / subtotal / tax_rate / cost from the API, so
 * this component simply renders whatever the API sends.  Add / qty
 * edit / delete are wired for both admin and tech (tech can only
 * mutate lines they added — backend enforces).
 *
 * Phase F7 · Feb-2026 — "Add charge for visit" additions (admin-only):
 *   * Category picker per line (uses shared income CategoryPicker).
 *   * Editable unit_price with "Custom price · pricebook was $X"
 *     hint when the admin overrides the pricebook default.
 *   * "Also save to pricebook" checkbox per line — flips the row's
 *     ``pricebook_writeback_flag`` and triggers a writeback fan-out
 *     on save.
 *   * Inline row error highlight when the backend returns a 4xx
 *     with ``error_code`` + ``line_index`` (e.g. archived category).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2, X as XIcon, Search, Loader2, Package } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Button, Toast } from "@/components/ui-kit";
import CategoryPicker from "@/components/income/CategoryPicker";
// Phase F2 · Feb-2026 — "Add from template" bulk-append dropdown that
// sits next to the pricebook "Add line" affordance in this section.
import ApplyChargeTemplateButton from "../../components/schedule/ApplyChargeTemplateButton";

const FALLBACK_STATUSES = new Set(["completed", "cancelled"]);

function useLineItems(jobId, active) {
  const [data, setData] = useState({ line_items: [], job_totals: null });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    if (!jobId || !active) return;
    setLoading(true);
    setErr("");
    try {
      const res = await api.get(`/jobs/${jobId}/line-items`);
      setData({
        line_items: res.line_items || [],
        job_totals: res.job_totals || null,
      });
    } catch (e) {
      setErr(e?.message || "Failed to load line items.");
    } finally {
      setLoading(false);
    }
  }, [jobId, active]);
  useEffect(() => { load(); }, [load]);
  return { ...data, loading, err, refresh: load };
}

function PricebookPickerModal({ open, onClose, onPick, isAdmin }) {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    api.get(`/pricebook-items${qs}`)
      .then((res) => setItems(res?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open, q]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center px-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      data-testid="pricebook-picker"
      onClick={onClose}
    >
      <div
        className="rounded-2xl w-full max-w-lg"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
            Add line item
          </div>
          <button
            onClick={onClose}
            style={{ background: "transparent", border: 0, cursor: "pointer" }}
            aria-label="Close picker"
          >
            <XIcon size={16} color={colors.muted} />
          </button>
        </div>
        <div className="p-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="relative">
            <Search
              size={14}
              className="absolute left-2 top-1/2 -translate-y-1/2"
              color={colors.muted}
            />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search catalog…"
              className="w-full pl-7 pr-2 py-1.5 rounded-md text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="pricebook-search"
            />
          </div>
        </div>
        <div className="max-h-80 overflow-y-auto">
          {loading ? (
            <div className="p-6 flex justify-center">
              <Loader2 size={18} className="animate-spin" color={colors.brand} />
            </div>
          ) : items.length === 0 ? (
            <div
              className="p-6 text-sm text-center"
              style={{ color: colors.muted }}
              data-testid="pricebook-empty"
            >
              No items in catalog{q ? " for that search" : ""}.
            </div>
          ) : (
            items.map((it) => (
              <button
                key={it.id}
                type="button"
                className="w-full text-left px-4 py-2 flex items-center gap-3"
                style={{
                  background: colors.surface,
                  borderBottom: `1px solid ${colors.border}`,
                  cursor: "pointer",
                }}
                onClick={() => onPick(it)}
                data-testid={`pricebook-item-${it.id}`}
              >
                <Package size={14} color={colors.brand} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="text-sm font-semibold"
                    style={{ color: colors.onSurface }}
                  >
                    {it.name}
                  </div>
                  <div
                    className="text-[11px]"
                    style={{ color: colors.muted }}
                  >
                    {it.category || it.unit || "—"}
                  </div>
                </div>
                {isAdmin && it.unit_price != null ? (
                  <div
                    className="text-sm font-semibold"
                    style={{ color: colors.onSurface }}
                  >
                    {money(it.unit_price)}
                  </div>
                ) : null}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default function LineItemsSection({ jobId, jobStatus, user }) {
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isTech = user?.role === "technician";
  const canView = isAdmin || isTech;
  const locked = FALLBACK_STATUSES.has(jobStatus || "");

  const { line_items, job_totals, loading, refresh } = useLineItems(jobId, canView);
  const [picker, setPicker] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [toast, setToast] = useState(null);
  const [qtyEdits, setQtyEdits] = useState({}); // {liId: "3"}
  const [priceEdits, setPriceEdits] = useState({});     // {liId: "12.50"}
  // Inline row-error highlight surfaces the backend's 4xx contract
  // ({error_code, line_index, attempted_category}) — matches the
  // invoice-side error handling so operators aren't blindsided.
  const [rowErrors, setRowErrors] = useState({}); // {liId: {error_code, attempted_category}}

  const parseErr = (e) => {
    // Backend returns FastAPI HTTPException detail; api wrapper often
    // stringifies to "{"error_code":...}" or throws with a body.
    const raw = e?.body || e?.detail || e?.message || "";
    if (typeof raw === "object" && raw.error_code) return raw;
    if (typeof raw === "string") {
      try {
        const j = JSON.parse(raw);
        if (j?.detail?.error_code) return j.detail;
        if (j?.error_code) return j;
      } catch { /* not JSON */ }
    }
    return null;
  };

  const add = async (pbItem) => {
    try {
      await api.post(`/jobs/${jobId}/line-items`, {
        pricebook_item_id: pbItem.id,
        quantity: 1,
      });
      setPicker(false);
      await refresh();
      setToast({ tone: "success", message: `${pbItem.name} added` });
    } catch (e) {
      const structured = parseErr(e);
      if (structured?.error_code) {
        setToast({
          tone: "error",
          message: `${structured.error_code}${
            structured.attempted_category
              ? ` · ${structured.attempted_category}`
              : ""
          }`,
        });
      } else {
        setToast({ tone: "error", message: e.message || "Add failed" });
      }
    }
  };

  const remove = async (li) => {
    setBusyId(li.id);
    try {
      await api.del(`/jobs/${jobId}/line-items/${li.id}`);
      await refresh();
      setToast({ tone: "success", message: "Line removed" });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusyId(null);
    }
  };

  const commitPatch = async (li, patch) => {
    setBusyId(li.id);
    setRowErrors((s) => { const c = { ...s }; delete c[li.id]; return c; });
    try {
      await api.patch(`/jobs/${jobId}/line-items/${li.id}`, patch);
      await refresh();
    } catch (e) {
      const structured = parseErr(e);
      if (structured?.error_code) {
        setRowErrors((s) => ({
          ...s,
          [li.id]: {
            error_code: structured.error_code,
            attempted_category: structured.attempted_category,
            available_categories: structured.available_categories,
          },
        }));
        setToast({
          tone: "error",
          message: `Row error: ${structured.error_code}`,
        });
      } else {
        setToast({ tone: "error", message: e.message || "Update failed" });
      }
    } finally {
      setBusyId(null);
    }
  };

  const commitQty = async (li) => {
    const raw = qtyEdits[li.id];
    if (raw == null || raw === "") return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) {
      setToast({ tone: "error", message: "Quantity must be > 0" });
      return;
    }
    if (n === li.quantity) {
      setQtyEdits((e) => { const c = { ...e }; delete c[li.id]; return c; });
      return;
    }
    await commitPatch(li, { quantity: n });
    setQtyEdits((e) => { const c = { ...e }; delete c[li.id]; return c; });
  };

  const commitPrice = async (li) => {
    const raw = priceEdits[li.id];
    if (raw == null || raw === "") return;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) {
      setToast({ tone: "error", message: "Price must be ≥ 0" });
      return;
    }
    if (n === Number(li.unit_price || 0)) {
      setPriceEdits((e) => { const c = { ...e }; delete c[li.id]; return c; });
      return;
    }
    await commitPatch(li, { unit_price: n });
    setPriceEdits((e) => { const c = { ...e }; delete c[li.id]; return c; });
  };

  const setCategory = (li, cat) => commitPatch(li, { category: cat || "" });
  const toggleWriteback = (li) =>
    commitPatch(li, { pricebook_writeback: !li.pricebook_writeback_flag });

  const columns = useMemo(() => {
    // Admin sees pricing + F7 columns; tech never.
    if (isAdmin) return ["Item", "Category", "Qty", "Unit", "Subtotal", "Save to pricebook", ""];
    return ["Item", "Qty", "Notes", ""];
  }, [isAdmin]);

  if (!canView) return null;

  return (
    <div
      className="rounded-2xl p-6 mb-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="job-line-items-section"
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3
            className="text-lg font-bold"
            style={{ color: colors.onSurface }}
          >
            Line Items
          </h3>
          {isAdmin ? (
            <p className="text-xs" style={{ color: colors.muted }}>
              Add items from the pricebook. Totals refresh on every change.
            </p>
          ) : (
            <p className="text-xs" style={{ color: colors.muted }}>
              Add parts/materials used on this job.
            </p>
          )}
        </div>
        {!locked ? (
          <div className="flex items-center gap-2">
            {isAdmin ? (
              <ApplyChargeTemplateButton
                jobId={jobId}
                onApplied={() => { refresh(); }}
                data-testid="li-apply-template"
              />
            ) : null}
            <Button
              testid="li-add-btn"
              onClick={() => setPicker(true)}
            >
              <Plus size={14} /> Add line
            </Button>
          </div>
        ) : null}
      </div>

      {loading && line_items.length === 0 ? (
        <div className="p-4 text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : line_items.length === 0 ? (
        <div
          className="p-6 text-sm text-center rounded-lg"
          style={{ background: colors.surfaceSecondary, color: colors.muted }}
          data-testid="li-empty"
        >
          No line items yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="li-table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c}
                    className="text-left text-[10px] uppercase font-bold px-2 py-1"
                    style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {line_items.map((li) => {
                const qtyEditing = qtyEdits[li.id] != null;
                const priceEditing = priceEdits[li.id] != null;
                const editable = !locked;
                const rowErr = rowErrors[li.id];
                const rowBorder = rowErr
                  ? `1px solid ${colors.error}`
                  : `1px solid ${colors.border}`;
                return (
                  <tr
                    key={li.id}
                    style={{ borderBottom: rowBorder }}
                    data-testid={`li-row-${li.id}`}
                  >
                    <td className="px-2 py-2 align-top">
                      <div
                        className="text-sm font-semibold"
                        style={{ color: colors.onSurface }}
                      >
                        {li.name || "Item"}
                      </div>
                      {li.description ? (
                        <div className="text-[11px]" style={{ color: colors.muted }}>
                          {li.description}
                        </div>
                      ) : null}
                    </td>
                    {isAdmin ? (
                      <td
                        className="px-2 py-2 align-top"
                        style={{ minWidth: 160 }}
                        data-testid={`li-category-cell-${li.id}`}
                      >
                        {editable ? (
                          <CategoryPicker
                            value={li.category || ""}
                            onChange={(cat) => setCategory(li, cat)}
                            disabled={busyId === li.id}
                            invalidReason={
                              rowErr?.error_code === "archived_category"
                                ? "archived_category"
                                : undefined
                            }
                            testid={`li-category-${li.id}`}
                          />
                        ) : (
                          <span style={{ color: colors.onSurface }}>
                            {li.category || "—"}
                          </span>
                        )}
                      </td>
                    ) : null}
                    <td className="px-2 py-2 align-top">
                      {editable ? (
                        <input
                          type="number"
                          min="0.01"
                          step="0.5"
                          value={qtyEditing ? qtyEdits[li.id] : li.quantity}
                          onChange={(e) =>
                            setQtyEdits((s) => ({ ...s, [li.id]: e.target.value }))
                          }
                          onBlur={() => qtyEditing && commitQty(li)}
                          onKeyDown={(e) => e.key === "Enter" && commitQty(li)}
                          disabled={busyId === li.id}
                          className="w-16 px-1.5 py-0.5 rounded-md text-sm"
                          style={{
                            border: `1px solid ${colors.border}`,
                            background: colors.surface,
                            color: colors.onSurface,
                          }}
                          data-testid={`li-qty-${li.id}`}
                        />
                      ) : (
                        <span>{li.quantity}</span>
                      )}
                    </td>
                    {isAdmin ? (
                      <>
                        <td
                          className="px-2 py-2 align-top"
                          style={{ color: colors.onSurface, minWidth: 110 }}
                        >
                          {editable ? (
                            <>
                              <div className="flex items-center gap-1">
                                <span style={{ color: colors.muted }}>$</span>
                                <input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={priceEditing ? priceEdits[li.id] : (li.unit_price ?? 0)}
                                  onChange={(e) =>
                                    setPriceEdits((s) => ({ ...s, [li.id]: e.target.value }))
                                  }
                                  onBlur={() => priceEditing && commitPrice(li)}
                                  onKeyDown={(e) => e.key === "Enter" && commitPrice(li)}
                                  disabled={busyId === li.id}
                                  className="w-24 px-1.5 py-0.5 rounded-md text-sm text-right"
                                  style={{
                                    border: `1px solid ${colors.border}`,
                                    background: colors.surface,
                                    color: colors.onSurface,
                                  }}
                                  data-testid={`li-unit-price-${li.id}`}
                                />
                              </div>
                              {li.custom_price_override_flag ? (
                                <div
                                  className="text-[10px] mt-0.5"
                                  style={{ color: colors.warning || colors.brand }}
                                  data-testid={`li-custom-price-hint-${li.id}`}
                                >
                                  Custom price
                                </div>
                              ) : null}
                            </>
                          ) : (
                            <span>
                              {li.unit_price != null ? money(li.unit_price) : "—"}
                            </span>
                          )}
                        </td>
                        <td
                          className="px-2 py-2 align-top text-right font-semibold"
                          style={{ color: colors.onSurface }}
                          data-testid={`li-subtotal-${li.id}`}
                        >
                          {li.subtotal != null ? money(li.subtotal) : "—"}
                        </td>
                        <td
                          className="px-2 py-2 align-top text-center"
                          data-testid={`li-writeback-cell-${li.id}`}
                        >
                          <label
                            className="inline-flex items-center gap-1 text-[11px]"
                            style={{ color: colors.muted, cursor: editable ? "pointer" : "default" }}
                          >
                            <input
                              type="checkbox"
                              checked={!!li.pricebook_writeback_flag}
                              onChange={() => toggleWriteback(li)}
                              disabled={!editable || busyId === li.id}
                              data-testid={`li-writeback-${li.id}`}
                            />
                            <span>Save</span>
                          </label>
                        </td>
                      </>
                    ) : (
                      <td
                        className="px-2 py-2 align-top text-[12px]"
                        style={{ color: colors.muted }}
                      >
                        {li.notes || "—"}
                      </td>
                    )}
                    <td className="px-2 py-2 align-top text-right">
                      {editable ? (
                        <button
                          type="button"
                          onClick={() => remove(li)}
                          disabled={busyId === li.id}
                          style={{
                            background: "transparent",
                            border: 0,
                            cursor: "pointer",
                            color: colors.error,
                          }}
                          aria-label="Remove line"
                          data-testid={`li-del-${li.id}`}
                        >
                          {busyId === li.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Trash2 size={14} />
                          )}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {isAdmin && job_totals ? (
              <tfoot data-testid="li-totals">
                <tr>
                  <td colSpan={4}></td>
                  <td
                    className="px-2 py-1 text-right text-xs font-semibold"
                    style={{ color: colors.muted }}
                  >
                    Subtotal
                  </td>
                  <td
                    className="px-2 py-1 text-right text-sm font-semibold"
                    style={{ color: colors.onSurface }}
                    data-testid="li-total-subtotal"
                  >
                    {money(job_totals.subtotal || 0)}
                  </td>
                  <td></td>
                </tr>
                {job_totals.tax ? (
                  <tr>
                    <td colSpan={4}></td>
                    <td
                      className="px-2 py-1 text-right text-xs"
                      style={{ color: colors.muted }}
                    >
                      Tax
                    </td>
                    <td
                      className="px-2 py-1 text-right text-sm"
                      style={{ color: colors.onSurface }}
                    >
                      {money(job_totals.tax || 0)}
                    </td>
                    <td></td>
                  </tr>
                ) : null}
                <tr>
                  <td colSpan={4}></td>
                  <td
                    className="px-2 py-1 text-right text-xs font-bold uppercase"
                    style={{ color: colors.muted }}
                  >
                    Total
                  </td>
                  <td
                    className="px-2 py-1 text-right text-base font-bold"
                    style={{ color: colors.onSurface }}
                    data-testid="li-total-total"
                  >
                    {money(job_totals.total || 0)}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      )}

      <PricebookPickerModal
        open={picker}
        onClose={() => setPicker(false)}
        onPick={add}
        isAdmin={isAdmin}
      />

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
