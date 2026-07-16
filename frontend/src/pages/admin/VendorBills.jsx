/**
 * Phase 51.K — Admin Vendor Bills CRUD (feeds AP Aging).
 * Endpoints:
 *   GET    /api/cfo/bills
 *   POST   /api/cfo/bills
 *   PATCH  /api/cfo/bills/{id}
 *   DELETE /api/cfo/bills/{id}
 */
import React, { useEffect, useState } from "react";
import { Receipt, Plus, X, Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";

function fmtMoney(cents) { return `$${(Number(cents || 0) / 100).toFixed(2)}`; }
function todayIso() { return new Date().toISOString().slice(0, 10); }

export default function VendorBills() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const res = await api.get("/cfo/bills");
      setRows(res?.items || []);
    } catch (e) { setError(e?.message || "Load failed"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setDraft({
      vendor_name: "", bill_date: todayIso(), due_date: todayIso(),
      amount_cents: 0, paid_amount_cents: 0, status: "open", notes: "",
    });
    setModalOpen(true);
  };
  const openEdit = (row) => { setDraft({ ...row }); setModalOpen(true); };
  const save = async () => {
    try {
      const payload = {
        vendor_name: draft.vendor_name,
        bill_date: draft.bill_date,
        due_date: draft.due_date,
        amount_cents: Math.round(Number(draft._amount || 0) * 100) || draft.amount_cents,
        paid_amount_cents: Math.round(Number(draft._paid || 0) * 100) || draft.paid_amount_cents || 0,
        status: draft.status,
        notes: draft.notes || "",
      };
      if (draft.id) await api.patch(`/cfo/bills/${draft.id}`, payload);
      else await api.post("/cfo/bills", payload);
      setModalOpen(false); setDraft(null); await load();
    } catch (e) { setError(e?.message || "Save failed"); }
  };
  const remove = async (row) => {
    const proceed = await mustConfirm({
      title: `Delete "${row.vendor_name}"?`,
      description: "This vendor bill will be permanently removed.",
      confirmText: "Delete",
      cancelText: "Cancel",
      tone: "destructive",
    });
    if (!proceed) return;
    try { await api.delete(`/cfo/bills/${row.id}`); await load(); }
    catch (e) { setError(e?.message || "Delete failed"); }
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="vendor-bills-page">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            <Receipt size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Vendor Bills</h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>Feeds the AP Aging card on CFO Reports.</p>
          </div>
        </div>
        <button type="button" onClick={openCreate}
                className="inline-flex items-center gap-1 text-sm font-bold px-3 py-2 rounded-md"
                style={{ background: colors.brand, color: "#fff", border: 0 }}
                data-testid="vendor-bills-create">
          <Plus size={14} /> New bill
        </button>
      </div>
      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="vendor-bills-error">{error}</div>
      ) : null}
      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>Loading…</div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="vendor-bills-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Vendor</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Due</th>
                <th className="text-right px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Amount</th>
                <th className="text-right px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Paid</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="vendor-bills-empty">
                  No bills yet. Add your first vendor bill above.
                </td></tr>
              ) : rows.map((r) => (
                <tr key={r.id} data-testid={`vendor-bill-row-${r.id}`}
                    style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2.5 font-semibold" style={{ color: colors.onSurface }}>{r.vendor_name}</td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>{r.due_date}</td>
                  <td className="px-3 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>{fmtMoney(r.amount_cents)}</td>
                  <td className="px-3 py-2.5 text-right" style={{ color: colors.muted }}>{fmtMoney(r.paid_amount_cents)}</td>
                  <td className="px-3 py-2.5">
                    <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                          style={r.status === "paid"
                            ? { background: "#DCFCE7", color: "#166534" }
                            : r.status === "partial"
                              ? { background: "#FEF3C7", color: "#92400E" }
                              : { background: "#FEE2E2", color: "#991B1B" }}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    <button type="button" onClick={() => openEdit(r)}
                            className="text-xs font-semibold px-2 py-1 rounded mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`vendor-bill-edit-${r.id}`}>Edit</button>
                    <button type="button" onClick={() => remove(r)}
                            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded"
                            style={{ border: `1px solid #FECACA`, background: colors.surface, color: "#B91C1C" }}
                            data-testid={`vendor-bill-delete-${r.id}`}>
                      <Trash2 size={11} /> Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {modalOpen && draft ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(15,23,42,0.55)" }}>
          <div className="w-full max-w-md rounded-2xl"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>{draft.id ? "Edit bill" : "New bill"}</h2>
              <button type="button" onClick={() => { setModalOpen(false); setDraft(null); }}
                      data-testid="vendor-bills-modal-close"><X size={18} /></button>
            </div>
            <div className="p-5 space-y-3">
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Vendor
                <input type="text" value={draft.vendor_name || ""} onChange={(e) => setDraft((x) => ({ ...x, vendor_name: e.target.value }))}
                       className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="vendor-bills-vendor" />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Bill date
                  <input type="date" value={draft.bill_date} onChange={(e) => setDraft((x) => ({ ...x, bill_date: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="vendor-bills-bill-date" />
                </label>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Due date
                  <input type="date" value={draft.due_date} onChange={(e) => setDraft((x) => ({ ...x, due_date: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="vendor-bills-due-date" />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Amount ($)
                  <input type="number" min="0" step="0.01"
                         defaultValue={((draft.amount_cents || 0) / 100).toFixed(2)}
                         onChange={(e) => setDraft((x) => ({ ...x, _amount: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="vendor-bills-amount" />
                </label>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Paid ($)
                  <input type="number" min="0" step="0.01"
                         defaultValue={((draft.paid_amount_cents || 0) / 100).toFixed(2)}
                         onChange={(e) => setDraft((x) => ({ ...x, _paid: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="vendor-bills-paid" />
                </label>
              </div>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Status
                <select value={draft.status || "open"} onChange={(e) => setDraft((x) => ({ ...x, status: e.target.value }))}
                        className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                        data-testid="vendor-bills-status">
                  <option value="open">Open</option>
                  <option value="partial">Partial</option>
                  <option value="paid">Paid</option>
                </select>
              </label>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2" style={{ borderTop: `1px solid ${colors.border}` }}>
              <button type="button" onClick={() => { setModalOpen(false); setDraft(null); }}
                      className="text-sm font-semibold px-3 py-1.5 rounded"
                      style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                      data-testid="vendor-bills-cancel">Cancel</button>
              <button type="button" onClick={save} disabled={!draft.vendor_name}
                      className="text-sm font-bold px-4 py-1.5 rounded"
                      style={{ background: colors.brand, color: "#fff", border: 0, opacity: !draft.vendor_name ? 0.5 : 1 }}
                      data-testid="vendor-bills-save">{draft.id ? "Save changes" : "Create"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
