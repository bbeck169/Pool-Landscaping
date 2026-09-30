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
import { format, parse, startOfWeek, getDay, addDays, startOfDay, endOfDay, startOfQuarter, endOfMonth } from "date-fns";
import { enUS } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
// Feb-2026 · Schedule polish — amber-accented job-notes chip.
import JobNotesCallout from "@/components/schedule/JobNotesCallout";
import { Plus, Search, X as XIcon, Filter, ChevronLeft, ChevronRight,
         CheckCircle2, Move as MoveIcon, ArrowUp, FileText, Star, Check, Trash2, Loader2, UsersRound,
         Pencil, Key, Navigation2, ChevronDown, ChevronUp, Map as MapIcon, RefreshCw } from "lucide-react";
// Phase F1 · Feb-2026 — Bulk multi-stop "Navigate route" URL builder.
import { runBulkNavigateRoute } from "../../lib/googleMapsRoute";

import { api } from "@/api";
// BULK-RESCHEDULE · Feb-2026 — imperative confirm before firing the
// server-side bulk move.  Uses the module-level ``mustConfirm``
// escape hatch (registered by ``<ConfirmProvider>`` at the app
// root) so we don't have to hoist a ``useConfirm()`` hook through
// the deeply-nested pill / grid components.
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { bulkReschedule as _bulkRescheduleHelper }
  from "@/lib/bulkReschedule";
import { colors, font } from "@/theme";
// Phase K73 · Feb-2026 — crew-hued deterministic palette for
// schedule map pins + calendar events. Replaces the pre-K73 flat
// 10-color hash palette while keeping ``display_color_hex`` wins.
import { crewHuedColorFromTech, groupByCrewForLegend } from "../../lib/crewPalette";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { useAuth } from "@/auth";
// Feb-2026 · Phase 1 — Tech "On my way" SMS CTA.
import OnMyWayButton from "@/components/schedule/OnMyWayButton";
// Feb-2026 · Schedule card redesign — customer name + address now
// open Google Maps directions directly (no dedicated Navigate
// button).  Shared helpers in ``@/utils/directions`` produce the
// same URL shape as the pre-Feb-2026 ``<NavigateJobButton />`` did.
import { buildDirectionsUrl, openDirections } from "@/utils/directions";
// Feb-2026 · Schedule enhancement — pending-no-crew admin nudge.
import PendingNoCrewNudge from "@/components/schedule/PendingNoCrewNudge";
// Feb-2026 · Phase 1 — Could-Not-Service modal.
import CouldNotServiceModal from "@/components/schedule/CouldNotServiceModal";
import { Gate, useCan } from "@/hooks/usePermissions";
import { useClockInGate, ClockInGateDialog } from "@/hooks/useClockInGate";
import ChecklistModal from "@/components/checklist/ChecklistModal";
import ServiceNotePill from "@/components/schedule/ServiceNotePill";
import TechWeatherWidget from "@/components/Weather/WeatherWidget";
import JobRainFlag from "@/components/Weather/JobRainFlag";
// SO-A · Feb-2026 — MARCO Suggestions right-side drawer.
import { MarcoSuggestionsPanel } from
  "@/components/schedule/MarcoSuggestionsPanel";
import WeekStrip from "@/components/schedule/WeekStrip";
// Phase 27 follow-up · Feb-2026 — the primary /schedule surface is
// CalendarSchedule (not TodaySchedule), so the compact tech-avatar
// swap has to live here too. Sized ``xs`` (20px) so per-job card
// height is preserved.
// Feb-2026 · Schedule polish — the per-card <TechAvatar> was
// removed from the JobRow; the import lives in
// /app/frontend/src/components/common/TechAvatar.jsx and is
// still used elsewhere (customer profile, dispatch board).
// Intentionally not imported here.
import ScheduleJobEditModal from "@/pages/schedule/ScheduleJobEditModal";
import { useNumberedOrder, NumberOrderInput, ReorderBanner, ReorderErrorBanner, BulkReorderModal, REORDER_LANE_ERROR_TEXT, REORDER_MIXED_LANE_ERROR_TEXT } from "@/pages/schedule/NumberedReorder";
// Feb-2026 · Batch #4 · Item 3 (continuation) — shared refresh
// button used by every schedule surface (month/agenda/grid + Today).
import ScheduleRefreshButton from "@/components/schedule/ScheduleRefreshButton";
import { CustomerLink, AddressLink } from "@/components/customer";
// Feb-2026 · numbered-order reorder — the ScheduleDayDnDPanel import
// was removed as part of the DnD → numbered-input pivot.  The number
// input primitives + the bulk-reorder modal are imported above.
// Feb-2026 · Google-Maps stops map above the DnD panel (reuses the
// app-wide ``<APIProvider>`` mounted in ``layouts/AppLayout.jsx``).
import ScheduleMap from "@/pages/schedule/ScheduleMap";
// Feb-2026 · P0 defensive · Google Maps SDK failures (billing
// disabled, key rotation, quota exhausted) throw inside
// @vis.gl/react-google-maps' render tree. Without a tight
// boundary around ScheduleMap, that throw takes out the entire
// schedule day view. Boundary keeps the rest of the page usable.
import ScheduleMapErrorBoundary from "@/components/schedule/ScheduleMapErrorBoundary";
// Feb 2026 · P0 Timezone Fix (Section C follow-up) — tenant-tz-aware
// "today" helpers. Same helpers already used by TodaySchedule for
// the analogous UTC-midnight bug where jobs hop dates at 5 PM local
// for a Phoenix tenant viewed from an eastern-tz browser. Source-of-
// truth ladder: server ``data.tz`` → tenant context → America/Phoenix.
import {
  getTenantTodayISO,
  getTenantISODate,
  TENANT_TZ_FALLBACK,
} from "@/lib/tenantTz";
// Phase K50 · Feb-2026 — Schedule job-card status background shading.
// Single source of truth: ``frontend/src/lib/jobStatus.js`` (web) +
// ``mobile/src/lib/jobStatus.ts`` (mobile).  DO NOT inline the hex
// codes here — extend the helper map if a new status is added.
import { jobStatusColor as k50JobStatusColor } from "../../lib/jobStatus";
// Phase P12 · Feb-2026 — Optimize Route error dialog uses the shared
// shadcn ``Dialog`` primitive so the modal inherits the app's a11y +
// focus-trap behavior. Do NOT bespoke this — matches the pattern
// used by every other confirm/error surface on the schedule page.
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";


// Feb-2026 · Schedule-UI · left-border indicator for status.
//   completed → red (#DC2626)
//   everything else (scheduled / active / pending / requested / …) → blue (#2563EB)
// The exact hex mirrors the ``STATUS_COLORS`` table above so future
// palette shifts keep the two in sync; this helper is intentionally
// narrower — a big colored bar is a coarser affordance than the
// existing status pill.
// Phase R1.1 · Feb-2026 — Schedule 500 · technician_id mismatch hotfix.
//
// Warn ONCE per session per bogus ``technician_id`` referenced by a
// job.  A module-level ``Set`` dedups the console noise so a
// tenant with N stale refs logs N warnings, not N × M renders.
// Reset only via a hard page reload — the "session" scope matches
// the mounted CalendarSchedule instance's lifetime.
const _WARNED_MISSING_TECH_IDS = new Set();
function _warnMissingTech(technicianId, jobId) {
  if (!technicianId) return;
  if (_WARNED_MISSING_TECH_IDS.has(technicianId)) return;
  _WARNED_MISSING_TECH_IDS.add(technicianId);
  // eslint-disable-next-line no-console
  console.warn(
    "[CalendarSchedule] job has technician_id not present in techColorMap — "
    + "rendering with neutral (unassigned) styling",
    { technician_id: technicianId, first_job_id: jobId },
  );
}
// Phase R1.1 · Feb-2026 — Neutral fallback color for jobs whose
// ``technician_id`` doesn't resolve to any technician in the tenant
// palette. Rendered as a muted slate so the pill is visible without
// implying a specific tech identity.  Same hex the "unassigned"
// legend row uses (see ``TechColorLegend``).
const _NEUTRAL_UNASSIGNED_HEX = "#94A3B8";

// ─────────────────────────────────────────────────────────────
// Phase P5 · Feb-2026 — Canonical technician_id resolver for the
// filter dropdown.  Parity with the R1.1 tech-color-map fix.
// ─────────────────────────────────────────────────────────────
//
// ``GET /technicians`` returns docs whose ``id`` field IS the
// canonical technicians.id for real tech rows AND for synth rows
// whose linked ``users`` doc has a ``technician_id`` stamped on
// it.  For synth rows on users WITHOUT a ``technician_id``, the
// backend falls back to the user's account id (``users.id``) as
// ``t.id`` — that's the exact shape of bug this phase pins.
//
// Prefer ``t.technician_id`` when the wire carries it explicitly;
// fall back to ``t.id`` for legacy responses.  The result is the
// value we ship on the ``<option value=...>`` AND the value we
// compare against ``job.technician_id`` in the filter predicate.
// No user account id (``users.id``) ever reaches the dropdown or
// the filter after this hop.
function _canonicalTechId(t) {
  if (!t) return "";
  return t.technician_id || t.id || "";
}

// Phase P11 · Feb-2026 — K42-parity lane-match predicate.
// ─────────────────────────────────────────────────────────────
//
// The tech-filter dropdown ships a single canonical id (per
// ``_canonicalTechId`` above), but jobs on the wire can carry
// that id under any of FIVE assignment fields depending on which
// write path stamped them:
//
//   * ``technician_id``           — canonical primary key.
//   * ``assigned_technician_id``  — R1.1 fallback (server P9 jail).
//   * ``assigned_to``             — legacy dispatch flow.
//   * ``tech_user_id``            — reorder-day-route + a few
//                                    older mobile write paths.
//   * ``crew_id``                 — a crew lane (multi-tech dispatch).
//
// The P9 backend jail and P10 lane-scope helper both do the multi-
// field ``$or`` union server-side; the client MUST mirror the same
// disjunction defensively so a stale in-flight response after a
// filter change (or a cache-window hit) doesn't render blanks for
// jobs that legitimately belong to the selected lane. Exported so
// neighbor files (the reorder scope memo in the same page, plus
// any future tech-scoped list page) can reuse the exact idiom.
//
// ``laneId`` acts as an "All" pseudo-value when falsy — every job
// passes. That matches the ``techId === ""`` "All techs" convention.
export function jobMatchesLane(job, laneId) {
  if (!laneId) return true;               // "All" pseudo-value.
  if (!job) return false;
  return (
    job.technician_id === laneId
    || job.assigned_technician_id === laneId
    || job.assigned_to === laneId
    || job.tech_user_id === laneId
    || job.crew_id === laneId
  );
}

export function getStatusBorderColor(status) {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "#DC2626";
  return "#2563EB";
}

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
  // Phase P47 · Feb-2026 — the ``missed`` bucket is written by the
  // auto-cleanup poller (``services/missed_job_scheduler.py``) when
  // a job stays open past ``MISSED_JOB_STALENESS_HOURS``.  Muted
  // red-orange fill + darker fg so it reads as "attention needed,
  // but not the same fire as reopened".
  missed:     { bg: "#FEE2E2", fg: "#B91C1C", label: "Missed" },
};

const jobHours = (j) => {
  const h = j.actual_hours ?? j.billable_hours ?? j.estimated_hours ?? 0;
  return `${(Number(h) || 0).toFixed(2)} BH`;
};
// Feb-2026 · Recurring-star detection — extended to include
// ``recurring_template_id`` so occurrences spawned from a recurring
// template (which typically don't carry the legacy ``is_recurring``
// flag) still render the 🔁 marker on the schedule card.  Exported
// for unit tests — see ``test/schedule-is-recurring-detection.test.jsx``.
// A UUID string is truthy; empty-string / null / undefined are
// falsy, so the loose truthy check handles the defensive cases
// without extra guards.
export const isRecurring = (j) =>
  Boolean(
    j.is_recurring
      || j.recurring
      || (j.recurrence && j.recurrence !== "none")
      || j.recurring_template_id,
  );

