/**
 * Feb-2026 · M2 · CustomerDetail → "Measurements" tab.
 *
 * Lists every ``/measurements`` row scoped to this customer (via
 * ``GET /api/measurements?customer_id=<id>`` — shipped in commit
 * ``9ecc749d3 feat(measurements): add type + unit fields …``) and
 * offers a per-row **Copy to Quote** clipboard action.  Bucket the
 * value column off the ``type`` field:
 *   * ``linear``    → ``distance_ft``   with unit ft/yd
 *   * ``area``      → ``area_sqft``     with unit sqft
 *   * ``perimeter`` → ``perimeter_ft``  with unit ft/yd
 *   * legacy/null   → best-effort (first non-zero of distance/area/perimeter)
 *
 * Header carries a **job filter** dropdown scoped to the set of
 * jobs referenced by the customer's measurements (or "All jobs").
 * Only visible to admin/super_admin/manager per the M2 role gate —
 * technicians and customers do not see the tab.
 *
 * Clipboard format (M2 ruling):
 *   ``{value} {unit} — {type} — {customer_name}, {job or "no job"}, {yyyy-mm-dd}``
 * Legacy rows (no type) drop the type token.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Ruler, Clipboard, CheckCircle2, Filter } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";


// Feb-2026 · M2 · role gate applied by ``CustomerDetail``'s TABS
// filter.  Kept next to the tab body so the test can lock the
// role set in a single place.
export const MEASUREMENTS_TAB_ROLES = ["admin", "super_admin", "manager"];


/** Filter a customer-detail ``TABS`` array by role, respecting
 *  each entry's optional ``roles: [...]`` gate.  Legacy entries
 *  (no ``roles`` field) stay visible to everyone. */
export function filterCustomerTabs(tabs, role) {
  if (!Array.isArray(tabs)) return [];
  return tabs.filter((t) => {
    if (!t || !Array.isArray(t.roles) || t.roles.length === 0) return true;
    return t.roles.includes(role);
  });
}


// ═══════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════
function _prettyType(t) {
  if (!t) return null;
  return t.charAt(0).toUpperCase() + t.slice(1);
}


function _isoDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return "";
  }
}


/** Value + unit resolver — bucket off ``type`` first, fall back to
 *  best-effort on legacy rows.  Returns ``{value, unit}`` with
 *  ``value`` already converted per unit (yd → ft/3, sqft direct). */
export function resolveMeasurementValue(row) {
  const t = row && row.type;
  const unit = row && row.unit;
  const toYards = (ft) => Number(ft || 0) / 3.0;
  if (t === "linear") {
    const ft = Number(row.distance_ft || 0);
    if (unit === "yd") return { value: toYards(ft), unit: "yd" };
    return { value: ft, unit: "ft" };
  }
  if (t === "area") {
    return { value: Number(row.area_sqft || 0), unit: "sqft" };
  }
  if (t === "perimeter") {
    const ft = Number(row.perimeter_ft || 0);
    if (unit === "yd") return { value: toYards(ft), unit: "yd" };
    return { value: ft, unit: "ft" };
  }
  // legacy fallback — first non-zero of distance / area / perimeter
  if (Number(row?.distance_ft) > 0) {
    return { value: Number(row.distance_ft), unit: "ft" };
  }
  if (Number(row?.area_sqft) > 0) {
    return { value: Number(row.area_sqft), unit: "sqft" };
  }
  if (Number(row?.perimeter_ft) > 0) {
    return { value: Number(row.perimeter_ft), unit: "ft" };
  }
  return { value: 0, unit: "ft" };
}


export function buildClipboardString(row, customerName, jobName) {
  const { value, unit } = resolveMeasurementValue(row);
  const rounded = Math.round(value * 100) / 100;
  const t = row && row.type;
  const date = _isoDate(row?.created_at);
  const job = (jobName && jobName.trim()) || "no job";
  const cust = (customerName && customerName.trim()) || "customer";
  if (t) {
    return `${rounded} ${unit} — ${t} — ${cust}, ${job}, ${date}`;
  }
  return `${rounded} ${unit} — ${cust}, ${job}, ${date}`;
}


