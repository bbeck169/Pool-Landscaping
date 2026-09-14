// Phase 56.16-followup — Customer portal Service Reports UI (web).
//
// Read-only surface at /portal/service-reports (list) and
// /portal/service-reports/:id (detail). Backend endpoints:
//   GET /api/customers/me/service-reports
//   GET /api/customers/me/service-reports/{id}
//
// SAFETY: this UI must NEVER render `internal_notes` or issue-tagged
// photos. Backend already redacts both — this file simply matches the
// customer-safe contract and never asks for the internal fields.

import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ClipboardCheck,
  Waves,
  Leaf,
  FileText,
  Check,
  Beaker,
  Droplet,
  Info,
  Calendar,
  User,
  MapPin,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
// Feb-2026 hotfix — client-side band derivation.  Mirrors backend
// ``services/chemistry_bands.py`` exactly so a portal load with a
// stale server payload (no ``label`` attached) still classifies the
// reading with the same thresholds the email builder uses.
import { bandForReading, DISPLAY_LABELS } from "@/utils/chemistryBands";
import {
  PageHeader,
  Skeleton,
  Chip,
  StatusPill,
  EmptyState,
} from "@/components/ui-kit";

// ─── helpers ────────────────────────────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return String(iso);
  }
}

function reportKind(row) {
  // Prefer the report's own template if present (detail view carries it).
  // Otherwise derive from job.service_type on the list row.
  const raw = (
    row?.template ||
    row?.service_type ||
    row?.job?.service_type ||
    ""
  )
    .toString()
    .toLowerCase();
  if (raw.includes("landscap") || raw.includes("mow") || raw.includes("lawn"))
    return "landscape";
  if (raw.includes("pool") || raw.includes("chem")) return "pool";
  return "generic";
}

function KindChip({ kind }) {
  if (kind === "pool")
    return <Chip label="Pool service" tone="brand" testid="report-kind" />;
  if (kind === "landscape")
    return <Chip label="Landscape service" tone="success" testid="report-kind" />;
  return <Chip label="Service" tone="neutral" testid="report-kind" />;
}

// Customer-friendly algae line. Never leaks raw dose/PPM numbers unless
// the tech chose to include them in `customer_notes` (rendered separately).
function algaeLine(sr) {
  const level = String(sr?.observations?.visible_algae || "").toLowerCase();
  if (level === "heavy")
    return "Visible algae observed and treated during this visit.";
  if (level === "light")
    return "Light algae was observed and treated during this visit.";
  return null;
}

