/**
 * Phase 47.3 — Job Costing panel.
 * Reads GET /jobs/{id}/costing and renders progress bars per bucket.
 * Embedded inside JobDetail as a collapsible section.
 *
 * Feb-2026 · Jobs Overhaul Phase 3b — editable overrides.
 * Each row (Labor / Materials / Equipment) exposes two inline
 * inputs — Budgeted (overrides baseline) and Actual (overrides
 * computed actual). Admin-equivalent roles only — non-admin sees
 * the display-only view (progress bars + numbers, no inputs).
 *
 * Write contract (locked by backend):
 *   * The FE sends the FULL merged ``costing_overrides`` dict on
 *     every PUT — the backend ``$set``s this field atomically and
 *     does NOT merge partials. We hydrate ``overrides`` state
 *     from the GET /costing response (which echoes the raw dict)
 *     and mutate exactly one cell on each inline-edit commit,
 *     then PUT the merged shape.
 *   * See ``backend/models.py::JobUpdate.costing_overrides`` for
 *     the pinned FE/BE invariant.
 */
import React, { useEffect, useState } from "react";
import { RefreshCw, DollarSign } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

function money(cents) {
  const v = (cents || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

// Phase 3b — compact dollar formatter for the inline-edit inputs
// (keeps 2 decimals so round-tripping ``125.75`` doesn't lose a
// penny). Separate from ``money`` which strips decimals for the
// at-a-glance progress bar labels.
function dollarsFromCents(cents) {
  const v = (cents || 0) / 100;
  return v.toFixed(2);
}

function toneForPct(pct) {
  if (pct > 100) return { bar: "#DC2626", label: "over" };
  if (pct >= 80) return { bar: "#F59E0B", label: "warn" };
  return { bar: "#16A34A", label: "ok" };
}

// Admin-equivalent gate — mirrors the backend ``ADMIN_ROLES`` set
// in ``routers/jobs.py::update_job``. Any role NOT in this set
// gets a display-only panel (no inputs rendered).
const ADMIN_ROLES = new Set(["admin", "super_admin", "owner", "manager"]);

// ──────────────────────────────────────────────────────────────
// Inline cents cell — click-to-edit, Enter commits, Escape
// reverts, blur commits, optimistic UI with rollback on failure.
// Mirrors the Phase 3a InlineEditTile keyboard contract from
// ``JobDetail.jsx`` (kept local here because the panel ships with
// cents conversion inline — a cross-cutting extraction belongs in
// Phase 3c alongside ``LineItemsEditor``).
function CentsCell({
  cents, editable, onCommit, displayTestid, inputTestid,
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(dollarsFromCents(cents));
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => {
    if (!editing) setDraft(dollarsFromCents(cents));
  }, [cents, editing]);

  const open = () => {
    if (!editable || saving) return;
    setDraft(dollarsFromCents(cents));
    setEditing(true);
  };
  const commit = async () => {
    if (saving) return;
    const n = Number(draft);
    if (Number.isNaN(n) || n < 0) {
      // Invalid local draft — stay open, let the user fix it.
      setDraft(dollarsFromCents(cents));
      return;
    }
    setSaving(true);
    const nextCents = Math.round(n * 100);
    const ok = await onCommit(nextCents);
    setSaving(false);
    if (ok !== false) setEditing(false);
  };
  const cancel = () => {
    setDraft(dollarsFromCents(cents));
    setEditing(false);
  };
  const onKeyDown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  };

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        step="0.01"
        min="0"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        disabled={saving}
        className="text-xs font-semibold px-1 py-0.5 rounded"
        style={{
          background: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
          width: "6rem",
        }}
        data-testid={inputTestid}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={open}
      disabled={!editable}
      className={
        editable ? "cursor-pointer hover:underline" : "cursor-default"
      }
      style={{
        color: colors.muted,
        background: "transparent",
        border: 0,
        padding: 0,
        font: "inherit",
      }}
      data-testid={displayTestid}
      aria-label={editable ? "Edit value" : undefined}
    >
      {money(cents)}
    </button>
  );
}


