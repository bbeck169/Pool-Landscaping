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
import withDragAndDrop from "react-big-calendar/lib/addons/dragAndDrop";
import "react-big-calendar/lib/addons/dragAndDrop/styles.css";
import { format, parse, startOfWeek, getDay, addDays, startOfDay, endOfDay,
         startOfMonth, startOfQuarter, endOfMonth } from "date-fns";
import { enUS } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
import { Plus, Search, X as XIcon, Filter, ChevronLeft, ChevronRight,
         CheckCircle2, Move as MoveIcon, ArrowUp, ArrowDown, FileText,
         Save as SaveIcon, Star } from "lucide-react";

import { api } from "@/api";
import { colors, font } from "@/theme";
import { useAuth } from "@/auth";
import { Gate, useCan } from "@/hooks/usePermissions";
import { useClockInGate, ClockInGateDialog } from "@/hooks/useClockInGate";
import ChecklistModal from "@/components/checklist/ChecklistModal";
import ServiceNotePill from "@/components/schedule/ServiceNotePill";
import TechWeatherWidget from "@/components/Weather/WeatherWidget";
import JobRainFlag from "@/components/Weather/JobRainFlag";

/** Phase 30W · service-type → card palette. Mirrors the mobile fix-pass. */
const SERVICE_PALETTE = (raw) => {
  const s = (raw || "").toLowerCase();
  if (s.includes("weekly") && s.includes("landsc"))  return { bg: "#DCFCE7", fg: "#166534", tag: "#059669" };
  if (s.includes("monthly") && s.includes("landsc")) return { bg: "#E0E7FF", fg: "#3730A3", tag: "#4F46E5" };
  if (s.includes("irrig"))                            return { bg: "#DBEAFE", fg: "#1E3A8A", tag: "#2563EB" };
  if (s.includes("rock"))                             return { bg: "#FEF3C7", fg: "#78350F", tag: "#B45309" };
  if (s.includes("pool") || s.includes("chem"))       return { bg: "#CFFAFE", fg: "#155E75", tag: "#0891B2" };
  if (s.includes("clean"))                            return { bg: "#FCE7F3", fg: "#831843", tag: "#BE185D" };
  return { bg: "#F3F4F6", fg: "#111827", tag: "#6B7280" };
};

/** Phase 30W · status pill palette. `completed → "Closed" (green)`, etc. */
const STATUS_PILL = {
  completed:  { bg: "#DCFCE7", fg: "#166534", label: "Closed" },
  active:     { bg: "#DBEAFE", fg: "#1E40AF", label: "In progress" },
  scheduled:  { bg: "#FEF3C7", fg: "#92400E", label: "Open" },
  pending:    { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  requested:  { bg: "#EDE9FE", fg: "#5B21B6", label: "Requested" },
  reopened:   { bg: "#FEE2E2", fg: "#991B1B", label: "Reopened" },
  cancelled:  { bg: "#F3F4F6", fg: "#4B5563", label: "Cancelled" },
  on_hold:    { bg: "#FFEDD5", fg: "#9A3412", label: "On hold" },
};

const jobHours = (j) => {
  const h = j.actual_hours ?? j.billable_hours ?? j.estimated_hours ?? 0;
  return `${(Number(h) || 0).toFixed(2)} BH`;
};
const isRecurring = (j) =>
  Boolean(j.is_recurring || j.recurring || (j.recurrence && j.recurrence !== "none"));

const MODE_KEY = "aq-schedule-mode-v1";

const locales = { "en-US": enUS };
const localizer = dateFnsLocalizer({
  format, parse, startOfWeek: (d) => startOfWeek(d, { weekStartsOn: 0 }), getDay, locales,
});
// Feb-2026 · Enhancement 1 — wrap the calendar with drag-and-drop.
// Admin drags an event card to a new slot → onEventDrop fires and we
// stage the reschedule in a confirmation modal before committing.
const DnDCalendar = withDragAndDrop(RBCCalendar);

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

function jobToEvent(job, techColorMap) {
  // Phase 30X · schedule is date-only. All events are all-day; landscaping /
  // pool service is booked by day, not by hour.
  const dateStr = job.scheduled_date;
  if (!dateStr) return null;
  const start = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(start.getTime())) return null;
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000 - 1);
  const status = (job.status || "scheduled").toLowerCase();
  // Phase 34d-follow — prepend a gold star to the title for VIP customers
  // so the RBC event tile carries the same visual weight as grid cards.
  const vipPrefix = job.customer_is_vip ? "★ " : "";
  // Phase 21 · Feb 2026 · Addition B — resolve the assigned tech's
  // display color. Falls through to the deterministic hashed fallback
  // when the tech has no ``display_color_hex`` set (or is unassigned).
  const techColor = techColorMap && job.technician_id
    ? (techColorMap.get(job.technician_id) || hashedTechColor(job.technician_id))
    : (job.technician_id ? hashedTechColor(job.technician_id) : null);
  return {
    id: job.id,
    title: `${vipPrefix}${job.customer_name || "Job"}${job.service_type ? ` · ${job.service_type}` : ""}`,
    start, end, allDay: true,
    resource: {
      job,
      status,
      colour: STATUS_COLORS[status] || colors.brand,
      techColor,
    },
  };
}