const MODE_KEY = "aq-schedule-mode-v1";
// Feb-2026 · Batched Wave #2 — persistent show/hide of the
// schedule map (grid mode). Key MUST match the mobile parity
// storage key in ``mobile/app/(app)/schedule/calendar.tsx``
// (``MAP_VISIBLE_KEY``) so users get a consistent default across
// devices when we eventually sync per-user prefs.
const MAP_VISIBLE_KEY = "schedule.mapVisible";

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
  // Phase P47 · Feb-2026 — muted red-orange for the ``missed``
  // bucket.  Distinct from ``reopened`` (bright red) and
  // ``cancelled`` (grey) so the calendar dot map still reads at a
  // glance.
  missed:     "#B91C1C",
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
  //
  // Phase R1.1 · Feb-2026 — Safe Check.  ``techColorMap`` is now
  // strictly keyed by ``technicians.id`` (see the ``useMemo`` below).
  // If a job's ``technician_id`` isn't in the map:
  //   * ``null`` / undefined → job is unassigned → ``techColor: null``
  //     (existing behavior preserved).
  //   * set-but-not-in-map → dangling ref → render with a NEUTRAL
  //     unassigned color AND WARN once per session (dedup via
  //     ``_WARNED_MISSING_TECH_IDS``).  Previous code fell through to
  //     ``hashedTechColor`` which invented a color per bogus id and
  //     poisoned the legend.
  let techColor = null;
  if (job.technician_id) {
    if (techColorMap && techColorMap.has(job.technician_id)) {
      techColor = techColorMap.get(job.technician_id);
    } else {
      _warnMissingTech(job.technician_id, job.id);
      techColor = _NEUTRAL_UNASSIGNED_HEX;
    }
  }
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
  // Feb 2026 · P0 Timezone Fix (Section C) — resolve the tenant IANA
  // tz once per render. Falls back to ``America/Phoenix`` (the backend
  // default + the TodaySchedule bootstrap value) so a post-5PM local
  // click on "Today" doesn't roll to tomorrow's calendar cell. Refined
  // from ``user.tenant.timezone`` when the auth payload carries it.
  //
  // Phase P15 · Feb-2026 — the picker in Business Settings dispatches
  // ``tenant:settings-updated`` on save. We listen for it and take
  // the new IANA name from ``detail.timezone`` so the "today" cell
  // math + day-window rendering updates without a full page reload.
  // The auth context still holds the pre-save value until the next
  // login (that's the auth layer's contract) — the override lives
  // here so this page reflects the change immediately.
  const [tenantTzOverride, setTenantTzOverride] = useState(null);
  const tenantTz = tenantTzOverride
    || user?.tenant?.timezone
    || user?.tenant_timezone
    || TENANT_TZ_FALLBACK;
  // K65.fix · Feb-2026 — flag that flips when the last load() call
  // aborted on the 20 s client-side hard timeout.  Drives the
  // "[Retry]" affordance on the error banner so the user has a
  // one-click path out of the stuck state instead of the previous
  // infinite "Loading…".
  const [loadTimedOut, setLoadTimedOut] = useState(false);

  // Feb 2026 · Task B — Schedule perf. Cache the last fetched
  // ``[start,end]`` window so that intra-window date navigation
  // (WeekStrip taps, month-cell clicks, arrow keys) doesn't re-hit
  // ``/api/jobs`` on every render. Each round-trip on this endpoint
  // sits at ~150-260ms on preview (network-bound); the enrichment
  // work server-side is <10ms. Skipping the fetch when the target
  // date sits comfortably inside the cached 150-day window makes
  // navigation feel instant and cuts network chatter by ~100% on
  // repeat clicks. ``fetchedRangeRef`` is a ref (not state) so
  // updating it never re-triggers the effect it guards.
  //
  // Format: {startISO: "YYYY-MM-DD", endISO: "YYYY-MM-DD"} or
  // {startISO: null, endISO: null} on cold start.
  const fetchedRangeRef = React.useRef({ startISO: null, endISO: null });
  // Interior safety margin — the cached window is [-60, +90] days
  // around the focus, so a 30-day buffer at each edge means users
  // can navigate ±30 days of the *last fetched* focus without a
  // re-fetch (i.e., 90 days of the interior are reusable).
  const _CACHE_MARGIN_DAYS = 30;

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

  // Feb-2026 · Batched Wave #2 — persistent map show/hide toggle.
  // Rendered above the grid in ``mode === "grid"``. Default = shown
  // (matches mobile default). Persisted to localStorage under the
  // shared ``MAP_VISIBLE_KEY`` so a page reload preserves the pick.
  const [mapVisible, setMapVisible] = useState(() => {
    try {
      const v = localStorage.getItem(MAP_VISIBLE_KEY);
      if (v === "false") return false;
      if (v === "true") return true;
    } catch {}
    return true;
  });
  const toggleMapVisible = React.useCallback(() => {
    setMapVisible((prev) => {
      const next = !prev;
      try { localStorage.setItem(MAP_VISIBLE_KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  // Phase 30W · grid-mode bookkeeping.
  const [checked, setChecked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveDate, setMoveDate] = useState("");
  const [toast, setToast] = useState(null);              // {text, kind:"info"|"err"}
  // Feb-2026 · numbered-order reorder — bulk modal open flag.
  const [bulkReorderOpen, setBulkReorderOpen] = useState(false);
  // Feb-2026 · Optimize Route — payload returned by
  // ``POST /api/schedule/optimize-route``. When present it seeds the
  // BulkReorderModal via ``initialOrder`` + ``optimizeSummary`` +
  // ``optimizeWarnings`` props (see NumberedReorder.jsx). Nulled on
  // modal close so the next open reverts to route_index seed.
  const [optimizePayload, setOptimizePayload] = useState(null);
  const [optimizing, setOptimizing] = useState(false);
  // Phase P12 · Feb-2026 — Optimize Route error dialog. Historically
  // any 4xx/5xx from ``POST /api/schedule/optimize-route`` was
  // swallowed into an ephemeral 3.2s toast (see ``toast_``) — user
  // saw the button do nothing and had no way to copy the code for
  // support. This state powers the shared ``<Dialog>`` render below
  // the page and surfaces ``err.data.detail.code`` + ``.message``
  // in a monospace tag so ops can escalate cleanly. Set on failure,
  // cleared on Close.
  const [optimizeError, setOptimizeError] = useState(null);
  // Phase 31 · Step 2b — tap-job opens the checklist modal in place of
  // navigating away to /jobs/:id. Preserves the /schedule URL so the
  // grid/calendar toggle, filters, and range presets survive the close.
  const [checklistJobId, setChecklistJobId] = useState(null);
  // Feb-2026 · Schedule-screen inline edit — admin+ opens the shared
  // ScheduleJobEditModal without leaving /schedule. On save we mutate
  // ``rawJobs`` in place so the affected card re-renders with the
  // new values (no full reload). Delete removes the card in place.
  const [editingJob, setEditingJob] = useState(null);
  // Feb-2026 · Phase 1 — Could-Not-Service modal target job.
  const [cnsJob, setCnsJob] = useState(null);
  const patchJobInPlace = React.useCallback((patched) => {
    setRawJobs((prev) => (prev || []).map((r) =>
      r.id === patched.id ? { ...r, ...patched } : r,
    ));
  }, []);
  const removeJobInPlace = React.useCallback((jid) => {
    setRawJobs((prev) => (prev || []).filter((r) => r.id !== jid));
  }, []);
  // Phase 56.3.C RBAC — technicians must not create jobs, regardless of
  // their department (pool / landscape / both). Admins + super_admins are
  // unaffected. Backend already enforces this via `require_admin` on
  // POST /api/jobs; the flag below hides the corresponding UI affordances
  // so techs never see a broken create surface.
  const canCreateJobs = ["admin", "super_admin"].includes((user?.role || "").toLowerCase());
  // Phase 56.3 follow-up — clock-in gate for landscape techs opening events.
  const clockGate = useClockInGate(user);

  // SO-A · Feb-2026 — MARCO Suggestions panel state.  ``marcoJob`` is the
  // job we're computing recommendations for; opening the panel is driven
  // by ``onSelectEvent`` for admins/managers only.
  const [marcoJob, setMarcoJob] = useState(null);

  // Feb-2026 · Schedule multi-select soft-delete state ------------------
  // ``selectedJobIds`` is a Set<string> keyed on job.id. Toolbar only
  // renders when it has at least one entry AND the caller is admin+.
  const [selectedJobIds, setSelectedJobIds] = useState(() => new Set());
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const canMultiSelectDelete = ["admin", "super_admin", "manager"].includes(
    (user?.role || "").toLowerCase());
  // Phase 28 · Feb-2026 — multi-select reassign to a new tech. Reuses
  // the same selection state; the toolbar adds a second action next to
  // "Delete N". Admin+ only, per backend permission check.
  const [assignConfirmOpen, setAssignConfirmOpen] = useState(false);
  const [assignPickedTechId, setAssignPickedTechId] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);
  const canMultiSelectAssign = canMultiSelectDelete;
  const toggleJobSelected = (jid) => {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (next.has(jid)) next.delete(jid); else next.add(jid);
      return next;
    });
  };
  const clearSelection = () => setSelectedJobIds(new Set());
  // Feb-2026 · Bulk-selection "Select all in view" — picks every
  // job currently rendered on the focused day (post-filter,
  // post-search). Uses ``dayJobs`` (derived below) via a ref so
  // the callback stays stable across renders. NOTE: ``dayJobs`` is
  // defined further down, hence the lazy ``jobsRef.current``.
  const dayJobsRef = React.useRef([]);
  const selectAllInView = React.useCallback(() => {
    const ids = (dayJobsRef.current || []).map((j) => j.id);
    setSelectedJobIds(new Set(ids));
  }, []);
  const doBulkDelete = async () => {
    setDeleteBusy(true);
    try {
      const ids = Array.from(selectedJobIds);
      const r = await api.post("/jobs/bulk-soft-delete", { job_ids: ids });
      const count = r?.count ?? 0;
      const failed = (r?.failed || []).length;
      if (failed) {
        setToast({ text: `Deleted ${count} of ${ids.length} · ${failed} failed`,
                     kind: "err" });
      } else {
        setToast({ text: `Deleted ${count} job(s)`, kind: "info" });
      }
      clearSelection();
      setDeleteConfirmOpen(false);
      await load();
    } catch (e) {
      setToast({ text: e?.message || "Bulk delete failed", kind: "err" });
    } finally { setDeleteBusy(false); }
  };
  const doBulkReassign = async () => {
    if (!assignPickedTechId) return;
    setAssignBusy(true);
    try {
      const ids = Array.from(selectedJobIds);
      const r = await api.post("/jobs/bulk-reassign", {
        job_ids: ids, new_tech_id: assignPickedTechId,
      });
      const count = r?.count ?? 0;
      const failed = (r?.failed || []).length;
      const techName = r?.new_tech_name || "tech";
      if (failed) {
        setToast({ text: `Reassigned ${count} of ${ids.length} to ${techName} · ${failed} failed`,
                     kind: "err" });
      } else {
        setToast({ text: `${count} job(s) reassigned to ${techName}`, kind: "info" });
      }
      clearSelection();
      setAssignConfirmOpen(false);
      setAssignPickedTechId("");
      await load();
    } catch (e) {
      setToast({ text: e?.message || "Bulk reassign failed", kind: "err" });
    } finally { setAssignBusy(false); }
  };

  // Phase F1 · Feb-2026 — Multi-stop "Navigate route" bulk action.
  // Builds a single Google Maps directions URL from the currently
  // selected jobs (cross-day / cross-tech safe — sorted by date,
  // route position, tech). Google Maps caps consumer routes at 10
  // stops (1 destination + 9 waypoints); the utility surfaces
  // warning / skipped toasts so the operator knows what landed.
  const doBulkNavigateRoute = () => {
    runBulkNavigateRoute({
      jobs: filteredJobs,
      selectedIds: selectedJobIds,
      onToast: setToast,
    });
  };

  const [view, setView] = useState(params.get("view") || "month");   // Phase 30X · month default
  const [date, setDate] = useState(() => {
    const d = params.get("date");
    // Feb 2026 · P0 Timezone Fix (Section C follow-up) — anchor
    // the URL-derived ``date`` at UTC noon so the tenant-tz-aware
    // ``getTenantISODate`` resolves back to the SAME ISO param the
    // caller passed, regardless of the browser's TZ (see the
    // WeekStrip onSelectDate handler below for the same rationale).
    if (d) {
      const [y, mo, da] = d.split("-").map(Number);
      if ([y, mo, da].every((n) => Number.isFinite(n))) {
        return new Date(Date.UTC(y, mo - 1, da, 12, 0, 0));
      }
    }
    return new Date();
  });
  const [range, setRange] = useState({ start: null, end: null });   // for the "Custom" preset row

  const [q, setQ] = useState(params.get("q") || "");
  // Phase S1 · Feb-2026 — per-tech filter with role-aware default +
  // localStorage persistence.
  //
  //   • Tech role   → default to the tech's own ``technician_id``
  //     (localStorage overridable, but the dropdown itself is
  //     hidden — techs can only ever see their own schedule).
  //   • Admin/manager/owner/super_admin → default to ``""`` (All techs).
  //   • URL ``?technician_id=`` always wins on first mount
  //     (link-shares stay predictable).
  //
  // Filtering rule (see the ``filteredJobs`` memo below): when a
  // specific tech is selected, jobs with an EMPTY ``technician_id``
  // (unassigned / "open") remain visible — techs may need to pick
  // up unassigned work.
  const _isTech = String(user?.role || "").toLowerCase() === "technician";
  const _isAdminLike = (user?.role === "admin"
                        || user?.role === "super_admin"
                        || user?.role === "manager"
                        || user?.role === "owner");
  const _techFilterKey = user?.id
    ? `schedule.tech_filter.${user.id}`
    : null;
  const [techId, setTechId] = useState(() => {
    // 1) URL param wins (link-shares, deep-links from dispatch).
    const urlV = params.get("technician_id");
    if (urlV) return urlV;
    // 2) Per-user localStorage remembers the last non-URL pick.
    try {
      if (_techFilterKey) {
        const saved = localStorage.getItem(_techFilterKey);
        if (saved !== null && saved !== undefined) return saved;
      }
    } catch { /* SSR / storage-blocked mode */ }
    // 3) Role-driven default.
    if (_isTech) return user?.technician_id || "";
    return "";                                    // admin-like → All techs
  });
  const [status, setStatus] = useState(params.get("status") || "");
  const [service, setService] = useState(params.get("service") || "");
  // Phase F6a · Feb-2026 — crew filter (WEB). Crew id → derives the
  // effective set of techs whose jobs render on the schedule; when
  // set, the tech dropdown becomes read-only (shows the crew's
  // members as chips) so operators can't accidentally narrow past
  // the crew scope.  Crew list is fetched once on mount.
  const [crewId, setCrewId] = useState(params.get("crew") || "");
  const [crews, setCrews] = useState([]);

  const setParam = (k, v) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  const load = async (opts = {}) => {
    const force = opts.force !== false; // default true → mutations always fetch
    // Feb 2026 · Task B — cache-window guard. When the caller
    // hasn't asked for a forced refresh AND the currently focused
    // date sits inside the cached ``[startISO+margin, endISO-margin]``
    // interior of the last fetched window, short-circuit. The
    // client already has the data — no need to hit the network.
    if (!force) {
      const cached = fetchedRangeRef.current;
      if (cached.startISO && cached.endISO) {
        const focusISO = format(date, "yyyy-MM-dd");
        const safeStart = format(addDays(new Date(`${cached.startISO}T00:00:00`), _CACHE_MARGIN_DAYS), "yyyy-MM-dd");
        const safeEnd   = format(addDays(new Date(`${cached.endISO}T00:00:00`), -_CACHE_MARGIN_DAYS), "yyyy-MM-dd");
        if (focusISO >= safeStart && focusISO <= safeEnd) {
          // Cached window comfortably covers this date. Preserve
          // the ``loading`` flag as-is (should already be false)
          // and return without touching state.
          return;
        }
      }
    }
    setLoading(true); setError(""); setLoadTimedOut(false);
    // K65.fix · Feb-2026 — 20 s per-call hard timeout override on
    // the /api/jobs leg (the other two calls already have a
    // .catch → [] fallback).  A prod-scale schedule hang used to
    // surface as an infinite "Loading…"; now it fails fast with an
    // actionable "Retry" banner.
    const SCHEDULE_LOAD_TIMEOUT_MS = 20000;
    try {
      // Phase F3.5 · Feb-2026 — trimmed the fetched schedule window
      // from ±60/+90 (150 days) to ±30/+60 (90 days). Same rendered
      // views (day/week/month + Custom presets max out at "Next 90
      // days") but the payload drops by 40% at prod scale. The
      // ``fetchedRangeRef`` cache guard below still short-circuits
      // in-window navigation so the effective refetch cadence is
      // unchanged.
      const focus = date;
      const start = format(addDays(focus, -30), "yyyy-MM-dd");
      const end   = format(addDays(focus,  60), "yyyy-MM-dd");
      // Phase P11 · Feb-2026 — push tech-scope to the server. When a
      // specific tech is selected, ship it as ``?technician_id=…``
      // so the backend jail (P9) does the multi-field ``$or`` union
      // server-side. That means:
      //   * tech-scoped views transfer O(day)tech instead of
      //     O(day)tenant. A 50-tech tenant used to bring back every
      //     job every fetch just to filter one lane locally.
      //   * jobs assigned via ``assigned_to`` / ``tech_user_id`` /
      //     ``assigned_technician_id`` / ``crew_id`` (not just
      //     ``technician_id``) now show up correctly — the P9 jail
      //     already knows about all five shapes.
      // "All" (admin only per P9-B) skips the param and gets the
      // full-tenant view. Kept the ``jobMatchesLane`` client-side
      // predicate below as a defensive fallback for in-flight
      // response races after a filter change.
      const _techScope = (techId && techId !== "all")
        ? `&technician_id=${encodeURIComponent(techId)}`
        : "";
      const [j, t, cr] = await Promise.all([
        api.get(
          `/jobs?start=${start}&end=${end}${crewId ? `&crew_id=${encodeURIComponent(crewId)}` : ""}${_techScope}`,
          SCHEDULE_LOAD_TIMEOUT_MS,
        ),
        api.get("/technicians", SCHEDULE_LOAD_TIMEOUT_MS).catch(() => []),
        // Phase F6a · Feb-2026 — crew list for the "All crews" dropdown.
        api.get("/crews", SCHEDULE_LOAD_TIMEOUT_MS).catch(() => []),
      ]);
      setRawJobs(Array.isArray(j) ? j : (j.items || j.data || []));
      setTechs(Array.isArray(t) ? t : (t.items || []));
      setCrews(Array.isArray(cr) ? cr : (cr.items || []));
      // Feb 2026 · Task B — stamp the fetched window so subsequent
      // in-window date navigation can skip the refetch above.
      fetchedRangeRef.current = { startISO: start, endISO: end };
    } catch (e) {
      const msg = e?.message || "Failed to load schedule";
      // K65.fix — the api.js wrapper stringifies AbortError as
      // "Request timed out — check your connection and try again."
      // Detect the timeout by prefix so the retry affordance
      // shows up specifically for stalled backends (not for auth
      // errors, 5xx, or malformed responses).
      const isTimeout = /timed out/i.test(msg);
      setLoadTimedOut(isTimeout);
      setError(
        isTimeout
          ? "Schedule is taking longer than usual."
          : msg,
      );
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load({ force: false }); }, [date]);
  // Phase F6a · Feb-2026 — crew changes bypass the cache-window
  // guard (server-side filter is different, so we must re-fetch).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load({ force: true }); }, [crewId]);
  // Phase P11 · Feb-2026 — tech-scope is now server-side, so any
  // change to the ``techId`` selection must invalidate the cached
  // range and refetch. Same shape as the crew-change hook above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load({ force: true }); }, [techId]);

  // Phase P15 · Feb-2026 — re-hydrate on tenant-settings updates.
  // BusinessSettings.jsx dispatches ``tenant:settings-updated`` with
  // ``detail.timezone`` set to the new IANA name on save.  We take
  // it as the local override so ``tenantTz`` uses the fresh zone
  // immediately AND force a schedule re-fetch so any day-window
  // computation on the wire lines up with the new tz.
  useEffect(() => {
    function onTenantSettingsUpdated(evt) {
      const nextTz = evt?.detail?.timezone;
      if (nextTz && typeof nextTz === "string") {
        setTenantTzOverride(nextTz);
      }
      // Force refetch so any tenant-tz-anchored server response
      // (e.g. dashboard action-cards, jobs day-window unions) picks
      // up the new zone without waiting for the next date change.
      load({ force: true });
    }
    window.addEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
    return () => window.removeEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─────────────────────────────────────────────────────────
  // Phase P5 · Feb-2026 — Legacy tech-filter self-heal.
  // ─────────────────────────────────────────────────────────
  //
  // Prior to P5 the dropdown's ``<option value=>`` was ``t.id``
  // which for synth rows on users WITHOUT a stamped
  // ``technician_id`` was actually the user account id
  // (``users.id``).  A pick made under the old code would
  // therefore persist a users.id into
  // ``localStorage["schedule.tech_filter.<user-id>"]`` — and that
  // stored value never matches any job's ``technician_id`` so the
  // filter renders an empty schedule the next time the page
  // loads.
  //
  // Self-heal: once the tenant's techs list is loaded, if the
  // currently-active ``techId`` is not in the set of canonical
  // technician_ids returned by ``GET /technicians``, clear it
  // back to ``""`` (All), scrub the localStorage entry, and log
  // ONE console.warn so we can catch any last stragglers in
  // Sentry.
  //
  // Phase P11 · Feb-2026 — loosen the once-per-mount ref guard.
  // The pre-P11 shape hard-locked the effect after ONE firing, so
  // if the techs list later reloaded (e.g. a tech was renamed /
  // added / removed by another dispatcher) the heal could never
  // re-evaluate.  Re-key the guard on the techs-list identity
  // instead — the effect fires at most once per fresh techs load
  // AND crucially, a crewless tech whose canonical id IS in the
  // fresh set is never cleared (the predicate is a plain
  // ``canonicalIds.has(techId)`` — no crew-anchor secondary check).
  const _healedLegacyTechFilterRef = React.useRef(null);
  useEffect(() => {
    if (!techs || techs.length === 0) return;
    // Same list ref? — heal already evaluated for this load event.
    if (_healedLegacyTechFilterRef.current === techs) return;
    _healedLegacyTechFilterRef.current = techs;
    if (!techId) return;                          // Already on "All".
    const canonicalIds = new Set(
      techs.map(_canonicalTechId).filter(Boolean),
    );
    // Phase P11 · loosened predicate — the only reason to clear is
    // "id absent from the canonical set".  A tech with no crew,
    // no jobs, no anchor of any kind is still a legit tech; if
    // ``_canonicalTechId`` returned an id for it, that id lives in
    // ``canonicalIds`` and the stored filter value is kept as-is.
    if (canonicalIds.has(techId)) return;         // Filter matches — no-op.
    // eslint-disable-next-line no-console
    console.warn(
      "[CalendarSchedule] stored tech filter value not present in "
      + "current techs list — clearing to 'All'. (Legacy user-id "
      + "persisted before Phase P5 canonicalization.)",
      { stored_tech_filter: techId },
    );
    setTechId("");
    setParam("technician_id", "");
    try {
      if (_techFilterKey) localStorage.removeItem(_techFilterKey);
    } catch { /* storage-blocked / private mode */ }
  }, [techs, techId, _techFilterKey]);   // eslint-disable-line react-hooks/exhaustive-deps


  // Phase F6a · Feb-2026 — resolved tech-id set for the currently
  // selected crew (empty when no crew filter is active).  Server
  // already filters `crew_id == X OR technician_id IN crew.tech_ids`
  // via the `?crew_id=` query; we still compute this on the client
  // so the tech dropdown can display the crew's members as chips
  // and the client-side tech filter respects the crew scope.
  const crewMemberIds = useMemo(() => {
    if (!crewId) return null;
    const c = crews.find((x) => x.id === crewId);
    return c ? (c.tech_ids || []) : [];
  }, [crewId, crews]);

  const filteredJobs = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return rawJobs.filter((j) => {
      // Phase F6a · Crew filter overrides the tech dropdown when
      // active — the server already scoped by crew, but a stale
      // page (or a broadening race) shouldn't render extra rows.
      if (crewId && crewMemberIds && crewMemberIds.length > 0) {
        const jobBelongsToCrew =
          j.crew_id === crewId ||
          crewMemberIds.includes(j.technician_id);
        if (!jobBelongsToCrew) return false;
      } else if (techId) {
        // Phase P11 · Feb-2026 — K42-parity lane match. The pre-P11
        // shape was ``j.technician_id !== techId && !!j.technician_id``
        // which:
        //   * ignored the FOUR other assignment fields the P9 jail
        //     unions server-side (``assigned_technician_id`` /
        //     ``assigned_to`` / ``tech_user_id`` / ``crew_id``);
        //   * silently kept "unassigned" jobs (empty
        //     ``technician_id``) alongside the tech-scoped set,
        //     mixing lanes in the tech's view.
        // ``jobMatchesLane`` mirrors the backend disjunction. This
        // is defensive: the server already filtered when the page
        // fired ``GET /jobs?technician_id=…`` — this predicate only
        // has to do work if a stale in-flight response arrived
        // AFTER the filter changed OR if the fetch fell back to
        // the cache-window (mostly-empty range hits).
        if (!jobMatchesLane(j, techId)) return false;
      }
      if (status && j.status !== status) return false;
      if (service && (j.service_type || "").toLowerCase() !== service.toLowerCase()) return false;
      if (ql) {
        const hay = `${j.customer_name || ""} ${j.title || ""} ${j.service_type || ""} ${j.address || ""}`.toLowerCase();
        if (!hay.includes(ql)) return false;
      }
      return true;
    });
  }, [rawJobs, q, techId, status, service, crewId, crewMemberIds]);

  // Phase K73 · Feb-2026 — build tech-id → color map using the
  // crew-hued palette (crew hue + individual saturation). Falls
  // back to the flat ``hashedTechColor`` for callers/tests that
  // don't provide crews.
  //
  // Phase R1.1 · Feb-2026 — STRICT keying on the canonical
  // ``technicians.id`` (per Phase K42 the wire always ships this
  // id).  Previously fell back to ``t.user_id`` when ``t.id`` was
  // absent — that entry never got looked up (because
  // ``jobs.technician_id`` stores ``technicians.id``) AND
  // shadowed a legit ``user_id``-keyed job lookup at
  // ``techColorMap.get(job.technician_id)`` if the two spaces
  // ever crossed.  Skip techs without a canonical ``id``; the
  // Safe Check in ``jobToEvent`` renders those jobs neutral and
  // warns once.
  const techColorMap = useMemo(() => {
    const m = new Map();
    const crewByTechId = new Map();
    for (const c of crews) {
      for (const tid of c.tech_ids || []) crewByTechId.set(tid, c.id);
    }
    for (const t of techs) {
      const id = t.id;
      if (!id) continue;
      m.set(id, crewHuedColorFromTech(t, crewByTechId.get(id) || null));
    }
    return m;
  }, [techs, crews]);

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
    setCrewId("");
    setParam("q", "");
    setParam("technician_id", "");
    setParam("status", "");
    setParam("service", "");
    setParam("crew", "");
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
    // SO-A · Feb-2026 — auto-open MARCO Suggestions for admins so the
    // best-fit tech is one click away.  The panel is a right-side drawer
    // that layers under the centered checklist modal without conflicting.
    const rawJob = ev?.resource?.job || null;
    const isAdminSelect = (user?.role === "admin"
      || user?.role === "super_admin"
      || user?.role === "manager");
    if (isAdminSelect && rawJob) setMarcoJob(rawJob);
  };

  // Feb-2026 · Enhancement 1 — drag-drop reschedule state + handlers.
  const isAdminRole = (user?.role === "admin" || user?.role === "super_admin"
                      || user?.role === "manager");
  // Feb 2026 · Calendar-view inline edit — double-click on an event
  // opens the ``ScheduleJobEditModal`` (same modal wired to the
  // Grid-view pencil affordance) so admins can retag work_class /
  // status / tech assignment without leaving /schedule. Techs and
  // customers never reach this path — single-click still routes to
  // the checklist modal for all roles (unchanged behaviour).
  // ``ev.resource.job`` carries the full doc set on ``jobToEvent()``.
  const onDoubleClickEvent = React.useCallback((ev) => {
    if (!isAdminRole) return;
    const rawJob = ev?.resource?.job || null;
    if (rawJob) setEditingJob(rawJob);
  }, [isAdminRole]);
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
  }, [rescheduleDraft]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'load' intentionally omitted (mount-only or stable-ref)

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
  // Feb 2026 · P0 Timezone Fix (Section C) — swap browser-local
  // ``format(date, "yyyy-MM-dd")`` for the tenant-tz-aware ISO date
  // so a Phoenix tenant viewed from an eastern-tz browser at 8 PM
  // Phoenix (post-UTC-midnight) STILL renders the correct day's
  // job list. Matches the TodaySchedule fix pattern.
  const focusISO = getTenantISODate(date, tenantTz);
  const dayJobs = useMemo(() => {
    // Phase P13 · Feb-2026 · P0 HOTFIX — tenant-local "today". The
    // pre-P13 filter compared ``(j.scheduled_date || "").slice(0,10)``
    // to ``focusISO`` — that worked ONLY if the wire's
    // ``scheduled_date`` string was itself derived in the tenant's
    // local tz at write time. Older write paths derived it from the
    // UTC datetime, so a job at 8pm Phoenix (03:00 UTC next day) got
    // stamped with tomorrow's date and disappeared from today's view
    // (the observed production symptom). Fix: also accept jobs whose
    // ``scheduled_start`` datetime bucketed through
    // ``getTenantISODate`` lands on the same tenant-local day.
    // Union-shape is defensive — jobs with a correct
    // ``scheduled_date`` still match via the fast string branch.
    const list = filteredJobs.filter((j) => {
      const sdISO = (j.scheduled_date || "").slice(0, 10);
      if (sdISO && sdISO === focusISO) return true;
      // Fallback: tenant-local ISO derived from ``scheduled_start``.
      const ss = j.scheduled_start;
      if (!ss) return false;
      return getTenantISODate(ss, tenantTz) === focusISO;
    });
    // Phase 30X · date-only surface. Order by route position only — no
    // time-of-day tiebreaker (schedule is per-day, not hourly).
    list.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    return list;
  }, [filteredJobs, focusISO, tenantTz]);

  // ── Phase P25 · Feb-2026 — Map data source: filter-INDEPENDENT.
  // Pre-P25 the map was fed ``dayJobs``, which applied the active
  // tech / crew / status / service / query filter chip. That meant
  // an operator who selected a single tech saw only that tech's
  // pins — pins for other techs' jobs at the same time silently
  // disappeared from the map (the reported "some technicians'
  // Today pins are missing" symptom). Spec §Item B: "ensure the
  // map's data source is independent of the filter chip".
  //
  // Fix: derive a second day-scoped list from ``rawJobs`` (bypass
  // ``filteredJobs`` entirely). Same tenant-tz bucketing rule as
  // ``dayJobs`` (P13 fallback for UTC-stamped ``scheduled_date``
  // strings). No client-side truncation, no ``.slice(0, N)``,
  // no ``maxJobs`` — every renderable pin ships to the map.
  const mapDayJobs = useMemo(() => {
    const list = (rawJobs || []).filter((j) => {
      const sdISO = (j.scheduled_date || "").slice(0, 10);
      if (sdISO && sdISO === focusISO) return true;
      const ss = j.scheduled_start;
      if (!ss) return false;
      return getTenantISODate(ss, tenantTz) === focusISO;
    });
    list.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    return list;
  }, [rawJobs, focusISO, tenantTz]);
  // Feb-2026 · Keep ``selectAllInView`` in sync with the derived
  // day list without stashing it in state.
  React.useEffect(() => { dayJobsRef.current = dayJobs; }, [dayJobs]);
  // Feb-2026 · Schedule-UI · per-day count map for the WeekStrip badges.
  // {iso: count} across every currently-visible job (post-filter).
  // Purely derived — no extra fetch, no backend touch. Recalculates
  // whenever the filtered job list changes.
  //
  // Phase P13 · Feb-2026 · P0 HOTFIX — same tenant-local bucketing as
  // ``dayJobs``: a job whose ``scheduled_date`` string was mis-stamped
  // in UTC (Phoenix 8pm → UTC next day) should count under the tenant
  // local day derived from ``scheduled_start``, not the misfiled
  // wire field.
  const weekCounts = useMemo(() => {
    const m = {};
    for (const j of filteredJobs) {
      const sdISO = (j.scheduled_date || "").slice(0, 10);
      let iso = sdISO;
      if (!iso && j.scheduled_start) {
        iso = getTenantISODate(j.scheduled_start, tenantTz);
      }
      if (!iso) continue;
      m[iso] = (m[iso] || 0) + 1;
    }
    return m;
  }, [filteredJobs, tenantTz]);
  useEffect(() => {}, [dayJobs]);
  const gridList = dayJobs;

  // Feb-2026 · numbered-order reorder — the schedule day's live
  // controller drives both the per-card inputs and the bulk modal.
  // We derive the (tech, date) hint from the day's first job so the
  // hardened backend accepts the payload without having to re-infer
  // on its side.  Only non-terminal jobs are numbered.
  const _TERMINAL_STATUSES = React.useMemo(
    () => new Set(["completed", "canceled", "cancelled", "skipped", "could_not_service"]),
    [],
  );
  const reorderableJobs = React.useMemo(
    () => dayJobs.filter((j) => !_TERMINAL_STATUSES.has((j.status || "").toLowerCase())),
    [dayJobs, _TERMINAL_STATUSES],
  );
  // ── Phase P10 · Feb-2026 — Lane scoping for reorder ──
  // A job's "lane" is the id the reorder resolver will scope on:
  // its ``technician_id`` when present, else its ``crew_id``,
  // else ``null`` (fully unassigned). Reorder gestures must be
  // scoped to a single non-null lane — mixed-lane batches would
  // race the backend's set-completeness check (the widened P10
  // filter still needs a single lane_id per request).
  const _laneOf = React.useCallback((j) => {
    if (!j) return null;
    return j.technician_id
      || j.assigned_technician_id
      || j.tech_user_id
      || j.assigned_to
      || j.crew_id
      || null;
  }, []);
  const _reorderLaneSet = React.useMemo(() => {
    const s = new Set();
    for (const j of reorderableJobs) {
      const lane = _laneOf(j);
      if (lane) s.add(lane);
    }
    return s;
  }, [reorderableJobs, _laneOf]);
  const _reorderHasUnassigned = React.useMemo(
    () => reorderableJobs.some((j) => !_laneOf(j)),
    [reorderableJobs, _laneOf],
  );
  // ``reorderLaneStatus``: what should the Reorder button do?
  //   * ``ready``          — single non-null lane, ≥2 jobs, no unassigned.
  //   * ``mixed_lanes``    — >1 distinct non-null lanes present.
  //   * ``has_unassigned`` — at least one job has no tech + no crew.
  //   * ``empty``          — <2 reorderable jobs (existing tooltip covers this).
  const reorderLaneStatus = React.useMemo(() => {
    if ((reorderableJobs || []).length < 2) return "empty";
    if (_reorderHasUnassigned && _reorderLaneSet.size === 0) {
      return "has_unassigned";
    }
    if (_reorderLaneSet.size > 1) return "mixed_lanes";
    if (_reorderLaneSet.size === 1 && _reorderHasUnassigned) {
      return "has_unassigned";
    }
    return _reorderLaneSet.size === 1 ? "ready" : "empty";
  }, [reorderableJobs, _reorderLaneSet, _reorderHasUnassigned]);
  // Lane-scoped subset that actually flows into the reorder modal
  // + hook. When the day mixes lanes we intentionally hand the
  // hook an empty list so it can't accidentally construct a
  // cross-lane payload — the Reorder button is disabled above
  // and the ``ReorderErrorBanner`` explains why.
  const _reorderScopedJobs = React.useMemo(() => {
    if (reorderLaneStatus !== "ready") return [];
    const [onlyLane] = Array.from(_reorderLaneSet);
    return reorderableJobs.filter((j) => _laneOf(j) === onlyLane);
  }, [reorderLaneStatus, _reorderLaneSet, reorderableJobs, _laneOf]);
  const _dayTechHint = React.useMemo(() => {
    const first = _reorderScopedJobs[0] || reorderableJobs[0];
    if (!first) return null;
    return _laneOf(first);
  }, [_reorderScopedJobs, reorderableJobs, _laneOf]);
  const orderController = useNumberedOrder(_reorderScopedJobs, {
    autoSave: isAdminRole,
    techUserId: _dayTechHint,
    date: focusISO,
    onSaved: () => load(),
  });

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
  // BULK-RESCHEDULE · Feb-2026 · web — single-call bulk reschedule.
  //
  // Replaces the pre-Feb-2026 per-job PUT loop with one server-
  // side ``POST /api/jobs/bulk-reschedule`` invocation.  The
  // extracted ``@/lib/bulkReschedule`` helper owns the confirm
  // dialog, api call, error-code translation, and lifecycle hooks
  // so the vitest can drive the exact same code path without
  // mounting this 3.4-kloc calendar component.
  const bulkMove = async () => {
    setBusy(true);
    try {
      const ids = Array.from(checked);
      const result = await _bulkRescheduleHelper({
        ids, date: moveDate,
        toast: toast_,
        onClear: () => {
          setChecked(new Set());
          setMoveOpen(false);
          setMoveDate("");
        },
        onReload: load,
        api, mustConfirm,
      });
      return result;
    } finally {
      setBusy(false);
    }
  };

  // Feb-2026 · Optimize Route — non-destructive pre-fill of the
  // Reorder modal. Calls the backend Google Directions v2 +
  // ORION-inspired zip-cluster tiebreaker pipeline, then opens the
  // Reorder modal seeded with the recommended order + a summary
  // banner. User still clicks Save Order to persist. Cancel /
  // close discards the optimization.
  const optimizeRoute = async () => {
    if ((reorderableJobs || []).length < 2) return;
    setOptimizing(true);
    try {
      const r = await api.post("/schedule/optimize-route", {
        date: focusISO,
        technician_id: _dayTechHint || null,
      });
      const totalSecs = Number(r?.total_duration_s || 0);
      const totalMeters = Number(r?.total_distance_m || 0);
      const h = Math.floor(totalSecs / 3600);
      const m = Math.round((totalSecs % 3600) / 60);
      const miles = (totalMeters / 1609.344).toFixed(1);
      const algo = String(r?.algorithm || "unknown");
      const summary = `Estimated ~${h}h ${m}m · ${miles}mi · ${algo}`;
      setOptimizePayload({
        orderedIds: Array.isArray(r?.ordered_job_ids) ? r.ordered_job_ids : [],
        summary,
        warnings: Array.isArray(r?.warnings) ? r.warnings : [],
      });
      // Phase P12 · non-blocking success toast when the backend
      // surfaced orphaned tech ids or unassigned jobs. These are
      // operator-actionable (run Data Repair · Orphaned Technician
      // sweep or assign the ghost job) but must NOT block the
      // Reorder modal from opening.
      const _orphans = Array.isArray(r?.orphaned_tech_ids) ? r.orphaned_tech_ids : [];
      const _skipped = Array.isArray(r?.skipped_unassigned) ? r.skipped_unassigned : [];
      if (_orphans.length || _skipped.length) {
        const _opt = Array.isArray(r?.ordered_job_ids) ? r.ordered_job_ids.length : 0;
        const _skipTotal = _orphans.length + _skipped.length;
        toast_(
          `Optimized ${_opt} jobs; ${_skipTotal} skipped `
          + `(unassigned or orphaned)`,
          "info",
        );
      }
      setBulkReorderOpen(true);
    } catch (e) {
      // Phase P12 · Feb-2026 — surface the real error in a modal
      // instead of the ephemeral red toast. Ladder walks every
      // error shape our ``api.js`` wrapper might attach the FastAPI
      // detail under, matching the P10 fix for reorder errors.
      const _msg =
        e?.data?.detail?.message
        || e?.data?.detail?.code
        || (typeof e?.data?.detail === "string" ? e.data.detail : null)
        || e?.body?.detail?.message
        || e?.body?.detail?.code
        || e?.message
        || "Optimization failed";
      const _code =
        e?.data?.detail?.code
        || e?.body?.detail?.code
        || (typeof e?.message === "string" ? e.message : "")
        || "";
      const _warns = Array.isArray(e?.data?.warnings)
        ? e.data.warnings
        : (Array.isArray(e?.body?.warnings) ? e.body.warnings : []);
      setOptimizeError({ message: String(_msg), code: String(_code), warnings: _warns });
    } finally {
      setOptimizing(false);
    }
  };
  // Feb-2026 · numbered-order reorder — replaces the old rearrange
  // mode (drag-handles + up/down chevrons + explicit "Save order"
  // button).  ``orderController`` (declared above) auto-saves on
  // input blur, and the bulk modal saves on its own explicit
  // "Save order" click.  No local shift/save helpers needed here.
  const _shift = () => {};   // kept as a no-op for prop compatibility
  const _saveReorder = () => {}; // ditto

  return (
    // Feb-2026 · scroll-trap prevention convention — the outer
    // ``<SafeScrollContainer>`` guarantees the whole document scrolls
    // naturally. The RBC calendar keeps its own internal wheel-scroll
    // for the time-of-day grid — that's expected + correct. See
    // ``components/layout/SafeScrollContainer.jsx`` for rationale.
    <SafeScrollContainer
      className="p-4 md:p-6"
      style={{ fontFamily: font.family }}
      data-testid="calendar-schedule"
    >
      {/* Feb-2026 · Weather-bar reconciliation — same shared
          ``WeatherWidget`` the admin Dashboard mounts. ``collapsible``
          collapses the widget to the current-conditions row + an
          expand toolbar (Hourly / 7-Day / Radar), matching the
          Dashboard's density. The widget's role gate allows
          technician / admin / super_admin (customers are hidden
          server-side too); it self-renders ``null`` for any other
          role. */}
      <TechWeatherWidget user={user} collapsible />

      {/* Feb-2026 · Schedule-UI · 7-day toggle strip.
          The strip drives the shared ``date`` state which also feeds
          the RBC calendar's ``date`` prop + the grid-view focus day.
          When a user picks Wed from the strip we hydrate ``date``
          which triggers the existing ±90-day fetch window logic.
          ``weekCounts`` is a derived memo — {iso: count} across
          every currently-visible job — so the strip can paint a
          per-day badge without an extra HTTP round-trip. */}
      <WeekStrip
        selectedDate={focusISO}
        counts={weekCounts}
        onSelectDate={(iso) => {
          // Feb 2026 · P0 Timezone Fix (Section C follow-up) — anchor
          // the ``date`` state at UTC noon on the picked ISO so
          // ``getTenantISODate(date, tenantTz)`` always resolves back
          // to the SAME ISO the user clicked, regardless of the
          // browser's local TZ. Constructing ``new Date(y, m-1, d)``
          // in browser-local time silently shifted the tenant day
          // back by one for any browser east of Phoenix (UTC-7),
          // which broke the Grid-view job filter for east-coast
          // dispatchers overseeing Phoenix tenants.
          const [y, m, d] = iso.split("-").map(Number);
          const next = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
          setDate(next);
          setParam("date", iso);
        }}
      />
      {/* Feb-2026 enhancement — pending-no-crew admin nudge. Renders
          for admin / manager / super_admin only; hides when the
          endpoint reports 0 stale jobs or the user has dismissed
          it for this session. */}
      <PendingNoCrewNudge user={user} />
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }} data-testid="calendar-title">
            Schedule
          </h1>
          <div className="text-xs" style={{ color: colors.muted }} data-testid="calendar-header-counts">
            {loading ? "Loading…" : (
              (() => {
                // Feb 2026 · Work-class split on the filtered view.
                // Renders in BOTH Grid and Calendar modes so the
                // service/repair breakdown is discoverable regardless
                // of which sub-view the operator is on. Legacy jobs
                // without ``work_class`` bucket into ``service``
                // (matches the read-time invariant in
                // ``backend/services/work_class.py``).
                const repair = filteredJobs.filter(
                  (j) => j && j.work_class === "repair",
                ).length;
                const service = filteredJobs.length - repair;
                return (
                  <>
                    <span data-testid="calendar-header-count-total">
                      {filteredJobs.length}
                    </span>
                    {" of "}{rawJobs.length}{" jobs"}
                    {filteredJobs.length > 0 ? (
                      <>
                        {" · "}
                        <span data-testid="calendar-header-count-service">
                          {service} svc
                        </span>
                        {" · "}
                        <span
                          data-testid="calendar-header-count-repair"
                          style={{
                            color: repair > 0 ? "#DC2626" : undefined,
                            fontWeight: repair > 0 ? 600 : undefined,
                          }}
                        >
                          {repair} repair
                        </span>
                      </>
                    ) : null}
                  </>
                );
              })()
            )}
          </div>
        </div>
        {/* Feb-2026 · Phase 1 — prominent top-level "On my way — next
            job" CTA. Visible when the currently-focused day has at
            least one non-terminal job and the caller's role can send
            (technician / manager / admin / super_admin; component
            self-gates). Targets the first non-terminal job in the
            day's ordered list (dayJobs is already sorted by
            route_order + scheduled_time). */}
        {(() => {
          const done = new Set(["completed", "canceled", "cancelled", "skipped"]);
          const nextJob = (dayJobs || []).find(
            (j) => !done.has(String(j.status || "").toLowerCase())
          );
          if (!nextJob) return null;
          return (
            <div className="ml-2" data-testid="on-my-way-next-wrap">
              <OnMyWayButton
                jobId={nextJob.id}
                customerFirstName={(nextJob.customer_name || "").split(" ")[0] || ""}
                variant="primary"
                testId="on-my-way-next-btn"
              />
            </div>
          );
        })()}
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
        {/* Feb-2026 · Batch #4 · Item 3 (continuation) — top-level
            refresh button. Previously the refresh affordance lived
            inside <GridPanel>, so techs viewing the Calendar mode
            (month/agenda) had no way to refetch without a full
            page reload. Lifted to the shared toolbar via the
            <ScheduleRefreshButton> component (also used by
            TodaySchedule) so the same
            ``data-testid="schedule-refresh"`` is present regardless
            of ``mode`` or the RBC internal ``view``. Wired to
            ``load({force:true})`` so route-cache is bypassed. */}
        <ScheduleRefreshButton
          busy={busy}
          onRefresh={() => load({ force: true })}
        />
        {isAdminRole ? (
          <button
            data-testid="calendar-send-to-dispatch"
            onClick={async () => {
              try {
                setBusy(true);
                const r = await api.post("/dispatch/import-schedule",
                                          { date: focusISO });
                toast_(`Sent ${r.job_count} jobs to Dispatch (${r.techs_written} techs).`);
                navigate(`/admin/dispatch?date=${focusISO}`);
              } catch (e) {
                toast_(`Send to Dispatch failed: ${e.message || e}`, "err");
              } finally {
                setBusy(false);
              }
            }}
            className="flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold"
            style={{ background: "#0F172A", color: "#fff" }}
            disabled={busy}
          >
            <MoveIcon size={14} /> Send to Dispatch Board
          </button>
        ) : null}
      </div>

      {/* Filter toolbar — Phase K52 Slice A · Feb-2026: navy chrome
          strip.  Every input on this row (search, select triggers,
          the "Clear" affordance) renders white-on-navy so the whole
          strip reads as one navigation surface.  Native <select>
          options and native <input type="date"> popovers remain
          browser-controlled and stay on their default (light)
          chrome — those are out of our reach without wholesale
          replacement with shadcn primitives, which is out of scope
          for K52. */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{
          background: colors.nav.bg,
          border: `1px solid ${colors.nav.border}`,
        }}
        data-testid="calendar-filters"
        data-k52-navy-strip="true"
      >
        {/*
         * Phase N1 · Feb-2026 — Universal input restyle. Search box
         * paints solid-white bg + navy text + blue focus ring so the
         * calendar search matches the sitewide input theme. Icon
         * adopts the same navy. The K52.1 navy chrome strip stays
         * as a colored container around the white input card.
         */}
        <div className="flex items-center gap-1 flex-1 min-w-[180px] bg-white border border-slate-200 rounded-lg px-2.5 py-1.5 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500 transition-colors">
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input
            data-testid="calendar-search"
            value={q}
            onChange={(e) => { setQ(e.target.value); setParam("q", e.target.value); }}
            placeholder="Search customer, service, address…"
            className="flex-1 bg-white outline-none text-sm text-[#0284C7] placeholder:text-[#0284C7]/55"
          />
          {q ? (
            <button onClick={() => { setQ(""); setParam("q", ""); }} data-testid="calendar-search-clear">
              <XIcon size={12} style={{ color: "#0284C7" }} />
            </button>
          ) : null}
        </div>

        {/* Phase S1 · Feb-2026 — dropdown is hidden entirely for
            the ``technician`` role. Admin / manager / owner see the
            full picker. ``schedule-tech-filter`` is the canonical
            testid (mirror lives on mobile) and
            ``calendar-filter-tech`` is preserved for pre-S1 tests. */}
        {_isTech ? null : (
        <select
          value={techId}
          onChange={(e) => {
            const nextV = e.target.value;
            setTechId(nextV);
            setParam("technician_id", nextV);
            // Persist per-user so the pick survives reloads. Techs
            // never reach this branch (dropdown hidden above) so no
            // no-op write is required for them.
            try {
              if (_techFilterKey) {
                localStorage.setItem(_techFilterKey, nextV);
              }
            } catch { /* storage-blocked / private mode */ }
          }}
          data-testid="schedule-tech-filter"
          data-testid-legacy="calendar-filter-tech"
          className="text-sm rounded-lg px-2 py-1.5"
          disabled={!!crewId}
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: crewId ? colors.nav.fgMuted : colors.nav.fg,
                   opacity: crewId ? 0.55 : 1,
                   cursor: crewId ? "not-allowed" : "pointer" }}
          title={crewId
            ? "Techs are locked to the selected crew — clear the crew filter to change"
            : undefined}
          aria-label="Technician"
        >
          <option value="">{crewId ? "Techs (from crew)" : "All techs"}</option>
          {techs.slice().sort((a, b) =>
            (a.name || a.email || "").localeCompare(b.name || b.email || "")
          ).map((t) => {
            // Phase P5 · Feb-2026 — canonical technician_id via
            // ``_canonicalTechId`` (prefers ``t.technician_id``,
            // falls back to ``t.id``). Filter predicate below
            // compares ``job.technician_id === techId`` so the
            // dropdown ID space is now guaranteed compatible
            // with ``jobs.technician_id``.  Skip techs where
            // the resolver can't produce a truthy id (defensive
            // — the backend UNION filter already omits those).
            const _tid = _canonicalTechId(t);
            if (!_tid) return null;
            return (
              <option key={_tid} value={_tid}>{t.name || t.email}</option>
            );
          })}
        </select>
        )}

        {/* Phase F6a · Feb-2026 — "All crews" filter (WEB only). Populates
            from GET /api/crews and adds a `crew_id` param to the schedule
            query. When set, the tech dropdown above is disabled and the
            crew's members render as chips (see block below).

            Phase P9-B · Feb-2026 — Technician Visibility Jail.
            The crew filter is hidden for the ``technician`` role — techs
            must never be able to widen or re-scope beyond their own
            jobs. Backend jails the query regardless; hiding the picker
            keeps the UI honest so a tech never sees an option that would
            silently no-op. */}
        {_isTech ? null : (
        <select
          value={crewId}
          onChange={(e) => { setCrewId(e.target.value); setParam("crew", e.target.value); }}
          data-testid="calendar-filter-crew"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: colors.nav.fg }}
        >
          <option value="">All crews</option>
          {crews.slice().sort((a, b) =>
            (a.name || "").localeCompare(b.name || "")
          ).map((c) => (
            <option key={c.id} value={c.id}>{c.name || "Unnamed crew"}</option>
          ))}
        </select>
        )}

        <select
          value={service}
          onChange={(e) => { setService(e.target.value); setParam("service", e.target.value); }}
          data-testid="calendar-filter-service"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: colors.nav.fg }}
        >
          <option value="">All services</option>
          {serviceTypes.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setParam("status", e.target.value); }}
          data-testid="calendar-filter-status"
          className="text-sm rounded-lg px-2 py-1.5"
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: colors.nav.fg }}
        >
          <option value="">All statuses</option>
          {Object.keys(STATUS_COLORS).map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
          ))}
        </select>

        {(q || techId || status || service || crewId) ? (
          <button
            onClick={clearFilters}
            data-testid="calendar-filter-clear"
            className="text-xs font-semibold px-2 py-1.5 rounded-lg"
            style={{ color: colors.nav.fg,
                     background: "rgba(255,255,255,0.10)",
                     border: `1px solid ${colors.nav.border}` }}
          >
            <Filter size={11} className="inline mr-1" /> Clear
          </button>
        ) : null}
      </div>

      {/* Phase F6a · Feb-2026 — crew-member chips row.  Renders only
          when a crew filter is active; shows the crew's members so
          operators see WHY the tech dropdown just got locked. */}
      {crewId && crewMemberIds && crewMemberIds.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 mb-3"
             data-testid="calendar-crew-chips">
          <span className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: colors.muted }}>
            Techs (from crew)
          </span>
          {crewMemberIds.map((tid) => {
            const t = techs.find(
              (x) => (x.user_id || x.id) === tid || x.id === tid,
            );
            const name = t?.name || t?.email || tid;
            return (
              <span
                key={tid}
                className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold"
                style={{ background: colors.surfaceSecondary,
                         color: colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid={`calendar-crew-chip-${tid}`}
              >
                {name}
              </span>
            );
          })}
        </div>
      ) : null}

      {/* Custom-range preset row — Phase K52 Slice A · Feb-2026:
          continuation of the navy filter strip.  Preset chips render
          white outline on navy; the ACTIVE preset uses the K52
          signature gradient so it matches Slice D's active-nav
          pattern. */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{
          background: colors.nav.bg,
          border: `1px solid ${colors.nav.border}`,
        }}
        data-testid="calendar-presets"
        data-k52-navy-strip="true"
      >
        <span className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: colors.nav.fgMuted }}>
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
                background: active ? colors.gradient.css : "transparent",
                color: colors.nav.fg,
                border: `1px solid ${active ? "transparent" : colors.nav.fgMuted}`,
                textShadow: active ? colors.gradient.textShadow : undefined,
              }}
              data-testid={`calendar-preset-${p.key}`}
              data-active={active ? "true" : "false"}
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
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: colors.nav.fg,
                   colorScheme: "dark" }}
        />
        <span className="text-xs" style={{ color: colors.nav.fgMuted }}>→</span>
        <input
          type="date"
          value={range.end ? format(range.end, "yyyy-MM-dd") : ""}
          onChange={(e) => setRange((r) => ({ ...r, key: "custom",
            end: e.target.value ? new Date(`${e.target.value}T23:59:59`) : null,
          }))}
          data-testid="calendar-range-to"
          className="text-xs rounded-lg px-2 py-1"
          style={{ background: colors.nav.bg,
                   border: `1px solid ${colors.nav.border}`,
                   color: colors.nav.fg,
                   colorScheme: "dark" }}
        />
        {rangeMatchEvents ? (
          <span
            className="text-xs font-semibold px-2 py-1 rounded-full"
            data-testid="calendar-range-count"
            style={{ background: "rgba(255,255,255,0.15)",
                     color: colors.nav.fg,
                     border: `1px solid ${colors.nav.border}` }}
          >
            {rangeMatchEvents.length} jobs in range
          </span>
        ) : null}
        {range.start ? (
          <button
            onClick={() => setRange({ start: null, end: null })}
            className="text-xs font-semibold"
            style={{ color: colors.nav.fgMuted }}
            data-testid="calendar-range-clear"
          >
            Clear
          </button>
        ) : null}
      </div>

      {error ? (
        <div
          data-testid="calendar-error"
          className="rounded-xl px-3 py-2 mb-3 text-xs flex items-center justify-between gap-3"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
        >
          <span>{error}</span>
          {loadTimedOut ? (
            <button
              type="button"
              data-testid="calendar-retry-btn"
              onClick={() => load({ force: true })}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: "#991B1B", color: "#fff" }}
            >
              Retry
            </button>
          ) : null}
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

      {/* Feb-2026 · Batched Wave #2 — Schedule Map (grid mode) with
          a persistent show/hide toggle. Rendered ABOVE the day list
          so the map is the first thing an operator sees when they
          land on /schedule. Toggle state persists to localStorage
          under ``schedule.mapVisible`` (mobile parity: same key is
          used with AsyncStorage in the Expo app). ScheduleMap
          itself self-hides when zero stops have coords, so the
          toggle header can render even on empty days and the map
          area quietly disappears — the toggle stays available for
          navigation to a day with coords. */}
      {mode === "grid" ? (
        <div className="mb-3" data-testid="schedule-map-wrap">
          <button
            type="button"
            onClick={toggleMapVisible}
            aria-expanded={mapVisible ? "true" : "false"}
            aria-controls="schedule-map-body"
            data-testid="schedule-map-toggle"
            data-map-visible={mapVisible ? "true" : "false"}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold mb-2"
            style={{
              background: colors.surface,
              color: mapVisible ? colors.brand : colors.muted,
              border: `1px solid ${colors.border}`,
              cursor: "pointer",
            }}
          >
            <MapIcon size={13} />
            <span>{mapVisible ? "Hide map" : "Show map"}</span>
            {mapVisible ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
          {mapVisible ? (
            <div id="schedule-map-body" data-testid="schedule-map-body">
              <ScheduleMapErrorBoundary>
                <ScheduleMap
                  jobs={mapDayJobs}
                  techs={techs}
                  techColorMap={techColorMap}
                />
              </ScheduleMapErrorBoundary>
            </div>
          ) : null}
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
        <TechColorLegend techs={techs} techColorMap={techColorMap} crews={crews} />
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
          onDoubleClickEvent={onDoubleClickEvent}
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
          onOpenCouldNotService={(j) => setCnsJob(j)}
          selectedJobIds={selectedJobIds}
          onToggleSelect={toggleJobSelected}
          canMultiSelectDelete={canMultiSelectDelete}
          onOpenBulkDelete={() => setDeleteConfirmOpen(true)}
          onClearSelection={clearSelection}
          onSelectAllInView={selectAllInView}
          onBulkNavigateRoute={doBulkNavigateRoute}
          canMultiSelectAssign={canMultiSelectAssign}
          onOpenBulkAssign={(techId) => {
            setAssignPickedTechId(techId);
            setAssignConfirmOpen(true);
          }}
          techs={techs}
          onOpenEdit={isAdminRole ? ((jobRow) => setEditingJob(jobRow)) : undefined}
          isAdminForCard={isAdminRole}
          orderController={orderController}
          onOpenBulkReorder={() => {
            // Phase P10 · Feb-2026 — the button below is disabled
            // for mixed_lanes / has_unassigned, but a keyboard
            // shortcut or programmatic call could still hit this
            // handler. Guard by raising the banner instead of
            // opening a modal that would 409 on Save.
            if (reorderLaneStatus === "mixed_lanes") {
              orderController.setLaneBanner?.({
                code: "mixed_lanes_client",
                text: REORDER_MIXED_LANE_ERROR_TEXT,
              });
              return;
            }
            if (reorderLaneStatus === "has_unassigned") {
              orderController.setLaneBanner?.({
                code: "no_lane_resolvable",
                text: REORDER_LANE_ERROR_TEXT,
              });
              return;
            }
            setOptimizePayload(null);
            setBulkReorderOpen(true);
          }}
          onOptimizeRoute={optimizeRoute}
          optimizing={optimizing}
          reorderableJobIds={_reorderScopedJobs.map((j) => j.id)}
          reorderLaneStatus={reorderLaneStatus}
          tenantTz={tenantTz}
        />
      )}

      {/* Feb-2026 · numbered-order reorder — bulk modal.  Only
          admins/managers/super_admins see the trigger + the modal;
          techs never see either. */}
      {bulkReorderOpen && isAdminRole ? (
        <BulkReorderModal
          jobs={_reorderScopedJobs}
          techUserId={_dayTechHint}
          date={focusISO}
          initialOrder={optimizePayload?.orderedIds || null}
          optimizeSummary={optimizePayload?.summary || null}
          optimizeWarnings={optimizePayload?.warnings || null}
          onClose={() => { setBulkReorderOpen(false); setOptimizePayload(null); }}
          onSaved={() => { setOptimizePayload(null); load(); }}
        />
      ) : null}

      {/* Feb-2026 · Batched Wave #2 — the ``<ScheduleMap />`` that
          used to render below the grid moved ABOVE the calendar/grid
          block (see ``schedule-map-wrap`` above) and is now
          controlled by the persistent ``mapVisible`` toggle. Do NOT
          re-add a second render here — it would double-render the
          map and duplicate every marker on the day. */}

      {/* Feb-2026 · Numbered-order reorder — the previous
          <ScheduleDayDnDPanel /> mount lived here; DnD was
          replaced by inline number inputs on each grid card
          plus a bulk "Reorder…" modal.  The persistence contract
          (POST /jobs/reorder) is unchanged. */}

      {/* Feb-2026 · Schedule multi-select · bulk soft-delete confirm. */}
      {deleteConfirmOpen ? (
        <BulkDeleteConfirmModal
          count={selectedJobIds.size}
          busy={deleteBusy}
          onCancel={() => setDeleteConfirmOpen(false)}
          onConfirm={doBulkDelete}
        />
      ) : null}

      {/* Phase 28 · Feb-2026 · Schedule multi-select · bulk reassign confirm. */}
      {assignConfirmOpen ? (
        <BulkReassignConfirmModal
          count={selectedJobIds.size}
          techs={techs}
          pickedTechId={assignPickedTechId}
          busy={assignBusy}
          onCancel={() => { setAssignConfirmOpen(false); setAssignPickedTechId(""); }}
          onConfirm={doBulkReassign}
        />
      ) : null}

      {/* Phase 56.3 follow-up — clock-in gate dialog for landscape techs. */}
      <ClockInGateDialog gate={clockGate} />

      {/* SO-A · Feb-2026 — MARCO Suggestions right-side drawer. */}
      {marcoJob && isAdminRole ? (
        <MarcoSuggestionsPanel
          jobId={marcoJob.id}
          targetDate={marcoJob.scheduled_date
            || (marcoJob.scheduled_start
                ? String(marcoJob.scheduled_start).slice(0, 10)
                : new Date().toISOString().slice(0, 10))}
          onClose={() => setMarcoJob(null)}
          onApplied={async () => { await load({ force: true }); }}
        />
      ) : null}

      {/* Phase P12 · Feb-2026 — Optimize Route error dialog.
          Fires when ``POST /api/schedule/optimize-route`` throws.
          Uses the shared shadcn ``Dialog`` primitive so it inherits
          the app's focus-trap + a11y semantics; kept scoped to
          error state so a null ``optimizeError`` renders nothing. */}
      <Dialog
        open={!!optimizeError}
        onOpenChange={(o) => { if (!o) setOptimizeError(null); }}
      >
        <DialogContent data-testid="optimize-error-dialog">
          <DialogHeader>
            <DialogTitle>Couldn&apos;t optimize route</DialogTitle>
            <DialogDescription>
              {optimizeError?.message || "Optimization failed."}
            </DialogDescription>
          </DialogHeader>
          {optimizeError?.code ? (
            <div className="text-sm text-muted-foreground">
              Support reference code:{" "}
              <code
                data-testid="optimize-error-code"
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
              >
                {optimizeError.code}
              </code>
            </div>
          ) : null}
          {Array.isArray(optimizeError?.warnings) && optimizeError.warnings.length ? (
            <ul
              data-testid="optimize-error-warnings"
              className="mt-2 list-disc pl-6 text-sm text-muted-foreground"
            >
              {optimizeError.warnings.map((w, i) => (
                <li key={i}>{String(w)}</li>
              ))}
            </ul>
          ) : null}
          <DialogFooter>
            <button
              data-testid="optimize-error-close"
              className="rounded-md border px-3 py-1.5 text-sm"
              onClick={() => setOptimizeError(null)}
            >
              Close
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
      {/* Feb-2026 · Schedule-screen inline edit modal. Mutates
          ``rawJobs`` in place on save so the affected card re-
          renders without a full reload. Delete removes it. */}
      <ScheduleJobEditModal
        open={!!editingJob}
        job={editingJob}
        user={user}
        onClose={() => setEditingJob(null)}
        onSaved={(updated) => {
          patchJobInPlace(updated);
          setEditingJob(null);
          setToast({ kind: "info",
                     text: `Job saved for ${updated.customer_name || "customer"}` });
        }}
        onDeleted={(jid) => {
          removeJobInPlace(jid);
          setEditingJob(null);
          setToast({ kind: "info", text: "Job deleted" });
        }}
      />
      {/* Feb-2026 · Phase 1 — Could-Not-Service modal. Mutates the
          job in place on success so its status pill flips to
          "Could Not Service" without a full reload. */}
      {cnsJob && (
        <CouldNotServiceModal
          job={cnsJob}
          onClose={() => setCnsJob(null)}
          onDone={(resp) => {
            if (resp?.job) patchJobInPlace(resp.job);
            else patchJobInPlace({ ...cnsJob, status: "could_not_service" });
          }}
        />
      )}
    </SafeScrollContainer>
  );
}

