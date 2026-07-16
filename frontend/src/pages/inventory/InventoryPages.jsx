/**
 * Phase 23 · Inventory Tracker — admin pages in one file.
 * Exports: InventoryList (default), InventoryDetail, InventoryPOs,
 *          InventoryAlerts, InventoryAnalytics.
 * All admin-only via App.js AdminOnly wrapper.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Plus, Package, AlertTriangle, ShoppingCart, TrendingUp,
  BarChart3, Trash2, PenSquare, Boxes, ChevronRight, Truck, PackageOpen,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

/* ─── helpers ────────────────────────────────────────────────────────── */
const CATEGORIES = [
  { value: "", label: "All" },
  { value: "chemical", label: "Chemicals" },
  { value: "part", label: "Parts" },
  { value: "equipment", label: "Equipment" },
  { value: "consumable", label: "Consumables" },
  { value: "other", label: "Other" },
];

const UNITS = ["gal", "lbs", "oz", "tabs", "ea", "linft", "sqft", "hr", "yd", "other"];

function stockTint(current, reorder) {
  const c = Number(current || 0);
  const r = Number(reorder || 0);
  if (c <= 0) return "#DC2626";
  if (c <= r) return "#EA580C";
  if (c <= r * 1.5) return "#F59E0B";
  return "#059669";
}

function StockPill({ current, reorder, unit }) {
  const c = Number(current || 0);
  const r = Number(reorder || 0);
  const color = stockTint(c, r);
  const label = c <= 0 ? "OUT" : c <= r ? "LOW" : "OK";
  return (
    <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
         style={{ backgroundColor: `${color}15`, color }}
         data-testid="inv-stock-pill">
      <span>{label}</span>
      <span style={{ opacity: 0.7 }}>· {c} {unit}</span>
    </div>
  );
}

function statusPill(status) {
  const map = {
    pending:   ["#F59E0B", "Pending"],
    ordered:   ["#0EA5E9", "Ordered"],
    received:  ["#059669", "Received"],
    cancelled: ["#6B7280", "Cancelled"],
  };
  const [c, l] = map[status] || ["#6B7280", status];
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold"
          style={{ backgroundColor: `${c}15`, color: c }}>
      {l}
    </span>
  );
}

/* ═════════ LIST ═══════════════════════════════════════════════════════ */
export default function InventoryList() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [category, setCategory] = useState("");
  const [lowStock, setLowStock] = useState(false);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
      if (lowStock) params.set("low_stock", "true");
      if (q) params.set("q", q);
      const r = await api.get(`/inventory/items?${params.toString()}`);
      setItems(r.items || []);
    } finally { setLoading(false); }
  }, [category, lowStock, q]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="inventory-list">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Boxes size={22} style={{ color: colors.brand }} />
            Inventory
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Chemical + parts stock levels. Auto-decrements on service report
            submit.
          </p>
        </div>
        <button onClick={() => nav("/admin/inventory/alerts")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="inv-alerts-link">
          <AlertTriangle size={14} /> Alerts
        </button>
        <button onClick={() => nav("/admin/inventory/purchase-orders")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="inv-pos-link">
          <Truck size={14} /> POs
        </button>
        <button onClick={() => nav("/admin/inventory/analytics")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="inv-analytics-link">
          <BarChart3 size={14} /> Analytics
        </button>
        <button onClick={() => setShowNew(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="inv-new-btn">
          <Plus size={14} /> New Item
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <select value={category} onChange={(e) => setCategory(e.target.value)}
                className="px-3 py-2 text-sm rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-category-filter">
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm"
               style={{ backgroundColor: colors.surface,
                         border: `1px solid ${colors.border}` }}>
          <input type="checkbox" checked={lowStock}
                 onChange={(e) => setLowStock(e.target.checked)}
                 data-testid="inv-lowstock-toggle" />
          <span>Low stock only</span>
        </label>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search by name…"
               className="flex-1 min-w-[200px] px-3 py-2 text-sm rounded-xl"
               style={{ backgroundColor: colors.surface,
                         border: `1px solid ${colors.border}` }}
               data-testid="inv-search" />
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No inventory items match this filter.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Item</th>
                <th className="p-2 text-left">Category</th>
                <th className="p-2 text-right">On Hand</th>
                <th className="p-2 text-right">Reorder @</th>
                <th className="p-2 text-right">Unit $</th>
                <th className="p-2 text-right">Value</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}
                    style={{ borderTop: `1px solid ${colors.border}`,
                             cursor: "pointer" }}
                    onClick={() => nav(`/admin/inventory/${it.id}`)}
                    data-testid={`inv-row-${it.id}`}>
                  <td className="p-2">
                    <div className="font-bold flex items-center gap-2"
                         style={{ color: colors.onSurface }}>
                      {it.name}
                      <StockPill current={it.current_qty}
                                 reorder={it.reorder_point}
                                 unit={it.unit} />
                    </div>
                    {it.supplier ? (
                      <div className="text-[10px]"
                           style={{ color: colors.muted }}>
                        {it.supplier}
                      </div>
                    ) : null}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {it.category}
                  </td>
                  <td className="p-2 text-right font-mono"
                      style={{ color: stockTint(it.current_qty, it.reorder_point) }}>
                    {Number(it.current_qty || 0).toFixed(1)} {it.unit}
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.muted }}>
                    {Number(it.reorder_point || 0).toFixed(1)}
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.muted }}>
                    ${Number(it.unit_cost || 0).toFixed(2)}
                  </td>
                  <td className="p-2 text-right font-bold"
                      style={{ color: colors.onSurface }}>
                    ${(Number(it.current_qty || 0) * Number(it.unit_cost || 0)).toFixed(0)}
                  </td>
                  <td className="p-2 text-right">
                    <ChevronRight size={14} style={{ color: colors.muted }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew ? (
        <NewItemModal onClose={() => setShowNew(false)}
                       onCreated={() => { setShowNew(false); load(); }} />
      ) : null}
    </div>
  );
}

