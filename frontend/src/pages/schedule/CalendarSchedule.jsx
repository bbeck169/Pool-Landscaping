/**
 * Phase 30 · Calendar Schedule (web).
 *
 * Replaces the old admin/dispatcher Jobs list AND the tech "Today" schedule
 * with a single unified calendar. Uses `react-big-calendar` with the
 * `date-fns` localizer so it plays nicely with the rest of the app (which
 * already ships date-fns).
 *
 *   • Views: Day / Week / Month + a Custom-range preset row (7/30/90 days,
 *     current quarter).
 *   • Filters: text search, technician, service type, status — ported from
 *     the old JobsList toolbar.
 *   • Empty-slot click → /jobs/new with the date prefilled.
 *   • Event click → /jobs/:id.
 *
 * RBAC: gated at the route level by `Jobs.read`; the "New job" button hides
 * behind `<Gate perm="Jobs" action="write">` from Phase 29C. Backend still
 * enforces its own gates on every mutation.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Calendar as RBCCalendar, dateFnsLocalizer } from "react-big-calendar";
import { format, parse, startOfWeek, getDay, addDays, startOfDay, endOfDay,
         startOfMonth, startOfQuarter, endOfMonth } from "date-fns";
import { enUS } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
import { Plus, Search, X as XIcon, Filter } from "lucide-react";

import { api } from "@/api";
import { colors, font } from "@/theme";
import { useAuth } from "@/auth";
import { Gate } from "@/hooks/usePermissions";

const locales = { "en-US": enUS };
const localizer = dateFnsLocalizer({
  format, parse, startOfWeek: (d) => startOfWeek(d, { weekStartsOn: 0 }), getDay, locales,
});

// Status → dot colour. Mirrors the old JobsList status pill palette so
// techs & dispatchers see the same signal on both screens.
const STATUS_COLORS = {
  scheduled:  "#0EA5E9",
  active:     "#059669",
  completed:  "#6B7280",
  pending:    "#F59E0B",
  requested:  "#8B5CF6",
  reopened:   "#DC2626",
  cancelled:  "#9CA3AF",
  on_hold:    "#F97316",
};

const RANGE_PRESETS = [
  { key: "7d",   label: "Next 7 days",  daysFromToday: 7 },
  { key: "30d",  label: "Next 30 days", daysFromToday: 30 },
  { key: "90d",  label: "Next 90 days", daysFromToday: 90 },
  { key: "q",    label: "This quarter", isQuarter: true },
];

function jobToEvent(job) {
  const dateStr = job.scheduled_date;
  if (!dateStr) return null;
  const base = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(base.getTime())) return null;
  const time = (job.scheduled_time || "09:00").split(":");
  const start = new Date(base);
  start.setHours(parseInt(time[0] || "9", 10), parseInt(time[1] || "0", 10), 0, 0);
  const durationMin = Number(job.duration_minutes) || 60;
  const end = new Date(start.getTime() + durationMin * 60000);
  const status = (job.status || "scheduled").toLowerCase();
  return {
    id: job.id,
    title: `${job.customer_name || "Job"}${job.service_type ? ` · ${job.service_type}` : ""}`,
    start, end,
    resource: {
      job,
      status,
      colour: STATUS_COLORS[status] || colors.brand,
    },
  };
}

export default function CalendarSchedule() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();

  const [rawJobs, setRawJobs] = useState([]);
  const [techs, setTechs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [view, setView] = useState(params.get("view") || "week");   // day | week | month | agenda
  const [date, setDate] = useState(() => {
    const d = params.get("date");
    return d ? new Date(`${d}T00:00:00`) : new Date();
  });
  const [range, setRange] = useState({ start: null, end: null });   // for the "Custom" preset row

  const [q, setQ] = useState(params.get("q") || "");
  const [techId, setTechId] = useState(params.get("technician_id") || "");
  const [status, setStatus] = useState(params.get("status") || "");
  const [service, setService] = useState(params.get("service") || "");

  const setParam = (k, v) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  const load = async () => {
    setLoading(true); setError("");
    try {
      // Ask the backend for a comfortable ±90 day window centred on the
      // current focused date. `?start=&end=` were added by Phase 30 backend
      // patch; if the server ignores them everything still works (returns
      // up to 1000 jobs) — honest degradation, not silent.
      const focus = date;
      const start = format(addDays(focus, -60), "yyyy-MM-dd");
      const end   = format(addDays(focus,  90), "yyyy-MM-dd");
      const [j, t] = await Promise.all([
        api.get(`/jobs?start=${start}&end=${end}`),
        api.get("/technicians").catch(() => []),
      ]);
      setRawJobs(Array.isArray(j) ? j : (j.items || j.data || []));
      setTechs(Array.isArray(t) ? t : (t.items || []));
    } catch (e) {
      setError(e.message || "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [date]);

  const filteredJobs = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return rawJobs.filter((j) => {
      if (techId && j.technician_id !== techId) return false;
      if (status && j.status !== status) return false;
      if (service && (j.service_type || "").toLowerCase() !== service.toLowerCase()) return false;
      if (ql) {
        const hay = `${j.customer_name || ""} ${j.title || ""} ${j.service_type || ""} ${j.address || ""}`.toLowerCase();
        if (!hay.includes(ql)) return false;
      }
      return true;
    });
  }, [rawJobs, q, techId, status, service]);

  const events = useMemo(
    () => filteredJobs.map(jobToEvent).filter(Boolean),
    [filteredJobs],
  );

  const serviceTypes = useMemo(() => {
    const s = new Set();
    rawJobs.forEach((j) => j.service_type && s.add(j.service_type));
    return Array.from(s).sort();
  }, [rawJobs]);

  const rangeMatchEvents = useMemo(() => {
    if (!range.start || !range.end) return null;
    const s = range.start.getTime(), e = range.end.getTime();
    return events.filter((ev) => ev.start.getTime() >= s && ev.start.getTime() <= e);
  }, [events, range]);

  const openPreset = (p) => {
    const now = startOfDay(new Date());
    if (p.isQuarter) {
      setRange({ start: startOfQuarter(now), end: endOfMonth(new Date(now.getFullYear(), now.getMonth() + 2, 1)) });
    } else {
      setRange({ start: now, end: endOfDay(addDays(now, p.daysFromToday - 1)) });
    }
  };

  const clearFilters = () => {
    setQ(""); setTechId(""); setStatus(""); setService("");
    ["q", "technician_id", "status", "service"].forEach((k) => setParam(k, ""));
  };

  const onSelectSlot = (slot) => {
    const d = format(slot.start, "yyyy-MM-dd");
    const t = format(slot.start, "HH:mm");
    navigate(`/jobs/new?date=${d}&time=${t}`);
  };
  const onSelectEvent = (ev) => {
    navigate(`/jobs/${ev.id}`);
  };

  const eventPropGetter = (ev) => ({
    style: {
      backgroundColor: ev.resource?.colour || colors.brand,
      borderRadius: 6,
      border: 0,
      color: "#fff",
      fontSize: 12,
      padding: "2px 4px",
    },
  });

  return (
    <div
      className="p-4 md:p-6"
      style={{ fontFamily: font.family }}
      data-testid="calendar-schedule"
    >
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }} data-testid="calendar-title">
            Schedule
          </h1>
          <div className="text-xs" style={{ color: colors.muted }}>
            {loading ? "Loading…" : `${filteredJobs.length} of ${rawJobs.length} jobs`}
          </div>
        </div>
        <div className="flex-1" />
        <Gate perm="Jobs" action="write">
          <button
            onClick={() => navigate("/jobs/new")}
            className="flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold"
            style={{ background: colors.brand, color: "#fff" }}
            data-testid="calendar-new-job"
          >
            <Plus size={14} /> New job
          </button>
        </Gate>
      </div>

      {/* Filter toolbar */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="calendar-filters"
      >
        <div className="flex items-center gap-1 flex-1 min-w-[180px]"
             style={{ background: colors.surfaceSecondary, borderRadius: 8, padding: "6px 10px",
                      border: `1px solid ${colors.border}` }}>
          <Search size={14} style={{ color: colors.muted }} />
          <input
            data-testid="calendar-search"
            value={q}
            onChange={(e) => { setQ(e.target.value); setParam("q", e.target.value); }}
            placeholder="Search customer, service, address…"
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: colors.onSurface }}
          />
          {q ? (
            <button onClick={() => { setQ(""); setParam("q", ""); }} data-testid="calendar-search-clear">
              <XIcon size={12} style={{ color: colors.muted }} />
            </button>
          ) : null}
        </div>

        <select
          value={techId}
          onChange={(e) => { setTechId(e.target.value); setParam("technician_id", e.target.value); }}
          data-testid="calendar-filter-tech"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        >
          <option value="">All techs</option>
          {techs.map((t) => (
            <option key={t.id} value={t.user_id || t.id}>{t.name || t.email}</option>
          ))}
        </select>

        <select
          value={service}
          onChange={(e) => { setService(e.target.value); setParam("service", e.target.value); }}
          data-testid="calendar-filter-service"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        >
          <option value="">All services</option>
          {serviceTypes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setParam("status", e.target.value); }}
          data-testid="calendar-filter-status"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        >
          <option value="">All statuses</option>
          {Object.keys(STATUS_COLORS).map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
          ))}
        </select>

        {(q || techId || status || service) ? (
          <button
            onClick={clearFilters}
            data-testid="calendar-filter-clear"
            className="text-xs font-semibold px-2 py-1.5 rounded-lg"
            style={{ color: colors.muted, background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
          >
            <Filter size={11} className="inline mr-1" /> Clear
          </button>
        ) : null}
      </div>

      {/* Custom-range preset row */}
      <div className="flex flex-wrap items-center gap-2 mb-3" data-testid="calendar-presets">
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.muted }}>
          Custom range
        </span>
        {RANGE_PRESETS.map((p) => {
          const active = range.start && p.key === range.key;
          return (
            <button
              key={p.key}
              onClick={() => { setRange({ ...range, key: p.key }); openPreset(p); }}
              className="text-xs font-semibold px-3 py-1 rounded-full"
              style={{
                background: active ? colors.brand : colors.surface,
                color: active ? "#fff" : colors.onSurface,
                border: `1px solid ${active ? "transparent" : colors.border}`,
              }}
              data-testid={`calendar-preset-${p.key}`}
            >
              {p.label}
            </button>
          );
        })}
        <input
          type="date"
          value={range.start ? format(range.start, "yyyy-MM-dd") : ""}
          onChange={(e) => setRange((r) => ({ ...r, key: "custom",
            start: e.target.value ? new Date(`${e.target.value}T00:00:00`) : null,
          }))}
          data-testid="calendar-range-from"
          className="text-xs rounded-lg px-2 py-1"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        />
        <span className="text-xs" style={{ color: colors.muted }}>→</span>
        <input
          type="date"
          value={range.end ? format(range.end, "yyyy-MM-dd") : ""}
          onChange={(e) => setRange((r) => ({ ...r, key: "custom",
            end: e.target.value ? new Date(`${e.target.value}T23:59:59`) : null,
          }))}
          data-testid="calendar-range-to"
          className="text-xs rounded-lg px-2 py-1"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        />
        {rangeMatchEvents ? (
          <span
            className="text-xs font-semibold px-2 py-1 rounded-full"
            data-testid="calendar-range-count"
            style={{ background: "#DBEAFE", color: "#1E40AF" }}
          >
            {rangeMatchEvents.length} jobs in range
          </span>
        ) : null}
        {range.start ? (
          <button
            onClick={() => setRange({ start: null, end: null })}
            className="text-xs font-semibold"
            style={{ color: colors.muted }}
            data-testid="calendar-range-clear"
          >
            Clear
          </button>
        ) : null}
      </div>

      {error ? (
        <div
          data-testid="calendar-error"
          className="rounded-xl px-3 py-2 mb-3 text-xs"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
        >
          {error}
        </div>
      ) : null}

      <div
        style={{ background: colors.surface, border: `1px solid ${colors.border}`,
                 borderRadius: 12, padding: 8, minHeight: 640 }}
        data-testid="calendar-view"
      >
        <RBCCalendar
          localizer={localizer}
          events={events}
          view={view}
          onView={(v) => { setView(v); setParam("view", v); }}
          date={date}
          onNavigate={(d) => { setDate(d); setParam("date", format(d, "yyyy-MM-dd")); }}
          views={["day", "week", "month", "agenda"]}
          startAccessor="start"
          endAccessor="end"
          style={{ height: 640, fontSize: 13 }}
          eventPropGetter={eventPropGetter}
          selectable
          onSelectSlot={onSelectSlot}
          onSelectEvent={onSelectEvent}
          popup
        />
      </div>

      {/* Status legend */}
      <div className="flex flex-wrap items-center gap-3 mt-3 text-xs" style={{ color: colors.muted }}>
        {Object.entries(STATUS_COLORS).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1">
            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: v }} />
            {k.replace(/_/g, " ")}
          </div>
        ))}
      </div>
    </div>
  );
}
