/**
 * Phase 20B.3 · Admin assets & maintenance tracker.
 */
import React, { useEffect, useState } from "react";
import { Wrench, Plus, X, Truck, PackageOpen, Hammer, Settings2 } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

const CATEGORIES = [
  { key: "", label: "All", icon: Settings2 },
  { key: "vehicle",   label: "Vehicles",   icon: Truck },
  { key: "equipment", label: "Equipment",  icon: PackageOpen },
  { key: "tool",      label: "Tools",      icon: Hammer },
];

const STATUS_COLORS = {
  active:      { bg: "#DCFCE7", fg: "#166534" },
  maintenance: { bg: "#FEF3C7", fg: "#92400E" },
  retired:     { bg: "#F3F4F6", fg: "#4B5563" },
};

export default function AdminAssets() {
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [cat, setCat] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [detail, setDetail] = useState(null);
  const [maintList, setMaintList] = useState([]);
  const [form, setForm] = useState({ name: "", category: "vehicle", asset_tag: "" });
  const [maintForm, setMaintForm] = useState({ kind: "service", cost: 0, notes: "" });

  const load = () => {
    const q = cat ? `?category=${cat}` : "";
    api.get(`/assets${q}`).then(setRows);
  };
  useEffect(load, [cat]);
  useEffect(() => { api.get("/team/users").then(setUsers).catch(() => {}); }, []);

  const create = async () => {
    if (!form.name.trim()) return;
    const _r = await api.post("/assets", form);
    setShowNew(false); setForm({ name: "", category: "vehicle", asset_tag: "" });
    load();
  };
  const openDetail = async (a) => {
    setDetail(a);
    const m = await api.get(`/assets/${a.id}/maintenance`).catch(() => []);
    setMaintList(m);
  };
  const assign = async (uid) => {
    await api.post(`/assets/${detail.id}/assign`, { user_id: uid });
    load();
    const fresh = await api.get(`/assets/${detail.id}`);
    setDetail(fresh);
  };
  const logMaint = async () => {
    await api.post(`/assets/${detail.id}/maintenance`, maintForm);
    setMaintForm({ kind: "service", cost: 0, notes: "" });
    const m = await api.get(`/assets/${detail.id}/maintenance`).catch(() => []);
    setMaintList(m);
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-assets-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Wrench size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              Assets & Equipment
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Track vehicles, pumps, and tools. Assign to techs and schedule maintenance.
          </p>
        </div>
        <button onClick={() => setShowNew(true)}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-bold rounded-xl"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="admin-assets-new-btn">
          <Plus size={14}/> Add Asset
        </button>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        {CATEGORIES.map((c) => (
          <button key={c.key} onClick={() => setCat(c.key)}
                  className="px-3 py-1.5 text-sm font-semibold rounded-full flex items-center gap-1.5 transition"
                  style={{
                    backgroundColor: cat === c.key ? colors.brand : colors.surface,
                    color: cat === c.key ? "#fff" : colors.onSurface,
                    border: `1px solid ${cat === c.key ? colors.brand : colors.border}`,
                  }}
                  data-testid={`assets-cat-${c.key || "all"}`}>
            <c.icon size={13}/> {c.label}
          </button>
        ))}
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="admin-assets-table">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: colors.background, color: colors.muted }}>
              {["Name", "Category", "Tag", "Assigned", "Status", ""].map((h) => (
                <th key={h} className="p-3 text-left text-xs font-semibold uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={6} className="p-8 text-center" style={{ color: colors.muted }}>
                No assets yet — click Add Asset to create one.
              </td></tr>
            ) : rows.map((a) => {
              const uName = (users.find((u) => u.id === a.assigned_to_user_id) || {}).name || "—";
              const sc = STATUS_COLORS[a.status || "active"];
              return (
                <tr key={a.id} onClick={() => openDetail(a)}
                    className="cursor-pointer hover:brightness-95"
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`asset-row-${a.id}`}>
                  <td className="p-3 font-semibold" style={{ color: colors.onSurface }}>{a.name}</td>
                  <td className="p-3" style={{ color: colors.muted }}>{a.category}</td>
                  <td className="p-3" style={{ color: colors.muted }}>{a.asset_tag || "—"}</td>
                  <td className="p-3" style={{ color: colors.muted }}>{uName}</td>
                  <td className="p-3">
                    <span className="text-xs font-bold uppercase px-2 py-0.5 rounded"
                          style={{ backgroundColor: sc.bg, color: sc.fg }}>
                      {a.status || "active"}
                    </span>
                  </td>
                  <td className="p-3 text-right text-xs" style={{ color: colors.muted }}>
                    {a.next_maintenance_due_at
                      ? `Due ${(a.next_maintenance_due_at || "").slice(0, 10)}` : ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* New asset modal */}
      {showNew && (
        <Modal onClose={() => setShowNew(false)} title="Add Asset">
          <input placeholder="Name (e.g., Truck #3)" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })}
                 className="w-full p-2.5 rounded-lg text-sm mb-2"
                 style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="asset-new-name" />
          <select value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  className="w-full p-2.5 rounded-lg text-sm mb-2"
                  style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="asset-new-cat">
            <option value="vehicle">Vehicle</option>
            <option value="equipment">Equipment</option>
            <option value="tool">Tool</option>
            <option value="other">Other</option>
          </select>
          <input placeholder="Asset tag (optional)"
                 value={form.asset_tag}
                 onChange={(e) => setForm({ ...form, asset_tag: e.target.value })}
                 className="w-full p-2.5 rounded-lg text-sm mb-4"
                 style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="asset-new-tag"/>
          <button onClick={create}
                  className="w-full py-2 rounded-lg text-sm font-bold"
                  style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                  data-testid="asset-new-submit">
            Create
          </button>
        </Modal>
      )}

      {/* Detail drawer */}
      {detail && (
        <Modal onClose={() => setDetail(null)} title={detail.name} wide>
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>
                Assign to
              </div>
              <select value={detail.assigned_to_user_id || ""}
                      onChange={(e) => assign(e.target.value || null)}
                      className="w-full p-2 text-sm rounded-lg mb-4"
                      style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="asset-detail-assign">
                <option value="">— Unassigned —</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{u.name || u.email}</option>
                ))}
              </select>
              <div className="text-xs" style={{ color: colors.muted }}>
                Status: <b>{detail.status || "active"}</b><br />
                Category: <b>{detail.category}</b><br />
                {detail.serial_number ? <>Serial: <b>{detail.serial_number}</b><br /></> : null}
                {detail.notes ? <>Notes: {detail.notes}<br /></> : null}
              </div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>
                Log maintenance
              </div>
              <select value={maintForm.kind}
                      onChange={(e) => setMaintForm({ ...maintForm, kind: e.target.value })}
                      className="w-full p-2 text-sm rounded-lg mb-2"
                      style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="maint-kind">
                <option value="service">Service</option>
                <option value="repair">Repair</option>
                <option value="inspection">Inspection</option>
              </select>
              <input type="number" placeholder="Cost ($)"
                     value={maintForm.cost}
                     onChange={(e) => setMaintForm({ ...maintForm, cost: Number(e.target.value) })}
                     className="w-full p-2 text-sm rounded-lg mb-2"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid="maint-cost"/>
              <input placeholder="Notes"
                     value={maintForm.notes}
                     onChange={(e) => setMaintForm({ ...maintForm, notes: e.target.value })}
                     className="w-full p-2 text-sm rounded-lg mb-2"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid="maint-notes"/>
              <button onClick={logMaint}
                      className="w-full py-2 text-sm font-bold rounded-lg"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="maint-submit">
                Log entry
              </button>
              <div className="text-xs font-bold uppercase mt-6 mb-2" style={{ color: colors.muted }}>
                History
              </div>
              <div className="max-h-48 overflow-auto space-y-1" data-testid="maint-history">
                {maintList.length === 0 ? (
                  <div className="text-xs" style={{ color: colors.muted }}>No maintenance logged.</div>
                ) : maintList.map((m) => (
                  <div key={m.id} className="text-xs p-2 rounded"
                       style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}` }}>
                    <b>{m.kind}</b> · ${(m.cost || 0).toFixed(2)} ·{" "}
                    {(m.performed_at || "").slice(0, 10)}
                    {m.notes ? <div style={{ color: colors.muted }}>{m.notes}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ children, title, onClose, wide }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
         style={{ background: "rgba(0,0,0,0.5)" }} onClick={onClose}>
      <div className={`${wide ? "max-w-2xl" : "max-w-sm"} w-full p-6 rounded-2xl`}
           onClick={(e) => e.stopPropagation()}
           style={{ backgroundColor: colors.surface }}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>{title}</h3>
          <button onClick={onClose} className="p-1 rounded"
                  style={{ color: colors.muted }}><X size={18}/></button>
        </div>
        {children}
      </div>
    </div>
  );
}