export default function JobCostingPanel({ jobId }) {
  const [data, setData] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [saveErr, setSaveErr] = useState(null);
  const { user } = useAuth() || {};
  const isAdmin = ADMIN_ROLES.has(user?.role || "");

  const applyPayload = (res) => {
    setData(res);
    setOverrides(res?.costing_overrides || {});
  };

  const load = async () => {
    if (!jobId) return;
    setLoading(true); setErr(null);
    try {
      const res = await api.get(`/jobs/${jobId}/costing`);
      applyPayload(res);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [jobId]);

  // Compute an optimistic merged ``data`` from (snapshot, bucket,
  // field, newCents). Shared between the on-commit optimistic
  // path and the rollback path.
  const mergeLocal = (snap, bucket, field, newCents) => {
    const key = field === "budgeted_cents" ? "baseline" : "actual";
    const nextSection = { ...snap[key], [`${bucket}_cents`]: newCents };
    const nextData = { ...snap, [key]: nextSection };
    const nextOverrides = {
      ...(snap.costing_overrides || {}),
      [bucket]: {
        ...((snap.costing_overrides || {})[bucket] || {}),
        [field]: newCents,
      },
    };
    nextData.costing_overrides = nextOverrides;
    // Recompute progress + profit so the UI reflects the edit
    // without waiting on the server round-trip. Backend uses the
    // same formula (see ``routers/budgets.py::job_costing``).
    const b = nextData.baseline;
    const a = nextData.actual;
    const pct = (num, den) =>
      den > 0 ? Math.round((num / den) * 1000) / 10 : 0;
    nextData.progress = {
      labor_pct:     pct(a.labor_cents,     b.labor_cents),
      materials_pct: pct(a.materials_cents, b.materials_cents),
      equipment_pct: pct(a.equipment_cents, b.equipment_cents),
    };
    const estCosts = b.labor_cents + b.materials_cents + b.equipment_cents;
    const actCosts = a.labor_cents + a.materials_cents + a.equipment_cents;
    nextData.estimated_net_profit_cents = b.revenue_cents - estCosts;
    nextData.actual_net_profit_cents = b.revenue_cents - actCosts;
    nextData.estimated_margin_pct = b.revenue_cents > 0
      ? Math.round((nextData.estimated_net_profit_cents / b.revenue_cents) * 10000) / 100
      : 0;
    nextData.actual_margin_pct = b.revenue_cents > 0
      ? Math.round((nextData.actual_net_profit_cents / b.revenue_cents) * 10000) / 100
      : 0;
    return nextData;
  };

  // Build the full merged costing_overrides dict for the PUT.
  // The backend $sets this field atomically — partial writes
  // clobber other buckets/fields — so we send the complete shape.
  const buildMergedOverrides = (bucket, field, newCents) => {
    const current = overrides || {};
    return {
      ...current,
      [bucket]: {
        ...(current[bucket] || {}),
        [field]: newCents,
      },
    };
  };

  const commitCell = async (bucket, field, newCents) => {
    if (!data) return false;
    const snapshot = data;
    const snapshotOverrides = overrides;
    const merged = buildMergedOverrides(bucket, field, newCents);
    // Optimistic — mutate local state immediately.
    const nextData = mergeLocal(snapshot, bucket, field, newCents);
    setData(nextData);
    setOverrides(merged);
    setSaveErr(null);
    try {
      await api.put(`/jobs/${jobId}`, { costing_overrides: merged });
      // Refetch so the server-authoritative merged + recomputed
      // numbers land in state (handles the edge case where our
      // local formula drifted from the backend's).
      await load();
      return true;
    } catch (e) {
      setData(snapshot);
      setOverrides(snapshotOverrides);
      setSaveErr(e?.message || "Save failed — reverted");
      return false;
    }
  };

  if (loading && !data) return (
    <div className="text-xs px-3 py-2 rounded-md" style={{ color: colors.muted }}
         data-testid="job-costing-loading">Loading costing…</div>
  );
  if (err) return (
    <div className="rounded-md p-3 text-sm"
         style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
         data-testid="job-costing-error">{err}</div>
  );
  if (!data) return null;

  const rows = [
    { key: "labor",     label: "Labor",     baseline: data.baseline.labor_cents,     actual: data.actual.labor_cents,     pct: data.progress.labor_pct },
    { key: "materials", label: "Materials", baseline: data.baseline.materials_cents, actual: data.actual.materials_cents, pct: data.progress.materials_pct },
    { key: "equipment", label: "Equipment", baseline: data.baseline.equipment_cents, actual: data.actual.equipment_cents, pct: data.progress.equipment_pct },
  ];
  const marginTone = (data.actual_margin_pct >= data.estimated_margin_pct) ? "#16A34A" : "#DC2626";

  return (
    <div className="rounded-2xl p-4 mt-4"
         style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="job-costing-panel">
      <div className="flex items-center gap-2 mb-3">
        <DollarSign size={16} color={colors.brand} />
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>Job Costing</div>
        <div className="text-xs" style={{ color: colors.muted }}>
          · {data.time_entries_count} time entries · {Math.round(data.total_labor_minutes / 60 * 10) / 10}h
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={load} className="text-xs font-semibold inline-flex items-center gap-1 px-2 py-1 rounded-md"
                style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                data-testid="job-costing-refresh">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {saveErr ? (
        <div className="rounded-md p-2 text-xs mb-3"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="job-costing-save-error">{saveErr}</div>
      ) : null}

      <div className="space-y-3 mb-4">
        {rows.map((r) => {
          const tone = toneForPct(r.pct);
          const pctCapped = Math.min(150, r.pct);
          return (
            <div key={r.key} data-testid={`job-costing-row-${r.key}`}>
              <div className="flex justify-between text-xs mb-1 items-center gap-2">
                <span className="font-semibold" style={{ color: colors.onSurface }}>{r.label}</span>
                <span style={{ color: colors.muted }} className="inline-flex items-center gap-1">
                  <CentsCell
                    cents={r.actual}
                    editable={isAdmin}
                    onCommit={(c) => commitCell(r.key, "actual_cents", c)}
                    displayTestid={`job-costing-${r.key}-actual-display`}
                    inputTestid={`job-costing-${r.key}-actual-input`}
                  />
                  <span>/</span>
                  <CentsCell
                    cents={r.baseline}
                    editable={isAdmin}
                    onCommit={(c) => commitCell(r.key, "budgeted_cents", c)}
                    displayTestid={`job-costing-${r.key}-budgeted-display`}
                    inputTestid={`job-costing-${r.key}-budgeted-input`}
                  />
                  <span>· <b style={{ color: tone.bar }}>{r.pct}%</b></span>
                </span>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.surfaceSecondary }}>
                <div className="h-full transition-all"
                     style={{ width: `${pctCapped}%`, background: tone.bar }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-2 gap-3 pt-3" style={{ borderTop: `1px solid ${colors.border}` }}>
        <div data-testid="job-costing-estimated-profit">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Estimated net profit</div>
          <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
            {money(data.estimated_net_profit_cents)}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>{data.estimated_margin_pct}% margin</div>
        </div>
        <div data-testid="job-costing-actual-profit">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Actual net profit</div>
          <div className="text-lg font-bold" style={{ color: marginTone }}>
            {money(data.actual_net_profit_cents)}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>{data.actual_margin_pct}% margin</div>
        </div>
      </div>
    </div>
  );
}
