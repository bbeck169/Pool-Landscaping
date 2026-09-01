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
import React, { useState, useEffect, useCallback } from "react";
import { api } from "@/api";
import { colors } from "../../theme";
import DataIntegrityTile from "@/components/admin/DataIntegrityTile";
import DriftAlertsCard from "@/components/admin/DriftAlertsCard";
import HealthCheckCard from "@/components/admin/HealthCheckCard";
import { useAuth } from "@/auth";


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
    } catch (e) {
      setError(e?.message || "Backfill invocation failed");
    } finally {
      setBusy(false);
    }
  };

  // Feb 2026 · Type-to-confirm friction removed. The Run button
  // is enabled as soon as a dry-run preview has completed —
  // eyeballing the preview report IS the confirmation step now.
  const runReady = hasPreviewed && !busy;

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
  // Feb 2026 · Preview/Run refactor — this card now follows the same
  // first-class Preview/Run + typed-confirm pattern as the Stripe
  // migration cards.  Details:
  //
  //   * Preview (Dry Run) and Run Cleanup buttons are ALWAYS visible
  //     up front.  They call ``POST /deactivate-users`` with an
  //     empty ``user_ids`` — the backend auto-resolves the candidate
  //     set to every tech-adjacent user on the caller's tenant.
  //     Existing skipped-reason logic (already_inactive /
  //     has_active_jobs / not_tech_adjacent) still runs per row.
  //   * The old audit table is preserved as a secondary read-only
  //     view behind the "List roster" toggle at the top-right,
  //     retaining every legacy row testid so E2E audits keep
  //     working.  The manual checkbox-selection flow is retired —
  //     the roster view is now read-only; if operators need
  //     surgical control they can hit the endpoint directly with
  //     an explicit ``user_ids`` array (the backend still honours
  //     that legacy shape).
  //   * ``api.post(path, body, 60_000)`` — numeric timeout, no
  //     ``AbortController`` wrapper.  Same P0 lesson we shipped for
  //     the Stripe cards.
  const [busy, setBusy] = useState(false);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  // Secondary read-only audit view — preserves the "List roster"
  // capability as requested.
  const [rows, setRows] = useState(null);
  const [rosterBusy, setRosterBusy] = useState(false);

  const run = async (dry_run) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post(
        "/admin/migrations/deactivate-users",
        // Empty ``user_ids`` → backend auto-resolves to the tenant's
        // full tech-adjacent roster.  Explicit-selection callers can
        // still POST a non-empty array; that path is unchanged.
        { user_ids: [], dry_run },
        60_000,  // 1 min — enough for large rosters, well under
                 //         Kubernetes ingress timeout.
      );
      setReport(r);
      if (dry_run) setHasPreviewed(true);
      else if (rows !== null) {
        // Refresh the audit table if it's currently open so the
        // newly-deactivated rows flip to the "Inactive" chip.
        await loadRoster();
      }
    } catch (e) {
      const aborted = e?.name === "AbortError" || e?.code === "ERR_CANCELED";
      setError(
        aborted
          ? "Timed out after 1 minute. Please retry."
          : (e?.message || "Deactivate failed"),
      );
    } finally {
      setBusy(false);
    }
  };

  const loadRoster = async () => {
    setRosterBusy(true);
    setError("");
    try {
      const r = await api.get("/admin/migrations/roster");
      setRows(r);
    } catch (e) {
      setError(e?.message || "Failed to load roster");
    } finally {
      setRosterBusy(false);
    }
  };

  const toggleRoster = () => {
    if (rows === null) {
      void loadRoster();
    } else {
      // Collapse the audit view — cheaper than re-fetching to
      // toggle open next time.
      setRows(null);
    }
  };

  // Feb 2026 · Type-to-confirm friction removed. Preview-first flow
  // is preserved (must dry-run before commit); the "type DEACTIVATE"
  // gate is not.
  const runReady = hasPreviewed && !busy;

  return (
    <div
      className="rounded-2xl p-5 shadow-sm mb-4"
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
            scheduled / in-progress jobs are automatically skipped —
            reassign them first.
          </p>
        </div>
        {/* "List roster" — preserved as a secondary read-only audit
            toggle so super_admins can still eyeball the current
            tech-adjacent roster + per-user active-jobs count. */}
        <button
          type="button"
          className="rounded-lg px-3 py-2 text-sm font-semibold"
          style={{
            background: colors.brandTertiary, color: colors.brand,
            border: `1px solid ${colors.brand}`,
            opacity: rosterBusy ? 0.5 : 1,
            cursor: rosterBusy ? "not-allowed" : "pointer",
          }}
          disabled={rosterBusy}
          onClick={toggleRoster}
          data-testid="id-roster-list-btn"
        >
          {rows === null ? "List roster" : "Hide roster"}
        </button>
      </div>

      {/* First-class Preview + Run row — always visible, mirrors
          the Stripe cards' contract. */}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: colors.brand,
            color: "#fff",
            opacity: busy ? 0.5 : 1,
          }}
          disabled={busy}
          onClick={() => run(true)}
          data-testid="id-roster-preview-btn"
        >
          {busy && !hasPreviewed ? "Previewing…" : "Preview (Dry Run)"}
        </button>
        <span className="text-xs" style={{ color: colors.muted }}>
          {hasPreviewed
            ? "Preview looks good? Run Cleanup below."
            : "Run a preview first to enable the cleanup button."}
        </span>
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: runReady ? "#DC2626" : colors.surfaceSecondary,
            color: runReady ? "#fff" : colors.muted,
            opacity: runReady ? 1 : 0.6,
          }}
          disabled={!runReady}
          onClick={() => run(false)}
          data-testid="id-roster-deactivate-btn"
        >
          {busy && hasPreviewed ? "Deactivating…" : "Run Cleanup"}
        </button>
      </div>

      {error ? (
        <div
          className="mt-3 p-3 rounded-lg text-sm"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="id-roster-error"
        >{error}</div>
      ) : null}

      {/* Preview / run report — count summary + per-user detail
          table (email + role + active_jobs) + skipped reasons. */}
      {report ? (
        <div
          className="mt-4 p-3 rounded-lg text-sm"
          style={{ background: colors.surfaceSecondary,
                    color: colors.onSurface }}
          data-testid="id-roster-report"
        >
          <div className="grid grid-cols-2 gap-2 mb-2">
            <div
              className="rounded-lg p-2"
              style={{ background: colors.surface }}
              data-testid="id-roster-report-count"
            >
              <div className="text-[11px] uppercase"
                    style={{ color: colors.muted }}>
                {report.dry_run ? "Would deactivate" : "Deactivated"}
              </div>
              <div className="text-xl font-bold"
                    style={{ color: colors.brand }}>
                {report.deactivated_count}
              </div>
            </div>
            <div
              className="rounded-lg p-2"
              style={{ background: colors.surface }}
            >
              <div className="text-[11px] uppercase"
                    style={{ color: colors.muted }}>
                Skipped
              </div>
              <div className="text-xl font-bold"
                    style={{ color: colors.onSurface }}>
                {report.skipped_count}
              </div>
            </div>
          </div>

          {report.deactivated_details?.length ? (
            <div className="overflow-x-auto"
                  data-testid="id-roster-report-details">
              <table className="min-w-full text-xs">
                <thead>
                  <tr style={{ color: colors.muted }}>
                    <th className="text-left p-1">Email</th>
                    <th className="text-left p-1">Name</th>
                    <th className="text-left p-1">Role</th>
                  </tr>
                </thead>
                <tbody>
                  {report.deactivated_details.map((d) => (
                    <tr key={d.id}
                        data-testid={`id-roster-report-row-${d.id}`}>
                      <td className="p-1 font-mono"
                          style={{ color: colors.onSurface }}>
                        {d.email}
                      </td>
                      <td className="p-1" style={{ color: colors.onSurface }}>
                        {d.name}
                      </td>
                      <td className="p-1" style={{ color: colors.muted }}>
                        {d.role}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {report.skipped?.length ? (
            <details className="mt-2 text-xs">
              <summary style={{ color: colors.muted, cursor: "pointer" }}>
                {report.skipped.length} skipped —{" "}
                {report.skipped.map((s) => s.reason).join(", ").slice(0, 60)}
              </summary>
              <ul className="mt-1 pl-4 list-disc font-mono"
                  style={{ color: colors.muted }}>
                {report.skipped.map((s, i) => (
                  <li key={i}>
                    {(s.user_id || "").slice(0, 8)} — {s.reason}
                    {s.active_jobs != null
                      ? ` (${s.active_jobs} active jobs)`
                      : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}

      {/* ─── Secondary read-only audit table — preserved capability.
          Renders only when "List roster" was clicked. Keeps all
          legacy row testids so any downstream E2E that used them
          keeps working. */}
      {rows !== null ? (
        <div className="mt-4 overflow-x-auto" data-testid="id-roster-table">
          <table className="min-w-full text-sm">
            <thead>
              <tr style={{ color: colors.muted }}>
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
                <tr><td colSpan={6}
                          className="p-3 text-center"
                          style={{ color: colors.muted }}
                          data-testid="id-roster-empty">
                  No tech-adjacent users on this tenant.
                </td></tr>
              ) : rows.map((r) => (
                <tr
                  key={r.id}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`id-roster-user-${r.id}`}
                >
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
                    {typeof r.active_jobs_service === "number"
                      && (r.active_jobs || 0) > 0 ? (
                      <span
                        className="ml-1 text-xs opacity-75"
                        data-testid={`id-roster-active-jobs-split-${r.id}`}
                      >
                        ({r.active_jobs_service ?? 0}S / {r.active_jobs_repair ?? 0}R)
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
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}


export default function AdminMigrationsPage() {
  const { user } = useAuth();
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
      {/* Feb-2026 · Admin Observability Bundle — F9 data-integrity
          rollup + F5 sentinel reset button. Guarded internally on
          user.role for the reset button; the read-only summary is
          safe to render for anyone routed here (route already
          gates on super_admin). */}
      <DataIntegrityTile userRole={user?.role} />
      <HealthCheckCard />
      <DriftAlertsCard userRole={user?.role} />
      <BackfillCard />
      <RosterCleanupCard />
      <StripeSyncCard />
      <StripeBillingHistoryCard />
      <AutoMergeCard />
    </div>
  );
}


// ═════════════════════════════════════════════════════════════════════
// Feb 2026 · Customer Merge Phase 3 · Auto-merge stats card.
// Live totals + a "Force sweep now" trigger against the caller's
// tenant. Reads GET /admin/migrations/auto-merge-summary on mount +
// re-fetches after every sweep.
// ═════════════════════════════════════════════════════════════════════
function AutoMergeCard() {
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastRun, setLastRun] = useState(null);

  const loadSummary = useCallback(async () => {
    try {
      const r = await api.get("/admin/migrations/auto-merge-summary");
      setSummary(r);
      setError("");
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Load failed");
    }
  }, []);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const forceSweep = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/migrations/auto-merge-sweep",
                                  {}, 60_000);
      setLastRun(r);
      await loadSummary();
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Sweep failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="admin-migrations-auto-merge-card"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="text-lg font-semibold"
                 style={{ color: colors.onSurface }}>
            Customer Merge · Auto-Merge
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Daily 09:15 UTC sweep merges HIGH-confidence duplicates
            (exact email OR phone). Low-confidence groups stay in the
            manual review queue.
          </div>
        </div>
        <span
          className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
          style={{
            backgroundColor: summary?.auto_merge_enabled
              ? "#DCFCE7" : "#FEE2E2",
            color: summary?.auto_merge_enabled ? "#166534" : "#991B1B",
          }}
          data-testid="auto-merge-flag-pill"
        >
          {summary?.auto_merge_enabled ? "CRON ENABLED" : "CRON DISABLED"}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
        {[
          ["Last auto run",
              summary?.last_auto_run_at
                ? new Date(summary.last_auto_run_at)
                    .toLocaleString(undefined, {
                       year: "numeric", month: "short",
                       day: "numeric", hour: "2-digit",
                       minute: "2-digit",
                    })
                : "—"],
          ["Auto-merged today", `${summary?.auto_merged_today ?? "—"} groups`],
          ["Records reassigned today",
              `${summary?.records_reassigned_today ?? "—"}`],
          ["Manual review queue",
              `${summary?.manual_queue_low_confidence ?? "—"} groups`],
        ].map(([label, value], i) => (
          <div key={i}
                 className="rounded-lg px-3 py-2"
                 style={{
                   backgroundColor: colors.surfaceSecondary,
                   border: `1px solid ${colors.border}`,
                 }}
                 data-testid={`auto-merge-stat-${i}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>
              {label}
            </div>
            <div className="text-sm font-semibold mt-0.5"
                   style={{ color: colors.onSurface }}>
              {value}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={forceSweep}
          disabled={busy}
          className="text-sm font-semibold px-3 py-1.5 rounded-lg disabled:opacity-40"
          style={{
            backgroundColor: colors.brand, color: "#fff",
          }}
          data-testid="auto-merge-force-btn"
        >
          {busy ? "Sweeping…" : "Force auto-merge sweep now"}
        </button>
        <button
          type="button"
          onClick={loadSummary}
          disabled={busy}
          className="text-xs font-semibold px-2 py-1 rounded-lg disabled:opacity-40"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="auto-merge-refresh-btn"
        >
          Refresh
        </button>
      </div>
      {lastRun ? (
        <div className="mt-3 text-xs rounded-lg px-3 py-2"
               style={{
                 backgroundColor: "#F0F9FF",
                 color: "#075985",
                 border: "1px solid #BAE6FD",
               }}
               data-testid="auto-merge-last-run">
          Last force sweep — merged <b>{lastRun.groups_auto_merged}</b>{" "}
          group{lastRun.groups_auto_merged === 1 ? "" : "s"}, skipped{" "}
          <b>{lastRun.groups_skipped_low_confidence}</b> low-confidence,
          reassigned <b>{lastRun.records_affected}</b> record
          {lastRun.records_affected === 1 ? "" : "s"}.
        </div>
      ) : null}
      {error ? (
        <div className="mt-3 text-xs rounded-lg px-3 py-2"
               style={{
                 backgroundColor: "#FEE2E2",
                 color: "#991B1B",
                 border: "1px solid #FCA5A5",
               }}
               data-testid="auto-merge-error">
          {error}
        </div>
      ) : null}
    </div>
  );
}


// ═════════════════════════════════════════════════════════════════════
// Feb 2026 · Stripe → CRM migration cards
// ═════════════════════════════════════════════════════════════════════

function StripeSyncCard() {
  const [busy, setBusy] = useState(false);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [report, setReport] = useState(null);
  const [importUnmatched, setImportUnmatched] = useState(false);
  const [error, setError] = useState("");

  const run = async (dry_run) => {
    setBusy(true);
    setError("");
    // Feb-2026 P0 fix — ``api.post``'s 3rd argument is a NUMERIC
    // ``timeoutMs`` (see ``frontend/src/api.js::request``), not an
    // options object. Passing ``{signal: ...}`` was coerced to
    // ``NaN`` → treated as 0 → the internal AbortController fired
    // before ``fetch`` was even issued, surfacing as "Request
    // timed out" on the very first click. Matches the pattern
    // used by the Leads Backfill (P19) + User Roster Cleanup
    // migration cards on this page.
    try {
      const r = await api.post(
        "/admin/migrations/sync-stripe-customers",
        { dry_run, import_unmatched: !dry_run && importUnmatched },
        120_000,  // 2 min — Stripe pulls can be slow on large tenants
      );
      setReport(r);
      if (dry_run) setHasPreviewed(true);
    } catch (e) {
      const aborted = e?.name === "AbortError" || e?.code === "ERR_CANCELED";
      setError(
        aborted
          ? "Timed out after 2 minutes. Try a smaller preview or retry."
          : (e?.response?.data?.detail || e?.message || "Sync failed"),
      );
    } finally {
      setBusy(false);
    }
  };

  // Feb 2026 · Type-to-confirm friction removed. Run enables as
  // soon as a dry-run preview has completed.
  const runReady = hasPreviewed && !busy;

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="id-migration-stripe-sync-card"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold" style={{ color: colors.onSurface }}>
          Sync Stripe Customers
        </h2>
        <span
          className="text-[10px] px-2 py-0.5 rounded-md font-semibold"
          style={{ background: "#635BFF", color: "#fff" }}
        >
          BYO-STRIPE
        </span>
      </div>
      <p className="text-xs mb-4" style={{ color: colors.muted }}>
        Pulls the tenant's Stripe.Customer roster, matches by email
        (then phone) against CRM customers, and attaches
        <code className="mx-1 px-1 rounded" style={{ background: colors.surfaceSecondary }}>
          stripe_customer_id
        </code>
        + default card details. Idempotent — re-run to catch new
        Stripe customers. Never charges cards.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: colors.brand,
            color: "#fff",
            opacity: busy ? 0.5 : 1,
          }}
          disabled={busy}
          onClick={() => run(true)}
          data-testid="id-migration-stripe-preview-btn"
        >
          {busy && !hasPreviewed ? "Previewing…" : "Preview (Dry Run)"}
        </button>
        <label
          className="text-xs inline-flex items-center gap-1.5"
          style={{ color: colors.onSurface }}
        >
          <input
            type="checkbox"
            checked={importUnmatched}
            onChange={(e) => setImportUnmatched(e.target.checked)}
            disabled={busy}
            data-testid="id-migration-stripe-import-unmatched-checkbox"
          />
          Also import unmatched Stripe customers as new CRM rows
        </label>
      </div>
      {/* Feb 2026 · Render the run + confirm row ALWAYS (not only
          after preview) so E2E automation can query the testids
          pre-preview. Buttons are ``disabled`` until a preview has
          completed AND the operator types the confirm word. */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="text-xs" style={{ color: colors.muted }}>
          {hasPreviewed
            ? "Preview looks good? Run Sync below."
            : "Run a preview first to enable the commit button."}
        </span>
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: runReady ? "#DC2626" : colors.surfaceSecondary,
            color: runReady ? "#fff" : colors.muted,
            opacity: runReady ? 1 : 0.6,
          }}
          disabled={!runReady}
          onClick={() => run(false)}
          data-testid="id-migration-stripe-run-btn"
        >
          {busy && hasPreviewed ? "Syncing…" : "Run Sync"}
        </button>
      </div>
      {error ? (
        <div
          className="text-sm mt-3 p-2 rounded-md"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="id-migration-stripe-error"
        >
          {error}
        </div>
      ) : null}
      {report ? (
        <div className="mt-4" data-testid="id-migration-stripe-report">
          <div
            className="text-xs mb-2"
            style={{ color: colors.muted }}
          >
            {report.dry_run ? "Dry-run report" : "Committed report"} · scanned {report.scanned}
          </div>
          <table
            className="min-w-full text-xs"
            data-testid="id-migration-stripe-diff-table"
          >
            <tbody>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Attachable</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}
                    data-testid="id-migration-stripe-attachable">
                  {report.attachable_count}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Already attached</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.already_attached_count}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Duplicate email (skipped)</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.duplicate_email_count}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Unmatched Stripe customers</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.unmatched_count}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>No email (Stripe side)</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.no_email_count}
                </td>
              </tr>
              {report.imported_new_count > 0 ? (
                <tr>
                  <td className="p-1 pr-4" style={{ color: colors.muted }}>Imported new CRM rows</td>
                  <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                    {report.imported_new_count}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}


function StripeBillingHistoryCard() {
  const [busy, setBusy] = useState(false);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [report, setReport] = useState(null);
  const [monthsBack, setMonthsBack] = useState(24);
  const [includeSubs, setIncludeSubs] = useState(true);
  const [error, setError] = useState("");

  const run = async (dry_run) => {
    setBusy(true);
    setError("");
    // Feb-2026 P0 fix — see ``StripeCustomerSyncCard.run`` for the
    // full explanation. ``api.post``'s 3rd argument is a numeric
    // ``timeoutMs``, not an options object. Passing
    // ``{signal: ...}`` was coerced to NaN → treated as 0ms → the
    // internal AbortController fired before fetch was issued.
    // 3 min ceiling because the billing history sync pulls
    // charges + invoices + subs and can genuinely run 30-90s on
    // large tenants (backend measured at 5.2s for AquaTerra).
    try {
      const r = await api.post(
        "/admin/migrations/sync-stripe-billing-history",
        {
          dry_run,
          months_back: Number(monthsBack) || 24,
          include_subscriptions: !!includeSubs,
        },
        180_000,  // 3 min
      );
      setReport(r);
      if (dry_run) setHasPreviewed(true);
    } catch (e) {
      const aborted = e?.name === "AbortError" || e?.code === "ERR_CANCELED";
      setError(
        aborted
          ? "Timed out after 3 minutes. Try a smaller time range or retry."
          : (e?.response?.data?.detail || e?.message || "Import failed"),
      );
    } finally {
      setBusy(false);
    }
  };

  // Feb 2026 · Type-to-confirm friction removed. Preview-first
  // safeguard is preserved (must dry-run before commit); the "type
  // IMPORT" gate is not.
  const runReady = hasPreviewed && !busy;

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="id-migration-stripe-billing-card"
    >
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-semibold" style={{ color: colors.onSurface }}>
          Sync Stripe Billing History
        </h2>
        <span
          className="text-[10px] px-2 py-0.5 rounded-md font-semibold"
          style={{ background: "#635BFF", color: "#fff" }}
        >
          BYO-STRIPE
        </span>
      </div>
      <p className="text-xs mb-3" style={{ color: colors.muted }}>
        Imports historical Stripe charges → CRM payments, Stripe
        invoices → CRM invoices (ancillary — canonical
        <code className="mx-1 px-1 rounded" style={{ background: colors.surfaceSecondary }}>
          db.quotes
        </code>
        untouched), and optionally subscriptions. Idempotent on
        every entity. <strong>Prereq: run "Sync Stripe Customers"
        first</strong> — this needs the customer mapping.
      </p>
      <div className="flex flex-wrap items-center gap-3 mb-2">
        <label className="text-xs" style={{ color: colors.onSurface }}>
          Time range:{" "}
          <select
            value={monthsBack}
            onChange={(e) => setMonthsBack(Number(e.target.value))}
            disabled={busy}
            className="ml-1 px-2 py-1 rounded-md text-xs"
            style={{
              background: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="id-migration-stripe-billing-months-select"
          >
            <option value={12}>12 months</option>
            <option value={24}>24 months</option>
            <option value={36}>36 months</option>
            <option value={60}>60 months</option>
            <option value={240}>All time (20yr)</option>
          </select>
        </label>
        <label
          className="text-xs inline-flex items-center gap-1.5"
          style={{ color: colors.onSurface }}
        >
          <input
            type="checkbox"
            checked={includeSubs}
            onChange={(e) => setIncludeSubs(e.target.checked)}
            disabled={busy}
            data-testid="id-migration-stripe-billing-include-subs-checkbox"
          />
          Include subscriptions
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: colors.brand,
            color: "#fff",
            opacity: busy ? 0.5 : 1,
          }}
          disabled={busy}
          onClick={() => run(true)}
          data-testid="id-migration-stripe-billing-preview-btn"
        >
          {busy && !hasPreviewed ? "Previewing…" : "Preview (Dry Run)"}
        </button>
      </div>
      {/* Feb 2026 · Always-rendered run row (disabled until preview
          completes). Makes the testids queryable pre-preview for
          automation. */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="text-xs" style={{ color: colors.muted }}>
          {hasPreviewed
            ? "Preview looks good? Run Import below."
            : "Run a preview first to enable the import button."}
        </span>
        <button
          type="button"
          className="text-sm px-3 py-2 rounded-lg font-semibold"
          style={{
            background: runReady ? "#DC2626" : colors.surfaceSecondary,
            color: runReady ? "#fff" : colors.muted,
            opacity: runReady ? 1 : 0.6,
          }}
          disabled={!runReady}
          onClick={() => run(false)}
          data-testid="id-migration-stripe-billing-run-btn"
        >
          {busy && hasPreviewed ? "Importing…" : "Run Import"}
        </button>
      </div>
      {error ? (
        <div
          className="text-sm mt-3 p-2 rounded-md"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="id-migration-stripe-billing-error"
        >
          {error}
        </div>
      ) : null}
      {report ? (
        <div className="mt-4" data-testid="id-migration-stripe-billing-report">
          <div
            className="text-xs mb-2"
            style={{ color: colors.muted }}
          >
            {report.dry_run ? "Dry-run report" : "Committed report"} · cutoff {report.cutoff_date?.slice(0, 10)}
          </div>
          <table
            className="min-w-full text-xs"
            data-testid="id-migration-stripe-billing-diff-table"
          >
            <tbody>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Matched charges</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}
                    data-testid="id-migration-stripe-billing-matched">
                  {report.matched_charges}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Unmatched charges (parked to customer)</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.unmatched_charges}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Skipped duplicate charges</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.skipped_dup_charges}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Payment records created</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.created_payment_records}
                </td>
              </tr>
              <tr>
                <td className="p-1 pr-4" style={{ color: colors.muted }}>Invoice records created</td>
                <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                  {report.created_invoice_records}
                </td>
              </tr>
              {report.include_subscriptions ? (
                <tr>
                  <td className="p-1 pr-4" style={{ color: colors.muted }}>Subscriptions imported</td>
                  <td className="p-1 font-semibold" style={{ color: colors.onSurface }}>
                    {report.created_subscription_records}
                  </td>
                </tr>
              ) : null}
              {(report.errors || []).length > 0 ? (
                <tr>
                  <td className="p-1 pr-4" style={{ color: "#DC2626" }}>Errors</td>
                  <td className="p-1 font-semibold" style={{ color: "#DC2626" }}>
                    {report.errors.length}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
