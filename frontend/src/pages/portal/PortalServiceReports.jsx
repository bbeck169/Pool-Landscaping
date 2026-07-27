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

  useEffect(() => {
    api
      .get("/customers/me/service-reports")
      .then((d) => setRows(Array.isArray(d) ? d : []))
      .catch((e) => {
        setErr(e?.message || "Failed to load service reports.");
        setRows([]);
      });
  }, []);

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
                    {byDate.get(day).map((r) => {
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
                        >
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
  const algae = algaeLine(sr);

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

      {/* Pool: chemical readings — Feb-2026 · Slice 3C · qualitative
          chips only. Customers see Below / Average / Above Avg /
          Elevated per reading; raw numeric values are never shown on
          the portal.  Backend already strips numeric readings and
          attaches the classification band. */}
      {kind === "pool" && readings.length > 0 ? (
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
              const band = r.label || sr?.readings_label?.[r.key] || "average";
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
                      {r.name || r.key}
                    </div>
                    {r.unit ? (
                      <div
                        className="text-xs"
                        style={{ color: colors.muted }}
                      >
                        {r.unit}
                      </div>
                    ) : null}
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
      {kind === "pool" && chemicalsAdded.length > 0 ? (
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
