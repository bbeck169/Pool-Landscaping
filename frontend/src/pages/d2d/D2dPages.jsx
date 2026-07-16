import React, { useEffect, useMemo, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import MapView from "@/components/MapView";

/* ═══ Phase 10 — D2D Sales module (admin-focused, single dense file) ═══ */

const DISPOS = [
  { k: "not_home",       label: "Not home",        color: "yellow" },
  { k: "not_interested", label: "Not interested",  color: "red" },
  { k: "callback",       label: "Callback later",  color: "orange" },
  { k: "interested",     label: "Interested",      color: "green" },
  { k: "sold",           label: "Sold / Booked",   color: "purple" },
];
const DISPO_LABEL = Object.fromEntries(DISPOS.map((d) => [d.k, d.label]));
const DISPO_COLOR = Object.fromEntries(DISPOS.map((d) => [d.k, d.color]));

const VISTANCIA = [33.7897, -112.3226];

/* ─── shared UI atoms ───────────────────────────────────────────────── */
function Card({ children, className = "", testid }) {
  return (
    <div
      className={`rounded-2xl bg-white p-5 ${className}`}
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      {children}
    </div>
  );
}

function Tile({ label, value, testid }) {
  return (
    <div className="rounded-2xl p-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid={testid}>
      <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>{label}</div>
      <div className="text-3xl font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
    </div>
  );
}

function DispoChip({ k }) {
  const bg = {
    not_home: "#FEF9C3", not_interested: "#FEE2E2", callback: "#FFEDD5",
    interested: "#DCFCE7", sold: "#EDE9FE",
  }[k] || colors.surfaceSecondary;
  const fg = {
    not_home: "#854D0E", not_interested: "#991B1B", callback: "#9A3412",
    interested: "#166534", sold: "#5B21B6",
  }[k] || colors.onSurfaceSecondary;
  return (
    <span
      className="inline-flex text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ backgroundColor: bg, color: fg }}
      data-testid={`d2d-dispo-${k}`}
    >
      {DISPO_LABEL[k] || k}
    </span>
  );
}

function Toast({ text }) {
  if (!text) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg" style={{ backgroundColor: colors.onSurface }} data-testid="d2d-toast">
      {text}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   1. Dashboard
   ═══════════════════════════════════════════════════════════════════ */
export function D2dDashboard() {
  const [rows, setRows] = useState(null);
  const [board, setBoard] = useState(null);
  useEffect(() => {
    api.get("/d2d/knocks").then((r) => setRows(Array.isArray(r) ? r : []));
    api.get("/d2d/leaderboard").then((r) => setBoard(Array.isArray(r) ? r : []));
  }, []);
  const todayIso = new Date().toISOString().slice(0, 10);
  const today = (rows || []).filter((k) => (k.created_at || "").startsWith(todayIso));
  const leads = today.filter((k) => k.disposition === "interested" || k.disposition === "sold");
  const booked = today.filter((k) => k.disposition === "sold");
  const activeCanvassers = new Set((rows || []).filter((k) => (k.created_at || "").startsWith(todayIso)).map((k) => k.tech_id)).size;
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6" data-testid="d2d-dashboard">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>D2D Sales</h1>
          <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Canvass · Log knocks · Convert doors into revenue</p>
        </div>
        <Link
          to="/d2d/map"
          className="px-4 py-2 rounded-xl text-sm font-semibold"
          style={{ backgroundColor: colors.brand, color: "#fff" }}
          data-testid="d2d-start-canvassing"
        >Start canvassing →</Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile label="Knocks today" value={today.length} testid="d2d-tile-knocks-today" />
        <Tile label="Leads today" value={leads.length} testid="d2d-tile-leads-today" />
        <Tile label="Booked today" value={booked.length} testid="d2d-tile-booked-today" />
        <Tile label="Active canvassers" value={activeCanvassers} testid="d2d-tile-active-canvassers" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card testid="d2d-leaderboard-preview">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-bold">Leaderboard</h2>
            <Link to="/d2d/leaderboard" className="text-xs font-semibold" style={{ color: colors.brand }}>View full →</Link>
          </div>
          {board === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
          {board && board.length === 0 && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No knocks yet.</div>}
          {board && board.slice(0, 5).map((r) => (
            <div key={r.tech_id} className="flex items-center justify-between py-2 border-b last:border-0" style={{ borderColor: colors.border }}>
              <div className="flex items-center gap-3">
                <span className="w-6 text-center font-bold" style={{ color: r.rank === 1 ? "#CA8A04" : colors.onSurfaceSecondary }}>#{r.rank}</span>
                <div>
                  <div className="font-semibold text-sm">{r.tech_name}{r.is_me && <span className="ml-2 text-xs" style={{ color: colors.brand }}>(you)</span>}</div>
                  <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{r.knocks} knocks · {r.leads} leads · {r.conversion_rate}% conv.</div>
                </div>
              </div>
              <div className="text-sm font-bold" style={{ color: colors.brandSecondary }}>{r.sold} sold</div>
            </div>
          ))}
        </Card>

        <Card testid="d2d-recent-knocks">
          <h2 className="text-lg font-bold mb-3">Recent knocks</h2>
          {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
          {rows && rows.length === 0 && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No knocks yet — hit the map to start.</div>}
          {rows && rows.slice(0, 12).map((k) => (
            <div key={k.id} className="py-2 border-b last:border-0 flex items-center gap-3" style={{ borderColor: colors.border }}>
              <DispoChip k={k.disposition} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate">{k.address || "—"}</div>
                <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{k.tech_name} · {(k.created_at || "").slice(0, 10)}{k.notes ? ` · ${k.notes.slice(0, 40)}` : ""}</div>
              </div>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   2. Canvassing map
   ═══════════════════════════════════════════════════════════════════ */
export function D2dMap() {
  const [zip, setZip] = useState("85383");
  const [days, setDays] = useState(60);
  const [customers, setCustomers] = useState([]);
  const [sold, setSold] = useState({ properties: [], error: null, loading: false });
  const [knocks, setKnocks] = useState([]);
  const [center, setCenter] = useState(VISTANCIA);
  const [drawer, setDrawer] = useState(null);
  const [logModal, setLogModal] = useState(null);
  const [toast, setToast] = useState("");
  const [myOnly, setMyOnly] = useState(false);

  const load = () => api.get("/d2d/knocks").then((r) => setKnocks(Array.isArray(r) ? r : []));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    api.get("/customers").then((r) => setCustomers(Array.isArray(r) ? r : (r?.rows || [])));
  }, []);
  useEffect(() => {
    setSold({ properties: [], error: null, loading: true });
    api.get(`/d2d/sold-leads?zip=${encodeURIComponent(zip)}&days=${days}`)
      .then((r) => setSold({ properties: r?.properties || [], error: null, loading: false }))
      .catch((e) => setSold({ properties: [], error: e.message || "Zillow data unavailable", loading: false }));
  }, [zip, days]);

  const layers = useMemo(() => {
    const customerPoints = (customers || [])
      .filter((c) => Number.isFinite(c.lat) && Number.isFinite(c.lng))
      .map((c) => ({
        id: c.id, lat: c.lat, lng: c.lng, color: "green",
        label: c.name, subtitle: `Existing customer · ${c.address || ""}`,
      }));
    const soldPoints = (sold.properties || [])
      .filter((p) => !p.skipped && !p.logged)
      .map((p) => ({
        id: p.zpid, lat: p.lat, lng: p.lng, color: "blue",
        label: p.address, subtitle: `Sold ${p.price ? `$${p.price.toLocaleString()}` : ""} · ${p.beds || "?"}bd/${p.baths || "?"}ba`,
        onClick: () => setDrawer({ kind: "sold", prop: p }),
      }));
    const filteredKnocks = myOnly ? knocks.filter((k) => k.mine !== false) : knocks;
    const knockPoints = (filteredKnocks || [])
      .filter((k) => Number.isFinite(k.lat) && Number.isFinite(k.lng))
      .map((k) => ({
        id: k.id, lat: k.lat, lng: k.lng, color: DISPO_COLOR[k.disposition] || "gray",
        label: k.address || DISPO_LABEL[k.disposition], subtitle: `${k.tech_name} · ${DISPO_LABEL[k.disposition]}${k.notes ? " · " + k.notes.slice(0, 40) : ""}`,
      }));
    const routeSorted = [...(filteredKnocks || [])]
      .filter((k) => Number.isFinite(k.lat) && Number.isFinite(k.lng))
      .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
    const polyline = routeSorted.map((k) => [k.lat, k.lng]);
    return [
      { key: "customers", points: customerPoints },
      { key: "sold", points: soldPoints },
      { key: "knocks", points: knockPoints, polyline, polylineColor: "#0284C7", dashed: true },
    ];
  }, [customers, sold, knocks, myOnly]);

  const geolocate = () => {
    if (!navigator.geolocation) return setToast("Geolocation unsupported");
    navigator.geolocation.getCurrentPosition(
      (pos) => setCenter([pos.coords.latitude, pos.coords.longitude]),
      () => setToast("Could not fetch location"),
    );
  };

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="d2d-map-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>Canvassing map</h1>
        <div className="flex items-center gap-2 ml-auto">
          <input value={zip} onChange={(e) => setZip(e.target.value)} placeholder="ZIP"
                 className="px-3 py-1.5 rounded-lg text-sm w-24" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="d2d-map-zip" />
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  className="px-3 py-1.5 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="d2d-map-days">
            {[7, 30, 60, 90, 180].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <button onClick={geolocate} className="px-3 py-1.5 rounded-lg text-sm font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="d2d-map-geolocate">📍 Geolocate</button>
          <button onClick={() => setMyOnly((v) => !v)} className="px-3 py-1.5 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: myOnly ? colors.brandTertiary : colors.surfaceSecondary, color: myOnly ? colors.onBrandTertiary : colors.onSurfaceSecondary }}
                  data-testid="d2d-map-my-toggle">
            {myOnly ? "My route" : "All team"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 text-xs" style={{ color: colors.onSurfaceSecondary }}>
        <span>🟢 Customer</span><span>🔵 Recently sold</span>
        <span>🟡 Not home</span><span>🔴 Not interested</span>
        <span>🟠 Callback</span><span>🟣 Sold/Booked</span>
      </div>

      {sold.error && (
        <div className="rounded-xl px-4 py-3 text-sm" style={{ backgroundColor: "#FEF3C7", color: "#78350F" }} data-testid="d2d-zillow-warning">
          Zillow data unavailable — {sold.error}
        </div>
      )}

      <MapView center={center} zoom={13} height={620} layers={layers} testid="d2d-map" />

      {drawer && (
        <div className="fixed top-0 right-0 h-full w-[420px] bg-white shadow-2xl z-40 p-6 overflow-y-auto" data-testid="d2d-drawer">
          <button onClick={() => setDrawer(null)} className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>← Close</button>
          <div className="text-lg font-bold">{drawer.prop.address}</div>
          <div className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
            Sold: ${drawer.prop.price?.toLocaleString?.() || "—"} · {drawer.prop.beds}bd/{drawer.prop.baths}ba
            {drawer.prop.sqft ? ` · ${drawer.prop.sqft} sqft` : ""}
          </div>
          {drawer.prop.image && <img alt="home" src={drawer.prop.image} className="mt-3 rounded-xl w-full" />}
          <div className="flex gap-2 mt-4">
            <button onClick={() => { setLogModal({ prop: drawer.prop }); setDrawer(null); }}
                    className="flex-1 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="d2d-drawer-log-knock">
              Log knock
            </button>
            <button onClick={async () => {
              try {
                await api.post(`/d2d/skip/${drawer.prop.zpid}`);
                setToast("Skipped");
                setDrawer(null);
                setSold((s) => ({ ...s, properties: s.properties.map((p) => p.zpid === drawer.prop.zpid ? { ...p, skipped: true } : p) }));
              } catch (e) { setToast(e.message); }
            }} className="flex-1 py-2 rounded-xl text-sm font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="d2d-drawer-skip">
              Skip
            </button>
          </div>
        </div>
      )}

      {logModal && (
        <LogKnockModal
          initial={{
            address: logModal.prop?.address || "",
            lat: logModal.prop?.lat, lng: logModal.prop?.lng,
            zpid: logModal.prop?.zpid, sold_price: logModal.prop?.price,
          }}
          onClose={() => setLogModal(null)}
          onSaved={() => { setLogModal(null); setToast("Knock logged"); load(); }}
        />
      )}

      <Toast text={toast} />
    </div>
  );
}

function LogKnockModal({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    address: initial?.address || "", lat: initial?.lat, lng: initial?.lng,
    zpid: initial?.zpid, sold_price: initial?.sold_price,
    disposition: "not_home", name: "", phone: "", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setSaving(true); setErr("");
    try {
      await api.post("/d2d/knocks", form);
      onSaved?.();
    } catch (e) { setErr(e.message); setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(0,0,0,.5)" }} data-testid="d2d-log-modal">
      <div className="bg-white rounded-2xl p-6 max-w-md w-full" style={{ border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold">Log knock</h2>
          <button onClick={onClose} className="text-sm" style={{ color: colors.onSurfaceSecondary }}>✕</button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold">Address</label>
            <input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                   data-testid="d2d-log-address" />
          </div>
          <div>
            <label className="text-xs font-semibold">Outcome</label>
            <select value={form.disposition} onChange={(e) => setForm({ ...form, disposition: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                    data-testid="d2d-log-dispo">
              {DISPOS.map((d) => <option key={d.k} value={d.k}>{d.label}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-semibold">Contact name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                     className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                     data-testid="d2d-log-name" />
            </div>
            <div>
              <label className="text-xs font-semibold">Phone</label>
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })}
                     className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                     data-testid="d2d-log-phone" />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold">Notes</label>
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
                      rows={3} className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                      data-testid="d2d-log-notes" />
          </div>
          {err && <div className="text-xs" style={{ color: colors.error }}>{err}</div>}
          <button onClick={save} disabled={saving}
                  className="w-full py-2 rounded-xl text-sm font-semibold text-white"
                  style={{ backgroundColor: colors.brand, opacity: saving ? 0.6 : 1 }}
                  data-testid="d2d-log-save">
            {saving ? "Saving…" : "Save knock"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   3. Knocks list
   ═══════════════════════════════════════════════════════════════════ */
export function D2dKnocks() {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [dispo, setDispo] = useState("");
  const [toast, setToast] = useState("");
  const load = () => api.get("/d2d/knocks").then((r) => setRows(Array.isArray(r) ? r : []));
  useEffect(() => { load(); }, []);
  const filtered = (rows || []).filter((k) =>
    (!q || (k.address || "").toLowerCase().includes(q.toLowerCase()) || (k.tech_name || "").toLowerCase().includes(q.toLowerCase()))
    && (!dispo || k.disposition === dispo)
  );
  const del = async (k) => {
    if (!(await mustConfirm({ title: "Delete this knock?", tone: "danger" }))) return;
    try { await api.delete(`/d2d/knocks/${k.id}`); setToast("Deleted"); load(); }
    catch (e) { setToast(e.message); }
  };
  const convert = async (k) => {
    try { const cust = await api.post(`/d2d/knocks/${k.id}/convert`); setToast(`Converted → ${cust.name}`); load(); }
    catch (e) { setToast(e.message); }
  };
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4" data-testid="d2d-knocks-page">
      <h1 className="text-2xl font-bold">Knocks</h1>
      <div className="flex flex-wrap gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search address or canvasser…"
               className="px-3 py-2 rounded-lg text-sm flex-1 min-w-[240px]" style={{ border: `1px solid ${colors.border}` }}
               data-testid="d2d-knocks-search" />
        <select value={dispo} onChange={(e) => setDispo(e.target.value)}
                className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                data-testid="d2d-knocks-dispo-filter">
          <option value="">All outcomes</option>
          {DISPOS.map((d) => <option key={d.k} value={d.k}>{d.label}</option>)}
        </select>
      </div>
      <Card testid="d2d-knocks-table">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
              <th className="pb-2">Date</th><th className="pb-2">Address</th><th className="pb-2">Canvasser</th>
              <th className="pb-2">Outcome</th><th className="pb-2">Notes</th><th className="pb-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && <tr><td colSpan={6} className="py-6 text-center" style={{ color: colors.onSurfaceSecondary }}>No knocks match.</td></tr>}
            {filtered.map((k) => (
              <tr key={k.id} className="border-t" style={{ borderColor: colors.border }} data-testid={`d2d-knock-row-${k.id}`}>
                <td className="py-2 pr-2">{(k.created_at || "").slice(0, 10)}</td>
                <td className="py-2 pr-2">{k.address || "—"}</td>
                <td className="py-2 pr-2">{k.tech_name}</td>
                <td className="py-2 pr-2"><DispoChip k={k.disposition} /></td>
                <td className="py-2 pr-2" style={{ color: colors.onSurfaceSecondary }}>{(k.notes || "").slice(0, 60)}</td>
                <td className="py-2 text-right">
                  {["interested", "sold"].includes(k.disposition) && !k.converted && (
                    <button onClick={() => convert(k)} className="text-xs font-semibold mr-3" style={{ color: colors.brandSecondary }} data-testid={`d2d-knock-convert-${k.id}`}>Convert</button>
                  )}
                  <button onClick={() => del(k)} className="text-xs font-semibold" style={{ color: colors.error }} data-testid={`d2d-knock-delete-${k.id}`}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   4. Open leads
   ═══════════════════════════════════════════════════════════════════ */
export function D2dOpenLeads() {
  const [rows, setRows] = useState(null);
  const [toast, setToast] = useState("");
  const load = () => api.get("/d2d/open-leads").then((r) => setRows(Array.isArray(r) ? r : []));
  useEffect(() => { load(); }, []);
  const convert = async (k) => {
    try { const cust = await api.post(`/d2d/knocks/${k.id}/convert`); setToast(`Converted → ${cust.name}`); load(); }
    catch (e) { setToast(e.message); }
  };
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="d2d-open-leads-page">
      <h1 className="text-2xl font-bold">Open leads</h1>
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Interested / booked doors that haven't been converted yet.</p>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No open leads yet — go book some doors!</div>}
        {rows && rows.map((k) => (
          <div key={k.id} className="py-3 border-b last:border-0 flex items-center gap-3" style={{ borderColor: colors.border }} data-testid={`d2d-open-lead-${k.id}`}>
            <DispoChip k={k.disposition} />
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm truncate">{k.name || "—"} · {k.address || "—"}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{k.tech_name} · {(k.notes || "").slice(0, 80)}</div>
            </div>
            <button onClick={() => convert(k)} className="text-xs font-semibold px-3 py-1.5 rounded-lg text-white" style={{ backgroundColor: colors.brand }} data-testid={`d2d-open-convert-${k.id}`}>
              Convert
            </button>
          </div>
        ))}
      </Card>
      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   5. Sold leads (Zillow)
   ═══════════════════════════════════════════════════════════════════ */
export function D2dSoldLeads() {
  const [zip, setZip] = useState("85383");
  const [days, setDays] = useState(60);
  const [data, setData] = useState({ properties: [], count: 0, loading: false, error: null });
  const [toast, setToast] = useState("");
  const load = () => {
    setData((d) => ({ ...d, loading: true, error: null }));
    api.get(`/d2d/sold-leads?zip=${encodeURIComponent(zip)}&days=${days}`)
      .then((r) => setData({ properties: r?.properties || [], count: r?.count || 0, loading: false, error: null }))
      .catch((e) => setData({ properties: [], count: 0, loading: false, error: e.message }));
  };
  useEffect(() => { load(); }, [zip, days]);
  const skip = async (p) => {
    try {
      await api.post(`/d2d/skip/${p.zpid}`);
      setToast("Skipped");
      setData((d) => ({ ...d, properties: d.properties.map((x) => x.zpid === p.zpid ? { ...x, skipped: true } : x) }));
    } catch (e) { setToast(e.message); }
  };
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4" data-testid="d2d-sold-leads-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Recently sold homes</h1>
        <div className="flex items-center gap-2 ml-auto">
          <input value={zip} onChange={(e) => setZip(e.target.value)} placeholder="ZIP"
                 className="px-3 py-1.5 rounded-lg text-sm w-24" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="d2d-sold-zip" />
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  className="px-3 py-1.5 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="d2d-sold-days">
            {[7, 30, 60, 90, 180].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>
      </div>
      {data.error && (
        <div className="rounded-xl px-4 py-3 text-sm" style={{ backgroundColor: "#FEF3C7", color: "#78350F" }} data-testid="d2d-sold-error">
          Zillow data unavailable — {data.error}
        </div>
      )}
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>{data.count} homes sold in the last {days} days.</p>
      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
              <th className="pb-2">Address</th><th className="pb-2">Sold</th><th className="pb-2">Beds/Baths</th>
              <th className="pb-2">Price</th><th className="pb-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.loading && <tr><td colSpan={5} className="py-6 text-center" style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>}
            {!data.loading && data.properties.length === 0 && !data.error && (
              <tr><td colSpan={5} className="py-6 text-center" style={{ color: colors.onSurfaceSecondary }}>No sold homes in this window.</td></tr>
            )}
            {data.properties.map((p) => (
              <tr key={p.zpid} className="border-t" style={{ borderColor: colors.border, opacity: p.skipped ? 0.4 : 1 }} data-testid={`d2d-sold-row-${p.zpid}`}>
                <td className="py-2 pr-2">
                  <div className="font-semibold">{p.address}</div>
                  <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>ZPID {p.zpid}{p.logged ? " · knocked" : ""}</div>
                </td>
                <td className="py-2 pr-2">{p.date_sold ? new Date(p.date_sold).toISOString().slice(0, 10) : "—"}</td>
                <td className="py-2 pr-2">{p.beds || "?"}bd / {p.baths || "?"}ba</td>
                <td className="py-2 pr-2">${(p.price || 0).toLocaleString()}</td>
                <td className="py-2 text-right">
                  {p.detail_url && <a href={p.detail_url} target="_blank" rel="noreferrer" className="text-xs font-semibold mr-3" style={{ color: colors.brand }}>Zillow</a>}
                  {!p.skipped && <button onClick={() => skip(p)} className="text-xs font-semibold" style={{ color: colors.onSurfaceSecondary }} data-testid={`d2d-sold-skip-${p.zpid}`}>Skip</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   6. Team report
   ═══════════════════════════════════════════════════════════════════ */
export function D2dReport() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/d2d/report").then(setData).catch(() => setData({ totals: {}, reps: [] })); }, []);
  const exportCsv = () => {
    if (!data) return;
    const rows = [["Canvasser", "Knocks", "Interested", "Sold", "Leads", "Conversions", "Conversion %"]];
    (data.reps || []).forEach((r) => rows.push([r.tech_name, r.knocks, r.interested, r.sold, r.leads, r.conversions, r.conversion_rate]));
    const csv = rows.map((r) => r.join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a"); a.href = url; a.download = "d2d-report.csv"; a.click();
  };
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4" data-testid="d2d-report-page">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">D2D team report</h1>
        <button onClick={exportCsv} className="px-3 py-1.5 rounded-lg text-sm font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="d2d-report-csv">Export CSV</button>
      </div>
      {data === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Tile label="Knocks" value={data.totals?.knocks || 0} />
            <Tile label="Leads" value={data.totals?.leads || 0} />
            <Tile label="Sold" value={data.totals?.sold || 0} />
            <Tile label="Conversions" value={data.totals?.conversions || 0} />
            <Tile label="Conversion %" value={`${data.totals?.conversion_rate || 0}%`} />
          </div>
          <Card testid="d2d-report-reps">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                  <th className="pb-2">Canvasser</th><th className="pb-2">Knocks</th><th className="pb-2">Interested</th>
                  <th className="pb-2">Sold</th><th className="pb-2">Leads</th><th className="pb-2">Conv.</th><th className="pb-2">Conv. %</th>
                </tr>
              </thead>
              <tbody>
                {(data.reps || []).length === 0 && <tr><td colSpan={7} className="py-6 text-center" style={{ color: colors.onSurfaceSecondary }}>No canvasser activity yet.</td></tr>}
                {(data.reps || []).map((r) => (
                  <tr key={r.tech_id || r.tech_name} className="border-t" style={{ borderColor: colors.border }}>
                    <td className="py-2 pr-2 font-semibold">{r.tech_name}</td>
                    <td className="py-2 pr-2">{r.knocks}</td>
                    <td className="py-2 pr-2">{r.interested}</td>
                    <td className="py-2 pr-2">{r.sold}</td>
                    <td className="py-2 pr-2">{r.leads}</td>
                    <td className="py-2 pr-2">{r.conversions}</td>
                    <td className="py-2 pr-2">{r.conversion_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   7. Leaderboard
   ═══════════════════════════════════════════════════════════════════ */
export function D2dLeaderboard() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/d2d/leaderboard").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  const medal = (rank) => rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `#${rank}`;
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto space-y-4" data-testid="d2d-leaderboard-page">
      <h1 className="text-2xl font-bold">Leaderboard</h1>
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Ranked by sales, then conversions, then knocks.</p>
      {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
      {rows && rows.length === 0 && <Card><div className="text-sm text-center py-4" style={{ color: colors.onSurfaceSecondary }}>No canvasser activity yet.</div></Card>}
      {rows && rows.map((r) => (
        <div key={r.tech_id || r.tech_name} className="rounded-2xl p-4 flex items-center gap-4"
             style={{
               background: r.rank === 1 ? "linear-gradient(135deg,#FEF3C7 0%,#FDE68A 100%)" : colors.surface,
               border: `1px solid ${r.is_me ? colors.brand : colors.border}`,
             }}
             data-testid={`d2d-leaderboard-${r.rank}`}>
          <div className="text-3xl font-bold w-14 text-center">{medal(r.rank)}</div>
          <div className="flex-1">
            <div className="font-bold text-lg">{r.tech_name}{r.is_me && <span className="ml-2 text-xs" style={{ color: colors.brand }}>(you)</span>}</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
              {r.knocks} knocks · {r.leads} leads · {r.conversion_rate}% conversion
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold" style={{ color: colors.brandSecondary }}>{r.sold}</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>sold</div>
          </div>
        </div>
      ))}
    </div>
  );
}