// Phase 21 · Feb 2026 · Addition B — deterministic hashed color for
// techs without an explicit ``display_color_hex``. Same algorithm as
// the pre-existing dispatch fallback so we don't visually re-key the
// board when this migration lands.
function hashedTechColor(seed) {
  if (!seed) return null;
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = ((h << 5) - h) + seed.charCodeAt(i);
    h |= 0;
  }
  const palette = [
    "#0EA5E9", "#22C55E", "#F97316", "#8B5CF6", "#EF4444",
    "#EAB308", "#14B8A6", "#EC4899", "#6366F1", "#F43F5E",
  ];
  return palette[Math.abs(h) % palette.length];
}


// Phase 21 · Feb 2026 · Addition B — apply a 15% alpha tint over a hex.
// Used for RBC event background so the tech color is visible without
// drowning the text.
function tintHex(hex, alpha = 0.15) {
  if (!hex || typeof hex !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(hex)) return "transparent";
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export default function CalendarSchedule() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const canWriteJobs = useCan("Jobs", "write");

  const [rawJobs, setRawJobs] = useState([]);
  const [techs, setTechs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Phase 30W · top-level view mode. Grid is the default; sessionStorage
  // remembers the user's last pick (same key convention as mobile).
  const [mode, setMode] = useState(() => {
    if (params.get("mode") === "calendar" || params.get("mode") === "grid") return params.get("mode");
    try {
      const saved = sessionStorage.getItem(MODE_KEY);
      if (saved === "calendar" || saved === "grid") return saved;
    } catch {}
    return "grid";
  });
  const setModePersist = (m) => {
    setMode(m);
    try { sessionStorage.setItem(MODE_KEY, m); } catch {}
    setParam("mode", m);
  };

  // Phase 30W · grid-mode bookkeeping.
  const [checked, setChecked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [rearrangeMode, setRearrangeMode] = useState(false);
  const [reorderList, setReorderList] = useState([]);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveDate, setMoveDate] = useState("");
  const [toast, setToast] = useState(null);              // {text, kind:"info"|"err"}
  const [reorderUnavailable, setReorderUnavailable] = useState(false);
  // Phase 31 · Step 2b — tap-job opens the checklist modal in place of
  // navigating away to /jobs/:id. Preserves the /schedule URL so the
  // grid/calendar toggle, filters, and range presets survive the close.
  const [checklistJobId, setChecklistJobId] = useState(null);
  // Phase 56.3.C RBAC — technicians must not create jobs, regardless of
  // their department (pool / landscape / both). Admins + super_admins are
  // unaffected. Backend already enforces this via `require_admin` on
  // POST /api/jobs; the flag below hides the corresponding UI affordances
  // so techs never see a broken create surface.
  const canCreateJobs = ["admin", "super_admin"].includes((user?.role || "").toLowerCase());
  // Phase 56.3 follow-up — clock-in gate for landscape techs opening events.
  const clockGate = useClockInGate(user);

  const [view, setView] = useState(params.get("view") || "month");   // Phase 30X · month default
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

  // Phase 21 · Feb 2026 · Addition B — build the tech-id → color map
  // from the techs list. Techs without a ``display_color_hex`` get
  // the deterministic hash-based fallback so every event carries a
  // stable color even when no admin picks one.
  const techColorMap = useMemo(() => {
    const m = new Map();
    for (const t of techs) {
      const id = t.id || t.user_id;
      if (!id) continue;
      m.set(id, t.display_color_hex || hashedTechColor(id));
    }
    return m;
  }, [techs]);

  const events = useMemo(
    () => {
      // Phase 34a fix — dedup by job.id BEFORE handing to react-big-calendar.
      // RBC uses event identity to key DOM nodes when segments span days;
      // any duplicate id in the source list triggers React
      // "duplicate key" warnings on the /schedule route. This dedup is a
      // belt-and-suspenders guard on top of the backend cleanup.
      const seen = new Set();
      const out = [];
      for (const j of filteredJobs) {
        const ev = jobToEvent(j, techColorMap);
        if (!ev) continue;
        if (seen.has(ev.id)) continue;
        seen.add(ev.id);
        out.push(ev);
      }
      return out;
    },
    [filteredJobs, techColorMap],
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
    // Phase 30X · date-only. Ignore any time bit the calendar hands us.
    // Phase 56.3.C — swallow slot-to-create clicks for technicians. They
    // must not be able to create jobs; the button-level gates hide the
    // "New job" affordances but the calendar grid also invokes this on
    // empty-slot click, so we short-circuit here as defense in depth.
    if (!canCreateJobs) return;
    const d = format(slot.start, "yyyy-MM-dd");
    navigate(`/jobs/new?date=${d}`);
  };
  const onSelectEvent = (ev) => {
    // Phase 31 · Step 2b — open the checklist modal in place of a hard
    // navigate. Preserves the /schedule route state (mode/filter/range).
    // Phase 56.3 follow-up — strict landscape techs must be clocked in
    // before we open the modal. Admins / super_admins / "All" role / pool
    // techs / customers are all bypassed inside the hook.
    clockGate.openJob(ev.id, () => setChecklistJobId(ev.id));
  };

  // Feb-2026 · Enhancement 1 — drag-drop reschedule state + handlers.
  const isAdminRole = (user?.role === "admin" || user?.role === "super_admin"
                      || user?.role === "manager");
  const [rescheduleDraft, setRescheduleDraft] = React.useState(null);
  const [reschedulePreview, setReschedulePreview] = React.useState(null);
  const [rescheduleBusy, setRescheduleBusy] = React.useState(false);
  const isDraggable = React.useCallback(() => isAdminRole, [isAdminRole]);

  const onEventDrop = React.useCallback(async ({ event, start, end }) => {
    if (!isAdminRole) return;
    const iso = new Date(start).toISOString();
    const endIso = end ? new Date(end).toISOString() : undefined;
    setRescheduleBusy(true);
    setRescheduleDraft({ event, start, end });
    try {
      // Dry-run first so the confirmation modal can preview the
      // notification text before we actually persist + notify.
      const preview = await api.post("/schedule/reschedule", {
        job_id: event.id,
        new_start_at: iso, new_end_at: endIso,
        dry_run: true,
      });
      setReschedulePreview(preview.preview || null);
    } catch (e) {
      toast_(`Reschedule preview failed: ${e.message || e}`, "err");
      setRescheduleDraft(null);
    } finally {
      setRescheduleBusy(false);
    }
  }, [isAdminRole]);

  const confirmReschedule = React.useCallback(async () => {
    if (!rescheduleDraft) return;
    setRescheduleBusy(true);
    try {
      const iso = new Date(rescheduleDraft.start).toISOString();
      const endIso = rescheduleDraft.end
        ? new Date(rescheduleDraft.end).toISOString() : undefined;
      const res = await api.post("/schedule/reschedule", {
        job_id: rescheduleDraft.event.id,
        new_start_at: iso, new_end_at: endIso,
        dry_run: false,
      });
      const parts = [];
      if (res.sent_email) parts.push("email sent");
      if (res.sent_sms) parts.push("SMS sent");
      toast_(
        `Rescheduled${parts.length ? " — " + parts.join(" + ") : ""}.`,
        parts.length ? "info" : "err",
      );
      setRescheduleDraft(null);
      setReschedulePreview(null);
      await load();
    } catch (e) {
      toast_(`Reschedule failed: ${e.message || e}`, "err");
    } finally {
      setRescheduleBusy(false);
    }
  }, [rescheduleDraft]);

  const cancelReschedule = React.useCallback(() => {
    setRescheduleDraft(null);
    setReschedulePreview(null);
  }, []);

  const eventPropGetter = (ev) => {
    // Phase 21 · Feb 2026 · Addition B — the RBC event card is tinted
    // in the tech's color and gets a 4px solid left border so the tech
    // assignment reads from across the room. When no tech color exists
    // we fall back to the pre-existing status-based background so the
    // Schedule keeps its original palette for unassigned jobs.
    const tech = ev.resource?.techColor;
    if (tech) {
      return {
        style: {
          backgroundColor: tintHex(tech, 0.18),
          borderLeft: `4px solid ${tech}`,
          borderTop: 0, borderRight: 0, borderBottom: 0,
          borderRadius: 6,
          color: colors.onSurface,
          fontSize: 12,
          padding: "2px 4px 2px 6px",
        },
      };
    }
    return {
      style: {
        backgroundColor: ev.resource?.colour || colors.brand,
        borderRadius: 6,
        border: 0,
        color: "#fff",
        fontSize: 12,
        padding: "2px 4px",
      },
    };
  };

  /* ─── Phase 30W · Grid-view derived state + actions ────────────── */
  const focusISO = format(date, "yyyy-MM-dd");
  const dayJobs = useMemo(() => {
    const list = filteredJobs.filter((j) => (j.scheduled_date || "").slice(0, 10) === focusISO);
    // Phase 30X · date-only surface. Order by route position only — no
    // time-of-day tiebreaker (schedule is per-day, not hourly).
    list.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    return list;
  }, [filteredJobs, focusISO]);
  useEffect(() => { setReorderList(dayJobs); }, [dayJobs]);
  const gridList = rearrangeMode ? reorderList : dayJobs;

  const toast_ = (text, kind = "info") => {
    setToast({ text, kind });
    setTimeout(() => setToast(null), 3200);
  };
  const toggleCheck = (id) => setChecked((cur) => {
    const n = new Set(cur);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const bulkComplete = async () => {
    if (!checked.size) return;
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { status: "completed" }); ok++; }
      catch { fail++; }
    }
    setBusy(false); setChecked(new Set());
    toast_(`${ok} closed · ${fail} failed`, fail > ok ? "err" : "info");
    await load();
  };
  const bulkMove = async () => {
    if (!checked.size || !/^\d{4}-\d{2}-\d{2}$/.test(moveDate)) {
      toast_("Pick a target date (YYYY-MM-DD).", "err"); return;
    }
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { scheduled_date: moveDate }); ok++; }
      catch { fail++; }
    }
    setBusy(false); setChecked(new Set());
    setMoveOpen(false); setMoveDate("");
    toast_(`${ok} moved · ${fail} failed`, fail > ok ? "err" : "info");
    await load();
  };
  const saveReorder = async () => {
    setBusy(true);
    try {
      await api.post("/jobs/reorder", { job_ids: reorderList.map((j) => j.id) });
      toast_(`Route saved for ${reorderList.length} jobs.`);
      await load();
    } catch (e) {
      const m = String(e?.message || "");
      if (/403|404|not.?found|forbidden|admin only/i.test(m)) {
        setReorderUnavailable(true);
        toast_("Rearrange endpoint not available for your role — order kept locally only.", "err");
      } else {
        toast_(m || "Reorder failed.", "err");
      }
    } finally {
      setBusy(false);
      setRearrangeMode(false);
    }
  };
  const shift = (id, dir) => setReorderList((cur) => {
    const i = cur.findIndex((j) => j.id === id);
    if (i < 0) return cur;
    const j = i + dir;
    if (j < 0 || j >= cur.length) return cur;
    const c = [...cur];
    [c[i], c[j]] = [c[j], c[i]];
    return c;
  });

  return (
    // BUG · Feb-2026 — full-page scroll. Outer container carries NO
    // ``overflow`` / ``height: 100vh`` / ``max-height`` rules so the
    // whole document scrolls naturally when the tech legend + weather
    // widget + calendar body + day-summary cards exceed the viewport
    // height. The RBC calendar keeps its own internal wheel-scroll
    // for the time-of-day grid (correct); the trap only happens when
    // the OUTER page also clamps its height, which we no longer do.
    // Mirrors the DispatchBoardPage fix pattern.
    <div
      className="p-4 md:p-6 pb-24"
      style={{ fontFamily: font.family }}
      data-testid="calendar-schedule"
    >
      {/* Feb-2026 · Tech-only weather header. TechWeatherWidget
          self-gates on ``user.role === "technician"``, so admins and
          impersonated views render nothing here. */}
      <TechWeatherWidget user={user} />
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
        {/* Phase 30W · Calendar ↔ Grid segmented control (Grid is default). */}
        <div
          className="inline-flex rounded-xl overflow-hidden"
          style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
          data-testid="schedule-mode-switch"
        >
          {[
            { k: "calendar", label: "Calendar" },
            { k: "grid",     label: "Grid" },
          ].map((m) => {
            const active = mode === m.k;
            return (
              <button
                key={m.k}
                onClick={() => setModePersist(m.k)}
                data-testid={`schedule-mode-${m.k}`}
                style={{
                  padding: "6px 14px",
                  fontSize: 12,
                  fontWeight: 700,
                  background: active ? colors.brand : "transparent",
                  color: active ? "#fff" : colors.onSurface,
                  border: 0,
                  cursor: "pointer",
                }}
              >
                {m.label}
              </button>
            );
          })}
        </div>
        <Gate perm="Jobs" action="write">
          {canCreateJobs ? (
            <button
              onClick={() => navigate("/jobs/new")}
              className="flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold"
              style={{ background: colors.brand, color: "#fff" }}
              data-testid="calendar-new-job"
            >
              <Plus size={14} /> New job
            </button>
          ) : null}
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

      {toast ? (
        <div
          className="rounded-xl px-3 py-2 mb-3 text-xs"
          style={{ background: toast.kind === "err" ? "#FEE2E2" : "#DCFCE7",
                   color: toast.kind === "err" ? "#991B1B" : "#166534",
                   border: `1px solid ${toast.kind === "err" ? "#FCA5A5" : "#86EFAC"}` }}
          data-testid="calendar-toast"
        >
          {toast.text}
        </div>
      ) : null}

      {mode === "calendar" ? (
      <div
        style={{ background: colors.surface, border: `1px solid ${colors.border}`,
                 borderRadius: 12, padding: 8, minHeight: 640 }}
        data-testid="calendar-view"
      >
        {/* Phase 21 · Feb 2026 · Addition B — tech color legend.
            Scrollable when many techs. Only rendered when at least
            one active tech has a color (explicit or hashed fallback). */}
        <TechColorLegend techs={techs} techColorMap={techColorMap} />
        <DnDCalendar
          localizer={localizer}
          events={events}
          view={view}
          onView={(v) => { setView(v); setParam("view", v); }}
          date={date}
          onNavigate={(d) => { setDate(d); setParam("date", format(d, "yyyy-MM-dd")); }}
          views={["month", "agenda"]}
          startAccessor="start"
          endAccessor="end"
          style={{ height: 640, fontSize: 13 }}
          eventPropGetter={eventPropGetter}
          selectable
          onSelectSlot={onSelectSlot}
          onSelectEvent={onSelectEvent}
          onEventDrop={onEventDrop}
          draggableAccessor={isDraggable}
          resizable={false}
          popup
          formats={{
            timeGutterFormat: () => "",
            eventTimeRangeFormat: () => "",
            agendaTimeFormat: () => "",
            agendaTimeRangeFormat: () => "",
          }}
        />
      </div>
      ) : (
        <GridPanel
          date={date}
          setDate={setDate}
          jobs={gridList}
          loading={loading}
          checked={checked}
          onToggle={toggleCheck}
          canWrite={canWriteJobs}
          rearrangeMode={rearrangeMode}
          setRearrangeMode={setRearrangeMode}
          onSaveReorder={saveReorder}
          onShift={shift}
          onBulkComplete={bulkComplete}
          onOpenMove={() => setMoveOpen(true)}
          moveOpen={moveOpen}
          setMoveOpen={setMoveOpen}
          moveDate={moveDate}
          setMoveDate={setMoveDate}
          onConfirmMove={bulkMove}
          busy={busy}
          onOpenJob={(id) => clockGate.openJob(id, () => setChecklistJobId(id))}
          onNewJob={canCreateJobs ? (() => navigate(`/jobs/new?date=${focusISO}`)) : undefined}
          reorderUnavailable={reorderUnavailable}
        />
      )}

      {/* Phase 56.3 follow-up — clock-in gate dialog for landscape techs. */}
      <ClockInGateDialog gate={clockGate} />

      {/* Feb-2026 · Enhancement 1 — Reschedule confirmation modal. */}
      {rescheduleDraft ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: "rgba(15,23,42,0.55)" }}
          role="dialog" aria-modal="true"
          data-testid="reschedule-confirm-modal"
          onClick={(e) => { if (e.target === e.currentTarget) cancelReschedule(); }}
        >
          <div
            className="w-full max-w-md rounded-2xl shadow-2xl"
            style={{ backgroundColor: colors.surface }}
          >
            <div className="p-5 space-y-3">
              <div className="text-base font-bold"
                   style={{ color: colors.onSurface }}
                   data-testid="reschedule-confirm-title">
                Confirm reschedule
              </div>
              {reschedulePreview ? (
                <div className="text-sm space-y-1"
                     style={{ color: colors.onSurface }}
                     data-testid="reschedule-confirm-preview">
                  <div>
                    Reschedule <strong>{reschedulePreview.customer_name || "customer"}</strong>{" "}
                    from <strong>{reschedulePreview.old_datetime}</strong>{" "}
                    → <strong>{reschedulePreview.new_datetime}</strong>.
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    This will send an{" "}
                    {reschedulePreview.customer_email ? "email" : ""}
                    {reschedulePreview.customer_email && reschedulePreview.customer_phone ? " + " : ""}
                    {reschedulePreview.customer_phone ? "SMS" : ""}
                    {(!reschedulePreview.customer_email && !reschedulePreview.customer_phone)
                       ? "no notification (no contact on file)" : " notification"} to the customer.
                  </div>
                  {reschedulePreview.tech_name ? (
                    <div className="text-xs" style={{ color: colors.muted }}>
                      Tech: <strong>{reschedulePreview.tech_name}</strong>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="text-sm" style={{ color: colors.muted }}>Loading preview…</div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 px-5 py-3"
                 style={{ borderTop: `1px solid ${colors.border}` }}>
              <button
                type="button"
                onClick={cancelReschedule}
                disabled={rescheduleBusy}
                className="px-3 py-1.5 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-50"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="reschedule-confirm-cancel-btn"
              >Cancel</button>
              <button
                type="button"
                onClick={confirmReschedule}
                disabled={rescheduleBusy || !reschedulePreview}
                className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white hover:brightness-95 disabled:opacity-50"
                style={{ backgroundColor: colors.brand }}
                data-testid="reschedule-confirm-btn"
              >{rescheduleBusy ? "…" : "Confirm & notify"}</button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Status legend — calendar mode only. */}
      {mode === "calendar" ? (
        <div className="flex flex-wrap items-center gap-3 mt-3 text-xs" style={{ color: colors.muted }}>
          {Object.entries(STATUS_COLORS).map(([k, v]) => (
            <div key={k} className="flex items-center gap-1">
              <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: v }} />
              {k.replace(/_/g, " ")}
            </div>
          ))}
        </div>
      ) : null}

      {/* Phase 31 · Step 2b — checklist modal (Grid + Calendar tap target). */}
      <ChecklistModal
        jobId={checklistJobId}
        open={!!checklistJobId}
        onClose={() => setChecklistJobId(null)}
        onSubmitted={() => { load(); }}
      />
    </div>
  );
}

