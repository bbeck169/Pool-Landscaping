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
import {
  Workflow,
  RefreshCw,
  Loader2,
  Filter,
  ChevronDown,
  X as XIcon,
  Image as ImageIcon,
  Video,
  MapPin,
  User,
  Star,
  Calendar as CalendarIcon,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { useAuth } from "@/auth";
import { Forbidden } from "@/hooks/usePermissions";
import { colors } from "@/theme";
import { StatusPill } from "@/components/ui-kit";

const SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "tech_asc", label: "Tech A → Z" },
  { value: "tech_desc", label: "Tech Z → A" },
  { value: "customer_asc", label: "Customer A → Z" },
  { value: "customer_desc", label: "Customer Z → A" },
];
const STATUS_OPTIONS = ["", "pending", "in_progress", "completed", "cancelled"];

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

function JobCard({ job, onOpen }) {
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
        background: colors.surface,
      }}
      data-testid={`ws-job-${job.id}`}
    >
      <div className="flex items-start gap-3">
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
          <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>
            Assigned to <b>{job.technician_name || "Unassigned"}</b>
            {job.line_items_count ? ` · ${job.line_items_count} line item${job.line_items_count === 1 ? "" : "s"}` : ""}
          </div>
          <MediaStrip jid={job.id} media={job.media} />
        </div>
        <div
          className="text-[11px] whitespace-nowrap text-right"
          style={{ color: colors.muted }}
          title={job.updated_at || job.created_at}
        >
          {relTime(job.updated_at || job.created_at)}
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
  // Phase 5A.2 · Feb 2026 — Workstream is admin-only. Manager, tech,
  // customer all get 403. Route-level <AdminOnly> catches them too.
  const allowed = role === "admin" || role === "super_admin";
  const isAdmin = allowed;

  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // Filter state — status intentionally omitted (Workstream = completed).
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
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
      api.get("/customers?limit=500").catch(() => []),
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
            Workstream — Completed Jobs
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
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="px-2 py-1 rounded-md text-sm"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface, minWidth: 180 }}
            data-testid="ws-filter-customer"
          >
            <option value="">All customers</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
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
          status,
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
            <JobCard key={j.id} job={j} onOpen={openJob} />
          ))
        )}
      </div>
    </div>
  );
}