/* ═══ Phase 30W · Grid panel ═════════════════════════════════════════ */
// Feb-2026 · Batch #4 · Item 3 — named export so the Vitest suite
// can render GridPanel in isolation and assert the refresh button's
// wiring without spinning up the entire CalendarSchedule tree.
export function GridPanel({
  date, setDate, jobs, loading, checked, onToggle, canWrite,
  onBulkComplete, onOpenMove, moveOpen, setMoveOpen, moveDate, setMoveDate,
  onConfirmMove, busy, onOpenJob, onNewJob,
  // Feb-2026 · Schedule multi-select soft-delete —
  selectedJobIds, onToggleSelect, canMultiSelectDelete,
  onOpenBulkDelete, onClearSelection, onSelectAllInView,
  // Phase F1 · Feb-2026 · multi-stop "Navigate route" bulk action —
  onBulkNavigateRoute,
  // Phase 28 · Feb-2026 · Schedule multi-select bulk reassign —
  canMultiSelectAssign, onOpenBulkAssign, techs,
  // Feb-2026 · Schedule-screen inline edit — admin+ Pencil affordance.
  onOpenEdit, isAdminForCard,
  // Feb-2026 · Phase 1 — Could-Not-Service modal opener.
  onOpenCouldNotService,
  // Feb-2026 · numbered-order reorder — the day's ordering
  // controller (drives inline inputs) + bulk-modal opener + the id
  // set that is actually reorderable (non-terminal only).
  orderController, onOpenBulkReorder, reorderableJobIds,
  // Phase P10 · Feb-2026 — lane-scope status for the Reorder button
  // (``ready`` | ``mixed_lanes`` | ``has_unassigned`` | ``empty``).
  reorderLaneStatus = "ready",
  onOptimizeRoute, optimizing,
  // Feb 2026 · P0 Timezone Fix (Section C follow-up) — tenant IANA
  // tz passed by the parent CalendarSchedule.  When present, the
  // Grid header's "focused day" ISO + "Today" pill both flip to
  // the tenant's day (matches the parent-level fix). Defaults to
  // ``TENANT_TZ_FALLBACK`` so the isolated Vitest harness (which
  // renders <GridPanel> without a parent) still behaves correctly.
  tenantTz = TENANT_TZ_FALLBACK,
}) {
  const focusISO = getTenantISODate(date, tenantTz);
  const isToday = focusISO === getTenantTodayISO(tenantTz);
  // Feb 2026 · P0 Timezone Fix (Section C follow-up) — day label
  // MUST match ``focusISO`` (which is tenant-tz-scoped).  Using
  // ``date.toLocaleDateString`` with no explicit ``timeZone`` fell
  // back to the browser's local zone, so an east-coast browser
  // viewing a Phoenix tenant at 8 PM Phoenix would see the header
  // read "Friday, Sep 18" while the ISO / jobs list rendered
  // "Sep 17". Explicit ``timeZone: tenantTz`` keeps them in lock-step.
  const dayLabel = date.toLocaleDateString(undefined, {
    weekday: "long", year: "numeric", month: "short", day: "numeric",
    timeZone: tenantTz,
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
        {/* Feb-2026 · Batch #4 · Item 3 (continuation) — the refresh
            affordance was hoisted to the CalendarSchedule top-level
            toolbar so it renders on Calendar (month/agenda) modes
            too, not just Grid. See the ``schedule-refresh`` button
            near ``calendar-send-to-dispatch``. This intentionally
            leaves the GridPanel without its own local refresh — one
            testid per page, no ambiguity for automation. */}
        <div className="flex-1" />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }} data-testid="grid-day-label">
          {dayLabel}
        </div>
      </div>

      {/* Bulk-action pill row — Feb-2026 HOTFIX (user report, live):
          technicians must NOT see the bulk-action strip (Complete /
          Move / Reorder / Optimize Route). These are dispatcher /
          planner actions. Per-job row actions (On my way / Could not
          service / individual complete) stay visible for techs.

          Gate is now ``canWrite && isAdminForCard`` — the entire strip
          is removed from the DOM for tech users, not just disabled.
          Complete + Move remain admin-visible even at zero selection
          (they self-disable via the ``checked.size === 0`` prop). */}
      {canWrite && isAdminForCard ? (
        <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="grid-bulk-pills">
          {/* Phase P10 · Feb-2026 — lane-scope error banner. Renders
              when reorder can't proceed (mixed lanes / unassigned
              jobs). Dismissable via the × button so the operator
              can hide it once they've read the guidance. */}
          {orderController ? (
            <div className="w-full">
              <ReorderErrorBanner controller={orderController} />
            </div>
          ) : null}
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
            <MoveIcon size={12} /> Bulk Reschedule ({checked.size})
          </button>
          <button
            onClick={onOpenBulkReorder}
            disabled={busy || !isAdminForCard || (reorderableJobIds || []).length < 2
                       || reorderLaneStatus === "mixed_lanes"
                       || reorderLaneStatus === "has_unassigned"}
            className="flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold"
            style={{
              background: "#7C3AED", color: "#fff",
              opacity: (!isAdminForCard || (reorderableJobIds || []).length < 2
                          || reorderLaneStatus === "mixed_lanes"
                          || reorderLaneStatus === "has_unassigned")
                ? 0.4 : 1,
            }}
            data-testid="grid-bulk-reorder"
            title={
              !isAdminForCard
                ? "Reorder is admin/manager only."
                : reorderLaneStatus === "mixed_lanes"
                  ? REORDER_MIXED_LANE_ERROR_TEXT
                  : reorderLaneStatus === "has_unassigned"
                    ? REORDER_LANE_ERROR_TEXT
                    : (reorderableJobIds || []).length < 2
                      ? "Need at least 2 non-terminal jobs to reorder."
                      : "Open the bulk reorder modal"
            }
          >
            <ArrowUp size={12} /> Reorder…
          </button>
          {/* Feb-2026 · Optimize Route — non-destructive pre-fill of the
              Reorder modal via Google Directions v2 + ORION-inspired
              zip-cluster tiebreaker. Admin/manager only (same gate as
              the Reorder button). Disabled when <2 stops or already
              optimizing. */}
          <button
            onClick={onOptimizeRoute}
            disabled={busy || optimizing || !isAdminForCard
                       || (reorderableJobIds || []).length < 2}
            className="flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold"
            style={{
              background: "#0F766E", color: "#fff",
              opacity: (!isAdminForCard || optimizing
                          || (reorderableJobIds || []).length < 2)
                ? 0.55 : 1,
            }}
            data-testid="id-optimize-route-btn"
            title={
              !isAdminForCard
                ? "Optimize Route is admin/manager only."
                : (reorderableJobIds || []).length < 2
                  ? "Need at least 2 stops to optimize"
                  : optimizing
                    ? "Optimizing…"
                    : "Compute a UPS-ORION-inspired optimal order (Google Directions v2)"
            }
          >
            {optimizing ? "Optimizing…" : "\u2732 Optimize Route"}
          </button>
        </div>
      ) : null}
      {isAdminForCard && orderController ? (
        <ReorderBanner controller={orderController} />
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

      {/* Feb-2026 · Schedule multi-select · action toolbar.
          Rendered above the row list when the caller is admin+ and at
          least one job is selected. Purely a UX affordance — clicking
          "Delete N" opens the shared confirm modal in the parent. */}
      {canMultiSelectDelete && selectedJobIds && selectedJobIds.size > 0 ? (
        <div
          className="flex items-center gap-2 rounded-xl mb-3 px-3 py-2"
          style={{ background: "#FEF3C7",
                     border: "1px solid #FDE68A", color: "#78350F" }}
          data-testid="grid-selection-toolbar"
        >
          <span className="text-sm font-bold" data-testid="grid-selection-count">
            {selectedJobIds.size} selected
          </span>
          {/* Feb-2026 · "Select all in view" inside the active
              toolbar — mirrors the pre-selection affordance so the
              user can escalate a partial pick to everything on the
              current day without clearing first. */}
          <button
            type="button"
            onClick={onSelectAllInView}
            className="text-xs font-semibold underline hover:no-underline"
            style={{ color: "#78350F" }}
            data-testid="grid-selection-select-all"
          >
            Select all in view
          </button>
          <button
            type="button"
            onClick={onClearSelection}
            className="text-xs font-semibold underline hover:no-underline"
            style={{ color: "#78350F" }}
            data-testid="grid-selection-clear"
          >
            Deselect all
          </button>
          <div className="flex-1" />
          {/* Phase F1 · Feb-2026 · Multi-stop "Navigate route" —
              disabled at 1 selection (single-stop navigation is
              already covered by the per-card <NavigateJobButton>);
              live at 2+.  Cross-day / cross-tech selections are
              sorted schedule-first by the URL builder. */}
          {onBulkNavigateRoute ? (() => {
            const single = selectedJobIds.size < 2;
            return (
              <button
                type="button"
                onClick={single ? undefined : onBulkNavigateRoute}
                disabled={single}
                title={single
                  ? "Select 2+ jobs to build a multi-stop route"
                  : `Open Google Maps route for ${selectedJobIds.size} stops`}
                className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-bold"
                style={{
                  background: single ? "#F5F5F4" : "#1D4ED8",
                  color: single ? "#A8A29E" : "#FFFFFF",
                  border: single ? "1px solid #E7E5E4" : "1px solid #1D4ED8",
                  cursor: single ? "not-allowed" : "pointer",
                }}
                data-testid="grid-selection-navigate-route"
              >
                <Navigation2 size={13} /> Navigate route
              </button>
            );
          })() : null}
          <button
            type="button"
            onClick={onOpenBulkDelete}
            className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-bold"
            style={{ background: "#DC2626", color: "#FFFFFF" }}
            data-testid="grid-selection-delete"
          >
            <Trash2 size={13} /> Delete {selectedJobIds.size}
          </button>
          {canMultiSelectAssign ? (
            <AssignTechDropdown
              techs={techs}
              onPick={onOpenBulkAssign}
              count={selectedJobIds.size}
            />
          ) : null}
        </div>
      ) : canMultiSelectDelete && Array.isArray(jobs) && jobs.length > 0 ? (
        // Feb-2026 · Pre-selection "Select all" affordance. Only
        // renders for super_admin / admin / manager (via
        // ``canMultiSelectDelete`` which the parent computed with
        // the same three-role list). Techs + customers never see
        // this row.
        <div
          className="flex items-center gap-2 rounded-xl mb-3 px-3 py-2"
          style={{ background: colors.surfaceSecondary,
                     border: `1px solid ${colors.border}`, color: colors.onSurface }}
          data-testid="grid-selection-preselect-bar"
        >
          <span className="text-xs" style={{ color: colors.muted }}>
            Bulk actions
          </span>
          <button
            type="button"
            onClick={onSelectAllInView}
            className="text-xs font-semibold px-2 py-1 rounded-lg"
            style={{ background: colors.surface,
                     border: `1px solid ${colors.border}`,
                     color: colors.onSurface }}
            data-testid="grid-selection-select-all"
          >
            Select all in view ({jobs.length})
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
          {jobs.map((j, _idx) => {
            const pill = STATUS_PILL[(j.status || "scheduled").toLowerCase()] || STATUS_PILL.scheduled;
            const svc = SERVICE_PALETTE(j.service_type);
            const isChecked = checked.has(j.id);
            // Feb-2026 · Schedule-UI · colored left border.
            const statusBorderColor = getStatusBorderColor(j.status);
            // Phase K50 · Feb-2026 — status-tinted card background.
            // Falls through to ``colors.surface`` (white) for statuses
            // outside the K50 map so the day/week view visual language
            // for ``on_hold`` / ``requested`` / ``reopened`` remains
            // unchanged (those retain their pill treatment).
            const k50CardBg = k50JobStatusColor(j.status) || colors.surface;
            // Feb-2026 · Schedule multi-select · per-card delete checkbox.
            const isSelectedForDelete = !!(selectedJobIds && selectedJobIds.has(j.id));
            return (
              <div
                key={j.id}
                className="flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer"
                style={{
                  background: k50CardBg,
                  border: `1px solid ${colors.border}`,
                  borderLeftWidth: 4,
                  borderLeftColor: statusBorderColor,
                }}
                data-testid={`grid-job-${j.id}`}
                data-status-color={statusBorderColor}
                data-k50-bg={k50CardBg}
                onClick={() => onOpenJob(j.id)}
                role="button"
              >
                {isAdminForCard && orderController
                  && (reorderableJobIds || []).includes(j.id) ? (
                  <NumberOrderInput
                    job={j}
                    controller={orderController}
                    testId={`grid-order-input-${j.id}`}
                  />
                ) : null}
                {canMultiSelectDelete ? (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onToggleSelect?.(j.id); }}
                    className="w-5 h-5 rounded-md flex items-center justify-center"
                    style={{
                      background: isSelectedForDelete ? "#DC2626" : "transparent",
                      border: `1.5px solid ${isSelectedForDelete ? "#DC2626" : colors.muted}`,
                    }}
                    aria-label={isSelectedForDelete ? "Deselect this job" : "Select this job for deletion"}
                    data-testid={`grid-select-${j.id}`}
                    data-selected={isSelectedForDelete ? "true" : "false"}
                  >
                    {isSelectedForDelete ? <Check size={12} color="#FFFFFF" /> : null}
                  </button>
                ) : null}
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
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] font-bold uppercase tracking-wide"
                       style={{ color: svc.tag }}>
                    {isRecurring(j) ? "🔁 " : ""}{j.service_type || "General"}
                  </div>
                  <div className="text-sm font-bold flex items-center gap-1.5" style={{ color: colors.onSurface }}>
                    {/* Feb-2026 · Schedule polish — the per-card
                        <TechAvatar> that used to render the
                        tech's initials (e.g. "MR") between the
                        route-number input and the customer name
                        was removed. The schedule day view is
                        already tech-scoped in the header, so the
                        per-card avatar was redundant clutter. */}
                    {/* Feb-2026 · Schedule card redesign —
                        customer name is now the primary directions
                        trigger.  The truncation styles
                        (``flex-1 min-w-0 overflow-hidden text-
                        ellipsis whitespace-nowrap``) are preserved
                        on the button so long names still ellipsise
                        inside the fixed card grid.  Falls back to
                        a plain ``<span>`` when neither coords nor
                        address are resolvable. */}
                    {buildDirectionsUrl(j) ? (
                      <button
                        type="button"
                        onClick={(e) => openDirections(j, e)}
                        className="flex-1 min-w-0 text-left cursor-pointer hover:underline focus:outline-none focus-visible:underline"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          color: colors.onSurface,
                          background: "transparent",
                          padding: 0,
                          border: 0,
                          font: "inherit",
                        }}
                        data-testid={`schedule-card-${j.id}-customer-name-directions`}
                        aria-label={`Open directions to ${j.customer_name || "customer"}`}
                      >
                        {j.customer_name || "Unknown"}
                      </button>
                    ) : (
                      <span
                        className="flex-1 min-w-0"
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        data-testid={`grid-job-title-${j.id}`}
                      >
                        {j.customer_name || "Unknown"}
                      </span>
                    )}
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
                  {/* Feb-2026 · Schedule card redesign — address sits
                      directly under the customer-name row, bumped to
                      ``text-lg`` and wired as a second directions
                      trigger (mirror of the name button above). */}
                  {j.address ? (
                    <div className="text-lg" style={{ color: colors.muted }}>
                      <button
                        type="button"
                        onClick={(e) => openDirections(j, e)}
                        className="text-left cursor-pointer hover:underline focus:outline-none focus-visible:underline truncate"
                        style={{
                          color: colors.muted,
                          background: "transparent",
                          padding: 0,
                          border: 0,
                          font: "inherit",
                          maxWidth: "100%",
                        }}
                        data-testid={`schedule-card-${j.id}-address-directions`}
                        aria-label={`Open directions to ${j.customer_name || "customer"}`}
                      >
                        {j.address}
                      </button>
                    </div>
                  ) : null}
                  {/* Feb-2026 · schedule polish — gate-code amber
                      pill (with lucide Key icon).  Merges the
                      property's ``access_notes`` free-text after a
                      bullet when present. Rendered only when at
                      least one of the fields is populated. */}
                  {(() => {
                    const code = j.customer_gate_code || j.gate_code;
                    const access = j.access_notes || j.access_instructions;
                    if (!code && !access) return null;
                    return (
                      <div className="mt-1">
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold"
                          style={{
                            background: "#FEF3C7",
                            color: "#78350F",
                            border: "1px solid #FCD34D",
                            fontFamily: "ui-monospace, SFMono-Regular, monospace",
                            maxWidth: "100%",
                          }}
                          title={
                            (code ? `Gate: ${code}` : "Access") +
                            (access ? ` · ${access}` : "")
                          }
                          data-testid={`job-gate-code-${j.id}`}
                        >
                          <Key size={11} />
                          {code ? <>Gate: <span style={{ letterSpacing: 1 }}>{code}</span></> : <>Access</>}
                          {access ? (
                            <span
                              className="truncate"
                              style={{ maxWidth: 160, fontWeight: 600, fontFamily: font.family }}
                              data-testid={`job-access-notes-${j.id}`}
                            >
                              {" · "}{access}
                            </span>
                          ) : null}
                        </span>
                      </div>
                    );
                  })()}
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
                  {/* Feb-2026 · Schedule polish — amber-accented job
                      notes chip. Shared component with TodaySchedule +
                      mobile so techs see the same treatment everywhere.
                      Component self-hides when both notes are empty. */}
                  <JobNotesCallout
                    jobId={j.id}
                    note={j.notes}
                    customerNote={j.customer_notes || j.account_notes}
                    truncated={j.notes_truncated}
                  />
                  <div className="flex items-center gap-2 mt-1 text-xs" style={{ color: colors.muted }}>
                    <FileText size={11} />
                    <span>{jobHours(j)}</span>
                    {/* Phase 30X · time-of-day removed. Schedule is per-day. */}
                  </div>
                  {/* Feb-2026 · Phase 1 — compact per-job "On my way"
                      SMS button. Rendered for technician / manager /
                      admin / super_admin (component self-gates on
                      role); hidden for completed / canceled jobs so a
                      dispatcher can't spam customers post-visit. */}
                  {["completed", "canceled", "cancelled", "skipped", "could_not_service"].includes(
                    String(j.status || "").toLowerCase()
                  ) ? null : (
                    <div className="mt-2 flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
                      <OnMyWayButton
                        jobId={j.id}
                        customerFirstName={(j.customer_name || "").split(" ")[0] || ""}
                        variant="compact"
                        testId={`on-my-way-btn-${j.id}`}
                      />
                      {/* Feb-2026 · Phase 1 — Could Not Service. Same
                          terminal-status guard as OMW plus the new
                          ``could_not_service`` status itself so we
                          can't re-open the modal after a mark. */}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); onOpenCouldNotService?.(j); }}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold"
                        // Feb-2026 HOTFIX (live user report) — was
                        // amber-100 which read as a "warning card"
                        // (soft). Now a proper WCAG-AA danger red
                        // via --action-cantservice-* tokens so techs
                        // see it as a destructive-adjacent action.
                        style={{
                          backgroundColor: "var(--action-cantservice-bg, #DC2626)",
                          color:           "var(--action-cantservice-fg, #FFFFFF)",
                          border:          "1px solid var(--action-cantservice-border, #B91C1C)",
                        }}
                        data-testid={`could-not-service-btn-${j.id}`}
                        data-action-role="cantservice"
                      >
                        Could not service
                      </button>
                    </div>
                  )}
                </div>
                <div
                  className="px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide"
                  style={{ background: pill.bg, color: pill.fg }}
                >
                  {pill.label}
                </div>
                {/* Feb-2026 · Batched Wave #1 — the per-job
                    <NavigateJobButton> that used to render here
                    (at the far right of the card) moved into the
                    title row above so it sits adjacent to the
                    customer name (mobile parity). Intentionally
                    NOT rendered a second time here. */}
                <button
                  onClick={(e) => { e.stopPropagation(); onOpenJob(j.id); }}
                  // Feb-2026 HOTFIX (live user report) — was a bare
                  // transparent chevron in muted-gray. Now a filled
                  // pill using --nav-arrow-* tokens so it reads as
                  // the primary "tap here → open job" affordance on
                  // the card (44×44 hit target for mobile a11y).
                  style={{
                    background: "var(--nav-arrow-bg, #1B1F5C)",
                    color: "var(--nav-arrow-fg, #FFFFFF)",
                    border: 0,
                    borderRadius: 12,
                    cursor: "pointer",
                    minWidth: 44,
                    minHeight: 44,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    boxShadow: "0 1px 2px rgba(0,0,0,0.12)",
                  }}
                  data-testid={`grid-open-${j.id}`}
                  data-action-role="nav-arrow"
                  aria-label="Open job detail"
                >
                  <ChevronRight size={22} strokeWidth={2.75} />
                </button>
                {/* Feb-2026 · Schedule-screen inline edit affordance.
                    Gated by ``isAdminRole`` (super_admin | admin |
                    manager) — techs and customers never see it.
                    Backend PUT /api/jobs/{id} also role-gates so a
                    forged request still 403s. */}
                {onOpenEdit && isAdminForCard ? (
                  <button
                    onClick={(e) => { e.stopPropagation(); onOpenEdit(j); }}
                    style={{ background: "transparent", border: 0, cursor: "pointer", color: colors.muted }}
                    data-testid={`grid-edit-${j.id}`}
                    aria-label="Edit job"
                    title="Edit job"
                  >
                    <Pencil size={16} />
                  </button>
                ) : null}
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
function TechColorLegend({ techs, techColorMap, crews = [] }) {
  // Phase K73 · Feb-2026 — group legend rows by crew so the
  // crew-hued palette becomes self-documenting (crew badge on
  // the left → members with saturation variants on the right).
  // Filter down to active techs and merge in the work-class
  // counter fields the pre-K73 legend surfaced.
  const activeTechs = React.useMemo(() => (
    (techs || []).filter((t) => t?.name && (t.active !== false))
  ), [techs]);
  const workLoadById = React.useMemo(() => {
    const m = new Map();
    for (const t of activeTechs) {
      const id = t.id || t.user_id;
      if (!id) continue;
      m.set(id, {
        activeJobs: Number(t.active_jobs) || 0,
        activeJobsRepair: Number(t.active_jobs_repair) || 0,
        activeJobsService: Number(t.active_jobs_service) || 0,
      });
    }
    return m;
  }, [activeTechs]);
  const groups = React.useMemo(
    () => groupByCrewForLegend(activeTechs, crews),
    [activeTechs, crews],
  );
  if (groups.length === 0) return null;
  return (
    <div
      className="flex items-center gap-4 overflow-x-auto pb-2 mb-2"
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid="calendar-tech-legend"
    >
      <span
        className="text-[10px] font-bold uppercase tracking-wider shrink-0"
        style={{ color: colors.muted }}
      >
        Techs
      </span>
      {groups.map((g) => (
        <div
          key={g.crewId || "solo"}
          className="flex items-center gap-2 shrink-0"
          data-testid={`calendar-tech-legend-crew-${g.crewId || "solo"}`}
        >
          <span
            className="text-[10px] font-bold uppercase tracking-wider shrink-0 px-1.5 py-0.5 rounded"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
            }}
          >
            {g.crewName}
          </span>
          {g.techs.map((t) => {
            const load = workLoadById.get(t.id) || { activeJobs: 0, activeJobsRepair: 0, activeJobsService: 0 };
            const color = techColorMap.get(t.id) || t.colorHex;
            return (
              <span
                key={t.id}
                className="inline-flex items-center gap-1.5 shrink-0"
                data-testid={`calendar-tech-legend-item-${t.id}`}
                data-color={color}
                data-explicit={t.isExplicit ? "1" : "0"}
                data-crew-id={g.crewId || ""}
                title={t.isExplicit ? `${t.name} (${color})` : `${t.name} (${g.crewName} · saturation variant)`}
              >
                <span
                  className="w-3 h-3 rounded-sm"
                  style={{
                    backgroundColor: color,
                    border: t.isExplicit ? "none" : `1px dashed ${colors.border}`,
                  }}
                />
                <span className="text-xs" style={{ color: colors.onSurface }}>{t.name}</span>
                {load.activeJobs > 0 ? (
                  <span
                    className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md ml-0.5"
                    style={{
                      background: colors.surfaceSecondary,
                      color: colors.onSurface,
                    }}
                    data-testid={`calendar-tech-legend-count-${t.id}`}
                    data-total={load.activeJobs}
                    data-service={load.activeJobsService}
                    data-repair={load.activeJobsRepair}
                  >
                    <span data-testid={`calendar-tech-legend-count-total-${t.id}`}>
                      {load.activeJobs}
                    </span>
                    {load.activeJobsRepair > 0 ? (
                      <>
                        <span aria-hidden="true" className="opacity-60"> · </span>
                        <span
                          data-testid={`calendar-tech-legend-count-repair-${t.id}`}
                          style={{ color: "#DC2626" }}
                          title={`${load.activeJobsRepair} repair${load.activeJobsRepair === 1 ? "" : "s"}`}
                        >
                          {load.activeJobsRepair}R
                        </span>
                      </>
                    ) : null}
                  </span>
                ) : null}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}


/**
 * Feb-2026 · Schedule multi-select · bulk soft-delete confirm dialog.
 *
 * Simple inline confirm — mirrors the destructive-variant pattern from
 * the Team page's DeleteTeamMemberDialog. Not a shadcn Dialog (matches
 * the rest of CalendarSchedule's inline-modal convention).
 */
function BulkDeleteConfirmModal({ count, busy, onCancel, onConfirm }) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={busy ? undefined : onCancel}
      data-testid="grid-bulk-delete-modal"
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="px-5 py-3 flex items-center justify-between"
             style={{ background: "#DC2626", color: "#FFFFFF" }}>
          <h2 className="text-base font-bold">Delete {count} job{count === 1 ? "" : "s"}?</h2>
          <button type="button" onClick={busy ? undefined : onCancel}
                  className="w-7 h-7 rounded-md flex items-center justify-center"
                  style={{ background: "rgba(255,255,255,0.18)" }}
                  data-testid="grid-bulk-delete-close"
                  aria-label="Close">
            <XIcon size={14} />
          </button>
        </div>
        <div className="p-5 space-y-3 text-sm" style={{ color: colors.onSurface }}>
          <p>
            Are you sure you want to delete <b>{count}</b> job{count === 1 ? "" : "s"}?
          </p>
          <p style={{ color: colors.muted }}>
            The jobs will be hidden from the schedule + list views. They can be
            undeleted by a super_admin. Historical completed jobs older than
            30 days are protected and will be skipped.
          </p>
        </div>
        <div className="px-5 py-3 flex items-center justify-end gap-2"
             style={{ background: colors.surfaceSecondary,
                        borderTop: `1px solid ${colors.border}` }}>
          <button type="button" onClick={onCancel} disabled={busy}
                  className="h-9 px-3 rounded-lg text-xs font-bold disabled:opacity-60"
                  style={{ background: colors.surface,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                  data-testid="grid-bulk-delete-cancel">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
                  className="inline-flex items-center gap-1 h-9 px-3 rounded-lg text-xs font-bold disabled:opacity-60"
                  style={{ background: "#DC2626", color: "#FFFFFF" }}
                  data-testid="grid-bulk-delete-confirm">
            {busy
              ? <><Loader2 size={13} className="animate-spin" /> Deleting…</>
              : <><Trash2 size={13} /> Delete</>}
          </button>
        </div>
      </div>
    </div>
  );
}



/**
 * Phase 28 · Feb-2026 · Schedule multi-select · Assign-tech dropdown.
 *
 * Rendered inline in the selection toolbar next to "Delete N". Click
 * opens a lightweight list of tech-family users (``pool_tech`` /
 * ``landscape_tech`` / ``technician``). Picking one fires
 * ``onPick(technician_id)`` which the parent uses to open the confirm
 * modal.
 */
function AssignTechDropdown({ techs, onPick, count }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    function _onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", _onDocClick);
    return () => document.removeEventListener("mousedown", _onDocClick);
  }, [open]);
  const options = (techs || []).filter((t) => {
    const role = (t.role || "").toLowerCase();
    return role === "pool_tech" || role === "landscape_tech"
        || role === "technician" || role === "tech";
  });
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-bold"
        style={{ background: "#0F6ED1", color: "#FFFFFF" }}
        data-testid="grid-selection-assign"
      >
        <UsersRound size={13} /> Assign tech {count} ▾
      </button>
      {open ? (
        <div
          className="absolute right-0 mt-1 rounded-lg shadow-xl"
          style={{
            background: "#fff",
            border: "1px solid #e5e7eb",
            minWidth: 220, maxHeight: 320, overflowY: "auto",
            zIndex: 40,
          }}
          data-testid="grid-selection-assign-menu"
        >
          {options.length === 0 ? (
            <div className="px-3 py-2 text-xs" style={{ color: "#6b7280" }}
                 data-testid="grid-selection-assign-empty">
              No techs available
            </div>
          ) : options.map((t) => (
            <button
              key={t.technician_id || t.id}
              type="button"
              onClick={() => {
                setOpen(false);
                onPick(t.technician_id || t.id);
              }}
              className="w-full text-left px-3 py-2 text-xs hover:bg-gray-100"
              style={{ color: "#111" }}
              data-testid={`grid-selection-assign-tech-${t.technician_id || t.id}`}
            >
              <div className="font-semibold">{t.name || t.first_name || t.email}</div>
              <div style={{ color: "#6b7280", fontSize: 10 }}>
                {(t.role || "").replace("_", " ")}
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}


/**
 * Phase 28 · Feb-2026 · Schedule multi-select · Bulk reassign confirm.
 *
 * Mirrors ``BulkDeleteConfirmModal`` — inline modal (no shadcn) for
 * consistency with the rest of CalendarSchedule. Shows the picked
 * tech's display name so admins can double-check before firing the
 * POST /api/jobs/bulk-reassign call.
 */
function BulkReassignConfirmModal({ count, techs, pickedTechId, busy,
                                        onCancel, onConfirm }) {
  const picked = (techs || []).find(
    (t) => (t.technician_id || t.id) === pickedTechId);
  const techName = (picked && (picked.name || picked.first_name || picked.email)) || "tech";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(15,23,42,0.55)" }}
      role="dialog" aria-modal="true"
      data-testid="grid-bulk-reassign-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div
        className="w-full max-w-md rounded-2xl shadow-2xl"
        style={{ backgroundColor: colors.surface }}
      >
        <div className="px-5 py-4">
          <div className="text-base font-bold"
               style={{ color: colors.onSurface }}
               data-testid="grid-bulk-reassign-title">
            Reassign {count} job(s) to {techName}?
          </div>
          <p className="text-xs mt-2" style={{ color: colors.muted }}>
            The previously-assigned tech (if any) will get an in-app
            notification. No SMS or email is sent to the customer.
          </p>
        </div>
        <div className="px-5 py-3 flex items-center justify-end gap-2"
             style={{ background: colors.surfaceSecondary,
                        borderTop: `1px solid ${colors.border}` }}>
          <button type="button" onClick={onCancel} disabled={busy}
                  className="h-9 px-3 rounded-lg text-xs font-bold disabled:opacity-60"
                  style={{ background: colors.surface,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                  data-testid="grid-bulk-reassign-cancel">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy || !pickedTechId}
                  className="inline-flex items-center gap-1 h-9 px-3 rounded-lg text-xs font-bold disabled:opacity-60"
                  style={{ background: "#0F6ED1", color: "#FFFFFF" }}
                  data-testid="grid-bulk-reassign-confirm">
            {busy
              ? <><Loader2 size={13} className="animate-spin" /> Reassigning…</>
              : <><UsersRound size={13} /> Reassign</>}
          </button>
        </div>
      </div>
    </div>
  );
}
