/**
 * Phase 53b · Feb-2026 — Editable EBIT report web UI.
 *
 * Self-contained section rendered inside the existing
 * ``ProfitReportPage`` (route ``/admin/reports/profit``). The panel:
 *
 *   • Fetches live EBIT via ``GET /api/ebit/compute``.
 *   • Renders four editable rows (revenue / cogs / opex / depreciation).
 *   • Each row supports two edit modes (locked pick 5C):
 *       – Adjustment (default): user enters a delta + optional note.
 *         Computed value stays visible; effective value shows bolded.
 *       – Override (admin-only toggle): user enters an absolute value
 *         that replaces the computed value entirely.
 *   • Effective EBIT total is recomputed client-side; server verifies
 *     on save (POST ``/api/ebit/snapshots``, always a new version).
 *   • Version history modal lists ``GET /api/ebit/snapshots`` in
 *     reverse chronological order. Loading an older version populates
 *     the editor read-only unless "Fork new version" is chosen.
 *   • Time-range picker: monthly / quarterly / custom (from-to).
 *   • Revenue-basis toggle: cash (default) / accrual.
 *   • Export: PDF (via ``window.print()`` scoped to the panel) + CSV
 *     (browser blob download).
 *
 * Role gate:
 *   – super_admin + admin: full edit + save + fork.
 *   – manager:              read-only (view + version history only).
 *   – tech / customer:      panel not rendered (parent page hides).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Percent, PiggyBank, Package, Wrench, DollarSign, Loader2, History,
  Save, FileDown, Printer, Sparkles, X, ChevronRight,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { useAuth } from "@/auth";

const LINE_KEYS = ["revenue", "cogs", "opex", "depreciation"];
const LINE_META = {
  revenue:      { label: "Revenue",       icon: DollarSign,  color: "#0891B2" },
  cogs:         { label: "COGS",          icon: Package,     color: "#B45309" },
  opex:         { label: "OpEx",          icon: Wrench,      color: "#7C3AED" },
  depreciation: { label: "Depreciation",  icon: PiggyBank,   color: "#0F766E" },
};
const RANGE_KINDS = [
  { key: "monthly",   label: "Monthly"   },
  { key: "quarterly", label: "Quarterly" },
  { key: "custom",    label: "Custom"    },
];

function fmtIsoDay(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function monthWindow() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  return { from: fmtIsoDay(start), to: fmtIsoDay(now) };
}
function quarterWindow() {
  const now = new Date();
  const qm = Math.floor(now.getMonth() / 3) * 3;
  const start = new Date(now.getFullYear(), qm, 1);
  return { from: fmtIsoDay(start), to: fmtIsoDay(now) };
}
function initialRange() { return { kind: "monthly", ...monthWindow() }; }

function toEffective(live, adjustments, overrides) {
  const out = {};
  for (const k of LINE_KEYS) {
    const base = Number(live?.[k] || 0);
    const adj = Number(adjustments?.[k] || 0);
    const ovr = overrides?.[k];
    out[k] = (ovr === null || ovr === undefined) ? base + adj : Number(ovr);
  }
  out.ebit = out.revenue - out.cogs - out.opex - out.depreciation;
  return out;
}
function blankAdjustments() {
  return LINE_KEYS.reduce((a, k) => ({ ...a, [k]: 0 }), {});
}
function blankOverrides() {
  return LINE_KEYS.reduce((a, k) => ({ ...a, [k]: null }), {});
}

// ═══════════════════════════════════════════════════════════════════
// Row: one editable EBIT line.
// ═══════════════════════════════════════════════════════════════════
function EbitLineRow({
  lineKey, computed, effective, adjustment, override,
  onAdjustmentChange, onOverrideChange, canEdit, editable, readOnly,
}) {
  const meta = LINE_META[lineKey];
  const Icon = meta.icon;
  const usingOverride = override !== null && override !== undefined;
  const overrideAllowed = canEdit && !readOnly;
  const inputsDisabled = readOnly || !editable;
  // Phase 53c-fix · Feb-2026 — when read-only (e.g. role=manager),
  // still render the inputs so the viewer can see any prior
  // adjustments/overrides — just gate them with ``disabled``.
  const showEditRow = editable || readOnly;

  return (
    <div
      className="flex flex-col gap-2 rounded-xl p-3 md:p-4"
      style={{ background: `${meta.color}0d`, border: `1px solid ${meta.color}33` }}
      data-testid={`ebit-row-${lineKey}`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5"
              style={{ color: meta.color }}>
          <Icon size={14} />
          <span className="text-xs uppercase font-bold tracking-wide">{meta.label}</span>
        </div>
        <span className="text-xs" style={{ color: colors.muted }}
              data-testid={`ebit-row-${lineKey}-computed`}>
          computed {money(computed)}
        </span>
        <div className="flex-1" />
        <span className="text-lg font-black" style={{ color: colors.onSurface }}
              data-testid={`ebit-row-${lineKey}-effective`}>
          {money(effective)}
        </span>
      </div>

      {showEditRow ? (
        <div className="flex flex-col gap-2">
          {usingOverride ? (
            <div className="flex items-center gap-2" data-testid={`ebit-row-${lineKey}-override-mode`}>
              <label className="text-xs font-semibold" style={{ color: meta.color }}>
                Override (absolute):
              </label>
              <input
                type="number"
                step="0.01"
                value={override ?? ""}
                onChange={(e) => onOverrideChange(e.target.value === "" ? 0 : Number(e.target.value))}
                disabled={inputsDisabled}
                title={readOnly ? "Read-only — contact admin to edit" : undefined}
                className="flex-1 text-sm px-2 py-1 rounded-md disabled:cursor-not-allowed disabled:opacity-60"
                style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
                data-testid={`ebit-row-${lineKey}-override-input`}
              />
              {readOnly ? null : (
                <button
                  type="button"
                  onClick={() => onOverrideChange(null)}
                  className="text-xs font-semibold px-2 py-1 rounded-md"
                  style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.muted }}
                  data-testid={`ebit-row-${lineKey}-override-clear`}
                >
                  Clear override
                </button>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2" data-testid={`ebit-row-${lineKey}-adjustment-mode`}>
              <label className="text-xs font-semibold" style={{ color: meta.color }}>
                Adjustment (delta):
              </label>
              <input
                type="number"
                step="0.01"
                value={adjustment ?? 0}
                onChange={(e) => onAdjustmentChange(e.target.value === "" ? 0 : Number(e.target.value))}
                disabled={inputsDisabled}
                title={readOnly ? "Read-only — contact admin to edit" : undefined}
                className="flex-1 text-sm px-2 py-1 rounded-md disabled:cursor-not-allowed disabled:opacity-60"
                style={{ border: `1px solid ${colors.border}`, background: colors.surface }}
                data-testid={`ebit-row-${lineKey}-adjustment-input`}
              />
              {overrideAllowed ? (
                <button
                  type="button"
                  onClick={() => onOverrideChange(computed)}
                  className="text-xs font-semibold px-2 py-1 rounded-md"
                  style={{ border: `1px solid ${meta.color}`, background: colors.surface, color: meta.color }}
                  data-testid={`ebit-row-${lineKey}-flip-override`}
                >
                  Flip to override
                </button>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Version history modal.
// ═══════════════════════════════════════════════════════════════════
function EbitVersionsModal({ open, onClose, snapshots, onLoad }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="ebit-versions-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl overflow-hidden shadow-2xl"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <header className="px-5 py-3 flex items-center justify-between"
                style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="flex items-center gap-2">
            <History size={14} color="#0891B2" />
            <div className="font-bold" style={{ color: colors.onSurface }}>
              Snapshot history for current range
            </div>
          </div>
          <button type="button" onClick={onClose}
                   className="p-1" style={{ color: colors.muted }}
                   aria-label="Close" data-testid="ebit-versions-close">
            <X size={16} />
          </button>
        </header>
        <div className="max-h-[60vh] overflow-y-auto">
          {snapshots.length === 0 ? (
            <div className="px-5 py-6 text-sm" style={{ color: colors.muted }}
                  data-testid="ebit-versions-empty">
              No saved snapshots for this range yet.
            </div>
          ) : (
            <ul className="divide-y" style={{ borderColor: colors.border }}
                 data-testid="ebit-versions-list">
              {snapshots.map((s) => (
                <li key={s.id} className="px-5 py-3 flex items-center gap-3"
                     data-testid={`ebit-versions-row-${s.id}`}>
                  <div className="text-xs px-2 py-0.5 rounded-full font-bold"
                        style={{ background: "#EFF6FF", color: "#1E3A8A" }}>
                    v{s.version}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate"
                          style={{ color: colors.onSurface }}>
                      EBIT {money(s.ebit)} · {s.revenue_basis}
                    </div>
                    <div className="text-[11px] font-mono truncate"
                          style={{ color: colors.muted }}>
                      {s.saved_at} · {s.author_user_id?.slice(0, 8) || "anon"}
                    </div>
                    {s.note ? (
                      <div className="text-[11px] italic truncate"
                            style={{ color: colors.muted }}>
                        "{s.note}"
                      </div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => onLoad(s)}
                    className="text-xs font-semibold px-2 py-1 rounded-md flex items-center gap-1"
                    style={{ background: "#0891B2", color: "#fff" }}
                    data-testid={`ebit-versions-load-${s.id}`}
                  >
                    Load <ChevronRight size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Top-level EBIT panel.
// ═══════════════════════════════════════════════════════════════════
export default function EbitPanel() {
  const { user } = useAuth() || {};
  const role = user?.role || "";
  const canEdit = role === "super_admin" || role === "admin";
  const canView = canEdit || role === "manager";

  const [range, setRange] = useState(initialRange());
  const [revenueBasis, setRevenueBasis] = useState("cash");
  const [live, setLive] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const [adjustments, setAdjustments] = useState(blankAdjustments());
  const [overrides, setOverrides] = useState(blankOverrides());
  const [note, setNote] = useState("");
  const [, setLoadedSnapshotId] = useState(null);
  const [loadedVersion, setLoadedVersion] = useState(null);
  const [readonly, setReadonly] = useState(false);

  const [versionsOpen, setVersionsOpen] = useState(false);
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotsBusy, setSnapshotsBusy] = useState(false);

  const printRef = useRef(null);

  const buildComputeQs = useCallback(() => {
    const p = new URLSearchParams();
    p.set("range", range.kind);
    p.set("from", range.from);
    p.set("to", range.to);
    p.set("revenue_basis", revenueBasis);
    return p.toString();
  }, [range, revenueBasis]);

  const fetchLive = useCallback(async () => {
    if (!canView) return;
    if (!range.from || !range.to) return;
    setBusy(true); setErr("");
    try {
      const res = await api.get(`/ebit/compute?${buildComputeQs()}`);
      setLive(res);
      // Reset edits when the underlying compute changes.
      setAdjustments(blankAdjustments());
      setOverrides(blankOverrides());
      setLoadedSnapshotId(null);
      setLoadedVersion(null);
      setReadonly(false);
      setNote("");
    } catch (e) {
      setErr(e?.message || "Failed to load EBIT.");
      setLive(null);
    } finally {
      setBusy(false);
    }
  }, [buildComputeQs, canView, range]);

  const fetchSnapshots = useCallback(async () => {
    if (!canView) return;
    setSnapshotsBusy(true);
    try {
      const p = new URLSearchParams();
      p.set("range_from", range.from);
      p.set("range_to", range.to);
      const res = await api.get(`/ebit/snapshots?${p.toString()}`);
      setSnapshots(res?.snapshots || []);
    } catch (_e) {
      setSnapshots([]);
    } finally {
      setSnapshotsBusy(false);
    }
  }, [range, canView]);

  useEffect(() => { fetchLive(); }, [fetchLive]);

  const effective = useMemo(
    () => toEffective(live || {}, adjustments, overrides),
    [live, adjustments, overrides],
  );

  const setOneAdjustment = (k, v) =>
    setAdjustments((a) => ({ ...a, [k]: Number(v) || 0 }));
  const setOneOverride = (k, v) =>
    setOverrides((o) => ({ ...o, [k]: v === null ? null : Number(v) || 0 }));

  const onRangeKind = (kind) => {
    if (kind === "monthly") setRange({ kind, ...monthWindow() });
    else if (kind === "quarterly") setRange({ kind, ...quarterWindow() });
    else setRange((r) => ({ ...r, kind: "custom" }));
  };
  const onCustomDate = (which, val) => setRange((r) => ({ ...r, [which]: val }));

  const openVersions = async () => {
    await fetchSnapshots();
    setVersionsOpen(true);
  };
  const loadSnapshot = (snap) => {
    setLoadedSnapshotId(snap.id);
    setLoadedVersion(snap.version);
    setAdjustments({ ...blankAdjustments(), ...(snap.line_adjustments || {}) });
    setOverrides({ ...blankOverrides(), ...(snap.line_overrides || {}) });
    setNote(snap.note || "");
    setReadonly(true);
    setVersionsOpen(false);
  };
  const forkNewVersion = () => setReadonly(false);

  const save = async () => {
    if (!canEdit) return;
    setSaving(true); setErr("");
    try {
      const body = {
        range_kind: range.kind,
        range_from: range.from,
        range_to: range.to,
        revenue_basis: revenueBasis,
        line_adjustments: adjustments,
        line_overrides: overrides,
        note,
      };
      const saved = await api.post(`/ebit/snapshots`, body);
      setLoadedSnapshotId(saved.id);
      setLoadedVersion(saved.version);
      await fetchSnapshots();
    } catch (e) {
      setErr(e?.message || "Failed to save snapshot.");
    } finally {
      setSaving(false);
    }
  };

  const exportCsv = () => {
    if (!live) return;
    const rows = [
      ["range_kind", range.kind],
      ["range_from", range.from],
      ["range_to", range.to],
      ["revenue_basis", revenueBasis],
      [],
      ["line", "computed", "adjustment", "override", "effective"],
      ...LINE_KEYS.map((k) => [
        k,
        Number(live[k] || 0).toFixed(2),
        Number(adjustments[k] || 0).toFixed(2),
        overrides[k] === null || overrides[k] === undefined ? "" : Number(overrides[k]).toFixed(2),
        Number(effective[k] || 0).toFixed(2),
      ]),
      ["ebit", "", "", "", Number(effective.ebit || 0).toFixed(2)],
    ];
    const csv = rows.map((r) =>
      r.map((c) => {
        const s = String(c ?? "");
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      }).join(","),
    ).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `ebit-${range.kind}-${range.from}_to_${range.to}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
  };

  const exportPdf = () => {
    // Native browser print — matches EstimateView + InvoiceView pattern.
    // Users pick "Save as PDF" in the print dialog.
    if (typeof window !== "undefined" && window.print) window.print();
  };

  if (!canView) {
    return (
      <div className="p-4 rounded-xl text-sm"
             style={{ background: "#FEE2E2", color: "#7F1D1D",
                       border: "1px solid #FCA5A5" }}
             data-testid="ebit-panel-forbidden">
        EBIT report is admin + manager only.
      </div>
    );
  }

  return (
    <section
      ref={printRef}
      className="rounded-2xl p-4 md:p-5 space-y-4"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="ebit-panel"
    >
      <header className="flex items-center gap-2 flex-wrap">
        <Sparkles size={18} color="#0891B2" />
        <h2 className="text-xl font-bold" style={{ color: colors.onSurface }}>
          EBIT
        </h2>
        {loadedVersion ? (
          <span className="text-xs px-2 py-0.5 rounded-full font-bold"
                 style={{ background: "#EFF6FF", color: "#1E3A8A" }}
                 data-testid="ebit-panel-loaded-version">
            v{loadedVersion} {readonly ? "(read-only)" : "(fork)"}
          </span>
        ) : (
          <span className="text-xs px-2 py-0.5 rounded-full font-bold"
                 style={{ background: "#F0FDF4", color: "#166534" }}
                 data-testid="ebit-panel-live-tag">
            live
          </span>
        )}
        {/* Phase 53c-fix · Feb-2026 — visible read-only badge for
             role=manager so it's obvious no save action is present. */}
        {!canEdit && canView ? (
          <span className="text-xs px-2 py-0.5 rounded-full font-bold"
                 style={{ background: "#FEF3C7", color: "#78350F" }}
                 title="Read-only — contact admin to edit"
                 data-testid="ebit-panel-readonly-badge">
            read-only
          </span>
        ) : null}
        <div className="flex-1" />
        <button
          type="button"
          onClick={openVersions}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
          data-testid="ebit-open-versions"
        >
          <History size={12} /> History
        </button>
        <button
          type="button"
          onClick={exportCsv}
          disabled={!live || busy}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white"
          style={{ background: "#0F766E", opacity: (!live || busy) ? 0.5 : 1 }}
          data-testid="ebit-export-csv"
        >
          <FileDown size={12} /> CSV
        </button>
        <button
          type="button"
          onClick={exportPdf}
          disabled={!live}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white"
          style={{ background: "#7C3AED", opacity: !live ? 0.5 : 1 }}
          data-testid="ebit-export-pdf"
        >
          <Printer size={12} /> PDF
        </button>
      </header>

      {/* ── Range picker + basis toggle ── */}
      <div className="flex items-center gap-2 flex-wrap"
             data-testid="ebit-range-picker">
        {RANGE_KINDS.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => onRangeKind(r.key)}
            className="text-xs px-2.5 py-1 rounded-full font-semibold transition-colors"
            style={range.kind === r.key
              ? { background: "#0891B2", color: "#fff", border: "1px solid #0891B2" }
              : { background: colors.surface, color: colors.muted, border: `1px solid ${colors.border}` }}
            data-testid={`ebit-range-${r.key}`}
            aria-pressed={range.kind === r.key}
          >
            {r.label}
          </button>
        ))}

        {range.kind === "custom" ? (
          <div className="flex gap-1.5 items-center" data-testid="ebit-custom-picker">
            <input
              type="date"
              value={range.from}
              onChange={(e) => onCustomDate("from", e.target.value)}
              className="text-xs px-2 py-1 rounded-md"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="ebit-custom-from"
            />
            <span className="text-xs" style={{ color: colors.muted }}>to</span>
            <input
              type="date"
              value={range.to}
              onChange={(e) => onCustomDate("to", e.target.value)}
              className="text-xs px-2 py-1 rounded-md"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="ebit-custom-to"
            />
          </div>
        ) : null}

        <div className="inline-flex rounded-lg overflow-hidden"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="ebit-basis-toggle">
          <button
            type="button"
            onClick={() => setRevenueBasis("cash")}
            className="text-xs px-3 py-1 font-semibold"
            style={revenueBasis === "cash"
              ? { background: "#0891B2", color: "#fff" }
              : { background: colors.surface, color: colors.muted }}
            data-testid="ebit-basis-cash"
            aria-pressed={revenueBasis === "cash"}
          >
            Cash
          </button>
          <button
            type="button"
            onClick={() => setRevenueBasis("accrual")}
            className="text-xs px-3 py-1 font-semibold"
            style={revenueBasis === "accrual"
              ? { background: "#0891B2", color: "#fff" }
              : { background: colors.surface, color: colors.muted }}
            data-testid="ebit-basis-accrual"
            aria-pressed={revenueBasis === "accrual"}
          >
            Accrual
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      {err ? (
        <div className="text-sm p-3 rounded-xl"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="ebit-error">
          {err}
        </div>
      ) : busy && !live ? (
        <div className="flex items-center gap-2 py-6 text-sm"
              style={{ color: colors.muted }}
              data-testid="ebit-loading">
          <Loader2 size={14} className="animate-spin" /> Loading EBIT…
        </div>
      ) : live ? (
        <>
          <div className="grid gap-3 md:grid-cols-2"
                data-testid="ebit-rows">
            {LINE_KEYS.map((k) => (
              <EbitLineRow
                key={k}
                lineKey={k}
                computed={Number(live[k] || 0)}
                effective={Number(effective[k] || 0)}
                adjustment={adjustments[k]}
                override={overrides[k]}
                onAdjustmentChange={(v) => setOneAdjustment(k, v)}
                onOverrideChange={(v) => setOneOverride(k, v)}
                canEdit={canEdit}
                editable={canEdit && !readonly}
                readOnly={!canEdit}
              />
            ))}
          </div>

          <div className="flex items-center justify-between rounded-xl p-4"
                style={{ background: "#0F172A", color: "#FFFFFF" }}
                data-testid="ebit-total-row">
            <div className="flex items-center gap-2">
              <Percent size={16} color="#22D3EE" />
              <span className="text-xs uppercase font-bold tracking-wide"
                     style={{ color: "#94A3B8" }}>
                EBIT (effective)
              </span>
            </div>
            <div className="text-2xl font-black" data-testid="ebit-total-value">
              {money(effective.ebit || 0)}
            </div>
          </div>

          {canEdit && !readonly ? (
            <div className="flex items-center gap-2 flex-wrap"
                  data-testid="ebit-save-row">
              <input
                type="text"
                placeholder="Note for this version (optional)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="flex-1 min-w-[180px] text-sm px-2 py-1.5 rounded-md"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid="ebit-save-note"
              />
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-bold text-white"
                style={{ background: "#0891B2", opacity: saving ? 0.5 : 1 }}
                data-testid="ebit-save-btn"
              >
                {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Save version
              </button>
            </div>
          ) : null}

          {readonly && canEdit ? (
            <div className="flex items-center gap-2">
              <span className="text-xs" style={{ color: colors.muted }}>
                Viewing a saved version. Fork to make a new editable copy.
              </span>
              <button
                type="button"
                onClick={forkNewVersion}
                className="text-xs font-semibold px-2 py-1 rounded-md"
                style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                data-testid="ebit-fork-btn"
              >
                Fork new version
              </button>
            </div>
          ) : null}
        </>
      ) : null}

      <EbitVersionsModal
        open={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        snapshots={snapshots}
        onLoad={loadSnapshot}
      />
      {snapshotsBusy ? null : null}
    </section>
  );
}