/* ─── new item modal ─────────────────────────────────────────────────── */
function NewItemModal({ onClose, onCreated }) {
  const [f, setF] = useState({
    name: "", category: "chemical", unit: "gal",
    current_qty: 0, reorder_point: 0, reorder_qty: 0,
    unit_cost: 0, supplier: "", location: "", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    if (!f.name.trim()) { setErr("Name required"); return; }
    setSaving(true); setErr("");
    try {
      await api.post("/inventory/items", {
        ...f,
        current_qty: Number(f.current_qty || 0),
        reorder_point: Number(f.reorder_point || 0),
        reorder_qty: Number(f.reorder_qty || 0),
        unit_cost: Number(f.unit_cost || 0),
      });
      onCreated();
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
         data-testid="inv-new-modal">
      <div className="rounded-2xl w-full max-w-lg p-5"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-4"
            style={{ color: colors.onSurface }}>
          New inventory item
        </h2>
        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2 block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Name</div>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="inv-form-name" />
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Category</div>
            <select value={f.category}
                    onChange={(e) => setF({ ...f, category: e.target.value })}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="inv-form-category">
              {CATEGORIES.filter((c) => c.value).map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Unit</div>
            <select value={f.unit}
                    onChange={(e) => setF({ ...f, unit: e.target.value })}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="inv-form-unit">
              {UNITS.map((u) => (<option key={u} value={u}>{u}</option>))}
            </select>
          </label>
          {[
            ["current_qty", "Current qty"],
            ["reorder_point", "Reorder at"],
            ["reorder_qty", "Reorder qty"],
            ["unit_cost", "Unit cost $"],
          ].map(([k, l]) => (
            <label key={k} className="block">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>{l}</div>
              <input type="number" step="0.1" value={f[k]}
                     onChange={(e) => setF({ ...f, [k]: e.target.value })}
                     className="w-full p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`inv-form-${k}`} />
            </label>
          ))}
          <label className="col-span-2 block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Supplier (optional)</div>
            <input value={f.supplier}
                   onChange={(e) => setF({ ...f, supplier: e.target.value })}
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="inv-form-supplier" />
          </label>
        </div>
        {err ? (
          <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>
            {err}
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                  data-testid="inv-form-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="inv-form-save">
            {saving ? "Saving…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═════════ DETAIL ═════════════════════════════════════════════════════ */
export function InventoryDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [item, setItem] = useState(null);
  const [movements, setMovements] = useState([]);
  const [delta, setDelta] = useState(0);
  const [reason, setReason] = useState("manual adjustment");
  const [adjusting, setAdjusting] = useState(false);

  const load = useCallback(async () => {
    const list = await api.get(`/inventory/items?q=`);
    const it = (list.items || []).find((x) => x.id === id);
    setItem(it || null);
    if (it) {
      const mv = await api.get(`/inventory/items/${id}/movements`);
      setMovements(mv.items || []);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (item === null) {
    return <div className="p-6 text-sm" style={{ color: colors.muted }}>
      Loading…
    </div>;
  }
  if (!item) {
    return <div className="p-6 text-sm" style={{ color: colors.muted }}>
      Item not found.
    </div>;
  }

  const adjust = async () => {
    const n = Number(delta);
    if (!n || Number.isNaN(n)) return;
    setAdjusting(true);
    try {
      await api.post(`/inventory/items/${id}/adjust`,
                     { delta: n, reason: reason || "manual adjustment" });
      setDelta(0);
      await load();
    } finally { setAdjusting(false); }
  };
  const del = async () => {
    if (!(await mustConfirm({ title: `Delete "${item.name}"?`, description: "This cannot be undone.", tone: "danger" }))) return;
    await api.delete(`/inventory/items/${id}`);
    nav("/admin/inventory");
  };

  const value = Number(item.current_qty || 0) * Number(item.unit_cost || 0);

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="inventory-detail">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/inventory")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-detail-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Package size={22} style={{ color: colors.brand }} />
            {item.name}
            <StockPill current={item.current_qty}
                       reorder={item.reorder_point}
                       unit={item.unit} />
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            {item.category} · {item.unit}
            {item.supplier ? ` · ${item.supplier}` : ""}
          </p>
        </div>
        <button onClick={del}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid #DC2626`,
                          color: "#DC2626" }}
                data-testid="inv-detail-delete">
          <Trash2 size={14} />
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          ["On hand", `${Number(item.current_qty).toFixed(1)} ${item.unit}`,
             stockTint(item.current_qty, item.reorder_point)],
          ["Reorder at", `${Number(item.reorder_point).toFixed(1)} ${item.unit}`,
             colors.onSurface],
          ["Unit cost", `$${Number(item.unit_cost).toFixed(2)}`,
             colors.onSurface],
          ["Value", `$${value.toFixed(2)}`, colors.brand],
        ].map(([l, v, c], i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-2xl font-bold mt-1"
                 style={{ color: c }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl p-5 mb-6"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-3"
            style={{ color: colors.onSurface }}>
          Stock adjustment
        </h2>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Delta (± {item.unit})</div>
            <input type="number" step="0.5" value={delta}
                   onChange={(e) => setDelta(e.target.value)}
                   className="w-32 p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="inv-adjust-delta" />
          </label>
          <label className="flex-1 min-w-[200px] block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Reason</div>
            <input value={reason} onChange={(e) => setReason(e.target.value)}
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="inv-adjust-reason" />
          </label>
          <button onClick={adjust} disabled={adjusting || !delta}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="inv-adjust-save">
            {adjusting ? "Saving…" : "Apply"}
          </button>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <div className="p-4 border-b" style={{ borderColor: colors.border }}>
          <h2 className="text-lg font-bold"
              style={{ color: colors.onSurface }}>
            Movement history
          </h2>
        </div>
        {movements.length === 0 ? (
          <div className="p-8 text-center text-sm"
               style={{ color: colors.muted }}>
            No movements yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">When</th>
                <th className="p-2 text-left">Kind</th>
                <th className="p-2 text-right">Delta</th>
                <th className="p-2 text-left">Reason</th>
                <th className="p-2 text-left">Source</th>
              </tr>
            </thead>
            <tbody>
              {movements.map((m) => (
                <tr key={m.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`inv-mv-row-${m.id}`}>
                  <td className="p-2 text-xs"
                      style={{ color: colors.muted }}>
                    {(m.ts || "").slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="p-2 text-xs font-bold"
                      style={{ color: colors.onSurface }}>{m.kind}</td>
                  <td className="p-2 text-right font-mono font-bold"
                      style={{ color: m.delta >= 0 ? "#059669" : "#DC2626" }}>
                    {m.delta >= 0 ? "+" : ""}{Number(m.delta).toFixed(1)}
                  </td>
                  <td className="p-2 text-xs"
                      style={{ color: colors.onSurface }}>{m.reason}</td>
                  <td className="p-2 text-[10px]"
                      style={{ color: colors.muted }}>
                    {m.ref_type}{m.ref_id ? ` · ${m.ref_id.slice(0, 8)}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ═════════ PURCHASE ORDERS ═════════════════════════════════════════════ */
export function InventoryPOs() {
  const nav = useNavigate();
  const [pos, setPos] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = statusFilter ? `?status=${statusFilter}` : "";
      const r = await api.get(`/inventory/purchase-orders${q}`);
      setPos(r.items || []);
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const setStatus = async (poid, status) => {
    await api.patch(`/inventory/purchase-orders/${poid}`, { status });
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="inventory-pos">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/inventory")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-pos-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <ShoppingCart size={22} style={{ color: colors.brand }} />
            Purchase orders
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Received POs auto-restock inventory and log restock movements.
          </p>
        </div>
        <select value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-2 text-sm rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-pos-filter">
          <option value="">All statuses</option>
          {["pending", "ordered", "received", "cancelled"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <button onClick={() => setShowNew(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="inv-po-new-btn">
          <Plus size={14} /> New PO
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : pos.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No purchase orders yet.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Created</th>
                <th className="p-2 text-left">Supplier</th>
                <th className="p-2 text-right">Items</th>
                <th className="p-2 text-right">Total</th>
                <th className="p-2 text-left">Status</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {pos.map((po) => (
                <tr key={po.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`inv-po-row-${po.id}`}>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {(po.created_at || "").slice(0, 10)}
                  </td>
                  <td className="p-2 text-xs font-bold"
                      style={{ color: colors.onSurface }}>{po.supplier}</td>
                  <td className="p-2 text-right text-xs">
                    {(po.items || []).length}
                  </td>
                  <td className="p-2 text-right font-bold"
                      style={{ color: colors.onSurface }}>
                    ${Number(po.total_cost || 0).toFixed(2)}
                  </td>
                  <td className="p-2">{statusPill(po.status)}</td>
                  <td className="p-2 flex gap-1 justify-end">
                    {po.status === "pending" ? (
                      <button onClick={() => setStatus(po.id, "ordered")}
                              className="px-2 py-1 text-xs font-bold rounded"
                              style={{ backgroundColor: "#0EA5E9",
                                        color: "#fff" }}
                              data-testid={`inv-po-order-${po.id}`}>
                        Mark ordered
                      </button>
                    ) : null}
                    {po.status === "ordered" ? (
                      <button onClick={() => setStatus(po.id, "received")}
                              className="px-2 py-1 text-xs font-bold rounded flex items-center gap-1"
                              style={{ backgroundColor: "#059669",
                                        color: "#fff" }}
                              data-testid={`inv-po-receive-${po.id}`}>
                        <PackageOpen size={10} /> Receive
                      </button>
                    ) : null}
                    {["pending", "ordered"].includes(po.status) ? (
                      <button onClick={() => setStatus(po.id, "cancelled")}
                              className="px-2 py-1 text-xs font-bold rounded"
                              style={{ backgroundColor: colors.background,
                                        color: colors.onSurface,
                                        border: `1px solid ${colors.border}` }}
                              data-testid={`inv-po-cancel-${po.id}`}>
                        Cancel
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew ? (
        <NewPOModal onClose={() => setShowNew(false)}
                     onCreated={() => { setShowNew(false); load(); }} />
      ) : null}
    </div>
  );
}

function NewPOModal({ onClose, onCreated }) {
  const [supplier, setSupplier] = useState("");
  const [items, setItems] = useState([]);
  const [inventoryItems, setInventoryItems] = useState([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/inventory/items").then((r) => setInventoryItems(r.items || []));
  }, []);

  const addLine = () => setItems([...items, { item_id: "", qty: 1, unit_cost: 0 }]);
  const updateLine = (i, patch) => {
    const next = [...items];
    next[i] = { ...next[i], ...patch };
    setItems(next);
  };
  const removeLine = (i) => setItems(items.filter((_, j) => j !== i));

  const total = useMemo(
    () => items.reduce((s, l) => s + Number(l.qty || 0) * Number(l.unit_cost || 0), 0),
    [items],
  );

  const save = async () => {
    if (!supplier.trim()) { setErr("Supplier required"); return; }
    if (items.length === 0) { setErr("Add at least one line"); return; }
    if (items.some((l) => !l.item_id || !l.qty)) {
      setErr("Every line needs an item and qty"); return;
    }
    setSaving(true); setErr("");
    try {
      await api.post("/inventory/purchase-orders", {
        supplier, items: items.map((l) => ({
          item_id: l.item_id,
          qty: Number(l.qty), unit_cost: Number(l.unit_cost || 0),
        })),
      });
      onCreated();
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
         data-testid="inv-po-modal">
      <div className="rounded-2xl w-full max-w-2xl p-5 max-h-[90vh] overflow-auto"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-4"
            style={{ color: colors.onSurface }}>
          New purchase order
        </h2>
        <label className="block mb-3">
          <div className="text-xs font-bold mb-1"
               style={{ color: colors.muted }}>Supplier</div>
          <input value={supplier} onChange={(e) => setSupplier(e.target.value)}
                 className="w-full p-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                 data-testid="inv-po-form-supplier" />
        </label>
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-bold" style={{ color: colors.muted }}>
            Line items
          </div>
          <button onClick={addLine}
                  className="px-2 py-1 text-xs font-bold rounded"
                  style={{ backgroundColor: colors.brandTertiary,
                           color: colors.brand }}
                  data-testid="inv-po-form-addline">
            + Add line
          </button>
        </div>
        {items.map((l, i) => (
          <div key={i} className="flex gap-2 mb-2 items-end">
            <select value={l.item_id}
                    onChange={(e) => updateLine(i, { item_id: e.target.value })}
                    className="flex-1 p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid={`inv-po-form-item-${i}`}>
              <option value="">Select item…</option>
              {inventoryItems.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name} ({x.unit})
                </option>
              ))}
            </select>
            <input type="number" step="0.5" value={l.qty}
                   onChange={(e) => updateLine(i, { qty: e.target.value })}
                   className="w-20 p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid={`inv-po-form-qty-${i}`}
                   placeholder="qty" />
            <input type="number" step="0.01" value={l.unit_cost}
                   onChange={(e) => updateLine(i, { unit_cost: e.target.value })}
                   className="w-24 p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid={`inv-po-form-cost-${i}`}
                   placeholder="$/unit" />
            <button onClick={() => removeLine(i)}
                    className="p-2 rounded-lg"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}`,
                             color: "#DC2626" }}
                    data-testid={`inv-po-form-remove-${i}`}>
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        <div className="mt-3 text-right text-sm font-bold"
             style={{ color: colors.onSurface }}>
          Total: ${total.toFixed(2)}
        </div>
        {err ? (
          <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>{err}</div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                  data-testid="inv-po-form-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="inv-po-form-save">
            {saving ? "Saving…" : "Create PO"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═════════ ALERTS ═════════════════════════════════════════════════════ */
export function InventoryAlerts() {
  const nav = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/inventory/alerts");
      setAlerts(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const quickPO = (a) => {
    // Prefill: navigate to PO page and open the modal state via URL flag.
    // Simpler: just jump to PO list, admin can add manually with pre-known item.
    nav("/admin/inventory/purchase-orders");
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="inventory-alerts">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/inventory")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-alerts-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <AlertTriangle size={22} style={{ color: "#EA580C" }} />
            Low-stock alerts
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Items at or below reorder point. Update by receiving a PO or
            adjusting stock directly.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : alerts.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          <TrendingUp size={36} style={{ color: "#059669", margin: "0 auto 8px" }} />
          <div className="font-bold" style={{ color: colors.onSurface }}>
            Everything is well-stocked.
          </div>
          <div className="text-xs mt-1">
            No items below their reorder point.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map((a) => (
            <div key={a.item_id}
                 className="rounded-2xl p-4 flex items-center justify-between"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${a.current_qty <= 0 ? "#DC2626" : "#F59E0B"}55` }}
                 data-testid={`inv-alert-row-${a.item_id}`}>
              <div>
                <div className="font-bold flex items-center gap-2"
                     style={{ color: colors.onSurface }}>
                  {a.name}
                  <StockPill current={a.current_qty}
                             reorder={a.reorder_point}
                             unit={a.unit} />
                </div>
                <div className="text-xs mt-1"
                     style={{ color: colors.muted }}>
                  {a.category} · {a.suggested_action} · suggest {a.reorder_qty} {a.unit}
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => nav(`/admin/inventory/${a.item_id}`)}
                        className="px-3 py-2 text-xs font-bold rounded-xl"
                        style={{ backgroundColor: colors.background,
                                 border: `1px solid ${colors.border}`,
                                 color: colors.onSurface }}
                        data-testid={`inv-alert-open-${a.item_id}`}>
                  Open
                </button>
                <button onClick={() => quickPO(a)}
                        className="px-3 py-2 text-xs font-bold rounded-xl flex items-center gap-1"
                        style={{ backgroundColor: colors.brand, color: "#fff" }}
                        data-testid={`inv-alert-po-${a.item_id}`}>
                  <ShoppingCart size={12} /> Create PO
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═════════ ANALYTICS ══════════════════════════════════════════════════ */
export function InventoryAnalytics() {
  const nav = useNavigate();
  const [a, setA] = useState(null);

  useEffect(() => { api.get("/inventory/analytics").then(setA); }, []);

  if (!a) {
    return <div className="p-6 text-sm" style={{ color: colors.muted }}>
      Loading…
    </div>;
  }

  const max = Math.max(...(a.most_used_last_30d || []).map((m) => m.used), 1);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6"
         data-testid="inventory-analytics">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/inventory")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="inv-analytics-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <BarChart3 size={22} style={{ color: colors.brand }} />
            Inventory analytics
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Total value, low-stock counts, most-used items in the last 30
            days, and a reorder forecast.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          ["Total value", `$${a.total_value.toFixed(0)}`, colors.brand],
          ["Total items", a.total_items, colors.onSurface],
          ["Low stock", a.low_stock_count, "#EA580C"],
          ["Out of stock", a.out_of_stock_count, "#DC2626"],
        ].map(([l, v, c], i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`inv-analytics-kpi-${i}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-2xl font-bold mt-1"
                 style={{ color: c }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-bold mb-3"
              style={{ color: colors.onSurface }}>
            Most used (30d)
          </h2>
          {(a.most_used_last_30d || []).length === 0 ? (
            <div className="text-xs text-center py-6"
                 style={{ color: colors.muted }}>
              No usage recorded in the last 30 days.
            </div>
          ) : (
            <div className="space-y-2">
              {a.most_used_last_30d.map((m) => (
                <div key={m.item_id}
                     data-testid={`inv-mostused-${m.item_id}`}>
                  <div className="flex justify-between text-sm mb-1">
                    <span style={{ color: colors.onSurface }}>{m.name}</span>
                    <span className="font-bold"
                          style={{ color: colors.onSurface }}>
                      {m.used.toFixed(1)} {m.unit}
                    </span>
                  </div>
                  <div className="h-4 rounded-lg overflow-hidden"
                       style={{ backgroundColor: "#F1F5F9" }}>
                    <div style={{ width: `${(m.used / max) * 100}%`,
                                    height: "100%",
                                    backgroundColor: colors.brand }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-bold mb-3"
              style={{ color: colors.onSurface }}>
            Reorder forecast
          </h2>
          {(a.reorder_forecast || []).length === 0 ? (
            <div className="text-xs text-center py-6"
                 style={{ color: colors.muted }}>
              Nothing pending reorder.
            </div>
          ) : (
            <div className="space-y-2">
              {a.reorder_forecast.map((r) => (
                <div key={r.item_id}
                     className="flex items-center justify-between px-3 py-2 rounded-lg"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`inv-forecast-${r.item_id}`}>
                  <div className="text-sm font-bold"
                       style={{ color: colors.onSurface }}>
                    {r.name}
                  </div>
                  <div className="text-xs"
                       style={{ color: stockTint(r.current_qty, r.reorder_point) }}>
                    {r.current_qty.toFixed(1)} / {r.reorder_point.toFixed(1)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
