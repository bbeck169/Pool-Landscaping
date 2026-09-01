/**
 * Slice M · Workstream — jobs feed.
 *
 * Replaces the Phase-31 telemetry list with a rich, filterable job feed
 * powered by GET /api/workstream/jobs.  The old telemetry endpoint is
 * still alive (see /api/workstream/events) but no longer surfaced here
 * — techs + admins want to see actual jobs, not raw events.
 *
 * • M2 filters (AND): since / until / tech_id / customer_id / status.
 * • M2 sort: newest, oldest, tech A→Z / Z→A, customer A→Z / Z→A.
 * • M3 inline thumbnails on job cards (up to 4 images + 2 videos).
 * • M4 clickable cards → /jobs/:id (keyboard-accessible).
 *
 * Tech pricing invariance is enforced on the server; the UI never
 * renders job_totals so the guarantee is belt-and-braces.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Workflow, RefreshCw, Loader2, ChevronDown, X as XIcon, Image as ImageIcon, Video, MapPin, User, Star, Calendar as CalendarIcon, Pencil, Trash2 } from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { useAuth } from "@/auth";
import { Forbidden } from "@/hooks/usePermissions";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import { colors } from "@/theme";
import { StatusPill } from "@/components/ui-kit";
// Phase 19 · Feb-2026 · Sub-item A — job assignee avatar.
import { UserAvatar } from "@/components/UserAvatar";
// Feb-2026 · Services / Repairs countdown pills (shared classifier
// with the mobile tech Schedule screen — see ``mobile/lib/jobCategory``).
import JobCountPill from "@/components/JobCountPill";
import { computePillCounts } from "@/lib/jobCategory";
// Feb-2026 · Workstream inline job edit — reuses the exact modal
// the Schedule page's Pencil affordance opens. Do NOT fork.
import ScheduleJobEditModal from "@/pages/schedule/ScheduleJobEditModal";
import { toast as sonnerToast } from "sonner";

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "tech_asc", label: "Tech A → Z" },
  { value: "tech_desc", label: "Tech Z → A" },
  { value: "customer_asc", label: "Customer A → Z" },
  { value: "customer_desc", label: "Customer Z → A" },
];
const _STATUS_OPTIONS = ["", "pending", "in_progress", "completed", "cancelled"];

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function humanDate(iso) {
  if (!iso) return "Not scheduled";
  const bare = String(iso).slice(0, 10);
  return bare;
}

// ── Sub-components ─────────────────────────────────────────────────
function MediaStrip({ jid, media }) {
  const [preview, setPreview] = useState(null);
  const total = (media?.photos_count || 0) + (media?.videos_count || 0);
  if (total === 0) return null;
  const thumbs = [
    ...(media.photo_thumbs || []).map((p) => ({ ...p, kind: "photo" })),
    ...(media.video_thumbs || []).map((v) => ({ ...v, kind: "video" })),
  ];
  const token = localStorage.getItem(TOKEN_KEY);
  return (
    <div
      className="flex items-center gap-1.5 mt-2"
      data-testid={`ws-job-media-${jid}`}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {thumbs.map((t, i) => (
        <button
          key={`${t.kind}-${t.id || i}`}
          type="button"
          className="relative rounded-md overflow-hidden border"
          style={{
            width: 44, height: 44, borderColor: colors.border,
            background: colors.surfaceSecondary, cursor: "pointer",
            padding: 0,
          }}
          onClick={(e) => {
            e.stopPropagation();
            setPreview(t);
          }}
          aria-label={t.kind === "photo" ? "Open photo" : "Open video"}
          data-testid={`ws-thumb-${jid}-${i}`}
        >
          {t.kind === "photo" ? (
            <img
              src={`${BACKEND}${t.url}`}
              alt=""
              className="w-full h-full object-cover"
              loading="lazy"
            />
          ) : (
            <div
              className="w-full h-full flex items-center justify-center"
              style={{ background: "#0F172A", color: "#FFF" }}
            >
              <Video size={18} />
            </div>
          )}
        </button>
      ))}
      {media.extra_count > 0 ? (
        <div
          className="rounded-md text-xs font-semibold flex items-center justify-center"
          style={{
            width: 44, height: 44,
            border: `1px dashed ${colors.borderStrong}`,
            color: colors.muted,
          }}
          data-testid={`ws-thumb-extra-${jid}`}
        >
          +{media.extra_count}
        </div>
      ) : null}
      <div
        className="ml-1 text-[11px] flex items-center gap-1.5"
        style={{ color: colors.muted }}
      >
        <ImageIcon size={11} /> {media.photos_count}
        <Video size={11} /> {media.videos_count}
      </div>

      {preview ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(0,0,0,0.85)" }}
          onClick={() => setPreview(null)}
          data-testid="ws-lightbox"
        >
          <button
            className="absolute top-4 right-4 text-white"
            onClick={() => setPreview(null)}
            aria-label="Close preview"
          >
            <XIcon size={28} />
          </button>
          {preview.kind === "photo" ? (
            <img
              src={`${BACKEND}${preview.url}`}
              alt=""
              className="max-h-[85vh] max-w-full rounded-lg"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <video
              controls
              autoPlay
              className="max-h-[85vh] max-w-full rounded-lg"
              onClick={(e) => e.stopPropagation()}
              src={`${BACKEND}${preview.url}${token ? `?token=${encodeURIComponent(token)}` : ""}`}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}

function JobCard({ job, onOpen, isSelected, onToggleSelect, canBulk, onEdit }) {
  const handleKey = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(job.id);
    }
  };
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => onOpen(job.id)}
      onKeyDown={handleKey}
      className="px-4 py-3 outline-none focus:ring-2"
      style={{
        borderBottom: `1px solid ${colors.border}`,
        cursor: "pointer",
        background: isSelected ? "#FEF3C7" : colors.surface,
      }}
      data-testid={`ws-job-${job.id}`}
    >
      <div className="flex items-start gap-3">
        {/* Feb-2026 · Workstream per-row select — visible only to
            super_admin / admin / manager. Technicians + customers see
            no checkbox at all. Click stops propagation so the card
            navigation isn't triggered when the user is picking rows
            for a bulk action. */}
        {canBulk ? (
          <input
            type="checkbox"
            checked={!!isSelected}
            onChange={(e) => {
              e.stopPropagation();
              onToggleSelect && onToggleSelect(job.id, e.target.checked);
            }}
            onClick={(e) => e.stopPropagation()}
            className="mt-1"
            data-testid={`ws-select-${job.id}`}
            aria-label={`Select ${job.title || job.id}`}
          />
        ) : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="flex items-center gap-2 flex-wrap">
            {job.status ? <StatusPill status={job.status} /> : null}
            <span className="text-xs" style={{ color: colors.muted }}>
              {job.service_type || "—"}
            </span>
            {job.customer_is_vip ? (
              <span
                className="inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                style={{ background: "#FEF3C7", color: "#92400E" }}
                data-testid={`ws-vip-${job.id}`}
              >
                <Star size={9} /> VIP
              </span>
            ) : null}
          </div>
          <div
            className="text-sm font-semibold mt-1"
            style={{ color: colors.onSurface }}
          >
            {job.title || "Untitled job"}
          </div>
          <div
            className="text-xs mt-0.5 flex flex-wrap items-center gap-x-2"
            style={{ color: colors.muted }}
          >
            <span className="inline-flex items-center gap-1">
              <User size={11} /> {job.customer_name || "—"}
            </span>
            <span>·</span>
            <span className="inline-flex items-center gap-1">
              <MapPin size={11} /> {job.property_label || job.property_address || "No property"}
            </span>
            <span>·</span>
            <span className="inline-flex items-center gap-1">
              <CalendarIcon size={11} /> {humanDate(job.scheduled_date)}
            </span>
          </div>
          <div className="text-[11px] mt-0.5 flex items-center gap-1.5"
               style={{ color: colors.muted }}
               data-testid={`ws-job-assignee-${job.id}`}>
            <UserAvatar
              user={{
                name: job.technician_name,
                // Phase 19 · Feb-2026 · Sub-item A — new server-side
                // field wired through the existing profile_photo_url
                // source that UserAvatar already reads.
                profile_photo_url: job.assignee_photo_url || null,
              }}
              size="xs"
              testid={`ws-job-assignee-avatar-${job.id}`}
            />
            <span>
              Assigned to <b>{job.technician_name || "Unassigned"}</b>
              {job.line_items_count ? ` · ${job.line_items_count} line item${job.line_items_count === 1 ? "" : "s"}` : ""}
            </span>
          </div>
          <MediaStrip jid={job.id} media={job.media} />
        </div>
        <div
          className="text-[11px] whitespace-nowrap text-right flex flex-col items-end gap-1"
          style={{ color: colors.muted }}
          title={job.updated_at || job.created_at}
        >
          {relTime(job.updated_at || job.created_at)}
          {/* Feb-2026 · Workstream inline edit — Pencil affordance
              only visible to super_admin / admin / manager. Click
              stops propagation so the card navigation doesn't
              fire; the parent opens the shared ScheduleJobEditModal
              with this job pre-loaded. */}
          {canBulk ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onEdit && onEdit(job);
              }}
              className="inline-flex items-center justify-center rounded-md"
              style={{
                width: 24, height: 24,
                background: colors.surfaceSecondary,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
              }}
              aria-label={`Edit job ${job.title || job.id}`}
              data-testid={`ws-edit-${job.id}`}
            >
              <Pencil size={12} />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ActiveFilterChips({ filters, sort, onClear, onClearAll }) {
  const chips = [];
  if (filters.since) chips.push({ k: "since", label: `Since ${filters.since}` });
  if (filters.until) chips.push({ k: "until", label: `Until ${filters.until}` });
  if (filters.tech_id) chips.push({ k: "tech_id", label: `Tech: ${filters.tech_name || filters.tech_id}` });
  if (filters.customer_id) chips.push({ k: "customer_id", label: `Customer: ${filters.customer_name || filters.customer_id}` });
  if (filters.status) chips.push({ k: "status", label: `Status: ${filters.status}` });
  if (sort && sort !== "newest") {
    chips.push({ k: "sort", label: `Sort: ${SORT_OPTIONS.find((s) => s.value === sort)?.label || sort}` });
  }
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 mb-3" data-testid="ws-active-chips">
      {chips.map((c) => (
        <span
          key={c.k}
          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full"
          style={{ background: colors.brandTertiary, color: colors.onBrandTertiary }}
          data-testid={`ws-chip-${c.k}`}
        >
          {c.label}
          <button
            type="button"
            className="ml-1"
            onClick={() => onClear(c.k)}
            aria-label={`Clear ${c.k}`}
            style={{ background: "transparent", border: 0, cursor: "pointer", color: "inherit" }}
          >
            <XIcon size={12} />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={onClearAll}
        className="text-xs font-semibold underline"
        style={{ color: colors.brand, background: "transparent", border: 0, cursor: "pointer" }}
        data-testid="ws-clear-all"
      >
        Clear all
      </button>
    </div>
  );
}

// ── Page ────────────────────────────────────────────────────────────
export default function WorkstreamPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const role = user?.role || "";
  // Feb-2026 · Workstream — view gate is unchanged (admin |
  // super_admin still owns the page); bulk-selection affordances
  // (per-row checkbox, Pencil edit, delete toolbar) additionally
  // admit ``manager`` per the shipped role-parity spec. Technicians
  // + customers never see the Workstream page or any of its bulk
  // affordances.
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  const isAdmin = allowed;
  const canBulk = role === "admin" || role === "super_admin" || role === "manager";

  const [jobs, setJobs] = useState([]);
  // Feb-2026 · Workstream bulk-select — same mental model as the
  // Schedule page: a Set<string> of job ids the user has ticked.
  // Toolbar only renders when ``canBulk`` AND (size > 0 OR the
  // caller wants the pre-selection "Select all in view" bar).
  const [selectedJobIds, setSelectedJobIds] = useState(() => new Set());
  const [editingJob, setEditingJob] = useState(null);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // Filter state — status intentionally omitted (Workstream = completed).
  // Phase K7 · Feb-2026 — default the date filter to TODAY on mount
  // so the initial fetch returns only today's completed jobs for
  // every role.  Users can still widen the range after mount.  The
  // ISO date is computed via ``toISOString().slice(0, 10)`` which
  // returns a stable UTC YYYY-MM-DD string; the backend endpoint
  // (``routers/workstream.py``) already interprets ``since``/
  // ``until`` as tenant-local calendar dates so this matches the
  // existing DispatchBoard "Today" convention.
  const _K7_TODAY_ISO = new Date().toISOString().slice(0, 10);
  const [since, setSince] = useState(_K7_TODAY_ISO);
  const [until, setUntil] = useState(_K7_TODAY_ISO);
  const [techId, setTechId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [sort, setSort] = useState("newest");
  const [limit] = useState(100);

  // Dropdown data (admins only)
  const [techs, setTechs] = useState([]);
  const [customers, setCustomers] = useState([]);

  useEffect(() => {
    if (!isAdmin) return;
    Promise.all([
      api.get("/technicians").catch(() => []),
      api.get("/customers?is_active=true&limit=500").catch(() => []),
    ]).then(([t, c]) => {
      setTechs(Array.isArray(t) ? t : t?.items || []);
      setCustomers(Array.isArray(c) ? c : c?.items || []);
    });
  }, [isAdmin]);

  const load = useCallback(async () => {
    if (!allowed) return;
    setLoading(true);
    setErr("");
    try {
      const qs = new URLSearchParams({ limit: String(limit), sort });
      if (since) qs.set("since", since);
      if (until) qs.set("until", until);
      if (techId) qs.set("tech_id", techId);
      if (customerId) qs.set("customer_id", customerId);
      // Phase 5A.2 — Workstream defaults to completed on the server.
      // Do not send status here; sending anything else is a 400.
      const data = await api.get(`/workstream/jobs?${qs.toString()}`);
      setJobs(data?.jobs || []);
      setTotal(data?.total || 0);
    } catch (e) {
      setErr(e?.message || "Failed to load Workstream jobs.");
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }, [allowed, limit, sort, since, until, techId, customerId]);

  useEffect(() => {
    load();
  }, [load]);

  const techName = useMemo(
    () => techs.find((t) => t.id === techId)?.name || "",
    [techs, techId],
  );
  const customerName = useMemo(
    () => customers.find((c) => c.id === customerId)?.name || "",
    [customers, customerId],
  );

  const clearOne = (k) => {
    if (k === "since") setSince("");
    else if (k === "until") setUntil("");
    else if (k === "tech_id") setTechId("");
    else if (k === "customer_id") setCustomerId("");
    else if (k === "sort") setSort("newest");
  };
  const clearAll = () => {
    setSince(""); setUntil(""); setTechId(""); setCustomerId("");
    setSort("newest");
  };

  const openJob = (jid) => navigate(`/workstream/${jid}`);

  // Feb-2026 · Bulk-select helpers — kept together so the mental
  // model matches the Schedule page's ``selectedJobIds`` handlers.
  const toggleSelect = useCallback((jid, on) => {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(jid); else next.delete(jid);
      return next;
    });
  }, []);
  const clearSelection = useCallback(() => {
    setSelectedJobIds(new Set());
  }, []);
  const selectAllInView = useCallback(() => {
    setSelectedJobIds(new Set((jobs || []).map((j) => j.id)));
  }, [jobs]);
  const doBulkDelete = useCallback(async () => {
    if (selectedJobIds.size === 0) return;
    setBulkBusy(true);
    try {
      const ids = Array.from(selectedJobIds);
      const res = await api.post("/jobs/bulk-delete", { ids });
      const okC = res?.deleted_count || 0;
      const failed = res?.failed || [];
      // Optimistic — remove the deleted rows locally.
      const deletedSet = new Set(res?.deleted || []);
      setJobs((prev) => (prev || []).filter((j) => !deletedSet.has(j.id)));
      setSelectedJobIds(new Set());
      setConfirmBulkDelete(false);
      if (failed.length === 0) {
        sonnerToast.success(`${okC} job${okC === 1 ? "" : "s"} deleted`);
      } else {
        sonnerToast(`${okC} deleted · ${failed.length} skipped`, {
          description: failed.slice(0, 3).map((f) => f.reason).join(" · "),
        });
      }
    } catch (e) {
      sonnerToast.error(e?.message || "Bulk delete failed");
    } finally {
      setBulkBusy(false);
    }
  }, [selectedJobIds]);

  // Feb-2026 · Countdown pills — derived client-side from the same
  // ``jobs`` array the list renders. Recomputes reactively via
  // ``useMemo`` whenever filters / sorts refetch and repopulate.
  const pillCounts = useMemo(() => computePillCounts(jobs), [jobs]);

  if (!allowed) {
    return <Forbidden reason="Workstream is admin-only." />;
  }

  return (
    <div
      className="p-4 md:p-6"
      style={{ background: colors.surfaceSecondary, minHeight: "100%" }}
    >
      <div className="flex items-center gap-3 mb-4">
        <Workflow size={22} color={colors.brand} />
        <div>
          <div
            className="text-xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="workstream-title"
          >
            Work Stream
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Service log of every finished job. Click any card to open the full Service Log.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-semibold"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            cursor: "pointer",
          }}
          data-testid="workstream-refresh"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </div>

      {/* Feb-2026 · Countdown pills — SERVICES / REPAIRS derived
          client-side from the current jobs list. Updates reactively
          as filters / sort change (both trigger ``load`` which
          repopulates the ``jobs`` state that ``pillCounts`` is
          memoised on). */}
      <div
        className="flex flex-wrap items-center gap-3 mb-4"
        data-testid="workstream-count-pills"
      >
        <JobCountPill
          category="services"
          total={pillCounts.services.total}
          remaining={pillCounts.services.remaining}
          testid="workstream-pill-services"
        />
        <JobCountPill
          category="repairs"
          total={pillCounts.repairs.total}
          remaining={pillCounts.repairs.remaining}
          testid="workstream-pill-repairs"
        />
      </div>

      {/* Filter bar */}
      <div
        className="rounded-lg p-3 mb-3 flex flex-wrap gap-2 items-end"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="workstream-filter-bar"
      >
        <div className="flex flex-col">
          <label
            className="text-[10px] font-bold uppercase mb-0.5"
            style={{ color: colors.muted }}
          >
            Since
          </label>
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="px-2 py-1 rounded-md text-sm"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="ws-filter-since"
          />
        </div>
        <div className="flex flex-col">
          <label
            className="text-[10px] font-bold uppercase mb-0.5"
            style={{ color: colors.muted }}
          >
            Until
          </label>
          <input
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="px-2 py-1 rounded-md text-sm"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="ws-filter-until"
          />
        </div>
        {isAdmin ? (
          <div className="flex flex-col">
            <label
              className="text-[10px] font-bold uppercase mb-0.5"
              style={{ color: colors.muted }}
            >
              Technician
            </label>
            <select
              value={techId}
              onChange={(e) => setTechId(e.target.value)}
              className="px-2 py-1 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface, minWidth: 160 }}
              data-testid="ws-filter-tech"
            >
              <option value="">All technicians</option>
              {techs.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="flex flex-col">
          <label
            className="text-[10px] font-bold uppercase mb-0.5"
            style={{ color: colors.muted }}
          >
            Customer
          </label>
          <div style={{ minWidth: 180 }}>
            <CustomerCombobox
              value={customerId}
              onChange={setCustomerId}
              customers={customers}
              testid="ws-filter-customer"
              placeholder="All customers"
            />
          </div>
        </div>
        <div className="flex flex-col">
          {/* Phase 5A.2 · Feb 2026 — status filter removed. Workstream
              lists ONLY completed jobs (server rejects anything else). */}
        </div>
        <div className="flex flex-col ml-auto">
          <label
            className="text-[10px] font-bold uppercase mb-0.5"
            style={{ color: colors.muted }}
          >
            Sort
          </label>
          <div className="relative">
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="px-2 py-1 pr-7 rounded-md text-sm appearance-none"
              style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface, minWidth: 160 }}
              data-testid="ws-sort"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <ChevronDown
              size={13}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2"
              color={colors.muted}
            />
          </div>
        </div>
      </div>

      <ActiveFilterChips
        filters={{
          since, until,
          tech_id: techId, tech_name: techName,
          customer_id: customerId, customer_name: customerName,
          // Feb-2026 · P1 cleanup — Workstream is scoped to
          // ``status = completed`` server-side; there is no local
          // ``status`` state. The old shorthand ``status,`` here
          // resolved to ``window.status`` (empty string) and produced
          // a silent-but-real ReferenceError under SSR / strict lint.
        }}
        sort={sort}
        onClear={clearOne}
        onClearAll={clearAll}
      />

      {err ? (
        <div
          className="rounded-md p-3 text-sm mb-3"
          style={{ background: "#FEE2E2", color: "#991B1B", border: "1px solid #FCA5A5" }}
          data-testid="workstream-error"
        >
          {err}
        </div>
      ) : null}

      <div className="flex items-center justify-between mb-2 px-1">
        <div className="text-xs" style={{ color: colors.muted }}>
          <b>{total}</b> job{total === 1 ? "" : "s"} match{total === 1 ? "es" : ""} your filters
        </div>
      </div>

      {/* Feb-2026 · Workstream bulk toolbar — mirrors the visual
          language of the Schedule page's ``grid-selection-toolbar``
          / ``grid-selection-preselect-bar``. Two modes:
            * pre-selection: shows a subtle "Select all in view (N)"
              chip when nothing is picked yet.
            * active: shows the amber selection bar with count +
              Deselect all + Delete N. */}
      {canBulk && selectedJobIds.size > 0 ? (
        <div
          className="flex items-center gap-2 rounded-xl mb-3 px-3 py-2"
          style={{ background: "#FEF3C7",
                     border: "1px solid #FDE68A", color: "#78350F" }}
          data-testid="ws-selection-toolbar"
        >
          <span className="text-sm font-bold" data-testid="ws-selection-count">
            {selectedJobIds.size} selected
          </span>
          <button
            type="button"
            onClick={selectAllInView}
            className="text-xs font-semibold underline hover:no-underline"
            style={{ color: "#78350F" }}
            data-testid="ws-selection-select-all-in-view"
          >
            Select all in view ({jobs.length})
          </button>
          <button
            type="button"
            onClick={clearSelection}
            className="text-xs font-semibold underline hover:no-underline"
            style={{ color: "#78350F" }}
            data-testid="ws-selection-clear"
          >
            Deselect all
          </button>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => setConfirmBulkDelete(true)}
            className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-bold"
            style={{ background: "#DC2626", color: "#FFFFFF" }}
            data-testid="ws-selection-delete"
          >
            <Trash2 size={13} /> Delete {selectedJobIds.size}
          </button>
        </div>
      ) : canBulk && Array.isArray(jobs) && jobs.length > 0 ? (
        <div
          className="flex items-center gap-2 rounded-xl mb-3 px-3 py-2"
          style={{ background: colors.surfaceSecondary,
                     border: `1px solid ${colors.border}`, color: colors.onSurface }}
          data-testid="ws-selection-preselect-bar"
        >
          <span className="text-xs" style={{ color: colors.muted }}>
            Bulk actions
          </span>
          <button
            type="button"
            onClick={selectAllInView}
            className="text-xs font-semibold px-2 py-1 rounded-lg"
            style={{ background: colors.surface,
                       border: `1px solid ${colors.border}`,
                       color: colors.onSurface }}
            data-testid="ws-selection-preselect-select-all"
          >
            Select all in view ({jobs.length})
          </button>
        </div>
      ) : null}

      <div
        className="rounded-lg overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="workstream-list"
      >
        {loading && jobs.length === 0 ? (
          <div className="p-8 flex items-center justify-center" data-testid="workstream-loading">
            <Loader2 size={20} className="animate-spin" color={colors.brand} />
          </div>
        ) : jobs.length === 0 ? (
          <div
            className="p-8 text-sm text-center"
            style={{ color: colors.muted }}
            data-testid="workstream-empty"
          >
            No jobs match these filters yet.
          </div>
        ) : (
          jobs.map((j) => (
            <JobCard
              key={j.id}
              job={j}
              onOpen={openJob}
              canBulk={canBulk}
              isSelected={selectedJobIds.has(j.id)}
              onToggleSelect={toggleSelect}
              onEdit={setEditingJob}
            />
          ))
        )}
      </div>

      {/* Feb-2026 · Shared edit modal — same component the Schedule
          page's Pencil affordance opens. NO fork. Saved / deleted
          callbacks patch the local ``jobs`` array so the list
          reflects the change without a full refetch. */}
      <ScheduleJobEditModal
        open={!!editingJob}
        job={editingJob}
        onClose={() => setEditingJob(null)}
        onSaved={(patched) => {
          setJobs((prev) => (prev || []).map(
            (j) => (j.id === patched.id ? { ...j, ...patched } : j)));
          setEditingJob(null);
          sonnerToast.success("Job updated");
        }}
        onDeleted={(jid) => {
          setJobs((prev) => (prev || []).filter((j) => j.id !== jid));
          setEditingJob(null);
          sonnerToast.success("Job deleted");
        }}
      />

      {/* Feb-2026 · Bulk-delete confirm — matches the Schedule
          page's confirm-modal ergonomics. Under 500 rows the plain
          modal fires with "Delete N" wording; over-threshold path
          could be added later if Workstream ops start needing it. */}
      {confirmBulkDelete ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !bulkBusy) {
              setConfirmBulkDelete(false);
            }
          }}
          data-testid="ws-bulk-delete-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                       border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold" style={{ color: "#DC2626" }}
                data-testid="ws-bulk-delete-title">
              Delete {selectedJobIds.size} job{selectedJobIds.size === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mt-2"
                style={{ color: colors.onSurfaceSecondary || colors.muted }}>
              Completed jobs with an active invoice will be skipped
              (backend cascade guard). Deletion is soft — a super_admin
              can restore later via backend tooling.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmBulkDelete(false)}
                disabled={bulkBusy}
                className="px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-60"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface }}
                data-testid="ws-bulk-delete-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doBulkDelete}
                disabled={bulkBusy}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="ws-bulk-delete-confirm"
              >
                {bulkBusy ? "Deleting…" : `Delete ${selectedJobIds.size}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
