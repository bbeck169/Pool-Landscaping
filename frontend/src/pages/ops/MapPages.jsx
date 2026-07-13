import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import MapView from "@/components/MapView";

/* Phase 10 companion — Leaflet-backed Dispatch & Schedule maps.
   These retrofit the two views deferred from Phase 5. */

const STATUS_COLOR = {
  scheduled: "blue", in_progress: "orange", on_the_way: "purple",
  completed: "green", canceled: "gray", pending: "yellow",
};

function useCustomerLookup(customers) {
  return useMemo(() => {
    const m = new Map();
    (customers || []).forEach((c) => m.set(c.id, c));
    return m;
  }, [customers]);
}

/* ─── /dispatch/map ─────────────────────────────────────────────── */
export function DispatchMap() {
  const [jobs, setJobs] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get("/jobs"),
      api.get("/customers"),
      api.get("/attendance/live").catch(() => []),
    ]).then(([j, c, a]) => {
      setJobs(Array.isArray(j) ? j : (j?.rows || []));
      setCustomers(Array.isArray(c) ? c : (c?.rows || []));
      setAttendance(Array.isArray(a) ? a : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const custMap = useCustomerLookup(customers);
  const today = new Date().toISOString().slice(0, 10);

  const layers = useMemo(() => {
    const todayJobs = (jobs || []).filter((j) => (j.scheduled_date || "").startsWith(today));
    const jobPoints = todayJobs.map((j) => {
      const cust = custMap.get(j.customer_id) || {};
      const lat = j.lat ?? cust.lat;
      const lng = j.lng ?? cust.lng;
      return {
        id: j.id, lat, lng,
        color: STATUS_COLOR[j.status] || "blue",
        label: j.title || cust.name || "Job",
        subtitle: `${j.customer_name || cust.name || ""} · ${j.status || "scheduled"} · ${j.technician_name || "unassigned"}`,
      };
    });
    const techPoints = (attendance || []).filter((a) => Number.isFinite(a.lat) && Number.isFinite(a.lng)).map((a) => ({
      id: a.id || a.technician_id, lat: a.lat, lng: a.lng, color: "purple",
      label: a.technician_name || a.name, subtitle: `On-site · ${a.note || ""}`,
    }));
    return [
      { key: "jobs-today", points: jobPoints },
      { key: "techs-live", points: techPoints },
    ];
  }, [jobs, custMap, attendance, today]);

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="dispatch-map-page">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">Dispatch map</h1>
        <Link to="/dispatch" className="text-sm font-semibold ml-auto" style={{ color: colors.brand }}>← Board view</Link>
      </div>
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Today's jobs colored by status · live tech pins where clocked in.</p>
      <div className="flex flex-wrap gap-3 text-xs" style={{ color: colors.onSurfaceSecondary }}>
        <span>🔵 Scheduled</span><span>🟠 In progress</span><span>🟢 Completed</span><span>🟡 Pending</span><span>🟣 Technician on-site</span>
      </div>
      {loading && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
      {!loading && layers[0].points.length === 0 && (
        <div className="rounded-xl px-4 py-3 text-sm" style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }} data-testid="dispatch-map-empty">
          No jobs scheduled for today with geocoded addresses. Pins appear once jobs have lat/lng or a customer with a mapped address.
        </div>
      )}
      <MapView height={620} layers={layers} testid="dispatch-map" />
    </div>
  );
}

/* ─── /schedule/map ─────────────────────────────────────────────── */
export function ScheduleMap() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") || new Date().toISOString().slice(0, 10);
  const [jobs, setJobs] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [tech, setTech] = useState(params.get("tech") || "");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.get("/jobs"), api.get("/customers"), api.get("/technicians")])
      .then(([j, c, t]) => {
        setJobs(Array.isArray(j) ? j : (j?.rows || []));
        setCustomers(Array.isArray(c) ? c : (c?.rows || []));
        setTechnicians(Array.isArray(t) ? t : []);
        setLoading(false);
      }).catch(() => setLoading(false));
  }, []);

  const custMap = useCustomerLookup(customers);
  const setDate = (d) => { const s = new URLSearchParams(params); s.set("date", d); setParams(s, { replace: true }); };
  const setTechAndUrl = (t) => { setTech(t); const s = new URLSearchParams(params); if (t) s.set("tech", t); else s.delete("tech"); setParams(s, { replace: true }); };

  const layers = useMemo(() => {
    const day = (jobs || []).filter((j) => (j.scheduled_date || "").startsWith(date));
    const filtered = tech ? day.filter((j) => j.technician_id === tech) : day;
    const byTech = new Map();
    filtered.forEach((j) => {
      const cust = custMap.get(j.customer_id) || {};
      const lat = j.lat ?? cust.lat, lng = j.lng ?? cust.lng;
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const key = j.technician_id || "_unassigned";
      if (!byTech.has(key)) byTech.set(key, []);
      byTech.get(key).push({ ...j, lat, lng, __customer: cust });
    });
    const palette = ["blue", "orange", "purple", "green", "yellow", "red"];
    const out = [];
    let idx = 0;
    byTech.forEach((jobsForTech, techId) => {
      const color = palette[idx % palette.length]; idx += 1;
      const sorted = [...jobsForTech].sort((a, b) => (a.route_order ?? 0) - (b.route_order ?? 0));
      const points = sorted.map((j) => ({
        id: j.id, lat: j.lat, lng: j.lng, color,
        label: j.title || j.__customer.name || "Job",
        subtitle: `${j.customer_name || j.__customer.name || ""} · ${j.technician_name || "unassigned"} · #${j.route_order ?? "?"}`,
      }));
      out.push({
        key: `tech-${techId}`,
        points,
        polyline: sorted.map((j) => [j.lat, j.lng]),
        polylineColor: color === "blue" ? "#0284C7" : color === "orange" ? "#EA580C" : color === "purple" ? "#7C3AED" : color === "green" ? "#16A34A" : color === "yellow" ? "#CA8A04" : "#DC2626",
      });
    });
    return out;
  }, [jobs, custMap, date, tech]);

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="schedule-map-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Schedule map</h1>
        <Link to="/schedule" className="text-sm font-semibold ml-auto" style={{ color: colors.brand }}>← Calendar view</Link>
      </div>
      <div className="flex flex-wrap gap-3 items-center">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
               className="px-3 py-1.5 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
               data-testid="schedule-map-date" />
        <select value={tech} onChange={(e) => setTechAndUrl(e.target.value)}
                className="px-3 py-1.5 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                data-testid="schedule-map-tech">
          <option value="">All technicians</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      {loading && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
      {!loading && layers.length === 0 && (
        <div className="rounded-xl px-4 py-3 text-sm" style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }} data-testid="schedule-map-empty">
          No routed jobs for {date}{tech ? " on this technician" : ""} with geocoded addresses.
        </div>
      )}
      <MapView height={620} layers={layers} testid="schedule-map" />
    </div>
  );
}