// ═══════════════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════════════
export function CustomerMeasurementsTab({ customer }) {
  const [rows, setRows] = useState(null);   // null = loading, [] = empty
  const [err, setErr] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobFilter, setJobFilter] = useState("__all__");

  const cid = customer?.id;
  const customerName = customer?.name || customer?.display_name || "Customer";

  // ── Fetch measurements + jobs in parallel on mount / cid change ──
  useEffect(() => {
    if (!cid) return;
    let alive = true;
    setRows(null);
    setErr(null);
    (async () => {
      try {
        const [ms, js] = await Promise.all([
          api.get(`/measurements?customer_id=${encodeURIComponent(cid)}`),
          api.get(`/jobs?customer_id=${encodeURIComponent(cid)}`),
        ]);
        if (!alive) return;
        setRows(Array.isArray(ms) ? ms : (ms?.items || []));
        setJobs(Array.isArray(js) ? js : (js?.items || []));
      } catch (e) {
        if (alive) setErr(e?.message || "Failed to load measurements");
      }
    })();
    return () => { alive = false; };
  }, [cid]);

  // ── Job filter dropdown options — only jobs referenced by rows ──
  const jobById = useMemo(() => {
    const m = new Map();
    for (const j of jobs || []) {
      if (j && j.id) m.set(j.id, j);
    }
    return m;
  }, [jobs]);

  const referencedJobIds = useMemo(() => {
    const s = new Set();
    for (const r of rows || []) {
      if (r?.job_id) s.add(r.job_id);
    }
    return Array.from(s);
  }, [rows]);

  const filteredRows = useMemo(() => {
    if (!Array.isArray(rows)) return [];
    if (jobFilter === "__all__") return rows;
    if (jobFilter === "__nojob__") {
      return rows.filter((r) => !r?.job_id);
    }
    return rows.filter((r) => r?.job_id === jobFilter);
  }, [rows, jobFilter]);

  const handleCopy = useCallback(async (row) => {
    const jobName = row?.job_id
      ? (jobById.get(row.job_id)?.title
         || jobById.get(row.job_id)?.name
         || row.job_id)
      : "no job";
    const line = buildClipboardString(row, customerName, jobName);
    try {
      await navigator.clipboard.writeText(line);
      toast.success("Copied to clipboard", { description: line });
    } catch {
      toast.error("Copy failed — clipboard permission denied");
    }
  }, [jobById, customerName]);

  // ── Loading + error + empty branches ─────────────────────────────
  if (err) {
    return (
      <div style={{ padding: 24, color: "#991B1B" }}
           data-testid="customer-measurements-error">
        {err}
      </div>
    );
  }
  if (rows === null) {
    return (
      <div style={{ padding: 24, color: colors.muted }}
           data-testid="customer-measurements-loading">
        Loading measurements…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: colors.muted }}
           data-testid="customer-measurements-empty">
        <div style={{
          width: 56, height: 56, borderRadius: 28,
          background: colors.nav.bg, color: "#fff",
          display: "inline-flex", alignItems: "center",
          justifyContent: "center", marginBottom: 12,
        }}>
          <Ruler size={26} />
        </div>
        <h3 style={{ margin: "0 0 6px", color: colors.onSurface,
                     fontSize: 16, fontWeight: 700 }}>
          No measurements yet for this customer.
        </h3>
        <p style={{ margin: 0, fontSize: 13 }}>
          Techs can add measurements from the mobile app's Satellite Measure
          or AR Ruler screen.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="customer-measurements-tab">
      {/* Header row · title + count + job filter */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "12px 16px",
        borderBottom: `1px solid ${colors.border}`,
      }} data-testid="customer-measurements-header">
        <Ruler size={18} style={{ color: colors.brand }} />
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700,
                       color: colors.onSurface }}>
          Measurements
        </h2>
        <span style={{
          padding: "2px 8px", borderRadius: 999, fontSize: 12,
          backgroundColor: colors.brandTertiary, color: colors.onSurface,
        }} data-testid="customer-measurements-count">
          {rows.length}
        </span>
        <div style={{ flex: 1 }} />
        <Filter size={14} style={{ color: colors.muted }} />
        <select
          value={jobFilter}
          onChange={(e) => setJobFilter(e.target.value)}
          style={{
            padding: "6px 8px", borderRadius: 8,
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface, color: colors.onSurface,
            fontSize: 13,
          }}
          data-testid="customer-measurements-job-filter"
        >
          <option value="__all__">All jobs</option>
          <option value="__nojob__">— no job —</option>
          {referencedJobIds.map((jid) => (
            <option key={jid} value={jid}>
              {jobById.get(jid)?.title
               || jobById.get(jid)?.name
               || `Job ${jid.slice(0, 8)}`}
            </option>
          ))}
        </select>
      </div>

      {/* List */}
      <ul style={{ margin: 0, padding: 0, listStyle: "none" }}
          data-testid="customer-measurements-list">
        {filteredRows.map((row) => {
          const { value, unit } = resolveMeasurementValue(row);
          const rounded = Math.round(value * 100) / 100;
          const prettyType = _prettyType(row.type) || "—";
          const tech = row.technician_name || row.created_by_name || "—";
          const jobName = row?.job_id
            ? (jobById.get(row.job_id)?.title
               || jobById.get(row.job_id)?.name
               || null)
            : null;
          return (
            <li key={row.id}
                style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "10px 16px",
                  borderBottom: `1px solid ${colors.border}`,
                  flexWrap: "wrap",
                }}
                data-testid={`customer-measurement-row-${row.id}`}>
              <span style={{
                padding: "3px 8px", borderRadius: 6, fontSize: 11,
                fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase",
                backgroundColor: colors.nav.bg, color: "#fff",
                minWidth: 76, textAlign: "center",
              }} data-testid={`customer-measurement-type-${row.id}`}>
                {prettyType}
              </span>
              <span style={{
                fontSize: 15, fontWeight: 700, color: colors.onSurface,
                minWidth: 120,
              }} data-testid={`customer-measurement-value-${row.id}`}>
                {rounded} <span style={{
                  fontSize: 12, fontWeight: 500, color: colors.muted,
                }}>{unit}</span>
              </span>
              <span style={{ fontSize: 13, color: colors.muted, flex: 1 }}
                    data-testid={`customer-measurement-tech-${row.id}`}>
                {tech}
                {jobName ? (
                  <span style={{ marginLeft: 8, color: colors.brand }}>
                    · {jobName}
                  </span>
                ) : null}
              </span>
              <span style={{ fontSize: 12, color: colors.muted, minWidth: 100 }}
                    data-testid={`customer-measurement-date-${row.id}`}>
                {_isoDate(row.created_at)}
              </span>
              <button
                onClick={() => handleCopy(row)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "6px 10px", borderRadius: 8,
                  border: `1px solid ${colors.inputBorder}`,
                  backgroundColor: colors.surface,
                  color: colors.inputBorder,
                  fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}
                data-testid={`customer-measurement-copy-${row.id}`}
              >
                <Clipboard size={13} />
                Copy to Quote
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default CustomerMeasurementsTab;
