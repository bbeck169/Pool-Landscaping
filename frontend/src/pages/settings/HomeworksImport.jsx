/**
 * Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.
 *
 * Admin-only page that hosts:
 *   • The connect form (Fernet-encrypted email+password creds).
 *   • The batch list table with rollback confirmations.
 *   • A "New import batch" modal that fires ``POST /batches``.
 *
 * Batches created here stay in ``pending`` state — 55-b lands the
 * customer scraper that flips them to ``running``.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Download, Plus, RotateCcw, Eye, Play, Cloud } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";
import ChallengeHandoffModal from "@/components/suppliers/ChallengeHandoffModal";


const ALL_ENTITY_TYPES = [
  "customers", "properties", "jobs", "recurring_schedules",
  "invoices", "payments", "quotes", "attachments",
];

const STATE_PALETTE = {
  pending:            { bg: "#F1F5F9", fg: "#475569" },
  running:            { bg: "#DBEAFE", fg: "#1E40AF" },
  paused:             { bg: "#FEF3C7", fg: "#92400E" },
  paused_challenge:   { bg: "#FCE7F3", fg: "#9D174D" },
  committed:          { bg: "#DCFCE7", fg: "#166534" },
  rolled_back:        { bg: "#E5E7EB", fg: "#6B7280" },
  failed:             { bg: "#FEE2E2", fg: "#991B1B" },
};


function StatePill({ state, id }) {
  const p = STATE_PALETTE[state] || STATE_PALETTE.pending;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: p.bg, color: p.fg }}
      data-testid={`hw-batch-state-${id}`}
    >
      {state.replace(/_/g, " ")}
    </span>
  );
}


export default function HomeworksImport() {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creds, setCreds] = useState(null);   // {has_credentials, email, updated_at}
  const [credsEmail, setCredsEmail] = useState("");
  const [credsPassword, setCredsPassword] = useState("");
  const [credsBusy, setCredsBusy] = useState(false);
  const [credsMsg, setCredsMsg] = useState("");
  const [newModalOpen, setNewModalOpen] = useState(false);
  const [newSelected, setNewSelected] = useState(() =>
    new Set(ALL_ENTITY_TYPES));
  const [newBusy, setNewBusy] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState(null);
  const [rollbackBusy, setRollbackBusy] = useState(false);
  // Phase 55-f — Batch detail drawer + dry-run + commit + progress poll.
  const [detailTarget, setDetailTarget] = useState(null);
  const [detailReport, setDetailReport] = useState(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [commitBusy, setCommitBusy] = useState(false);
  const [progress, setProgress] = useState(null);
  const pollRef = useRef(null);
  // Phase 55-b — Scrape orchestrator + challenge handoff.
  const [scrapeBusy, setScrapeBusy] = useState(false);
  const [challengeInfo, setChallengeInfo] = useState(null);   // {slug}

  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => clearPoll(), [clearPoll]);

  const loadBatches = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const r = await api.get("/imports/homeworks/batches");
      setBatches(Array.isArray(r?.batches) ? r.batches : []);
    } catch (e) {
      setError(e?.message || "Failed to load batches.");
    } finally { setLoading(false); }
  }, []);

  const loadCreds = useCallback(async () => {
    try {
      const r = await api.get("/imports/homeworks/credentials");
      setCreds(r || null);
    } catch { setCreds(null); }
  }, []);

  useEffect(() => { loadBatches(); loadCreds(); },
             [loadBatches, loadCreds]);

  const saveCreds = async () => {
    if (!credsEmail.trim() || !credsPassword) return;
    setCredsBusy(true); setCredsMsg("");
    try {
      await api.post("/imports/homeworks/credentials", {
        email: credsEmail.trim(),
        password: credsPassword,
      });
      setCredsPassword("");
      setCredsMsg("Credentials saved.");
      await loadCreds();
    } catch (e) {
      setCredsMsg(e?.message || "Save failed.");
    } finally { setCredsBusy(false); }
  };

  const toggleEntity = (t) => setNewSelected((prev) => {
    const next = new Set(prev);
    if (next.has(t)) next.delete(t); else next.add(t);
    return next;
  });

  const createBatch = async () => {
    if (newBusy || newSelected.size === 0) return;
    setNewBusy(true);
    try {
      await api.post("/imports/homeworks/batches", {
        entity_types_planned: Array.from(newSelected),
      });
      setNewModalOpen(false);
      await loadBatches();
    } catch (e) {
      setError(e?.message || "Create failed.");
    } finally { setNewBusy(false); }
  };

  const doRollback = async () => {
    if (!rollbackTarget || rollbackBusy) return;
    setRollbackBusy(true);
    try {
      await api.post(
        `/imports/homeworks/batches/${rollbackTarget.id}/rollback`, {},
      );
      setRollbackTarget(null);
      await loadBatches();
    } finally { setRollbackBusy(false); }
  };

  // Phase 55-f — Load dry-run + progress for a batch.
  const openDetail = useCallback(async (batch) => {
    setDetailTarget(batch);
    setDetailReport(null);
    setProgress(null);
    setDetailBusy(true);
    try {
      const [rep, prog] = await Promise.all([
        api.get(`/imports/homeworks/batches/${batch.id}/dryrun`),
        api.get(`/imports/homeworks/batches/${batch.id}/progress`),
      ]);
      setDetailReport(rep || null);
      setProgress(prog || null);
    } catch (e) {
      setError(e?.message || "Failed to load batch detail.");
    } finally { setDetailBusy(false); }
  }, []);

  const closeDetail = useCallback(() => {
    clearPoll();
    setDetailTarget(null);
    setDetailReport(null);
    setProgress(null);
  }, [clearPoll]);

  const startProgressPoll = useCallback((batchId) => {
    clearPoll();
    pollRef.current = setInterval(async () => {
      try {
        const p = await api.get(
          `/imports/homeworks/batches/${batchId}/progress`);
        setProgress(p || null);
        if (p && (p.state === "committed" || p.state === "rolled_back")) {
          clearPoll();
          await loadBatches();
          // Also refresh dryrun to reflect final warnings + counts.
          try {
            const rep = await api.get(
              `/imports/homeworks/batches/${batchId}/dryrun`);
            setDetailReport(rep || null);
          } catch { /* non-fatal */ }
        }
      } catch { /* non-fatal — next tick will retry */ }
    }, 2000);
  }, [clearPoll, loadBatches]);

  const doCommit = async () => {
    if (!detailTarget || commitBusy) return;
    setCommitBusy(true);
    startProgressPoll(detailTarget.id);
    try {
      await api.post(
        `/imports/homeworks/batches/${detailTarget.id}/commit`, {});
      // Final refresh — poll will also catch this but do one deterministic
      // update so the UI doesn't feel laggy.
      const [rep, prog] = await Promise.all([
        api.get(`/imports/homeworks/batches/${detailTarget.id}/dryrun`),
        api.get(`/imports/homeworks/batches/${detailTarget.id}/progress`),
      ]);
      setDetailReport(rep || null);
      setProgress(prog || null);
      await loadBatches();
    } catch (e) {
      setError(e?.message || "Commit failed.");
    } finally {
      setCommitBusy(false);
      clearPoll();
    }
  };

  // Phase 55-b — Kick off the Copilot CRM scraper. If the response
  // carries ``challenge_required``, open the Phase 54h-b handoff
  // modal so the operator can push cookies via bookmarklet, then
  // retry via ``onRetry``.
  const doScrape = async () => {
    if (!detailTarget || scrapeBusy) return;
    setScrapeBusy(true);
    startProgressPoll(detailTarget.id);
    try {
      const r = await api.post(
        `/imports/homeworks/batches/${detailTarget.id}/scrape`, {});
      if (r && r.challenge_required) {
        setChallengeInfo({ slug: r.slug || "homeworks" });
      }
      // Refresh detail regardless.
      const [rep, prog] = await Promise.all([
        api.get(`/imports/homeworks/batches/${detailTarget.id}/dryrun`),
        api.get(`/imports/homeworks/batches/${detailTarget.id}/progress`),
      ]);
      setDetailReport(rep || null);
      setProgress(prog || null);
      await loadBatches();
    } catch (e) {
      setError(e?.message || "Scrape failed.");
    } finally {
      setScrapeBusy(false);
      clearPoll();
    }
  };

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4"
          data-testid="homeworks-import-page">
      <PageHeader
        icon={Download}
        title="Import from Homeworks"
        subtitle="One-shot migration from Copilot CRM. Connect your account, plan a batch, and roll back any run if the shape drifts."
      />

      {/* ── Credentials card ─────────────────────────────────── */}
      <div className="rounded-lg p-4"
            style={{ background: "#fff",
                     border: `1px solid ${colors.border}` }}>
        <h2 className="text-sm font-bold mb-2"
            style={{ color: colors.onSurface }}>
          Copilot CRM connection
        </h2>
        {creds?.has_credentials ? (
          <div className="text-xs mb-3" style={{ color: colors.muted }}
                data-testid="hw-creds-cached-line">
            Cached account: <span className="font-mono">{creds.email}</span>
            {creds.updated_at ? ` (updated ${creds.updated_at.slice(0, 10)})` : null}
          </div>
        ) : (
          <div className="text-xs mb-3" style={{ color: colors.muted }}>
            No credentials cached yet. Enter your Copilot CRM login below.
          </div>
        )}
        <div className="flex flex-wrap gap-2 items-end">
          <input
            type="email"
            placeholder="you@example.com"
            value={credsEmail}
            onChange={(e) => setCredsEmail(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[200px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="hw-creds-email"
          />
          <input
            type="password"
            placeholder="password"
            value={credsPassword}
            onChange={(e) => setCredsPassword(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[160px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="hw-creds-password"
          />
          <button
            type="button"
            onClick={saveCreds}
            disabled={credsBusy || !credsEmail.trim() || !credsPassword}
            className="text-xs font-bold px-3 py-2 rounded-md text-white disabled:opacity-60"
            style={{ background: colors.brand }}
            data-testid="hw-creds-save"
          >
            {credsBusy ? "Saving…" : "Save credentials"}
          </button>
          {credsMsg ? (
            <span className="text-xs" style={{ color: colors.muted }}
                   data-testid="hw-creds-msg">{credsMsg}</span>
          ) : null}
        </div>
      </div>

      {/* ── Batches list ─────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold" style={{ color: colors.onSurface }}>
          Import batches
        </h2>
        <button
          type="button"
          onClick={() => setNewModalOpen(true)}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md text-white"
          style={{ background: colors.brand }}
          data-testid="hw-new-batch-btn"
        >
          <Plus size={12} /> New import batch
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="hw-batches-loading">Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
              data-testid="hw-batches-error">{error}</div>
      ) : batches.length === 0 ? (
        <div className="rounded-lg p-6 text-sm text-center"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.muted }}
              data-testid="hw-batches-empty">
          No import batches yet. Click "New import batch" above to plan
          your first migration run.
        </div>
      ) : (
        <div className="rounded-lg overflow-hidden"
              style={{ background: "#fff",
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="hw-batches-table">
            <thead style={{ background: colors.surfaceSecondary }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Batch</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>State</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Entities</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Started</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>&nbsp;</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} data-testid={`hw-batch-row-${b.id}`}>
                  <td className="px-3 py-2 font-mono text-[10px]"
                      style={{ color: colors.muted }}>
                    {b.id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2">
                    <StatePill state={b.state} id={b.id} />
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                    {(b.entity_types_planned || []).length} planned
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>
                    {b.started_at ? b.started_at.slice(0, 16) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => openDetail(b)}
                      title="View dry-run + progress"
                      className="inline-flex items-center gap-0.5 text-[11px] font-bold mr-3"
                      style={{ color: colors.brand, textDecoration: "underline" }}
                      data-testid={`hw-batch-view-${b.id}`}
                    >
                      <Eye size={11} /> View
                    </button>
                    {b.state !== "rolled_back" ? (
                      <button
                        type="button"
                        onClick={() => setRollbackTarget(b)}
                        title="Rollback"
                        className="inline-flex items-center gap-0.5 text-[11px] font-bold"
                        style={{ color: "#DC2626", textDecoration: "underline" }}
                        data-testid={`hw-batch-rollback-${b.id}`}
                      >
                        <RotateCcw size={11} /> Rollback
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── New batch modal ──────────────────────────────────── */}
      {newModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget)
                                    setNewModalOpen(false); }}
          data-testid="hw-new-batch-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white"
            style={{ border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}>
              Plan an import batch
            </h2>
            <p className="text-xs mb-3" style={{ color: colors.muted }}>
              Select which entity types this batch will pull from Copilot
              CRM. All 8 are selected by default.
            </p>
            <div className="space-y-1 mb-4">
              {ALL_ENTITY_TYPES.map((t) => (
                <label key={t}
                        className="flex items-center gap-2 text-sm cursor-pointer"
                        style={{ color: colors.onSurface }}>
                  <input
                    type="checkbox"
                    checked={newSelected.has(t)}
                    onChange={() => toggleEntity(t)}
                    data-testid={`hw-new-batch-entity-${t}`}
                    className="cursor-pointer"
                  />
                  {t.replace(/_/g, " ")}
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setNewModalOpen(false)}
                disabled={newBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-slate-100"
                data-testid="hw-new-batch-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={createBatch}
                disabled={newBusy || newSelected.size === 0}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ background: colors.brand }}
                data-testid="hw-new-batch-submit"
              >
                {newBusy ? "Creating…" : "Create batch"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ── Rollback confirmation ─────────────────────────────── */}
      {rollbackTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget && !rollbackBusy)
                                    setRollbackTarget(null); }}
          data-testid="hw-rollback-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white"
            style={{ border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}>
              Rollback batch {rollbackTarget.id.slice(0, 8)}?
            </h2>
            {(() => {
              const counts = rollbackTarget?.entity_counts_completed || {};
              const totalRows = Object.values(counts).reduce(
                (a, n) => a + (Number(n) || 0), 0);
              const collectionsTouched = Object.keys(counts).filter(
                (k) => (Number(counts[k]) || 0) > 0).length;
              // Phase 55-e — surface photo count separately so the
              // operator knows blobs will leave storage too (not
              // just DB rows).
              const photoCount = Number(counts.photos || 0);
              return (
                <p className="text-sm mb-4" style={{ color: colors.muted }}
                    data-testid="hw-rollback-warning">
                  This will delete {totalRows} imported record
                  {totalRows === 1 ? "" : "s"} across {collectionsTouched}
                  {" "}collection{collectionsTouched === 1 ? "" : "s"}
                  {photoCount > 0 ? (
                    <>
                      {", including "}
                      <strong data-testid="hw-rollback-photo-count">
                        {photoCount} photo{photoCount === 1 ? "" : "s"}
                      </strong>
                      {" from storage"}
                    </>
                  ) : null}
                  . Idempotent — safe to run twice.
                </p>
              );
            })()}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRollbackTarget(null)}
                disabled={rollbackBusy}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-slate-100"
                data-testid="hw-rollback-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doRollback}
                disabled={rollbackBusy}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ background: "#DC2626" }}
                data-testid="hw-rollback-confirm-btn"
              >
                {rollbackBusy ? "Rolling back…" : "Confirm rollback"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ── Batch detail drawer (Phase 55-f) ─────────────────── */}
      {detailTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget && !commitBusy)
                                    closeDetail(); }}
          data-testid="hw-detail-drawer"
        >
          <div
            className="w-full max-w-2xl rounded-2xl p-6 shadow-2xl bg-white max-h-[85vh] overflow-y-auto"
            style={{ border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold"
                    style={{ color: colors.onSurface }}>
                  Batch {detailTarget.id.slice(0, 8)} · Dry-run report
                </h2>
                <div className="text-xs mt-1" style={{ color: colors.muted }}>
                  State:{" "}
                  <StatePill
                    state={(progress?.state) || detailTarget.state}
                    id={`detail-${detailTarget.id}`}
                  />
                </div>
              </div>
              <button
                type="button"
                onClick={closeDetail}
                disabled={commitBusy}
                className="text-xs font-bold px-2 py-1 rounded-md bg-slate-100"
                data-testid="hw-detail-close"
              >
                Close
              </button>
            </div>

            {detailBusy && !detailReport ? (
              <div className="text-sm py-6 text-center"
                    style={{ color: colors.muted }}
                    data-testid="hw-detail-loading">
                Loading dry-run…
              </div>
            ) : detailReport ? (
              <>
                <table className="w-full text-xs mb-4 rounded overflow-hidden"
                        style={{ border: `1px solid ${colors.border}` }}
                        data-testid="hw-detail-dryrun-table">
                  <thead style={{ background: colors.surfaceSecondary }}>
                    <tr>
                      <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Entity</th>
                      <th className="text-right px-3 py-2" style={{ color: colors.muted }}>New</th>
                      <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Matched</th>
                      <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Conflict</th>
                      <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detailReport.entity_counts || {}).map(
                      ([et, c]) => (
                        <tr key={et}
                             data-testid={`hw-detail-row-${et}`}>
                          <td className="px-3 py-2 font-semibold"
                              style={{ color: colors.onSurface }}>{et}</td>
                          <td className="px-3 py-2 text-right"
                              style={{ color: colors.onSurface }}>{c.new || 0}</td>
                          <td className="px-3 py-2 text-right"
                              style={{ color: colors.onSurface }}>{c.matched || 0}</td>
                          <td className="px-3 py-2 text-right"
                              style={{ color: c.conflict ? "#DC2626" : colors.onSurface }}>
                            {c.conflict || 0}
                          </td>
                          <td className="px-3 py-2 text-right font-bold"
                              style={{ color: colors.onSurface }}>{c.total || 0}</td>
                        </tr>
                      ),
                    )}
                    {Object.keys(detailReport.entity_counts || {}).length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-3 py-4 text-center"
                             style={{ color: colors.muted }}
                             data-testid="hw-detail-empty">
                          No staging rows yet. Run the Copilot CRM scraper first.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>

                {progress ? (
                  <div className="rounded-md p-3 text-xs mb-4"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface }}
                        data-testid="hw-detail-progress">
                    <div className="font-bold mb-1">Progress</div>
                    {Object.entries(progress.entity_counts_completed || {})
                      .length === 0 ? (
                      <div style={{ color: colors.muted }}>Not yet started.</div>
                    ) : (
                      Object.entries(progress.entity_counts_completed || {}).map(
                        ([et, done]) => {
                          const total = (detailReport.entity_counts?.[et]?.total) ?? 0;
                          return (
                            <div key={et}
                                  className="flex justify-between py-0.5"
                                  data-testid={`hw-progress-row-${et}`}>
                              <span>{et}</span>
                              <span>{done} / {total || "?"}</span>
                            </div>
                          );
                        })
                    )}
                    {progress.error_count > 0 ? (
                      <div className="mt-2 font-bold"
                            style={{ color: "#DC2626" }}
                            data-testid="hw-progress-errors">
                        {progress.error_count} error
                        {progress.error_count === 1 ? "" : "s"} during commit —
                        Resume to retry unprocessed rows.
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {(detailReport.warnings || []).length > 0 ? (
                  <div className="rounded-md p-3 text-xs mb-4"
                        style={{ background: "#FEF3C7",
                                  color: "#92400E" }}
                        data-testid="hw-detail-warnings">
                    <div className="font-bold mb-1">
                      {detailReport.warnings.length} warning
                      {detailReport.warnings.length === 1 ? "" : "s"}
                    </div>
                    {detailReport.warnings.slice(0, 5).map((w, i) => (
                      <div key={i}>
                        [{w.entity_type}] {w.error}
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}

            {/* Commit / Resume / Scrape CTA */}
            {(() => {
              const state = progress?.state || detailReport?.state
                             || detailTarget.state;
              const canCommit = state === "paused";
              const canResume = state === "committed"
                                 && (progress?.error_count || 0) > 0;
              const canScrape = state === "pending"
                                 || state === "paused_challenge";
              if (!canCommit && !canResume && !canScrape) return null;
              return (
                <div className="flex justify-end gap-2 pt-2 border-t"
                      style={{ borderColor: colors.border }}>
                  {canScrape ? (
                    <button
                      type="button"
                      onClick={doScrape}
                      disabled={scrapeBusy}
                      className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                      style={{ background: "#7C3AED" }}
                      data-testid="hw-scrape-btn"
                    >
                      <Cloud size={12} />
                      {scrapeBusy ? "Scraping…"
                                    : state === "paused_challenge"
                                      ? "Retry after handoff"
                                      : "Scrape from Copilot CRM"}
                    </button>
                  ) : null}
                  {(canCommit || canResume) ? (
                    <button
                      type="button"
                      onClick={doCommit}
                      disabled={commitBusy}
                      className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                      style={{ background: colors.brand }}
                      data-testid={canResume ? "hw-resume-btn"
                                                : "hw-commit-btn"}
                    >
                      <Play size={12} />
                      {commitBusy ? "Committing…"
                                  : canResume ? "Resume commit"
                                                : "Commit batch"}
                    </button>
                  ) : null}
                </div>
              );
            })()}
          </div>
        </div>
      ) : null}

      {/* ── Challenge handoff modal (Phase 55-b · Copilot CRM) ── */}
      {challengeInfo ? (
        <ChallengeHandoffModal
          slug={challengeInfo.slug || "homeworks"}
          displayName="Homeworks (Copilot CRM)"
          loginUrl="https://secure.copilotcrm.com/login"
          onClose={() => setChallengeInfo(null)}
          onRetry={() => {
            setChallengeInfo(null);
            if (detailTarget) doScrape();
          }}
        />
      ) : null}
    </div>
  );
}
