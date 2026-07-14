import React, { useEffect, useMemo, useState, useCallback } from "react";
import { api } from "@/api";
import { colors, brandGradientCss, money } from "@/theme";
import {
  Clock, CheckCircle2, XCircle, Download, MapPin, DollarSign, TrendingUp,
  AlertTriangle, User as UserIcon, Filter, RefreshCw, Calendar,
} from "lucide-react";

/* Shared UI helpers */
const Card = ({ children, className = "", testId }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);

const BtnPrimary = ({ children, testId, ...rest }) => (
  <button className="px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
          style={{ background: brandGradientCss }} data-testid={testId} {...rest}>{children}</button>
);

const BtnGhost = ({ children, testId, ...rest }) => (
  <button className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                   border: `1px solid ${colors.border}` }}
          data-testid={testId} {...rest}>{children}</button>
);

const Chip = ({ children, tone = "muted", testId }) => {
  const map = {
    ok:      { bg: "#DCFCE7", fg: colors.success },
    warn:    { bg: "#FEF3C7", fg: "#92400E" },
    danger:  { bg: "#FEE2E2", fg: colors.error },
    info:    { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
    muted:   { bg: colors.surfaceSecondary, fg: colors.muted },
  };
  const c = map[tone] || map.muted;
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
          style={{ backgroundColor: c.bg, color: c.fg }} data-testid={testId}>
      {children}
    </span>
  );
};

const Section = ({ title, subtitle, right, children }) => (
  <div className="p-4 md:p-8 max-w-7xl mx-auto">
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div>
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
        {subtitle && <p className="text-sm mt-1" style={{ color: colors.muted }}>{subtitle}</p>}
      </div>
      {right}
    </div>
    {children}
  </div>
);

function useDateRange(defaultDays = 14) {
  const iso = (d) => new Date(d).toISOString().slice(0, 10);
  const to = iso(new Date());
  const from = iso(Date.now() - defaultDays * 86400_000);
  const [range, setRange] = useState({ from, to });
  return [range, setRange];
}

/* ────────────────────────────────────────────────────────────────────
   /workforce/timesheets
   ──────────────────────────────────────────────────────────────────── */
