/**
 * Feb-2026 · Admin migrations page — super_admin only.
 *
 * Currently exposes one card: P19 backfill for empty "Website Visitor"
 * leads.  The card supports a two-step interaction:
 *   1. Preview (Dry Run) — POST with dry_run=true. Renders the diff
 *      table so the admin can inspect exactly what would change.
 *   2. Run Backfill — disabled until step 1 has been run at least
 *      once AND the admin types "BACKFILL" into the confirmation
 *      field. POSTs with dry_run=false, then renders the persisted
 *      report (matched / enriched counts + per-lead diff).
 *
 * The endpoint enforces the super_admin gate + tenant scope; this
 * page is a thin driver over the API. If we add more one-off
 * migrations later, they'll live here as sibling cards.
 */
import React, { useState } from "react";
import { api } from "@/api";
import { colors } from "../../theme";


function DiffTable({ enrichments }) {
  if (!enrichments || enrichments.length === 0) {
    return (
      <div
        className="text-sm py-4"
        style={{ color: colors.muted }}
        data-testid="id-migration-p19-empty"
      >
        No leads matched the P19 candidate filter on this tenant.
        (Fallback name "Website Visitor" with empty phone AND email.)
      </div>
    );
  }
  return (
    <div
      className="overflow-x-auto mt-3"
      data-testid="id-migration-p19-diff-table"
    >
      <table className="min-w-full text-xs font-mono">
        <thead>
          <tr style={{ color: colors.muted }}>
            <th className="text-left p-2">Lead</th>
            <th className="text-left p-2">Field</th>
            <th className="text-left p-2">Before</th>
            <th className="text-left p-2">After</th>
          </tr>
        </thead>
        <tbody>
          {enrichments.flatMap((e) =>
            Object.keys(e.after || {}).map((field) => (
              <tr
                key={`${e.lead_id}-${field}`}
                style={{ borderTop: `1px solid ${colors.border}` }}
                data-testid={`id-migration-p19-diff-row-${e.lead_id}-${field}`}
              >
                <td className="p-2" style={{ color: colors.onSurfaceSecondary }}>
                  {e.lead_id.slice(0, 8)}
                </td>
                <td className="p-2 font-semibold" style={{ color: colors.onSurface }}>
                  {field}
                </td>
                <td className="p-2" style={{ color: colors.muted }}>
                  {String(e.before?.[field] ?? "—")}
                </td>
                <td className="p-2" style={{ color: colors.brand }}>
                  {String(e.after?.[field] ?? "—")}
                </td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}


function BackfillCard() {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [hasPreviewed, setHasPreviewed] = useState(false);

  const invoke = async (dry_run) => {
    setBusy(true); setError("");
    try {
      const r = await api.post(
        "/admin/migrations/backfill-website-visitor-leads"
        + `?dry_run=${dry_run ? "true" : "false"}`,
      );
      setReport(r);
      if (dry_run) setHasPreviewed(true);
      // Reset the typed-confirm after a real run so re-clicking
      // requires re-typing "BACKFILL" — protects against accidental
      // double-writes.
      if (!dry_run) setConfirmText("");
    } catch (e) {
      setError(e?.message || "Backfill invocation failed");
    } finally {
      setBusy(false);
    }
  };

  const runReady = hasPreviewed && confirmText === "BACKFILL" && !busy;

  return (
    <div
      className="rounded-2xl p-5 shadow-sm"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="id-migration-p19-card"
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h2
            className="text-lg font-bold"
            style={{ color: colors.onSurface }}
          >
            Backfill "Website Visitor" leads (P19)
          </h2>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Enrich legacy public-form leads whose contact fields were
            dropped by the pre-P17 extractor. Matching logic uses
            the linked <code>form_submissions.values</code> (±5-min
            window). Idempotent — running twice is safe.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mt-4 items-center">
        <button
          type="button"
          className="rounded-lg px-4 py-2 text-sm font-semibold"
          style={{
            background: colors.brandTertiary, color: colors.brand,
            border: `1px solid ${colors.brand}`,
            opacity: busy ? 0.5 : 1,
            cursor: busy ? "not-allowed" : "pointer",
          }}
          disabled={busy}
          onClick={() => invoke(true)}
          data-testid="id-migration-p19-preview"
        >
          {busy && !hasPreviewed ? "Previewing…" : "Preview (Dry Run)"}
        </button>

        <div className="flex items-center gap-2 ml-2">
          <input
            type="text"
            placeholder='Type "BACKFILL" to enable →'
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm font-mono"
            style={{
              background: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
              width: 240,
              opacity: hasPreviewed ? 1 : 0.5,
            }}
            disabled={!hasPreviewed || busy}
            data-testid="id-migration-p19-confirm-input"
          />
          <button
            type="button"
            className="rounded-lg px-4 py-2 text-sm font-semibold"
            style={{
              background: runReady ? "#DC2626" : colors.surfaceSecondary,
              color: runReady ? "#fff" : colors.muted,
              border: `1px solid ${runReady ? "#DC2626" : colors.border}`,
              cursor: runReady ? "pointer" : "not-allowed",
            }}
            disabled={!runReady}
            onClick={() => invoke(false)}
            data-testid="id-migration-p19-run"
          >
            {busy && hasPreviewed ? "Running…" : "Run Backfill"}
          </button>
        </div>
      </div>

      {error ? (
        <div
          className="mt-4 p-3 rounded-lg text-sm"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="id-migration-p19-error"
        >
          {error}
        </div>
      ) : null}

      {report ? (
        <div className="mt-4">
          <div
            className="grid grid-cols-3 gap-2 text-sm"
            data-testid="id-migration-p19-summary"
          >
            <div
              className="rounded-lg p-3"
              style={{ background: colors.surfaceSecondary }}
            >
              <div className="text-[11px] uppercase" style={{ color: colors.muted }}>
                Matched
              </div>
              <div className="text-xl font-bold" style={{ color: colors.onSurface }}>
                {report.matched_leads}
              </div>
            </div>
            <div
              className="rounded-lg p-3"
              style={{ background: colors.surfaceSecondary }}
            >
              <div className="text-[11px] uppercase" style={{ color: colors.muted }}>
                {report.dry_run ? "Would enrich" : "Enriched"}
              </div>
              <div className="text-xl font-bold" style={{ color: colors.brand }}>
                {report.dry_run
                  ? report.enrichments.length
                  : report.enriched_leads}
              </div>
            </div>
            <div
              className="rounded-lg p-3"
              style={{ background: colors.surfaceSecondary }}
            >
              <div className="text-[11px] uppercase" style={{ color: colors.muted }}>
                Skipped (no match)
              </div>
              <div className="text-xl font-bold" style={{ color: colors.onSurface }}>
                {report.skipped_no_match}
              </div>
            </div>
          </div>

          <DiffTable enrichments={report.enrichments} />

          {report.warnings?.length ? (
            <details className="mt-3 text-xs">
              <summary style={{ color: colors.muted, cursor: "pointer" }}>
                {report.warnings.length} warning
                {report.warnings.length === 1 ? "" : "s"}
              </summary>
              <ul
                className="mt-1 pl-4 list-disc font-mono"
                style={{ color: colors.muted }}
                data-testid="id-migration-p19-warnings"
              >
                {report.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


function RosterCleanupCard() {
  const [rows, setRows] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);

  const load = async () => {
    setBusy(true); setError("");
    try {
      const r = await api.get("/admin/migrations/roster");
      setRows(r);
      setSelected(new Set());
      setReport(null);
    } catch (e) {
      setError(e?.message || "Failed to load roster");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (uid, disabled) => {
    if (disabled) return;
    setSelected((prev) => {
      const s = new Set(prev);
      if (s.has(uid)) s.delete(uid); else s.add(uid);
      return s;
    });
  };

  const commit = async (dry_run) => {
    if (selected.size === 0) return;
    setBusy(true); setError("");
    try {
      const r = await api.post(
        "/admin/migrations/deactivate-users",
        { user_ids: Array.from(selected), dry_run },
      );
      setReport(r);
      if (!dry_run) {
        // Refresh so deactivated rows show the inactive chip
        // + selection cleared.
        await load();
        setConfirmText("");
      }
    } catch (e) {
      setError(e?.message || "Deactivate failed");
    } finally {
      setBusy(false);
    }
  };

  const runReady =
    selected.size > 0 && confirmText === "DEACTIVATE" && !busy;

  return (
    <div
      className="rounded-2xl p-5 shadow-sm mt-6"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="id-roster-cleanup-card"
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            User Roster Cleanup
          </h2>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Soft-deactivate tech-adjacent users to remove them from
            assign-tech dropdowns.  History (past jobs, invoices,
            service reports) is preserved.  Users with active
            scheduled / in-progress jobs must be reassigned first.
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg px-3 py-2 text-sm font-semibold"
          style={{
            background: colors.brandTertiary, color: colors.brand,
            border: `1px solid ${colors.brand}`,
            opacity: busy ? 0.5 : 1,
            cursor: busy ? "not-allowed" : "pointer",
          }}
          disabled={busy}
          onClick={load}
          data-testid="id-roster-list-btn"
        >
          {rows === null ? "List roster" : "Reload"}
        </button>
      </div>

      {error ? (
        <div
          className="mt-3 p-3 rounded-lg text-sm"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="id-roster-error"
        >{error}</div>
      ) : null}

      {rows !== null ? (
        <div className="mt-4 overflow-x-auto" data-testid="id-roster-table">
          <table className="min-w-full text-sm">
            <thead>
              <tr style={{ color: colors.muted }}>
                <th className="text-left p-2 w-8"></th>
                <th className="text-left p-2">Name</th>
                <th className="text-left p-2">Email</th>
                <th className="text-left p-2">Role</th>
                <th className="text-left p-2">Active jobs</th>
                <th className="text-left p-2">Status</th>
                <th className="text-left p-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={7}
                          className="p-3 text-center"
                          style={{ color: colors.muted }}
                          data-testid="id-roster-empty">
                  No tech-adjacent users on this tenant.
                </td></tr>
              ) : rows.map((r) => {
                const rowDisabled =
                  r.is_deactivated || (r.active_jobs || 0) > 0;
                return (
                  <tr
                    key={r.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`id-roster-user-${r.id}`}
                  >
                    <td className="p-2">
                      <input
                        type="checkbox"
                        checked={selected.has(r.id)}
                        onChange={() => toggle(r.id, rowDisabled)}
                        disabled={rowDisabled}
                        data-testid={`id-roster-check-${r.id}`}
                      />
                    </td>
                    <td className="p-2 font-semibold"
                        style={{ color: colors.onSurface }}>{r.name}</td>
                    <td className="p-2" style={{ color: colors.muted }}>{r.email}</td>
                    <td className="p-2" style={{ color: colors.muted }}>{r.role}</td>
                    <td className="p-2" style={{
                      color: (r.active_jobs || 0) > 0
                        ? "#DC2626" : colors.muted,
                    }}
                        data-testid={`id-roster-active-jobs-${r.id}`}>
                      {r.active_jobs || 0}
                      {/* Feb 2026 · Work-class split. Only rendered
                          when the payload carries the new fields AND
                          there's at least one repair — keeps the
                          column compact for the common case. */}
                      {typeof r.active_jobs_repair === "number"
                        && r.active_jobs_repair > 0 ? (
                        <span
                          className="ml-1 text-xs opacity-75"
                          data-testid={`id-roster-active-jobs-split-${r.id}`}
                        >
                          ({r.active_jobs_service ?? 0}S / {r.active_jobs_repair}R)
                        </span>
                      ) : null}
                    </td>
                    <td className="p-2">
                      {r.is_deactivated ? (
                        <span
                          className="px-2 py-0.5 rounded-full text-xs"
                          style={{ background: colors.surfaceSecondary,
                                    color: colors.muted }}
                          data-testid={`id-roster-inactive-chip-${r.id}`}
                        >Inactive</span>
                      ) : (
                        <span
                          className="px-2 py-0.5 rounded-full text-xs"
                          style={{ background: "#DCFCE7", color: "#166534" }}
                        >Active</span>
                      )}
                    </td>
                    <td className="p-2 text-xs" style={{ color: colors.muted }}>
                      {String(r.created_at || "").slice(0, 10)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {rows.length > 0 ? (
            <div
              className="mt-4 flex flex-wrap items-center gap-2"
              data-testid="id-roster-action-row"
            >
              <span className="text-sm" style={{ color: colors.muted }}>
                {selected.size} selected
              </span>
              <button
                type="button"
                className="rounded-lg px-3 py-2 text-sm"
                style={{
                  background: colors.brandTertiary,
                  color: colors.brand,
                  border: `1px solid ${colors.brand}`,
                  opacity: selected.size === 0 || busy ? 0.5 : 1,
                  cursor: selected.size === 0 || busy ? "not-allowed" : "pointer",
                }}
                disabled={selected.size === 0 || busy}
                onClick={() => commit(true)}
                data-testid="id-roster-preview-btn"
              >
                Preview (Dry Run)
              </button>
              <input
                type="text"
                placeholder='Type "DEACTIVATE" to enable →'
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="rounded-lg px-3 py-2 text-sm font-mono"
                style={{
                  background: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface, width: 240,
                  opacity: selected.size > 0 ? 1 : 0.5,
                }}
                disabled={selected.size === 0 || busy}
                data-testid="id-roster-confirm-input"
              />
              <button
                type="button"
                className="rounded-lg px-4 py-2 text-sm font-semibold"
                style={{
                  background: runReady ? "#DC2626" : colors.surfaceSecondary,
                  color: runReady ? "#fff" : colors.muted,
                  border: `1px solid ${runReady ? "#DC2626" : colors.border}`,
                  cursor: runReady ? "pointer" : "not-allowed",
                }}
                disabled={!runReady}
                onClick={() => commit(false)}
                data-testid="id-roster-deactivate-btn"
              >
                Deactivate selected
              </button>
            </div>
          ) : null}

          {report ? (
            <div
              className="mt-4 p-3 rounded-lg text-sm"
              style={{ background: colors.surfaceSecondary,
                        color: colors.onSurface }}
              data-testid="id-roster-report"
            >
              <div>
                <strong>{report.dry_run ? "Would deactivate" : "Deactivated"}:</strong>{" "}
                {report.deactivated_count}
              </div>
              <div>
                <strong>Skipped:</strong> {report.skipped_count}
              </div>
              {report.skipped?.length ? (
                <ul className="mt-2 pl-4 list-disc text-xs font-mono"
                    style={{ color: colors.muted }}>
                  {report.skipped.map((s, i) => (
                    <li key={i}>
                      {s.user_id.slice(0, 8)} — {s.reason}
                      {s.active_jobs != null
                        ? ` (${s.active_jobs} active jobs)`
                        : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


export default function AdminMigrationsPage() {
  return (
    <div
      className="max-w-4xl mx-auto p-6"
      data-testid="id-admin-migrations-page"
    >
      <h1
        className="text-2xl font-bold mb-1"
        style={{ color: colors.onSurface }}
      >
        Admin · Migrations
      </h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>
        Super-admin-only backfills. Every action is logged with your
        user id + target tenant. Preview first — then explicitly
        confirm before writing.
      </p>
      <BackfillCard />
      <RosterCleanupCard />
    </div>
  );
}
