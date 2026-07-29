/**
 * LZ5 · Feb-2026 — Lumino Payment Link Backfill (admin utility).
 *
 * Super-admin only. Fires POST /api/admin/lumino/backfill-payment-links
 * in either dry-run (preview) or live mode. Preview lists the first
 * N candidates without side effects. Live mode requires a confirm
 * modal, then paints the per-invoice result table.
 */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Zap, ShieldCheck, AlertTriangle, CheckCircle2, XCircle, Play,
  Eye,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { useAuth } from "@/auth";

const MAX_LIMIT = 500;
const PREVIEW_ROWS_SHOWN = 25;

function StatusPill({ status }) {
  const styles = {
    dispatched: { bg: "#DCFCE7", fg: "#166534", label: "Dispatched" },
    skipped: { bg: "#F1F5F9", fg: "#475569", label: "Skipped" },
    error: { bg: "#FEE2E2", fg: "#991B1B", label: "Error" },
  };
  const s = styles[status] || { bg: "#F1F5F9", fg: "#475569", label: status };
  return (
    <span
      className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.fg }}
      data-testid={`lumino-backfill-status-${status}`}
    >
      {s.label}
    </span>
  );
}

function ConfirmModal({ count, onCancel, onConfirm, busy }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={busy ? undefined : onCancel}
      data-testid="lumino-backfill-confirm-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="lumino-backfill-confirm-modal"
      >
        <header
          className="px-5 py-3 flex items-center gap-2"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <AlertTriangle size={16} color="#B45309" />
          <div className="font-bold" style={{ color: colors.onSurface }}>
            Dispatch {count} Lumino link request{count === 1 ? "" : "s"}?
          </div>
        </header>
        <div className="px-5 py-4 space-y-2 text-sm"
              style={{ color: colors.onSurface }}>
          <p>
            This will fire the Zapier catch-hook once per candidate
            invoice (with a 250 ms pause between calls). Each dispatch
            is recorded in <code>db.audits</code> with{" "}
            <code>kind=lumino_backfill</code> so it can be reconciled
            after the fact.
          </p>
          <p style={{ color: colors.onSurfaceSecondary }}>
            Invoices already carrying a Lumino payment URL, paid
            invoices, and cancelled/void invoices are automatically
            skipped by the endpoint.
          </p>
        </div>
        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`,
                    background: colors.surfaceSecondary }}
        >
          <button
            onClick={onCancel}
            disabled={busy}
            className="px-3 py-1.5 text-sm font-semibold rounded-lg"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface,
                      opacity: busy ? 0.5 : 1 }}
            data-testid="lumino-backfill-confirm-cancel"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="px-3 py-1.5 text-sm font-semibold rounded-lg text-white"
            style={{ background: "#B45309",
                      opacity: busy ? 0.7 : 1 }}
            data-testid="lumino-backfill-confirm-proceed"
          >
            {busy ? "Dispatching…" : "Proceed"}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default function LuminoBackfillPage() {
  const nav = useNavigate();
  const { user } = useAuth() || {};
  const isSuper = user?.role === "super_admin";

  const [dryRun, setDryRun] = useState(true);
  const [limit, setLimit] = useState(25);
  const [minCreatedAt, setMinCreatedAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null);   // dry-run response
  const [runResult, setRunResult] = useState(null); // live-run response
  const [showConfirm, setShowConfirm] = useState(false);

  if (!isSuper) {
    return (
      <div className="p-8 max-w-2xl mx-auto"
             data-testid="lumino-backfill-forbidden">
        <div className="rounded-xl p-4 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}>
          <b>Super-admin only.</b> This tool dispatches live Zapier
          calls and is restricted.
        </div>
      </div>
    );
  }

  const buildBody = (isDryRun) => {
    const body = {
      dry_run: isDryRun,
      limit: Math.min(Math.max(parseInt(limit, 10) || 1, 1), MAX_LIMIT),
    };
    if (minCreatedAt) body.min_created_at = `${minCreatedAt}T00:00:00Z`;
    return body;
  };

  const runPreview = async () => {
    setBusy(true); setErr(""); setRunResult(null);
    try {
      const res = await api.post(
        "/admin/lumino/backfill-payment-links", buildBody(true),
      );
      setPreview(res);
    } catch (e) {
      setErr(e?.message || "Preview failed.");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const openConfirm = () => setShowConfirm(true);
  const closeConfirm = () => { if (!busy) setShowConfirm(false); };

  const runLive = async () => {
    setBusy(true); setErr("");
    try {
      const res = await api.post(
        "/admin/lumino/backfill-payment-links", buildBody(false),
      );
      setRunResult(res);
      setShowConfirm(false);
      // Refresh preview so the counters reflect the new state.
      setPreview(null);
    } catch (e) {
      setErr(e?.message || "Backfill failed.");
    } finally {
      setBusy(false);
    }
  };

  const previewCount = preview?.total_candidates ?? null;
  const previewRows = (preview?.results || []).slice(0, PREVIEW_ROWS_SHOWN);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-5"
           data-testid="lumino-backfill-page">
      <button
        onClick={() => nav(-1)}
        className="flex items-center gap-1 text-sm font-semibold mb-1"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>

      <div className="flex items-center gap-2">
        <Zap size={22} color="#7C3AED" />
        <h1 className="text-2xl font-bold"
             style={{ color: colors.onSurface }}>
          Lumino Backfill
        </h1>
        <span className="text-xs px-2 py-0.5 rounded-full inline-flex items-center gap-1"
               style={{ background: "#DBEAFE", color: "#1E40AF" }}>
          <ShieldCheck size={11} /> Super-admin
        </span>
      </div>
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
        Retroactively fire Lumino payment-link requests for unpaid
        invoices that pre-date the Zapier bridge (or where the initial
        dispatch was lost). Paid invoices, cancelled invoices, and
        invoices that already carry a Lumino URL are skipped
        automatically.
      </p>

      {/* ── Form ── */}
      <div className="rounded-2xl p-5 space-y-4"
             style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="lumino-backfill-form">
        <div className="flex flex-wrap gap-4 items-end">
          <label className="flex items-center gap-2 text-sm font-semibold"
                  style={{ color: colors.onSurface }}
                  data-testid="lumino-backfill-dry-run-label">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              data-testid="lumino-backfill-dry-run-toggle"
            />
            Dry-run (preview only)
          </label>

          <div className="flex flex-col">
            <label className="text-xs uppercase font-semibold mb-1"
                    style={{ color: colors.onSurfaceSecondary }}>
              Limit (1–{MAX_LIMIT})
            </label>
            <input
              type="number"
              min={1}
              max={MAX_LIMIT}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className="px-3 py-1.5 text-sm rounded-lg w-28"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="lumino-backfill-limit-input"
            />
          </div>

          <div className="flex flex-col">
            <label className="text-xs uppercase font-semibold mb-1"
                    style={{ color: colors.onSurfaceSecondary }}>
              Only invoices created on/after
            </label>
            <input
              type="date"
              value={minCreatedAt}
              onChange={(e) => setMinCreatedAt(e.target.value)}
              className="px-3 py-1.5 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="lumino-backfill-min-created-at"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-2 border-t"
              style={{ borderColor: colors.border }}>
          <button
            onClick={runPreview}
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
            style={{ background: "#0891B2", opacity: busy ? 0.6 : 1 }}
            data-testid="lumino-backfill-preview-btn"
          >
            <Eye size={13} />
            {busy ? "Loading…" : "Preview candidates"}
          </button>
          <button
            onClick={openConfirm}
            disabled={busy || dryRun || (preview?.total_candidates ?? 0) === 0}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
            style={{
              background: "linear-gradient(135deg, #7C3AED 0%, #B45309 100%)",
              opacity: (busy || dryRun || (preview?.total_candidates ?? 0) === 0) ? 0.4 : 1,
            }}
            data-testid="lumino-backfill-run-btn"
            title={
              dryRun
                ? "Uncheck Dry-run to enable"
                : (preview?.total_candidates ?? 0) === 0
                  ? "Run Preview first"
                  : "Dispatch Lumino link requests"
            }
          >
            <Play size={13} /> Run backfill
          </button>
          {err ? (
            <span className="text-xs text-red-700"
                   data-testid="lumino-backfill-error">
              {err}
            </span>
          ) : null}
        </div>
      </div>

      {/* ── Preview panel ── */}
      {preview ? (
        <div className="rounded-2xl p-5"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="lumino-backfill-preview-panel">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-lg font-bold"
                 style={{ color: colors.onSurface }}>
              Preview
            </h2>
            <span className="text-sm font-semibold"
                   style={{ color: "#0891B2" }}
                   data-testid="lumino-backfill-preview-count">
              {previewCount} candidate{previewCount === 1 ? "" : "s"}
            </span>
          </div>
          {previewCount === 0 ? (
            <div className="text-sm py-3"
                  style={{ color: colors.onSurfaceSecondary }}>
              No unpaid invoices without a Lumino link were found for
              the current filters.
            </div>
          ) : (
            <table className="w-full text-sm"
                    data-testid="lumino-backfill-preview-table">
              <thead>
                <tr style={{ color: colors.onSurfaceSecondary }}>
                  <th className="text-left py-1">Invoice #</th>
                  <th className="text-left py-1">Customer</th>
                  <th className="text-right py-1">Total</th>
                  <th className="text-left py-1">Status</th>
                  <th className="text-left py-1">Created</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.map((r) => (
                  <tr key={r.invoice_id}
                       className="border-t"
                       style={{ borderColor: colors.border }}
                       data-testid={`lumino-backfill-preview-row-${r.invoice_id}`}>
                    <td className="py-1 font-mono text-xs">
                      {r.invoice_number || r.invoice_id?.slice(0, 8)}
                    </td>
                    <td className="py-1">{r.customer_name || "—"}</td>
                    <td className="py-1 text-right font-semibold">
                      {money(r.total || 0)}
                    </td>
                    <td className="py-1 text-xs"
                         style={{ color: colors.onSurfaceSecondary }}>
                      {r.status || "—"}
                    </td>
                    <td className="py-1 text-xs"
                         style={{ color: colors.onSurfaceSecondary }}>
                      {(r.created_at || "").slice(0, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {previewCount > PREVIEW_ROWS_SHOWN ? (
            <div className="text-xs pt-2"
                  style={{ color: colors.onSurfaceSecondary }}>
              Showing first {PREVIEW_ROWS_SHOWN} of {previewCount}.
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ── Live run results ── */}
      {runResult ? (
        <div className="rounded-2xl p-5"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="lumino-backfill-results-panel">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-lg font-bold"
                 style={{ color: colors.onSurface }}>
              Backfill results
            </h2>
            <div className="flex gap-3 text-sm">
              <span className="inline-flex items-center gap-1"
                     style={{ color: "#166534" }}
                     data-testid="lumino-backfill-dispatched-count">
                <CheckCircle2 size={13} /> {runResult.dispatched} dispatched
              </span>
              <span className="inline-flex items-center gap-1"
                     style={{ color: "#475569" }}
                     data-testid="lumino-backfill-skipped-count">
                {runResult.skipped} skipped
              </span>
              <span className="inline-flex items-center gap-1"
                     style={{ color: "#991B1B" }}
                     data-testid="lumino-backfill-errors-count">
                <XCircle size={13} /> {runResult.errors} error{runResult.errors === 1 ? "" : "s"}
              </span>
            </div>
          </div>
          <table className="w-full text-sm"
                  data-testid="lumino-backfill-results-table">
            <thead>
              <tr style={{ color: colors.onSurfaceSecondary }}>
                <th className="text-left py-1">Invoice #</th>
                <th className="text-left py-1">Status</th>
                <th className="text-left py-1">Correlation ID</th>
                <th className="text-left py-1">Reason</th>
              </tr>
            </thead>
            <tbody>
              {(runResult.results || []).map((r) => (
                <tr key={r.invoice_id}
                     className="border-t"
                     style={{ borderColor: colors.border }}
                     data-testid={`lumino-backfill-result-row-${r.invoice_id}`}>
                  <td className="py-1 font-mono text-xs">
                    {r.invoice_number || r.invoice_id?.slice(0, 8)}
                  </td>
                  <td className="py-1">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="py-1 font-mono text-[11px]"
                       style={{ color: colors.onSurfaceSecondary }}>
                    {r.correlation_id || "—"}
                  </td>
                  <td className="py-1 text-xs"
                       style={{ color: colors.onSurfaceSecondary }}>
                    {r.reason || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {showConfirm ? (
        <ConfirmModal
          count={preview?.total_candidates || 0}
          busy={busy}
          onCancel={closeConfirm}
          onConfirm={runLive}
        />
      ) : null}
    </div>
  );
}