export function TimesheetsPage() {
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [range, setRange] = useDateRange(14);
  const [userId, setUserId] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const qs = new URLSearchParams({ from: range.from, to: range.to });
      if (userId) qs.set("user_id", userId);
      if (status) qs.set("status", status);
      setRows(await api.get(`/workforce/timesheets?${qs}`));
    } finally { setBusy(false); }
  }, [range.from, range.to, userId, status]);

  useEffect(() => {
    api.get("/team").then((t) => setUsers(t || [])).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (id, kind) => {
    try {
      await api.post(`/workforce/timesheets/${id}/${kind}`,
                     kind === "reject" ? { reason: "" } : undefined);
      load();
    } catch (e) { alert(e.message); }
  };

  const dl = async () => {
    const qs = new URLSearchParams({ from: range.from, to: range.to });
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/workforce/export/timesheets.csv?${qs}`;
    const token = localStorage.getItem("token") || "";
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `timesheets_${range.from}_${range.to}.csv`;
    a.click();
  };

  const totalHours = useMemo(
    () => rows.reduce((s, r) => s + (r.hours || 0), 0).toFixed(2),
    [rows]
  );
  const totalOT = useMemo(
    () => rows.reduce((s, r) => s + (r.overtime_hours || 0), 0).toFixed(2),
    [rows]
  );

  return (
    <Section
      title="Timesheets"
      subtitle="Review, approve, and export crew time entries. Overtime is auto-computed daily and weekly."
      right={
        <div className="flex gap-2 flex-wrap">
          <BtnGhost onClick={load} testId="ts-refresh"><RefreshCw size={14}/> Refresh</BtnGhost>
          <BtnPrimary onClick={dl} testId="ts-export-csv"><Download size={14}/> CSV</BtnPrimary>
        </div>
      }
    >
      <Card className="p-4 mb-4" testId="ts-filters">
        <div className="flex items-center gap-3 flex-wrap">
          <Filter size={14} style={{ color: colors.muted }}/>
          <input type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })}
                 className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="ts-from"/>
          <span style={{ color: colors.muted }}>→</span>
          <input type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })}
                 className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="ts-to"/>
          <select value={userId} onChange={(e) => setUserId(e.target.value)}
                  className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="ts-user">
            <option value="">All techs</option>
            {users.map((u) => (
              <option key={u.id} value={u.user_id || u.id}>{u.name || u.email}</option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
                  className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="ts-status">
            <option value="">Any status</option>
            <option value="open">Open</option>
            <option value="submitted">Submitted</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <div className="ml-auto text-xs" style={{ color: colors.muted }}>
            <span className="font-bold" style={{ color: colors.onSurface }}>{totalHours}h</span> total · <span className="font-bold" style={{ color: colors.error }}>{totalOT}h</span> overtime
          </div>
        </div>
      </Card>

      <Card className="overflow-x-auto" testId="ts-table-card">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Date</th>
              <th className="text-left p-3 font-semibold">Tech</th>
              <th className="text-left p-3 font-semibold">Job</th>
              <th className="text-right p-3 font-semibold">Hours</th>
              <th className="text-right p-3 font-semibold">OT</th>
              <th className="text-right p-3 font-semibold">Miles</th>
              <th className="text-left p-3 font-semibold">Status</th>
              <th className="text-right p-3 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`ts-row-${r.id}`}>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.day}</td>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.user_name || r.user_id}</td>
                <td className="p-3" style={{ color: colors.onSurfaceSecondary }}>
                  {r.job_title || r.job_id}
                  {r.out_of_geofence ? (
                    <Chip tone="danger" testId={`ts-oog-${r.id}`}>Out of geofence</Chip>
                  ) : null}
                </td>
                <td className="p-3 text-right font-semibold" style={{ color: colors.onSurface }}>{(r.hours || 0).toFixed(2)}</td>
                <td className="p-3 text-right font-semibold"
                    style={{ color: r.overtime_hours ? colors.error : colors.muted }}>
                  {(r.overtime_hours || 0).toFixed(2)}
                </td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{(r.mileage_miles || 0).toFixed(2)}</td>
                <td className="p-3">
                  <Chip tone={r.status === "approved" ? "ok"
                              : r.status === "rejected" ? "danger"
                              : r.status === "submitted" ? "info" : "warn"}
                        testId={`ts-status-${r.id}`}>
                    {r.status}
                  </Chip>
                </td>
                <td className="p-3 text-right">
                  {r.status === "submitted" ? (
                    <div className="flex gap-1 justify-end">
                      <button onClick={() => act(r.id, "approve")}
                              className="text-xs px-2 py-1 rounded-md font-semibold text-white"
                              style={{ backgroundColor: colors.success }}
                              data-testid={`ts-approve-${r.id}`}>
                        <CheckCircle2 size={12} className="inline"/> Approve
                      </button>
                      <button onClick={() => act(r.id, "reject")}
                              className="text-xs px-2 py-1 rounded-md font-semibold"
                              style={{ backgroundColor: colors.surfaceSecondary, color: colors.error,
                                       border: `1px solid ${colors.border}` }}
                              data-testid={`ts-reject-${r.id}`}>
                        <XCircle size={12} className="inline"/> Reject
                      </button>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
            {rows.length === 0 && !busy && (
              <tr><td colSpan={8} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="ts-empty">
                No timesheets in this range.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </Section>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /workforce/crew-map — Google Maps live crew view
   ──────────────────────────────────────────────────────────────────── */
export function CrewMapPage() {
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const mapRef = React.useRef(null);
  const gmapRef = React.useRef(null);
  const markersRef = React.useRef({});

  const refresh = useCallback(async () => {
    try { setRows(await api.get("/workforce/crew-map")); } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  // Google Maps script load
  useEffect(() => {
    if (window.google?.maps) { setLoaded(true); return; }
    const key = process.env.REACT_APP_GOOGLE_API_KEY;
    if (!key) { setLoaded(true); return; }
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${key}`;
    s.async = true; s.onload = () => setLoaded(true);
    document.head.appendChild(s);
  }, []);

  // Init map
  useEffect(() => {
    if (!loaded || !window.google?.maps || gmapRef.current || !mapRef.current) return;
    gmapRef.current = new window.google.maps.Map(mapRef.current, {
      zoom: 11,
      center: rows[0]?.last_ping
        ? { lat: rows[0].last_ping.lat, lng: rows[0].last_ping.lng }
        : { lat: 33.7005, lng: -112.2280 },  // Vistancia, AZ default
      streetViewControl: false,
      mapTypeControl: false,
    });
  }, [loaded, rows]);

  // Sync markers
  useEffect(() => {
    if (!gmapRef.current || !window.google?.maps) return;
    const seen = new Set();
    rows.forEach((r) => {
      const pos = { lat: r.last_ping.lat, lng: r.last_ping.lng };
      seen.add(r.user.id);
      if (markersRef.current[r.user.id]) {
        markersRef.current[r.user.id].setPosition(pos);
      } else {
        const m = new window.google.maps.Marker({
          position: pos, map: gmapRef.current, title: r.user.name || r.user.email,
          label: { text: (r.user.name || "T")[0], color: "#fff", fontWeight: "700" },
          icon: {
            path: window.google.maps.SymbolPath.CIRCLE,
            scale: 12,
            fillColor: r.clocked_in ? colors.success : colors.muted,
            fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2,
          },
        });
        m.addListener("click", () => setSelected(r));
        markersRef.current[r.user.id] = m;
      }
    });
    // Remove stale
    Object.keys(markersRef.current).forEach((uid) => {
      if (!seen.has(uid)) { markersRef.current[uid].setMap(null); delete markersRef.current[uid]; }
    });
  }, [rows]);

  return (
    <Section
      title="Crew Map"
      subtitle="Live tech locations, refreshed every 30 seconds."
      right={<BtnGhost onClick={refresh} testId="crewmap-refresh"><RefreshCw size={14}/> Refresh</BtnGhost>}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <Card className="overflow-hidden" testId="crewmap-canvas-card">
            <div ref={mapRef} style={{ width: "100%", height: 520 }} data-testid="crewmap-canvas"/>
          </Card>
        </div>
        <div className="space-y-2" data-testid="crewmap-side">
          {rows.map((r) => (
            <Card key={r.user.id}
                  className="p-3 cursor-pointer"
                  testId={`crewmap-row-${r.user.id}`}
                  onClick={() => setSelected(r)}>
              <div className="flex items-center gap-2 mb-1">
                <UserIcon size={16} style={{ color: colors.brand }}/>
                <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>
                  {r.user.name || r.user.email}
                </div>
                <div className="ml-auto">
                  <Chip tone={r.clocked_in ? "ok" : "muted"}>{r.clocked_in ? "On shift" : "Off"}</Chip>
                </div>
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {r.current_entry?.job_title || "—"}
              </div>
              <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
                {r.hours_today.toFixed(2)}h today · last ping {new Date(r.last_ping.ts).toLocaleTimeString()}
              </div>
            </Card>
          ))}
          {rows.length === 0 && (
            <Card className="p-4 text-sm" testId="crewmap-empty">
              <span style={{ color: colors.muted }}>
                No tech pings in the last 24h — pings begin flowing when a tech clocks in on mobile.
              </span>
            </Card>
          )}
        </div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-40 flex items-end md:items-center justify-center p-2"
             style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
             onClick={() => setSelected(null)}
             data-testid="crewmap-modal">
          <div className="w-full max-w-md rounded-2xl p-5"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               onClick={(e) => e.stopPropagation()}>
            <div className="text-base font-bold mb-2" style={{ color: colors.onSurface }}>
              {selected.user.name || selected.user.email}
            </div>
            <div className="text-sm" style={{ color: colors.onSurface }}>
              Current job: <span className="font-semibold">{selected.current_entry?.job_title || "—"}</span>
            </div>
            <div className="text-sm mt-1" style={{ color: colors.onSurface }}>
              Hours today: <span className="font-semibold">{selected.hours_today.toFixed(2)}h</span>
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Last ping: {new Date(selected.last_ping.ts).toLocaleString()} · battery {selected.last_ping.battery ?? "—"}%
            </div>
            <div className="mt-3 flex justify-end">
              <BtnGhost onClick={() => setSelected(null)} testId="crewmap-modal-close">Close</BtnGhost>
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /workforce/job-costing
   ──────────────────────────────────────────────────────────────────── */
export function JobCostingPage() {
  const [jobs, setJobs] = useState([]);
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const js = await api.get("/jobs");
      // Only completed / active jobs for costing view (skip trivial pending).
      const filtered = (js || []).filter((j) => ["completed", "active", "in_progress"].includes(j.status));
      setJobs(filtered.slice(0, 100));
      const costs = await Promise.all(
        filtered.slice(0, 100).map((j) =>
          api.get(`/workforce/job-cost/${j.id}`).catch(() => null))
      );
      setRows(costs.filter(Boolean));
    } finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <Section
      title="Job Costing"
      subtitle="Precise P&L per job — labor + materials + mileage vs. revenue."
      right={<BtnGhost onClick={load} testId="jc-refresh"><RefreshCw size={14}/> Refresh</BtnGhost>}
    >
      <Card className="overflow-x-auto" testId="jc-table-card">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Job</th>
              <th className="text-right p-3 font-semibold">Revenue</th>
              <th className="text-right p-3 font-semibold">Labor</th>
              <th className="text-right p-3 font-semibold">Mat.</th>
              <th className="text-right p-3 font-semibold">Mileage</th>
              <th className="text-right p-3 font-semibold">Total Cost</th>
              <th className="text-right p-3 font-semibold">Margin</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.job_id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  className="cursor-pointer hover:brightness-95"
                  onClick={() => setSelected(r)}
                  data-testid={`jc-row-${r.job_id}`}>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.job_title}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurface }}>{money(r.revenue)}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{money(r.labor_cost)}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{money(r.materials_cost)}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{money(r.mileage_cost)}</td>
                <td className="p-3 text-right font-semibold" style={{ color: colors.onSurface }}>{money(r.total_cost)}</td>
                <td className="p-3 text-right font-bold"
                    style={{ color: r.gross_margin < 0 ? colors.error : colors.success }}>
                  {money(r.gross_margin)}
                  {r.gross_margin_pct !== null && (
                    <div className="text-[10px] font-normal" style={{ color: colors.muted }}>
                      {r.gross_margin_pct}%
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && !busy && (
              <tr><td colSpan={7} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="jc-empty">
                No costed jobs yet — clock into a job on mobile to see it here.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>

      {selected && (
        <div className="fixed inset-0 z-40 flex items-end md:items-center justify-center p-2"
             style={{ backgroundColor: "rgba(0,0,0,0.55)" }} onClick={() => setSelected(null)}
             data-testid="jc-drilldown">
          <div className="w-full max-w-md rounded-2xl p-5"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               onClick={(e) => e.stopPropagation()}>
            <div className="text-base font-bold mb-4" style={{ color: colors.onSurface }}>{selected.job_title}</div>
            <div className="space-y-2 text-sm">
              {[
                ["Revenue", money(selected.revenue), colors.brand],
                ["Labor cost", `${money(selected.labor_cost)} · ${selected.labor_hours}h`],
                ["Materials", money(selected.materials_cost)],
                ["Mileage", `${money(selected.mileage_cost)} · ${selected.mileage_miles}mi × $${selected.mileage_rate_usd}/mi`],
                ["Total cost", money(selected.total_cost)],
                ["Gross margin", `${money(selected.gross_margin)} (${selected.gross_margin_pct ?? "—"}%)`,
                  selected.gross_margin < 0 ? colors.error : colors.success],
              ].map(([label, val, tone]) => (
                <div key={label} className="flex justify-between">
                  <span style={{ color: colors.muted }}>{label}</span>
                  <span className="font-semibold" style={{ color: tone || colors.onSurface }}>{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /workforce/mileage
   ──────────────────────────────────────────────────────────────────── */
export function MileagePage() {
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState("");
  const [range, setRange] = useDateRange(30);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/team").then((t) => setUsers(t || [])).catch(() => {});
  }, []);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const qs = new URLSearchParams({ from: range.from, to: range.to });
      if (userId) qs.set("user_id", userId);
      setRows(await api.get(`/workforce/mileage?${qs}`));
    } finally { setBusy(false); }
  }, [range.from, range.to, userId]);
  useEffect(() => { load(); }, [load]);

  const total = rows.reduce((s, r) => s + (r.miles || 0), 0).toFixed(2);

  return (
    <Section
      title="Mileage"
      subtitle="Per-tech mileage, computed from GPS pings during active shifts."
      right={<BtnGhost onClick={load} testId="mile-refresh"><RefreshCw size={14}/> Refresh</BtnGhost>}
    >
      <Card className="p-4 mb-4" testId="mile-filters">
        <div className="flex items-center gap-3 flex-wrap">
          <Calendar size={14} style={{ color: colors.muted }}/>
          <input type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })}
                 className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="mile-from"/>
          <span style={{ color: colors.muted }}>→</span>
          <input type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })}
                 className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="mile-to"/>
          <select value={userId} onChange={(e) => setUserId(e.target.value)}
                  className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="mile-user">
            <option value="">All techs</option>
            {users.map((u) => (
              <option key={u.id} value={u.user_id || u.id}>{u.name || u.email}</option>
            ))}
          </select>
          <div className="ml-auto text-xs" style={{ color: colors.muted }}>
            <span className="font-bold" style={{ color: colors.onSurface }}>{total}mi</span> total
          </div>
        </div>
      </Card>

      <Card className="overflow-x-auto" testId="mile-table-card">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Day</th>
              <th className="text-left p-3 font-semibold">Tech</th>
              <th className="text-right p-3 font-semibold">Entries</th>
              <th className="text-right p-3 font-semibold">Miles</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`mile-row-${r.user_id}-${r.day}`}>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.day}</td>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.user_name || r.user_id}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{r.entries}</td>
                <td className="p-3 text-right font-semibold" style={{ color: colors.onSurface }}>{(r.miles || 0).toFixed(2)}</td>
              </tr>
            ))}
            {rows.length === 0 && !busy && (
              <tr><td colSpan={4} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="mile-empty">
                No mileage recorded in this range.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </Section>
  );
}
