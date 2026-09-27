/**
 * Phase 11 · Feb 2026 — Equipment Service Trackers (Filter & Salt Cell).
 *
 * Two list pages (``/tracking/filter``, ``/tracking/salt-cell``) plus a
 * spreadsheet-style manage view (``/tracking/{type}/manage``).
 *
 * Visual language (per reference screenshot + user feedback):
 *   · Only the "Due Date" cell tints per status:
 *       green = current, orange = coming due, red = past due.
 *     The row background stays neutral; the interval chip stays green.
 *   · Row icon color is theme-per-type (filter=green, salt cell=teal),
 *     NOT status-per-tracker.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Filter as FilterIcon,
  Droplets,
  Search,
  Settings2,
  ChevronLeft,
  ChevronRight,
  Plus,
  Trash2,
  CheckCircle2,
  Save,
  List as ListIcon,
  CalendarDays,
} from "lucide-react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { toast } from "sonner";
import CustomerCombobox from "@/components/customers/CustomerCombobox";

// ─── Type theming (semantic per tracker type, NOT status) ───────────
const TYPE_THEME = {
  filter: {
    label: "Filter",
    IconEl: FilterIcon,
    iconBg: "#DCFCE7",     // green-100
    iconFg: "#16A34A",     // green-600
    headerAccent: "#16A34A",
  },
  salt_cell: {
    label: "Salt Cell",
    IconEl: Droplets,
    iconBg: "#CCFBF1",     // teal-100
    iconFg: "#0D9488",     // teal-600
    headerAccent: "#0D9488",
  },
};

const STATUS_COLOR = {
  current: "#16A34A",     // green-600
  coming_due: "#EA580C",  // orange-600
  past_due: "#DC2626",    // red-600
};

const STATUS_LABEL = {
  current: "Current",
  coming_due: "Coming Due",
  past_due: "Past Due",
};

const STATUS_FILTERS = [
  { v: "", l: "All" },
  { v: "current", l: "Current" },
  { v: "coming_due", l: "Coming Due" },
  { v: "past_due", l: "Past Due" },
];


function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, {
      month: "short", day: "numeric", year: "numeric",
    });
  } catch {
    return iso;
  }
}


// ═══════════════════════════════════════════════════════════════════
// Feb-2026 · Pool Service PS-C — inline month-grid calendar.
//
//   Rendered inside ``EquipmentTrackerListPage`` when the user
//   toggles from List → Calendar.  Deliberately built inline (no
//   new dep) — the tracker page's visual needs are narrow (day
//   cells + event dots + month nav), and the codebase-standard
//   ``react-big-calendar`` (used by ``pages/schedule/CalendarSchedule
//   .jsx``) is overkill here (drag-drop, day/week/month/agenda
//   views, event editing).  ``components/ui/calendar.jsx`` is a
//   shadcn date-picker — not an event-display grid.
//
//   Palette (PS-C ruling #6):
//     · Navy #1B1F5C — inactive toggle text/border.
//     · Blue #3B82F6 — active toggle background + event dots.
//
//   Events on a day cell: rendered as up-to-3 stacked dots plus a
//   ``+N`` count when there are more.  Clicking any event dot OR
//   the day cell deep-links to the tracker's row (highlighted by
//   query param ``?focus={id}`` — the list surface reads it and
//   scrolls the row into view).
// ═══════════════════════════════════════════════════════════════════
const _MONTH_LABELS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const _WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];


function _yyyy_mm_dd(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}


function _startOfMonthGrid(year, monthIndex) {
  // Grid always starts on the Sunday <= day 1 of the month, so
  // the first row includes the trailing days of the prior month.
  const first = new Date(year, monthIndex, 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return start;
}


function TrackerCalendarGrid({ rows, trackerType, onDayClick,
                                 onEventClick }) {
  const today = useMemo(() => new Date(), []);
  const [cursor, setCursor] = useState({
    year: today.getFullYear(),
    monthIndex: today.getMonth(),
  });

  // Group rows by their ``due_at`` day-key (YYYY-MM-DD).
  const eventsByDay = useMemo(() => {
    const out = {};
    (rows || []).forEach((r) => {
      const raw = r?.due_at;
      if (!raw) return;
      // ``due_at`` from the backend is a date-only ISO ("2026-02-15"),
      // rendered via fmtDate elsewhere with a "T00:00:00" suffix.
      // Take the first 10 chars as the day-key so we don't
      // introduce a tz round-trip.
      const key = String(raw).slice(0, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return;
      (out[key] ||= []).push(r);
    });
    return out;
  }, [rows]);

  const monthEventCount = useMemo(() => {
    return Object.entries(eventsByDay).filter(([key]) => {
      const [y, m] = key.split("-").map(Number);
      return y === cursor.year && (m - 1) === cursor.monthIndex;
    }).reduce((acc, [, evs]) => acc + evs.length, 0);
  }, [eventsByDay, cursor]);

  const gridStart = _startOfMonthGrid(cursor.year, cursor.monthIndex);
  // Always render 6 weeks (42 cells) so the grid height doesn't
  // jitter between months with different week counts.
  const cells = useMemo(() => {
    const out = [];
    for (let i = 0; i < 42; i += 1) {
      const d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      out.push(d);
    }
    return out;
  }, [gridStart]);

  function shiftMonth(delta) {
    setCursor((cur) => {
      const m = cur.monthIndex + delta;
      const yearShift = Math.floor(m / 12);
      const monthIndex = ((m % 12) + 12) % 12;
      return { year: cur.year + yearShift, monthIndex };
    });
  }
  function jumpToday() {
    setCursor({ year: today.getFullYear(),
                  monthIndex: today.getMonth() });
  }

  const _todayKey = _yyyy_mm_dd(today);
  const _headerLabel = `${_MONTH_LABELS[cursor.monthIndex]} ${cursor.year}`;

  return (
    <div
      className="bg-white rounded-xl border border-zinc-200 overflow-hidden"
      data-testid={`tracker-calendar-${trackerType}`}
    >
      {/* Month strip */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-200">
        <button
          onClick={() => shiftMonth(-1)}
          className="p-1.5 rounded-md hover:bg-zinc-100 text-zinc-600"
          aria-label="Previous month"
          data-testid="tracker-calendar-prev-month"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-3">
          <div
            className="text-sm font-semibold"
            style={{ color: "#1B1F5C" }}
            data-testid="tracker-calendar-month-label"
          >
            {_headerLabel}
          </div>
          <button
            onClick={jumpToday}
            className="text-xs px-2 py-0.5 rounded-md border border-zinc-200 text-zinc-600 hover:bg-zinc-50"
            data-testid="tracker-calendar-today-btn"
          >
            Today
          </button>
        </div>
        <button
          onClick={() => shiftMonth(1)}
          className="p-1.5 rounded-md hover:bg-zinc-100 text-zinc-600"
          aria-label="Next month"
          data-testid="tracker-calendar-next-month"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* Weekday header */}
      <div className="grid grid-cols-7 border-b border-zinc-200 bg-zinc-50">
        {_WEEKDAY_LABELS.map((w) => (
          <div
            key={w}
            className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500 py-2 text-center"
          >
            {w}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div
        className="grid grid-cols-7 relative"
        data-testid="tracker-calendar-grid"
      >
        {cells.map((d, i) => {
          const key = _yyyy_mm_dd(d);
          const inMonth = d.getMonth() === cursor.monthIndex;
          const isToday = key === _todayKey;
          const events = eventsByDay[key] || [];
          return (
            <button
              key={i}
              onClick={() => onDayClick && onDayClick(key, events)}
              className="text-left px-2 py-2 border-b border-r border-zinc-100 min-h-[84px] focus:outline-none focus:z-10 focus:ring-2 focus:ring-offset-0"
              style={{
                background: inMonth ? "#fff" : "#F8FAFC",
                color: inMonth ? "#111827" : "#94A3B8",
              }}
              data-testid={`tracker-calendar-day-${key}`}
              data-in-month={String(inMonth)}
              data-event-count={events.length}
            >
              <div
                className="inline-flex items-center justify-center text-[12px] font-semibold rounded-full w-6 h-6"
                style={
                  isToday
                    ? { background: "#3B82F6", color: "#FFFFFF" }
                    : {}
                }
              >
                {d.getDate()}
              </div>
              {events.length > 0 ? (
                <div className="mt-1 space-y-0.5">
                  {events.slice(0, 3).map((ev) => (
                    <div
                      key={ev.id}
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEventClick && onEventClick(ev);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          e.stopPropagation();
                          onEventClick && onEventClick(ev);
                        }
                      }}
                      className="flex items-center gap-1.5 truncate text-[11px] font-medium hover:underline"
                      style={{ color: "#1B1F5C" }}
                      data-testid={`tracker-calendar-event-${ev.id}`}
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ background: "#3B82F6" }}
                      />
                      <span className="truncate">
                        {ev.customer_name || "Tracker"}
                      </span>
                    </div>
                  ))}
                  {events.length > 3 ? (
                    <div
                      className="text-[10px] font-semibold"
                      style={{ color: "#1B1F5C" }}
                      data-testid={`tracker-calendar-day-${key}-more`}
                    >
                      +{events.length - 3} more
                    </div>
                  ) : null}
                </div>
              ) : null}
            </button>
          );
        })}

        {/* Empty-month overlay (ruling #5) — a subtle centered
            note that never blocks the day-cell clicks. */}
        {monthEventCount === 0 ? (
          <div
            className="pointer-events-none absolute inset-0 flex items-center justify-center"
            data-testid={`tracker-calendar-empty-${trackerType}`}
          >
            <div
              className="px-4 py-2 rounded-full text-xs font-semibold"
              style={{
                background: "rgba(27, 31, 92, 0.06)",
                color: "#1B1F5C",
              }}
            >
              No maintenance scheduled this month
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}


// LocalStorage key for the List/Calendar preference (PS-C ruling
// #3).  Keyed per-tracker so filter + salt cell preferences don't
// clobber each other.
function _viewPrefKey(trackerType) {
  return `tracker_view_pref:${trackerType}`;
}




// ═══════════════════════════════════════════════════════════════════════
// List view: /tracking/filter and /tracking/salt-cell
// ═══════════════════════════════════════════════════════════════════════
export function EquipmentTrackerListPage({ trackerType }) {
  const theme = TYPE_THEME[trackerType];
  const _nav = useNavigate();

  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({ current: 0, coming_due: 0, past_due: 0 });
  const [statusFilter, setStatusFilter] = useState("");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  // Feb-2026 · PS-C — List/Calendar toggle.  Preference persisted
  // per-tracker in localStorage (ruling #3); default "list" for
  // existing users so nothing changes on first paint.
  const [viewMode, setViewMode] = useState(() => {
    try {
      const stored = window.localStorage.getItem(
        _viewPrefKey(trackerType),
      );
      return stored === "calendar" ? "calendar" : "list";
    } catch {
      return "list";
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        _viewPrefKey(trackerType), viewMode,
      );
    } catch {
      /* localStorage may be blocked in test envs — safe no-op */
    }
  }, [trackerType, viewMode]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        tracker_type: trackerType,
        is_active: "true",
      });
      if (statusFilter) params.set("status", statusFilter);
      if (q) params.set("q", q);
      const res = await api.get(`/equipment/trackers?${params}`);
      setRows(res.trackers || []);
      setCounts(res.counts_by_status || { current: 0, coming_due: 0, past_due: 0 });
    } catch (e) {
      toast.error(e.message || "Failed to load trackers");
    } finally {
      setLoading(false);
    }
  }, [trackerType, statusFilter, q]);

  useEffect(() => { load(); }, [load]);

  async function markCleaned(t) {
    setBusy(t.id);
    try {
      await api.post(`/equipment/trackers/${t.id}/mark-cleaned`, {});
      toast.success(`${theme.label} cleaning logged`);
      load();
    } catch (e) {
      toast.error(e.message || "Failed to mark cleaned");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50" data-testid={`tracker-list-page-${trackerType}`}>
      {/* Header strip */}
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{ background: theme.iconBg, color: theme.iconFg }}
            >
              <theme.IconEl className="w-6 h-6" strokeWidth={2} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-900"
                  data-testid={`tracker-list-title-${trackerType}`}>
                {theme.label} Cleaning Tracker
              </h1>
              <p className="text-sm text-zinc-500 mt-0.5">
                {rows.length} tracker{rows.length === 1 ? "" : "s"}
                {" · "}
                <span style={{ color: STATUS_COLOR.past_due, fontWeight: 600 }}>
                  {counts.past_due} past due
                </span>
                {" · "}
                <span style={{ color: STATUS_COLOR.coming_due, fontWeight: 600 }}>
                  {counts.coming_due} coming due
                </span>
              </p>
            </div>
          </div>
          <Link
            to={`/tracking/${trackerType === "salt_cell" ? "salt-cell" : "filter"}/manage`}
            data-testid={`tracker-manage-link-${trackerType}`}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 transition"
          >
            <Settings2 className="w-4 h-4" />
            Manage tracking
          </Link>
        </div>

        {/* Filters strip */}
        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#0284C7]" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search customer name or address…"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-zinc-200 bg-white text-sm placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-300"
              data-testid={`tracker-search-${trackerType}`}
            />
          </div>
          <div className="flex items-center gap-1 bg-zinc-100 rounded-lg p-1">
            {STATUS_FILTERS.map((s) => (
              <button
                key={s.v || "all"}
                onClick={() => setStatusFilter(s.v)}
                data-testid={`tracker-status-filter-${s.v || "all"}`}
                className={`px-3 py-1 text-sm rounded-md transition ${
                  statusFilter === s.v
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-600 hover:text-zinc-900"
                }`}
              >
                {s.l}
              </button>
            ))}
          </div>
          {/* Feb-2026 · PS-C — List/Calendar view toggle.  Navy
              inactive / Blue active per ruling #6.  Search + status
              filters still apply to the row set the calendar reads
              from, so users can e.g. filter by "past due" then flip
              to Calendar to see them plotted on the month. */}
          <div
            className="ml-auto flex items-center rounded-lg overflow-hidden"
            style={{ border: `1px solid #1B1F5C` }}
            data-testid="tracker-view-toggle"
          >
            <button
              onClick={() => setViewMode("list")}
              data-testid="tracker-view-list"
              aria-pressed={viewMode === "list"}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                background: viewMode === "list" ? "#3B82F6" : "#FFFFFF",
                color:      viewMode === "list" ? "#FFFFFF" : "#1B1F5C",
              }}
            >
              <ListIcon className="w-3.5 h-3.5" />
              List
            </button>
            <button
              onClick={() => setViewMode("calendar")}
              data-testid="tracker-view-calendar"
              aria-pressed={viewMode === "calendar"}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                background: viewMode === "calendar" ? "#3B82F6" : "#FFFFFF",
                color:      viewMode === "calendar" ? "#FFFFFF" : "#1B1F5C",
                borderLeft: "1px solid #1B1F5C",
              }}
            >
              <CalendarDays className="w-3.5 h-3.5" />
              Calendar
            </button>
          </div>
        </div>
      </div>

      {/* Body — List (existing) OR Calendar (PS-C).  Loading /
          empty states still route through the list body since
          they read from the row set + filters. */}
      {viewMode === "calendar" && !loading ? (
        <div className="max-w-7xl mx-auto px-6 py-6">
          <TrackerCalendarGrid
            rows={rows}
            trackerType={trackerType}
            onEventClick={(ev) => {
              // Ruling #4 — deep-link to the tracker row via a
              // ``?focus={id}`` query param.  The list view is
              // still the source of truth for row detail; scrolling
              // + highlight is a listener no-op today (parked for a
              // follow-up), but the URL change gives the user a
              // shareable anchor.
              _nav(
                `/tracking/${trackerType === "salt_cell" ? "salt-cell" : "filter"}?focus=${ev.id}`,
              );
              setViewMode("list");
            }}
            onDayClick={() => { /* no-op today */ }}
          />
        </div>
      ) : null}

      {/* List body */}
      {viewMode === "list" ? (
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-2">
        {loading && (
          <div className="text-center py-16 text-zinc-500" data-testid={`tracker-loading-${trackerType}`}>
            Loading trackers…
          </div>
        )}
        {!loading && rows.length === 0 && (
          <div className="text-center py-16 bg-white rounded-xl border border-dashed border-zinc-200"
               data-testid={`tracker-empty-${trackerType}`}>
            <theme.IconEl className="w-8 h-8 mx-auto text-zinc-300" />
            <p className="mt-3 text-sm text-zinc-500">
              No {theme.label.toLowerCase()} trackers match this view.
            </p>
            <Link
              to={`/tracking/${trackerType === "salt_cell" ? "salt-cell" : "filter"}/manage`}
              className="inline-block mt-4 text-sm text-zinc-900 underline"
            >
              Add or import trackers
            </Link>
          </div>
        )}
        {!loading && rows.map((t) => (
          <div
            key={t.id}
            className="bg-white rounded-xl border border-zinc-200 px-4 py-3 flex items-center gap-4 hover:border-zinc-300 transition"
            data-testid={`tracker-row-${t.id}`}
          >
            <div
              className="w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: theme.iconBg, color: theme.iconFg }}
            >
              <theme.IconEl className="w-5 h-5" strokeWidth={2} />
            </div>

            <div className="min-w-0 flex-1">
              <div className="font-medium text-zinc-900 truncate"
                   data-testid={`tracker-row-name-${t.id}`}>
                {t.customer_name || "—"}
              </div>
              <div className="text-sm text-zinc-500 truncate">
                {t.property_address || ""}
              </div>
              <div className="mt-1.5">
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  style={{ background: "#DCFCE7", color: "#166534" }}
                  data-testid={`tracker-interval-chip-${t.id}`}
                >
                  every {t.interval_months} {t.interval_months === 1 ? "month" : "months"}
                </span>
              </div>
            </div>

            <div className="flex-shrink-0 text-right">
              <div className="text-xs uppercase tracking-wide text-zinc-400 mb-0.5">
                Due Date
              </div>
              <div
                className="text-sm font-semibold"
                style={{ color: STATUS_COLOR[t.status_computed] || STATUS_COLOR.current }}
                data-testid={`tracker-due-date-${t.id}`}
                data-status={t.status_computed}
              >
                {fmtDate(t.due_at)}
              </div>
              <div className="text-[11px] text-zinc-400 mt-0.5">
                {STATUS_LABEL[t.status_computed]}
              </div>
            </div>

            <button
              onClick={() => markCleaned(t)}
              disabled={busy === t.id}
              className="ml-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-200 text-sm text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 transition"
              data-testid={`tracker-mark-cleaned-${t.id}`}
            >
              <CheckCircle2 className="w-4 h-4" style={{ color: theme.iconFg }} />
              Mark cleaned
            </button>
          </div>
        ))}
      </div>
      ) : null}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════