// ─── list view ──────────────────────────────────────────────────────────
export function PortalServiceReports() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [totalPages, setTotalPages] = useState(0);
  // Feb-2026 · Customer service-reports enhancements — search +
  // filters (service_type + date range) + URL-sync so the filters
  // survive a refresh / share. Debounced 300ms on the search box.
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [serviceType, setServiceType] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  React.useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    // URL params keep filters shareable.
    const sp = new URLSearchParams();
    if (qDebounced) sp.set("q", qDebounced);
    if (serviceType) sp.set("service_type", serviceType);
    if (fromDate) sp.set("from", fromDate);
    if (toDate) sp.set("to", toDate);
    sp.set("page", String(page));
    sp.set("page_size", String(pageSize));
    const query = sp.toString();
    api
      .get(`/customers/me/service-reports?${query}`)
      .then((d) => {
        // Feb-2026 · Enhancements — endpoint now emits the paginated
        // ``{items, ...}`` shape. Legacy array response is defensively
        // still handled.
        if (Array.isArray(d)) {
          setRows(d);
          setTotal(d.length);
          setTotalPages(1);
        } else {
          setRows(Array.isArray(d?.items) ? d.items : []);
          setTotal(Number(d?.total || 0));
          setTotalPages(Number(d?.total_pages || 0));
        }
      })
      .catch((e) => {
        setErr(e?.message || "Failed to load service reports.");
        setRows([]);
      });
  }, [qDebounced, serviceType, fromDate, toDate, page, pageSize]);

  // Reset to page 1 whenever a filter changes so the user doesn't
  // land on a stale page-N with an empty result set.
  useEffect(() => {
    setPage(1);
  }, [qDebounced, serviceType, fromDate, toDate]);

  return (
    <div
      className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="portal-service-reports"
      data-tour-id="service-reports-list"
    >
      <PageHeader
        title="Service Reports"
        subtitle="Every visit we complete comes with a report — chemistry, work performed, photos, and any notes from your tech."
      />

      {/* Feb-2026 · Enhancements — search + filters bar. Stacks
          vertically at < sm, grid at ≥ sm. All filters URL-synced
          via the effect above so the page is shareable. */}
      <div className="mb-4 flex flex-col sm:grid sm:grid-cols-4 gap-2"
            data-testid="sr-list-filters">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search notes, name, address…"
          className="rounded-lg px-3 py-2 text-sm sm:col-span-2"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface }}
          data-testid="sr-list-search"
        />
        <input
          type="text"
          value={serviceType}
          onChange={(e) => setServiceType(e.target.value)}
          placeholder="Service type"
          className="rounded-lg px-3 py-2 text-sm"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface }}
          data-testid="sr-list-filter-service-type"
        />
        <div className="flex gap-2">
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm flex-1"
            style={{ border: `1px solid ${colors.border}`,
                      background: colors.surface }}
            aria-label="From date"
            data-testid="sr-list-filter-from"
          />
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm flex-1"
            style={{ border: `1px solid ${colors.border}`,
                      background: colors.surface }}
            aria-label="To date"
            data-testid="sr-list-filter-to"
          />
        </div>
      </div>

      {err ? (
        <div
          className="rounded-2xl p-4 mb-4 flex items-start gap-3"
          style={{
            backgroundColor: "#FEE2E2",
            border: "1px solid #FCA5A5",
            color: "#991B1B",
          }}
          data-testid="portal-service-reports-error"
        >
          <Info size={16} className="mt-0.5 shrink-0" />
          <div className="text-sm">{err}</div>
        </div>
      ) : null}

      {rows === null ? (
        <Skeleton style={{ height: 220 }} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="No service reports yet"
          hint="Your first report will appear here after your next scheduled visit."
        />
      ) : (
        (() => {
          // Phase 34 · Feb 2026 — group service reports by date
          // (submitted_at → scheduled_start). Newest date group first;
          // items within a group keep their existing order. Divider +
          // long-date header between groups.
          const byDate = new Map();
          for (const r of rows) {
            const day = (r.submitted_at || r.scheduled_start || r.created_at || "").slice(0, 10) || "Unknown date";
            if (!byDate.has(day)) byDate.set(day, []);
            byDate.get(day).push(r);
          }
          const dayKeys = Array.from(byDate.keys()).sort((a, b) => b.localeCompare(a));
          const fmtHeader = (d) => {
            if (d === "Unknown date") return d;
            try {
              return new Date(d + "T00:00:00").toLocaleDateString(undefined,
                { weekday: "long", month: "short", day: "numeric", year: "numeric" });
            } catch { return d; }
          };
          return (
            <div data-testid="portal-service-reports-grouped">
              {/* Task PP · Feb 2026 — subtle instructional hint. Only
                   surfaces when at least one visit row exists (the
                   grouped block is only rendered in that case). */}
              <p className="text-sm italic mb-4"
                  style={{ color: colors.muted }}
                  data-testid="service-reports-click-hint">
                Click any visit below to open its full details, photos, and chemicals.
              </p>
              {dayKeys.map((day, gi) => (
                <div key={day} data-testid={`portal-service-reports-date-group-${day}`}
                     className={gi > 0 ? "pt-6 mt-6" : ""}
                     style={gi > 0 ? { borderTop: `1px solid ${colors.border}` } : {}}>
                  <h2 className="text-sm font-bold mb-3"
                      style={{ color: colors.onSurface }}
                      data-testid={`portal-service-reports-date-header-${day}`}>
                    {fmtHeader(day)}
                  </h2>
                  <ul className="space-y-2" data-testid="portal-service-reports-list">
                    {byDate.get(day).map((r, idx) => {
                      const kind = reportKind(r);
                      const KindIcon = kind === "landscape" ? Leaf : Waves;
                      const iconTone =
                        kind === "landscape" ? colors.success : colors.brand;
                      return (
                        <li
                          key={r.id}
                          onClick={() => navigate(`/portal/service-reports/${r.id}`)}
                          className="cursor-pointer flex items-center gap-3 p-4 rounded-xl transition hover:brightness-95"
                          style={{
                            backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}`,
                          }}
                          data-testid={`portal-service-report-card-${r.id}`}
                          data-report-id={r.id}
                          data-row-index={idx}
                        >
                          {/* Feb-2026 · Enhancements ship — expose the
                              new ``sr-list-row-<i>`` testid on a
                              hidden sentinel so the tester + Vitest
                              can resolve rows by index while the
                              existing multi-body-water suite keeps
                              looking rows up by report id. */}
                          <span
                            className="hidden"
                            data-testid={`sr-list-row-${idx}`}
                            aria-hidden="true"
                          />
                          <div
                            className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
                            style={{ backgroundColor: iconTone + "22", color: iconTone }}
                          >
                            <KindIcon size={18} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <KindChip kind={kind} />
                              <span
                                className="text-xs"
                                style={{ color: colors.muted }}
                                data-testid={`portal-service-report-date-${r.id}`}
                              >
                                {fmtDate(r.submitted_at || r.scheduled_start)}
                              </span>
                              {/* Feb-2026 · Multi-body Phase 2 — small badge showing
                                  the number + type mix of bodies serviced on this
                                  visit. Only rendered when the report has >1 body;
                                  single-body baseline stays visually unchanged. */}
                              {r.water_body_count && r.water_body_count > 1 ? (
                                <span
                                  className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                                  style={{
                                    backgroundColor: "#E0F2FE",
                                    color: "#0369A1",
                                    border: "1px solid #7DD3FC",
                                  }}
                                  data-testid={`portal-service-report-bodies-${r.id}`}
                                >
                                  {r.water_body_count} bodies of water
                                </span>
                              ) : null}
                            </div>
                  <div
                    className="text-sm font-semibold mt-1 truncate"
                    style={{ color: colors.onSurface }}
                  >
                    {r.job_title || "Service visit"}
                  </div>
                  <div
                    className="text-xs mt-0.5"
                    style={{ color: colors.muted }}
                  >
                    {r.tech_name ? (
                      <>
                        <User
                          size={11}
                          className="inline mr-1"
                          style={{ verticalAlign: -1 }}
                        />
                        {r.tech_name}
                      </>
                    ) : (
                      "Technician not recorded"
                    )}
                  </div>
                  {/* Body-mix line — verbose enough for a quick glance
                      but suppressed for single-body reports so the
                      baseline UX stays clean. */}
                  {Array.isArray(r.water_bodies_summary)
                    && r.water_bodies_summary.length > 1 ? (
                    <div
                      className="text-[11px] mt-1"
                      style={{ color: colors.muted }}
                      data-testid={`portal-service-report-body-mix-${r.id}`}
                    >
                      {r.water_bodies_summary
                        .map((s) => s.label || s.type)
                        .join(" · ")}
                    </div>
                  ) : null}
                </div>
                          <StatusPill status="completed" />
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </div>
          );
        })()
      )}
      {/* Feb-2026 · Enhancements — pagination controls. Always
          mounted (post-tester fix) so mobile + Vitest can locate
          the testids regardless of whether ``total_pages > 1``.
          The buttons carry their own disabled logic so a single-
          page result set still renders the row with both buttons
          greyed out and a truthful ``Page 1 of 1`` indicator. */}
      <div className="mt-4 flex items-center justify-between gap-2"
            data-testid="sr-list-pagination">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="sr-list-pagination-prev"
        >
          ← Prev
        </button>
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="sr-list-page-indicator">
          Page {page} of {Math.max(totalPages, 1)} ({total} total)
        </div>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(Math.max(totalPages, 1), p + 1))}
          disabled={page >= Math.max(totalPages, 1)}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="sr-list-pagination-next"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

// ─── detail view ────────────────────────────────────────────────────────
export function PortalServiceReportDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [sr, setSr] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setSr(null);
    setErr("");
    api
      .get(`/customers/me/service-reports/${id}`)
      .then(setSr)
      .catch((e) =>
        setErr(e?.message || "This service report is not available.")
      );
  }, [id]);

  if (err) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <button
          onClick={() => navigate("/portal/service-reports")}
          className="flex items-center gap-1 text-sm font-semibold mb-4"
          style={{ color: colors.muted }}
          data-testid="portal-service-report-back"
        >
          <ArrowLeft size={14} /> Service reports
        </button>
        <div
          className="rounded-2xl p-6"
          style={{
            backgroundColor: "#FEE2E2",
            border: "1px solid #FCA5A5",
            color: "#991B1B",
          }}
          data-testid="portal-service-report-error"
        >
          {err}
        </div>
      </div>
    );
  }
  if (!sr) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Skeleton style={{ height: 240 }} />
      </div>
    );
  }

  const kind = reportKind(sr);
  const KindIcon = kind === "landscape" ? Leaf : Waves;
  const iconTone = kind === "landscape" ? colors.success : colors.brand;

  const readings = Array.isArray(sr.chemical_readings)
    ? sr.chemical_readings.filter(
        (r) => r && (r.label || r.value !== null && r.value !== undefined && r.value !== "")
      )
    : [];
  const chemicalsAdded = Array.isArray(sr.chemicals_added)
    ? sr.chemicals_added.filter((c) => c && (c.name || c.chemical))
    : [];
  const checklistItems = Array.isArray(sr.checklist_items)
    ? sr.checklist_items
    : [];
  // Backend already stripped internal/issue-tagged photos on this endpoint.
  const photos = Array.isArray(sr.photos) ? sr.photos : [];
  // Feb-2026 · Customer service-report enhancements — job-attached
  // photos ship in a separate ``job_photos`` array so tech-attached
  // photos (``sr.photos``) keep their attribution intact.
  const jobPhotos = Array.isArray(sr.job_photos) ? sr.job_photos : [];
  const algae = algaeLine(sr);
  // Feb-2026 · Multi-body Phase 2 — when the report carries multiple
  // water bodies, we render per-body sub-sections and suppress the
  // flat top-level chemistry/chemicals surface (backend still returns
  // them as a legacy mirror, but they'd duplicate what's inside
  // ``water_bodies[0]``). Single-body reports keep the classic layout.
  const bodies = Array.isArray(sr.water_bodies) ? sr.water_bodies : [];
  const isMultiBody = bodies.length > 1;

  return (
    <div
      className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="portal-service-report-detail"
    >
      <button
        onClick={() => navigate("/portal/service-reports")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
        data-testid="portal-service-report-back"
      >
        <ArrowLeft size={14} /> Service reports
      </button>

      {/* Header card */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <div className="flex items-start gap-3">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
            style={{ backgroundColor: iconTone + "22", color: iconTone }}
          >
            <KindIcon size={22} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <KindChip kind={kind} />
              <StatusPill status="completed" />
              {/*
                Feb-2026 · Repair-mode marker on the portal card.
                Small orange chip so customers can quickly see the
                visit was a repair vs a routine service. Backend
                stamps ``work_class`` on the report at bootstrap; the
                same value is redacted-safe to expose (no PII).
              */}
              {(sr.work_class || "").toLowerCase() === "repair" ? (
                <span
                  className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  style={{
                    backgroundColor: "#FED7AA",
                    color: "#9A3412",
                    border: "1px solid #FDBA74",
                  }}
                  data-testid="portal-service-report-repair-chip"
                >
                  Repair
                </span>
              ) : null}
            </div>
            <h1
              className="text-2xl font-bold mt-2"
              style={{ color: colors.onSurface }}
              data-testid="portal-service-report-title"
            >
              {sr?.job?.title || "Service visit"}
            </h1>
            <div
              className="text-sm mt-1 flex flex-wrap gap-x-4 gap-y-1"
              style={{ color: colors.muted }}
            >
              <span data-testid="portal-service-report-visit-date">
                <Calendar
                  size={12}
                  className="inline mr-1"
                  style={{ verticalAlign: -1 }}
                />
                {fmtDate(sr.submitted_at || sr?.job?.scheduled_start)}
              </span>
              {sr.tech_name ? (
                <span data-testid="portal-service-report-tech">
                  <User
                    size={12}
                    className="inline mr-1"
                    style={{ verticalAlign: -1 }}
                  />
                  {sr.tech_name}
                </span>
              ) : null}
              {sr?.job?.address ? (
                <span data-testid="portal-service-report-address">
                  <MapPin
                    size={12}
                    className="inline mr-1"
                    style={{ verticalAlign: -1 }}
                  />
                  {sr.job.address}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Algae observation (pool only, customer-friendly language) */}
      {kind === "pool" && algae ? (
        <div
          className="rounded-2xl p-4 mb-4 flex items-start gap-3"
          style={{
            backgroundColor: "#FEF9C3",
            border: "1px solid #FDE68A",
            color: "#854D0E",
          }}
          data-testid="portal-service-report-algae"
        >
          <Info size={16} className="mt-0.5 shrink-0" />
          <div className="text-sm font-medium">{algae}</div>
        </div>
      ) : null}

      {/* Feb-2026 · Multi-body Phase 2 — per-body chemistry / chemicals
          breakdown. Only renders when the visit covered more than one
          body of water (e.g., Pool + Spa). Each body gets its own card
          with the type label, its qualitative readings (bands only —
          matches Slice 3C safety rules), and its chemicals list. This
          section replaces the flat top-level readings/chemicals for
          multi-body reports; single-body reports keep the classic
          layout above. */}
      {isMultiBody
       && (sr.work_class || "").toLowerCase() !== "repair" ? (
        <Section
          icon={Droplet}
          title={`Serviced ${bodies.length} bodies of water`}
          testid="portal-service-report-water-bodies"
        >
          <div
            className="space-y-3"
            data-testid="portal-service-report-water-bodies-list"
          >
            {bodies.map((b, bi) => {
              const bReadings = Array.isArray(b?.readings)
                ? b.readings.filter(
                    (r) => r && (r.label || (r.value !== null && r.value !== undefined && r.value !== "")),
                  )
                : [];
              const bChems = Array.isArray(b?.chemicals_used)
                ? b.chemicals_used.filter((c_) => c_ && (c_.name || c_.chemical))
                : [];
              const bMedia = Array.isArray(b?.media)
                ? b.media.filter((m) => m && m.url)
                : [];
              const typeSlug = (b?.type || "pool");
              const label = b?.label || typeSlug;
              // Reuse the pool cyan for pool bodies; neutral tint
              // otherwise. Kept in one place so it matches the tech UI.
              const tintBg   = typeSlug === "pool" ? "#E0F2FE" : "#F1F5F9";
              const tintFg   = typeSlug === "pool" ? "#0369A1" : "#334155";
              const tintBd   = typeSlug === "pool" ? "#7DD3FC" : "#CBD5E1";
              return (
                <div
                  key={b?.id || bi}
                  className="rounded-xl overflow-hidden"
                  style={{
                    border: `1px solid ${tintBd}`,
                    backgroundColor: colors.surface,
                  }}
                  data-testid={`portal-service-report-body-${bi}`}
                >
                  <div
                    className="flex items-center gap-2 px-3 py-2"
                    style={{ backgroundColor: tintBg }}
                  >
                    <span
                      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                      style={{
                        backgroundColor: colors.surface,
                        color: tintFg,
                        border: `1px solid ${tintBd}`,
                      }}
                      data-testid={`portal-service-report-body-badge-${bi}`}
                    >
                      {typeSlug.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase())}
                    </span>
                    <span
                      className="text-sm font-semibold"
                      style={{ color: colors.onSurface }}
                      data-testid={`portal-service-report-body-label-${bi}`}
                    >
                      {label}
                    </span>
                  </div>
                  <div className="p-3 space-y-3">
                    {bReadings.length > 0 ? (
                      <div>
                        <div
                          className="text-[11px] uppercase tracking-wider font-bold mb-2"
                          style={{ color: colors.muted }}
                        >
                          Water chemistry
                        </div>
                        <ul
                          className="grid grid-cols-1 sm:grid-cols-2 gap-2"
                          data-testid={`portal-service-report-body-readings-${bi}`}
                        >
                          {bReadings.map((r, ri) => {
                            const derived = bandForReading(r.key, r.value);
                            const _CHIP_KEY = {
                              "Below Average": "below",
                              "Average":       "average",
                              "Above Average": "above",
                              "Elevated":      "elevated",
                            };
                            const band = r.label || _CHIP_KEY[derived] || "average";
                            const displayName = DISPLAY_LABELS[r.key] || r.name || r.key;
                            return (
                              <li
                                key={r.key || r.name || ri}
                                className="flex items-center justify-between rounded-xl p-3"
                                style={{
                                  backgroundColor: colors.surfaceSecondary,
                                  border: `1px solid ${colors.divider}`,
                                }}
                                data-testid={`portal-service-report-body-${bi}-reading-${r.key || ri}`}
                              >
                                <div className="min-w-0">
                                  <div
                                    className="text-sm font-semibold truncate"
                                    style={{ color: colors.onSurface }}
                                  >
                                    {displayName}
                                  </div>
                                </div>
                                <ChemChip band={band} testid={`chem-label-${bi}-${r.key || ri}`} />
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                    {bChems.length > 0 ? (
                      <div>
                        <div
                          className="text-[11px] uppercase tracking-wider font-bold mb-2"
                          style={{ color: colors.muted }}
                        >
                          Chemicals added
                        </div>
                        <ul
                          className="space-y-1.5"
                          data-testid={`portal-service-report-body-chemicals-${bi}`}
                        >
                          {bChems.map((c_, ci) => {
                            const name = c_.name || c_.chemical || "Chemical";
                            const amount = c_.amount ?? c_.qty ?? c_.quantity ?? "";
                            const unit = c_.unit || c_.default_unit || "";
                            return (
                              <li
                                key={ci}
                                className="flex items-center justify-between text-sm py-1"
                                data-testid={`portal-service-report-body-${bi}-chemical-${ci}`}
                              >
                                <span style={{ color: colors.onSurface }}>{name}</span>
                                <span
                                  className="font-semibold"
                                  style={{ color: colors.onSurface }}
                                >
                                  {amount} {unit}
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                    {bMedia.length > 0 ? (
                      <div
                        className="text-[11px]"
                        style={{ color: colors.muted }}
                        data-testid={`portal-service-report-body-media-count-${bi}`}
                      >
                        {bMedia.length} photo{bMedia.length === 1 ? "" : "s"} attached
                      </div>
                    ) : null}
                    {(b?.notes || "").trim() ? (
                      <div
                        className="text-xs whitespace-pre-wrap"
                        style={{ color: colors.onSurface }}
                        data-testid={`portal-service-report-body-notes-${bi}`}
                      >
                        {b.notes}
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      ) : null}

      {/* Pool: chemical readings — Feb-2026 · Slice 3C · qualitative
          chips only. Customers see Below / Average / Above Avg /
          Elevated per reading; raw numeric values are never shown on
          the portal.  Backend already strips numeric readings and
          attaches the classification band.
          Feb-2026 · Repair-mode addition — repair visits omit the
          chemistry surface entirely (matches the tech-facing form).
          Feb-2026 · Multi-body Phase 2 — when the report has multiple
          bodies, the flat top-level readings/chemicals sections are
          suppressed. The per-body breakdown below carries the same
          data + labels. */}
      {kind === "pool"
       && !isMultiBody
       && readings.length > 0
       && (sr.work_class || "").toLowerCase() !== "repair" ? (
        <Section
          icon={Droplet}
          title="Water chemistry"
          testid="portal-service-report-readings"
        >
          <ul
            className="grid grid-cols-1 sm:grid-cols-2 gap-2"
            data-testid="portal-service-report-readings-list"
          >
            {readings.map((r, i) => {
              // Feb-2026 hotfix — prefer the server-attached
              // classification when present, else derive from the
              // numeric value using the SAME thresholds the door-
              // hanger email uses.  Falls back to the pre-hotfix
              // "average" default only when neither path resolves.
              const derived = bandForReading(r.key, r.value);
              // ChemChip keys are lowercase short codes; the helper
              // returns display labels ("Above Average" etc.).
              // Map full display → chip key here so the chip picks
              // the correct color + short label.
              const _CHIP_KEY = {
                "Below Average": "below",
                "Average":       "average",
                "Above Average": "above",
                "Elevated":      "elevated",
              };
              const band = r.label || _CHIP_KEY[derived] || "average";
              const displayName = DISPLAY_LABELS[r.key] || r.name || r.key;
              return (
                <li
                  key={r.key || r.name || i}
                  className="flex items-center justify-between rounded-xl p-3"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.divider}`,
                  }}
                  data-testid={`portal-service-report-reading-${r.key || i}`}
                >
                  <div className="min-w-0">
                    <div
                      className="text-sm font-semibold truncate"
                      style={{ color: colors.onSurface }}
                    >
                      {displayName}
                    </div>
                    {/* Numeric value + unit intentionally NOT rendered
                        on customer-facing surfaces — only the band chip
                        conveys the reading (Feb-2026 hotfix). */}
                  </div>
                  <ChemChip
                    band={band}
                    testid={`chem-label-${r.key || i}`}
                  />
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}

      {/* Pool: chemicals added */}
      {kind === "pool" && !isMultiBody && chemicalsAdded.length > 0 ? (
        <Section
          icon={Beaker}
          title="Chemicals added"
          testid="portal-service-report-chemicals"
        >
          <ul className="space-y-1.5">
            {chemicalsAdded.map((c, i) => {
              const name = c.name || c.chemical || "Chemical";
              const amount = c.amount ?? c.qty ?? c.quantity ?? "";
              const unit = c.unit || c.default_unit || "";
              return (
                <li
                  key={i}
                  className="flex items-center justify-between text-sm py-1"
                  data-testid={`portal-service-report-chemical-${i}`}
                >
                  <span style={{ color: colors.onSurface }}>{name}</span>
                  <span className="font-semibold" style={{ color: colors.onSurface }}>
                    {amount} {unit}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}

      {/* Checklist — pool + landscape */}
      {checklistItems.length > 0 ? (
        <Section
          icon={ClipboardCheck}
          title={
            kind === "landscape"
              ? "Landscape checklist"
              : "Service checklist"
          }
          testid="portal-service-report-checklist"
        >
          <ul className="space-y-1.5">
            {checklistItems.map((it, i) => {
              const checked = !!it.checked;
              return (
                <li
                  key={it.id || i}
                  className="flex items-center gap-2 text-sm"
                  data-testid={`portal-service-report-checklist-item-${i}`}
                >
                  <span
                    className="w-5 h-5 rounded-md flex items-center justify-center shrink-0"
                    style={{
                      backgroundColor: checked
                        ? colors.success + "22"
                        : colors.surfaceTertiary,
                      color: checked ? colors.success : colors.muted,
                      border: `1px solid ${
                        checked ? colors.success : colors.border
                      }`,
                    }}
                  >
                    {checked ? <Check size={13} /> : null}
                  </span>
                  <span
                    style={{
                      color: checked ? colors.onSurface : colors.muted,
                      textDecoration: "none",
                    }}
                  >
                    {it.label}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}

      {/* Customer notes (verbatim customer_notes). Never internal_notes. */}
      {(sr.customer_notes || "").trim() ? (
        <Section
          icon={FileText}
          title="Notes from your tech"
          testid="portal-service-report-customer-notes"
        >
          <p
            className="text-sm whitespace-pre-wrap"
            style={{ color: colors.onSurface }}
          >
            {sr.customer_notes}
          </p>
        </Section>
      ) : null}

      {/* Feb-2026 · Enhancements — job-attached photos. Rendered
          in a separate section under a distinct heading so the
          attribution stays intact (tech-uploaded vs. admin/customer
          -uploaded on the underlying job). Responsive: stacked at
          < sm, 2-col grid at >= sm. ``thumb`` is a data-URI, so
          it renders inline without any auth handshake. */}
      {jobPhotos.length > 0 ? (
        <Section
          icon={Waves}
          title="Job Photos"
          testid="service-report-job-photos-section"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {jobPhotos.map((p, i) => {
              const src = p.thumb || p.preview || "";
              if (!src) return null;
              return (
                <img
                  key={p.id || i}
                  src={src}
                  alt={p.caption || `Job photo ${i + 1}`}
                  className="w-full aspect-square object-cover rounded-lg"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid={`service-report-job-photo-${i}`}
                />
              );
            })}
          </div>
        </Section>
      ) : null}

      {/* Customer-safe photos (backend already filtered internal/issue tags) */}
      {photos.length > 0 ? (
        <Section
          icon={Waves}
          title="Visit photos"
          testid="portal-service-report-photos"
        >
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {photos.map((p, i) => {
              const src =
                typeof p === "string"
                  ? p
                  : p.url || p.data_url || p.data || p.thumb_url || "";
              if (!src) return null;
              return (
                <img
                  key={p.id || i}
                  src={src}
                  alt={p.label || `Visit photo ${i + 1}`}
                  className="w-full aspect-square object-cover rounded-lg"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid={`portal-service-report-photo-${i}`}
                />
              );
            })}
          </div>
        </Section>
      ) : null}

      {/*
        Feb-2026 · Portal visit videos. Rendered whenever the redacted
        response carries a non-empty ``videos`` array. Native HTML5
        ``<video controls>`` — no library dependency, mobile-friendly,
        works on iOS Safari. Backend serves via signed public URL
        (``services/portal_media.py``) so ``<video src>`` doesn't need
        an auth header.
      */}
      {Array.isArray(sr.videos) && sr.videos.length > 0 ? (
        <Section
          icon={Waves}
          title="Visit videos"
          testid="portal-service-report-videos"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {sr.videos.map((v, i) => {
              const src = v.stream_url || v.url || "";
              if (!src) return null;
              return (
                <div
                  key={v.id || i}
                  className="rounded-lg overflow-hidden bg-black"
                  data-testid={`portal-service-report-video-${i}`}
                >
                  <video
                    controls
                    preload="metadata"
                    src={src}
                    className="w-full h-56 object-contain bg-black"
                  />
                </div>
              );
            })}
          </div>
        </Section>
      ) : null}
    </div>
  );
}

// ─── shared section shell ───────────────────────────────────────────────
function Section({ icon: Icon, title, testid, children }) {
  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-2 mb-3">
        {Icon ? (
          <span style={{ color: colors.brand }}>
            <Icon size={16} />
          </span>
        ) : null}
        <h3
          className="text-sm font-bold uppercase tracking-wide"
          style={{ color: colors.onSurface }}
        >
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}


// Feb-2026 · Slice 3C · Chemistry band chip.  Colour hint per spec:
// below=blue · average=green · above=amber · elevated=red.
const CHEM_BAND_STYLES = {
  below:    { bg: "#DBEAFE", fg: "#1E3A8A", label: "Below" },
  average:  { bg: "#DCFCE7", fg: "#166534", label: "Average" },
  above:    { bg: "#FEF3C7", fg: "#92400E", label: "Above Avg" },
  elevated: { bg: "#FEE2E2", fg: "#991B1B", label: "Elevated" },
};

function ChemChip({ band, testid }) {
  const style = CHEM_BAND_STYLES[band] || CHEM_BAND_STYLES.average;
  return (
    <span
      className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold shrink-0"
      style={{ backgroundColor: style.bg, color: style.fg }}
      data-testid={testid}
      data-band={band}
    >
      {style.label}
    </span>
  );
}