/* ═══ Phase 30W · Grid panel ═════════════════════════════════════════ */
function GridPanel({
  date, setDate, jobs, loading, checked, onToggle, canWrite,
  rearrangeMode, setRearrangeMode, onSaveReorder, onShift,
  onBulkComplete, onOpenMove, moveOpen, setMoveOpen, moveDate, setMoveDate,
  onConfirmMove, busy, onOpenJob, onNewJob, reorderUnavailable,
}) {
  const focusISO = format(date, "yyyy-MM-dd");
  const isToday = focusISO === format(new Date(), "yyyy-MM-dd");
  const dayLabel = date.toLocaleDateString(undefined, {
    weekday: "long", year: "numeric", month: "short", day: "numeric",
  });

  return (
    <div
      style={{ background: colors.surface, border: `1px solid ${colors.border}`,
               borderRadius: 12, padding: 16, minHeight: 640 }}
      data-testid="grid-view"
    >
      {/* Day-nav header */}
      <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="grid-day-head">
        <button
          onClick={() => setDate(addDays(date, -1))}
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`,
                   color: colors.onSurface }}
          data-testid="grid-prev-day"
        >
          <ChevronLeft size={16} />
        </button>
        <button
          onClick={() => setDate(new Date())}
          className="h-9 px-3 rounded-full text-xs font-bold"
          style={{
            background: isToday ? colors.brand : colors.surfaceSecondary,
            color: isToday ? "#fff" : colors.onSurface,
            border: `1px solid ${isToday ? "transparent" : colors.border}`,
          }}
          data-testid="grid-today"
        >
          Today
        </button>
        <button
          onClick={() => setDate(addDays(date, 1))}
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`,
                   color: colors.onSurface }}
          data-testid="grid-next-day"
        >
          <ChevronRight size={16} />
        </button>
        <div className="flex-1" />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }} data-testid="grid-day-label">
          {dayLabel}
        </div>
      </div>

      {/* Bulk-action pill row */}
      {canWrite ? (
        <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="grid-bulk-pills">
          <button
            onClick={onBulkComplete}
            disabled={busy || checked.size === 0}
            className="flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold"
            style={{ background: "#059669", color: "#fff",
                     opacity: (busy || checked.size === 0) ? 0.4 : 1 }}
            data-testid="grid-bulk-complete"
          >
            <CheckCircle2 size={12} /> Complete ({checked.size})
          </button>
          <button
            onClick={onOpenMove}
            disabled={busy || checked.size === 0}
            className="flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold"
            style={{ background: "#2563EB", color: "#fff",
                     opacity: (busy || checked.size === 0) ? 0.4 : 1 }}
            data-testid="grid-bulk-move"
          >
            <MoveIcon size={12} /> Move these events ({checked.size})
          </button>
          <button
            onClick={rearrangeMode ? onSaveReorder : () => setRearrangeMode(true)}
            disabled={busy || reorderUnavailable}
            className="flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold"
            style={{ background: rearrangeMode ? "#059669" : "#7C3AED", color: "#fff",
                     opacity: reorderUnavailable ? 0.4 : 1 }}
            data-testid="grid-bulk-rearrange"
            title={reorderUnavailable ? "Reorder endpoint not available for your role." : ""}
          >
            {rearrangeMode ? <SaveIcon size={12} /> : <ArrowUp size={12} />}
            {rearrangeMode ? "Save order" : "Rearrange"}
          </button>
          {reorderUnavailable ? (
            <span className="text-xs" style={{ color: colors.muted }} data-testid="grid-reorder-unavailable">
              Rearrange not available for this role.
            </span>
          ) : null}
        </div>
      ) : null}

      {/* Inline move date picker */}
      {moveOpen ? (
        <div
          className="rounded-xl p-3 mb-3 flex flex-wrap items-center gap-2"
          style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
          data-testid="grid-move-box"
        >
          <span className="text-xs font-semibold" style={{ color: colors.onSurface }}>
            Move {checked.size} job{checked.size === 1 ? "" : "s"} to:
          </span>
          <input
            type="date"
            value={moveDate}
            onChange={(e) => setMoveDate(e.target.value)}
            className="rounded-lg px-2 py-1 text-xs"
            style={{ background: colors.surface, border: `1px solid ${colors.border}`,
                     color: colors.onSurface }}
            data-testid="grid-move-input"
          />
          <button
            onClick={onConfirmMove}
            disabled={busy}
            className="h-7 px-3 rounded-full text-xs font-bold"
            style={{ background: colors.brand, color: "#fff", opacity: busy ? 0.5 : 1 }}
            data-testid="grid-move-confirm"
          >
            Move
          </button>
          <button
            onClick={() => { setMoveOpen(false); setMoveDate(""); }}
            className="h-7 px-3 rounded-full text-xs font-semibold"
            style={{ background: colors.surface, color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
            data-testid="grid-move-cancel"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {/* Rows */}
      {loading ? (
        <div className="py-10 text-center text-xs" style={{ color: colors.muted }} data-testid="grid-loading">
          Loading…
        </div>
      ) : jobs.length === 0 ? (
        <div
          className="rounded-xl py-10 text-center"
          style={{ background: colors.surfaceSecondary, border: `1px dashed ${colors.border}` }}
          data-testid="grid-empty"
        >
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Nothing on {focusISO}
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Change the filters, jump to a different day, or add a new job.
          </div>
          <Gate perm="Jobs" action="write">
            {onNewJob ? (
              <button
                onClick={onNewJob}
                className="mt-3 inline-flex items-center gap-1 px-3 h-8 rounded-lg text-xs font-bold"
                style={{ background: colors.brand, color: "#fff" }}
                data-testid="grid-new-job"
              >
                <Plus size={12} /> New job
              </button>
            ) : null}
          </Gate>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {jobs.map((j, idx) => {
            const pill = STATUS_PILL[(j.status || "scheduled").toLowerCase()] || STATUS_PILL.scheduled;
            const svc = SERVICE_PALETTE(j.service_type);
            const isChecked = checked.has(j.id);
            return (
              <div
                key={j.id}
                className="flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer"
                style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`grid-job-${j.id}`}
                onClick={() => { if (!rearrangeMode) onOpenJob(j.id); }}
                role="button"
              >
                {rearrangeMode ? (
                  <div className="flex flex-col items-center gap-0.5 w-8">
                    <button
                      onClick={(e) => { e.stopPropagation(); onShift(j.id, -1); }}
                      disabled={idx === 0}
                      style={{ background: "transparent", border: 0, cursor: idx === 0 ? "default" : "pointer", opacity: idx === 0 ? 0.3 : 1 }}
                      data-testid={`grid-reorder-up-${j.id}`}
                    >
                      <ArrowUp size={14} color={colors.brand} />
                    </button>
                    <span className="text-[10px] font-bold" style={{ color: colors.brand }}>{idx + 1}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); onShift(j.id, 1); }}
                      disabled={idx === jobs.length - 1}
                      style={{ background: "transparent", border: 0, cursor: idx === jobs.length - 1 ? "default" : "pointer",
                               opacity: idx === jobs.length - 1 ? 0.3 : 1 }}
                      data-testid={`grid-reorder-down-${j.id}`}
                    >
                      <ArrowDown size={14} color={colors.brand} />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); onToggle(j.id); }}
                    className="w-6 h-6 rounded-full flex items-center justify-center"
                    style={{ background: isChecked ? colors.brand : "transparent",
                             border: `1.5px solid ${isChecked ? colors.brand : colors.muted}` }}
                    data-testid={`grid-check-${j.id}`}
                    aria-label={isChecked ? "uncheck" : "check"}
                  >
                    {isChecked ? <CheckCircle2 size={13} color="#fff" /> : null}
                  </button>
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] font-bold uppercase tracking-wide"
                       style={{ color: svc.tag }}>
                    {isRecurring(j) ? "🔁 " : ""}{j.service_type || "General"}
                  </div>
                  <div className="text-sm font-bold flex items-center gap-1.5" style={{ color: colors.onSurface }}>
                    <span>{j.customer_name || "Unknown"}</span>
                    {j.customer_is_vip ? (
                      <span
                        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider"
                        style={{
                          backgroundColor: "#FEF3C7",
                          color: "#92400E",
                          border: "1px solid #F59E0B",
                        }}
                        data-testid={`job-vip-badge-${j.id}`}
                        data-vip="true"
                        title="VIP customer"
                      >
                        <Star size={9} fill="#F59E0B" color="#F59E0B" /> VIP
                      </span>
                    ) : null}
                    {/* Feb-2026 · rain-flag — informational only, no
                        rescheduling. Uses the shared hourly hook so
                        no extra HTTP requests. */}
                    <JobRainFlag
                      jobId={j.id}
                      scheduledDate={j.scheduled_date}
                    />
                  </div>
                  {j.address ? (
                    <div className="text-xs truncate" style={{ color: colors.muted }}>{j.address}</div>
                  ) : null}
                  {(j.customer_gate_code || j.gate_code) ? (
                    <div className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold"
                         style={{ background: "#FEF3C7", color: "#92400E", border: "1px solid #FDE68A",
                                  fontFamily: "ui-monospace, SFMono-Regular, monospace" }}
                         data-testid={`job-gate-code-${j.id}`}>
                      🔑 Gate: {j.customer_gate_code || j.gate_code}
                    </div>
                  ) : null}
                  {/* Feb-2026 Note-pill — specialty-specific service note. */}
                  {j.service_note ? (
                    <div className="mt-1">
                      <ServiceNotePill
                        note={j.service_note}
                        serviceType={j.service_type}
                        jobId={j.id}
                        compact
                      />
                    </div>
                  ) : null}
                  {(j.customer_notes || j.account_notes) ? (
                    <div className="text-[11px] mt-1 line-clamp-2" style={{ color: colors.onSurfaceSecondary }}
                         data-testid={`job-notes-preview-${j.id}`}>
                      <span className="font-semibold">Notes: </span>
                      {String(j.customer_notes || j.account_notes).slice(0, 60)}
                      {String(j.customer_notes || j.account_notes).length > 60 ? "…" : ""}
                    </div>
                  ) : null}
                  <div className="flex items-center gap-2 mt-1 text-xs" style={{ color: colors.muted }}>
                    <FileText size={11} />
                    <span>{jobHours(j)}</span>
                    {/* Phase 30X · time-of-day removed. Schedule is per-day. */}
                  </div>
                </div>
                <div
                  className="px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide"
                  style={{ background: pill.bg, color: pill.fg }}
                >
                  {pill.label}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); onOpenJob(j.id); }}
                  style={{ background: "transparent", border: 0, cursor: "pointer", color: colors.muted }}
                  data-testid={`grid-open-${j.id}`}
                  aria-label="Open job detail"
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


/**
 * Phase 21 · Feb 2026 · Addition B — Tech color legend.
 *
 * Renders a horizontal scroll strip above the calendar mapping each
 * active tech to their display color. Only shows techs with any
 * indication of activity so it doesn't clutter with archived users.
 */
function TechColorLegend({ techs, techColorMap }) {
  const active = React.useMemo(() => {
    return (techs || [])
      .filter((t) => t?.name && (t.active !== false))
      .map((t) => {
        const id = t.id || t.user_id;
        return {
          id,
          name: t.name,
          color: techColorMap.get(id) || hashedTechColor(id),
          isExplicit: !!t.display_color_hex,
        };
      });
  }, [techs, techColorMap]);
  if (active.length === 0) return null;
  return (
    <div
      className="flex items-center gap-3 overflow-x-auto pb-2 mb-2"
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid="calendar-tech-legend"
    >
      <span
        className="text-[10px] font-bold uppercase tracking-wider shrink-0"
        style={{ color: colors.muted }}
      >
        Techs
      </span>
      {active.map((t) => (
        <span
          key={t.id}
          className="inline-flex items-center gap-1.5 shrink-0"
          data-testid={`calendar-tech-legend-item-${t.id}`}
          data-color={t.color}
          data-explicit={t.isExplicit ? "1" : "0"}
          title={t.isExplicit ? `${t.name} (${t.color})` : `${t.name} (fallback color)`}
        >
          <span
            className="w-3 h-3 rounded-sm"
            style={{
              backgroundColor: t.color,
              border: t.isExplicit ? "none" : `1px dashed ${colors.border}`,
            }}
          />
          <span className="text-xs" style={{ color: colors.onSurface }}>{t.name}</span>
        </span>
      ))}
    </div>
  );
}