// Manage view: /tracking/filter/manage and /tracking/salt-cell/manage
// Spreadsheet-style editable grid — inline edit interval_months,
// quick-toggle is_active. Save-on-blur through the existing PATCH.
// ═══════════════════════════════════════════════════════════════════════
export function EquipmentTrackerManagePage({ trackerType }) {
  const theme = TYPE_THEME[trackerType];
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ tracker_type: trackerType });
      if (statusFilter) params.set("status", statusFilter);
      const res = await api.get(`/equipment/trackers?${params}`);
      setRows(res.trackers || []);
    } catch (e) {
      toast.error(e.message || "Failed to load trackers");
    } finally {
      setLoading(false);
    }
  }, [trackerType, statusFilter]);

  useEffect(() => { load(); }, [load]);

  async function patchRow(id, patch) {
    try {
      const updated = await api.patch(`/equipment/trackers/${id}`, patch);
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...updated } : r)));
      toast.success("Saved");
    } catch (e) {
      toast.error(e.message || "Save failed");
      load();
    }
  }

  async function removeRow(id) {
    const ok = await mustConfirm({
      title: "Deactivate this tracker?",
      description: "History is kept for audit; only new reminders stop.",
      tone: "danger", confirmText: "Deactivate",
    });
    if (!ok) return;
    try {
      await api.del(`/equipment/trackers/${id}`);
      setRows((prev) => prev.filter((r) => r.id !== id));
      toast.success("Deactivated");
    } catch (e) {
      toast.error(e.message || "Delete failed");
    }
  }

  async function openAdd() {
    if (customers.length === 0) {
      try {
        const list = await api.get("/customers?is_active=true");
        const arr = Array.isArray(list) ? list : (list.customers || list.items || []);
        setCustomers(arr);
      } catch (e) {
        toast.error(e.message || "Failed to load customers");
        return;
      }
    }
    setShowAdd(true);
  }

  const backHref = `/tracking/${trackerType === "salt_cell" ? "salt-cell" : "filter"}`;

  return (
    <div className="min-h-screen bg-zinc-50" data-testid={`tracker-manage-page-${trackerType}`}>
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              to={backHref}
              className="p-2 rounded-lg hover:bg-zinc-100 transition"
              data-testid={`tracker-manage-back-${trackerType}`}
            >
              <ChevronLeft className="w-5 h-5 text-zinc-600" />
            </Link>
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ background: theme.iconBg, color: theme.iconFg }}
            >
              <theme.IconEl className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-zinc-900">
                Manage {theme.label} Trackers
              </h1>
              <p className="text-sm text-zinc-500 mt-0.5">
                Inline-edit cadence, deactivate, or add new trackers.
              </p>
            </div>
          </div>
          <button
            onClick={openAdd}
            data-testid={`tracker-add-btn-${trackerType}`}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 transition"
          >
            <Plus className="w-4 h-4" />
            Add tracker
          </button>
        </div>
        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.v || "all"}
              onClick={() => setStatusFilter(s.v)}
              data-testid={`tracker-manage-status-${s.v || "all"}`}
              className={`px-3 py-1 text-sm rounded-md transition ${
                statusFilter === s.v
                  ? "bg-zinc-900 text-white"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
              }`}
            >
              {s.l}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
          <div className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
            <div className="col-span-4">Customer</div>
            <div className="col-span-3">Address</div>
            <div className="col-span-2">Interval (months)</div>
            <div className="col-span-2">Due Date</div>
            <div className="col-span-1 text-right">Active</div>
          </div>
          {loading && (
            <div className="py-10 text-center text-sm text-zinc-500">Loading…</div>
          )}
          {!loading && rows.length === 0 && (
            <div className="py-10 text-center text-sm text-zinc-400">
              No trackers to manage.
            </div>
          )}
          {!loading && rows.map((t) => (
            <div key={t.id}
                 data-testid={`tracker-manage-row-${t.id}`}
                 className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-100 items-center hover:bg-zinc-50/70">
              <div className="col-span-4 text-sm text-zinc-900 truncate">
                {t.customer_name || "—"}
              </div>
              <div className="col-span-3 text-sm text-zinc-500 truncate">
                {t.property_address || ""}
              </div>
              <div className="col-span-2">
                <IntervalInput
                  value={t.interval_months}
                  onSave={(v) => patchRow(t.id, { interval_months: v })}
                  testid={`tracker-manage-interval-${t.id}`}
                />
              </div>
              <div className="col-span-2 text-sm font-medium"
                   style={{ color: STATUS_COLOR[t.status_computed] || STATUS_COLOR.current }}>
                {fmtDate(t.due_at)}
              </div>
              <div className="col-span-1 flex items-center justify-end gap-2">
                <label className="inline-flex items-center cursor-pointer" title="Active">
                  <input
                    type="checkbox"
                    checked={!!t.is_active}
                    onChange={(e) => patchRow(t.id, { is_active: e.target.checked })}
                    data-testid={`tracker-manage-active-${t.id}`}
                    className="w-4 h-4 rounded border-zinc-300"
                  />
                </label>
                <button
                  onClick={() => removeRow(t.id)}
                  className="p-1.5 rounded hover:bg-red-50 text-zinc-400 hover:text-red-600 transition"
                  data-testid={`tracker-manage-delete-${t.id}`}
                  title="Deactivate"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {showAdd && (
        <AddTrackerDialog
          trackerType={trackerType}
          customers={customers}
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }}
        />
      )}
    </div>
  );
}


