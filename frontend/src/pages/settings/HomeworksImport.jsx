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
import React, { useCallback, useEffect, useState } from "react";
import { Download, Plus, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";


const ALL_ENTITY_TYPES = [
  "customers", "properties", "jobs", "recurring_schedules",
  "invoices", "payments", "quotes", "attachments",
];

const STATE_PALETTE = {
  pending:      { bg: "#F1F5F9", fg: "#475569" },
  running:      { bg: "#DBEAFE", fg: "#1E40AF" },
  paused:       { bg: "#FEF3C7", fg: "#92400E" },
  committed:    { bg: "#DCFCE7", fg: "#166534" },
  rolled_back:  { bg: "#E5E7EB", fg: "#6B7280" },
  failed:       { bg: "#FEE2E2", fg: "#991B1B" },
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
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              Every row inserted under this batch will be permanently
              deleted. This action is idempotent — safe to run twice.
            </p>
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
    </div>
  );
}
