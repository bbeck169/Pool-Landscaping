/**
 * Slice K2 · Job Line Items panel.
 *
 * Renders a pricebook-backed line-item table on the Job Detail page.
 * Server projection is the security boundary — technicians never
 * receive unit_price / subtotal / tax_rate / cost from the API, so
 * this component simply renders whatever the API sends.  Add / qty
 * edit / delete are wired for both admin and tech (tech can only
 * mutate lines they added — backend enforces).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2, X as XIcon, Search, Loader2, Package } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Button, Toast } from "@/components/ui-kit";

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
      setToast({ tone: "error", message: e.message });
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
    setBusyId(li.id);
    try {
      await api.patch(`/jobs/${jobId}/line-items/${li.id}`, { quantity: n });
      await refresh();
      setQtyEdits((e) => { const c = { ...e }; delete c[li.id]; return c; });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusyId(null);
    }
  };

  const columns = useMemo(() => {
    // Admin sees pricing columns; tech never.
    if (isAdmin) return ["Item", "Qty", "Unit", "Subtotal", ""];
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
          <Button
            testid="li-add-btn"
            onClick={() => setPicker(true)}
          >
            <Plus size={14} /> Add line
          </Button>
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
                const editing = qtyEdits[li.id] != null;
                const editable = !locked;
                return (
                  <tr
                    key={li.id}
                    style={{ borderBottom: `1px solid ${colors.border}` }}
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
                    <td className="px-2 py-2 align-top">
                      {editable ? (
                        <input
                          type="number"
                          min="0.01"
                          step="0.5"
                          value={editing ? qtyEdits[li.id] : li.quantity}
                          onChange={(e) =>
                            setQtyEdits((s) => ({ ...s, [li.id]: e.target.value }))
                          }
                          onBlur={() => editing && commitQty(li)}
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
                          className="px-2 py-2 align-top text-right"
                          style={{ color: colors.onSurface }}
                        >
                          {li.unit_price != null ? money(li.unit_price) : "—"}
                        </td>
                        <td
                          className="px-2 py-2 align-top text-right font-semibold"
                          style={{ color: colors.onSurface }}
                          data-testid={`li-subtotal-${li.id}`}
                        >
                          {li.subtotal != null ? money(li.subtotal) : "—"}
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
                  <td colSpan={2}></td>
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
                    <td colSpan={2}></td>
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
                  <td colSpan={2}></td>
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