// ─── Inline save-on-blur interval editor ─────────────────────────────
function IntervalInput({ value, onSave, testid }) {
  const [v, setV] = useState(String(value ?? ""));
  useEffect(() => { setV(String(value ?? "")); }, [value]);
  return (
    <input
      type="number"
      min="1"
      max="120"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        const n = parseInt(v, 10);
        if (!Number.isFinite(n) || n < 1 || n > 120) {
          setV(String(value ?? ""));
          toast.error("Interval must be between 1 and 120 months");
          return;
        }
        if (n !== value) onSave(n);
      }}
      data-testid={testid}
      className="w-20 px-2 py-1 rounded border border-zinc-200 text-sm text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-300"
    />
  );
}


// ─── Add-tracker dialog ──────────────────────────────────────────────
function AddTrackerDialog({ trackerType, customers, onClose, onCreated }) {
  const theme = TYPE_THEME[trackerType];
  const [customerId, setCustomerId] = useState("");
  const [interval, setInterval] = useState(trackerType === "salt_cell" ? 12 : 3);
  const [lastCleaned, setLastCleaned] = useState(new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!customerId) {
      toast.error("Select a customer");
      return;
    }
    setSaving(true);
    try {
      await api.post("/equipment/trackers", {
        customer_id: customerId,
        tracker_type: trackerType,
        interval_months: interval,
        last_cleaned_at: lastCleaned,
        is_active: true,
      });
      toast.success(`${theme.label} tracker added`);
      onCreated();
    } catch (e) {
      toast.error(e.message || "Failed to add tracker");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-zinc-900/40 flex items-center justify-center z-50 p-4"
         onClick={onClose}
         data-testid={`tracker-add-dialog-${trackerType}`}>
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center"
               style={{ background: theme.iconBg, color: theme.iconFg }}>
            <theme.IconEl className="w-5 h-5" />
          </div>
          <h2 className="text-lg font-semibold text-zinc-900">
            Add {theme.label} Tracker
          </h2>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="text-sm font-medium text-zinc-700">Customer</span>
            <div className="mt-1">
              <CustomerCombobox
                value={customerId}
                onChange={setCustomerId}
                customers={customers}
                testid={`tracker-add-customer-${trackerType}`}
                placeholder="— select —"
              />
            </div>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-zinc-700">Interval (months)</span>
            <input
              type="number" min="1" max="120"
              value={interval}
              onChange={(e) => setInterval(parseInt(e.target.value || "0", 10))}
              data-testid={`tracker-add-interval-${trackerType}`}
              className="mt-1 block w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-zinc-700">Last cleaned</span>
            <input
              type="date"
              value={lastCleaned}
              onChange={(e) => setLastCleaned(e.target.value)}
              data-testid={`tracker-add-last-cleaned-${trackerType}`}
              className="mt-1 block w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
            />
          </label>
        </div>
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm text-zinc-700 hover:bg-zinc-100 transition"
            data-testid={`tracker-add-cancel-${trackerType}`}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 transition disabled:opacity-50"
            data-testid={`tracker-add-submit-${trackerType}`}
          >
            <Save className="w-4 h-4" />
            {saving ? "Adding…" : "Add tracker"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ─── Convenience route wrappers ──────────────────────────────────────
export function FilterTrackerListPage()   { return <EquipmentTrackerListPage   trackerType="filter" />; }
export function FilterTrackerManagePage() { return <EquipmentTrackerManagePage trackerType="filter" />; }
export function SaltCellTrackerListPage()   { return <EquipmentTrackerListPage   trackerType="salt_cell" />; }
export function SaltCellTrackerManagePage() { return <EquipmentTrackerManagePage trackerType="salt_cell" />; }
