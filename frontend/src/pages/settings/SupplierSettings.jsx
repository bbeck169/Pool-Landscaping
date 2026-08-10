/**
 * Phase 54b · Feb-2026 — Wholesale Supplier Settings.
 *
 * Per-supplier cards. Pool360 is fully wired in this phase; the four
 * other suppliers (SiteOne / Ewing / Heritage / ePoolSupply) render
 * a "Coming in 54c/d/e" placeholder card.
 *
 * Role gate — mirrors the backend router:
 *   * super_admin / admin  → edit + sync
 *   * manager              → read-only (form disabled, no action btns)
 *   * technician / customer → redirected out (App.js route wrapper)
 *
 * The legal disclaimer under the credentials form is intentionally
 * literal — see the Phase 54b spec. Do not rephrase it.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Save, RefreshCw, PlayCircle, Trash2, CheckCircle2,
  AlertTriangle, Clock, ShieldAlert, PlugZap,
} from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { toast } from "sonner";
import { SUPPLIER_METADATA, WIRED_SLUGS, HANDOFF_SLUGS } from "./supplier_metadata";
import ChallengeHandoffModal from "@/components/suppliers/ChallengeHandoffModal";
import SessionStatusPill from "@/components/suppliers/SessionStatusPill";

const LEGAL_DISCLAIMER =
  "Automated syncing may be subject to your wholesaler's Terms of Service. " +
  "By connecting, you acknowledge responsibility for compliance with those terms.";

const TEST_CONN_ERROR_COPY = {
  login_failed: "Login failed — check the username and password.",
  rate_limited: "Rate-limited by the wholesaler. Wait a minute and try again.",
  timeout:      "Connection timed out (>15 s). The wholesaler may be slow — try again.",
  unknown:      "Connection failed for an unknown reason. See server logs for details.",
};

function formatDT(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); }
  catch { return iso; }
}

function StatusPill({ status }) {
  const map = {
    success:  { bg: "#DCFCE7", fg: colors.success, label: "Success" },
    running:  { bg: colors.brandTertiary, fg: colors.onBrandTertiary, label: "Running" },
    error:    { bg: "#FEE2E2", fg: colors.error, label: "Error" },
  };
  const m = map[status] || { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary, label: status || "—" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: m.bg, color: m.fg }}
      data-testid={`sync-job-status-${status || "unknown"}`}
    >
      {m.label}
    </span>
  );
}

function ComingSoonCard({ supplier }) {
  const meta = SUPPLIER_METADATA[supplier.slug] || {};
  const label = meta.coming_in
    ? `Coming in Phase ${meta.coming_in}`
    : "Coming soon";
  return (
    <div
      className="rounded-xl p-5"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`supplier-card-${supplier.slug}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-base font-semibold" style={{ color: colors.onSurface }}>
            {meta.display_name || supplier.display_name}
          </div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            {label}
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
          data-testid={`supplier-status-${supplier.slug}`}
        >
          <Clock size={12} /> Not connected
        </span>
      </div>
    </div>
  );
}

function WiredSupplierCard({ supplier, readOnly }) {
  const meta = SUPPLIER_METADATA[supplier.slug] || {};
  const displayName = meta.display_name || supplier.display_name;
  const [creds, setCreds] = useState({ has_credentials: false, updated_at: null });
  const [form, setForm] = useState({ username: "", password: "" });
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, message}
  const [jobs, setJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(true);

  const refreshJobs = useCallback(async () => {
    setLoadingJobs(true);
    try {
      const r = await api.get(`/suppliers/${supplier.slug}/sync-jobs?limit=10`);
      setJobs(r.jobs || []);
    } catch (e) {
      toast.error(e.message || "Failed to load sync history");
    } finally {
      setLoadingJobs(false);
    }
  }, [supplier.slug]);

  const refreshCreds = useCallback(async () => {
    try {
      const r = await api.get(`/suppliers/${supplier.slug}/credentials`);
      setCreds(r);
    } catch (e) {
      toast.error(e.message || "Failed to load credentials status");
    }
  }, [supplier.slug]);

  useEffect(() => { refreshCreds(); refreshJobs(); }, [refreshCreds, refreshJobs]);

  const [syncFreq, setSyncFreq] = useState(supplier.sync_frequency || "daily");
  useEffect(() => {
    setSyncFreq(supplier.sync_frequency || "daily");
  }, [supplier.sync_frequency]);
  const patchFrequency = async (next) => {
    if (readOnly) return;
    const prev = syncFreq;
    setSyncFreq(next); // optimistic
    try {
      await api.patch(`/suppliers/${supplier.slug}`, { sync_frequency: next });
      toast.success(`Sync frequency updated to ${next}.`);
    } catch (e) {
      setSyncFreq(prev);
      toast.error(e.message || "Failed to update sync frequency");
    }
  };

  const saveCreds = async () => {
    if (readOnly) return;
    if (!form.username || !form.password) {
      toast.error("Username and password are required.");
      return;
    }
    setSaving(true);
    try {
      await api.post(`/suppliers/${supplier.slug}/credentials`, {
        username: form.username, password: form.password,
      });
      setForm({ username: "", password: "" });
      await refreshCreds();
      toast.success("Credentials saved (encrypted at rest).");
    } catch (e) {
      toast.error(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const deleteCreds = async () => {
    if (readOnly) return;
    if (!window.confirm(meta.delete_confirm_text
        || `Remove saved ${displayName} credentials? Syncs will stop working until new credentials are provided.`)) return;
    try {
      await api.delete(`/suppliers/${supplier.slug}/credentials`);
      await refreshCreds();
      toast.success("Credentials removed.");
    } catch (e) {
      toast.error(e.message || "Delete failed");
    }
  };

  const runSync = async () => {
    if (readOnly) return;
    setSyncing(true);
    try {
      const r = await api.post(`/suppliers/${supplier.slug}/sync`, {});
      toast.success(`Sync started (job ${String(r.job_id || "").slice(0, 8)}…). Refreshing history in a few seconds.`);
      // Poll the job list once after a short delay so the operator
      // sees status transition without a manual refresh.
      setTimeout(refreshJobs, 3500);
    } catch (e) {
      const msg = e?.data?.detail?.message
        || (typeof e?.data?.detail === "string" ? e.data.detail : "")
        || e.message
        || "Sync failed to start";
      toast.error(msg);
    } finally {
      setSyncing(false);
    }
  };

  const runTest = async () => {
    if (readOnly) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.post(`/suppliers/${supplier.slug}/test-connection`, {});
      if (r.ok) {
        setTestResult({ ok: true, message: "Connection OK." });
        toast.success("Connection OK.");
      } else if (r.challenge_required) {
        // Phase 54h-b · Aug-2026 — Turnstile handoff flow. Open the
        // modal so the operator can solve in their own browser + POST
        // cookies back via bookmarklet or DevTools paste.
        setChallengeOpen(true);
        setTestResult({ ok: false,
                         message: "Challenge required — see modal." });
      } else {
        const copy = TEST_CONN_ERROR_COPY[r.error] || `Connection failed (${r.error}).`;
        setTestResult({ ok: false, message: copy });
        toast.error(copy);
      }
    } catch (e) {
      const msg = e?.data?.detail?.message
        || (typeof e?.data?.detail === "string" ? e.data.detail : "")
        || e.message
        || "Test failed";
      setTestResult({ ok: false, message: msg });
      toast.error(msg);
    } finally {
      setTesting(false);
    }
  };
  const [challengeOpen, setChallengeOpen] = useState(false);

  return (
    <div
      className="rounded-xl p-5"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`supplier-card-${supplier.slug}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-base font-semibold" style={{ color: colors.onSurface }}>
            {displayName}
          </div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            {meta.tagline || "Wholesale pricebook sync."}
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium"
          style={{
            backgroundColor: creds.has_credentials ? "#DCFCE7" : colors.surfaceSecondary,
            color: creds.has_credentials ? colors.success : colors.onSurfaceSecondary,
          }}
          data-testid={`supplier-status-${supplier.slug}`}
        >
          {creds.has_credentials
            ? (<><CheckCircle2 size={12} /> Connected</>)
            : (<><ShieldAlert size={12} /> Not connected</>)}
        </span>
      </div>

      {/* Credentials form */}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs" style={{ color: colors.muted }}>
            {meta.username_label || `${displayName} username`}
          </span>
          <input
            type="text"
            autoComplete="off"
            value={form.username}
            disabled={readOnly}
            onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
            placeholder={creds.has_credentials
              ? "•••••• (saved)"
              : (meta.username_placeholder || `your-${supplier.slug}-username`)}
            className="mt-1 w-full px-3 py-2 rounded-lg text-sm disabled:opacity-60"
            style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
            data-testid={`supplier-${supplier.slug}-username-input`}
          />
        </label>
        <label className="block">
          <span className="text-xs" style={{ color: colors.muted }}>
            {meta.password_label || "Password"}
          </span>
          <input
            type="password"
            autoComplete="new-password"
            value={form.password}
            disabled={readOnly}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            placeholder={creds.has_credentials
              ? "•••••• (saved)"
              : (meta.password_placeholder || `your-${supplier.slug}-password`)}
            className="mt-1 w-full px-3 py-2 rounded-lg text-sm disabled:opacity-60"
            style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
            data-testid={`supplier-${supplier.slug}-password-input`}
          />
        </label>
      </div>

      {/* Legal disclaimer — literal per Phase 54b spec */}
      <p
        className="text-xs mt-3"
        style={{ color: colors.muted }}
        data-testid={`supplier-${supplier.slug}-legal-disclaimer`}
      >
        {LEGAL_DISCLAIMER}
      </p>

      {/* Actions */}
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 mt-4">
          <button
            onClick={saveCreds}
            disabled={saving || !form.username || !form.password}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: colors.brandPrimary, color: colors.onBrandPrimary }}
            data-testid={`supplier-${supplier.slug}-save-btn`}
          >
            <Save size={14} />
            {saving ? "Saving…" : "Save credentials"}
          </button>

          <button
            onClick={runSync}
            disabled={syncing || !creds.has_credentials}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: colors.brandSecondary, color: colors.onSurfaceInverse }}
            data-testid={`supplier-${supplier.slug}-sync-btn`}
          >
            <PlayCircle size={14} />
            {syncing ? "Starting…" : "Sync now"}
          </button>

          <button
            onClick={runTest}
            disabled={testing || !creds.has_credentials}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid={`supplier-${supplier.slug}-test-connection-btn`}
            title={`Slug: ${supplier.slug}`}
          >
            <PlugZap size={14} />
            {testing ? "Testing…" : `Test connection · ${displayName}`}
          </button>

          {/* Phase 54h-d · Aug-2026 — Turnstile session status pill.
              Silent for non-opt-in suppliers (Ewing / ePoolSupply) —
              they never cache sessions. */}
          {HANDOFF_SLUGS.has(supplier.slug) ? (
            <SessionStatusPill
              slug={supplier.slug}
              displayName={displayName}
              canManage={!readOnly}
              onRetry={runTest}
            />
          ) : null}

          {/* Aug-2026 · UX cleanup — surface the raw slug in a small
              monospace hint next to the button so an admin can
              correlate the "Pool360" display name to the "poolcorp"
              slug that shows up in backend logs. */}
          <code
            className="text-[10px] font-mono px-1.5 py-0.5 rounded"
            style={{ backgroundColor: colors.surfaceAlt,
                      color: colors.muted,
                      border: `1px solid ${colors.border}` }}
            data-testid={`supplier-${supplier.slug}-slug-hint`}
          >
            {supplier.slug}
          </code>

          {testResult && (
            <span
              className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs"
              style={{
                backgroundColor: testResult.ok ? "#DCFCE7" : "#FEE2E2",
                color: testResult.ok ? colors.success : colors.error,
              }}
              data-testid={`supplier-${supplier.slug}-test-result`}
            >
              {testResult.ok
                ? <><CheckCircle2 size={12} /> Connected</>
                : <><AlertTriangle size={12} /> {testResult.message}</>}
            </span>
          )}

          <button
            onClick={refreshJobs}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid={`supplier-${supplier.slug}-refresh-history-btn`}
          >
            <RefreshCw size={14} />
            Refresh history
          </button>

          {creds.has_credentials && (
            <button
              onClick={deleteCreds}
              className="ml-auto inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
              style={{ border: `1px solid ${colors.border}`, color: colors.error }}
              data-testid={`supplier-${supplier.slug}-delete-btn`}
            >
              <Trash2 size={14} />
              Remove
            </button>
          )}
        </div>
      )}

      {readOnly && (
        <div
          className="mt-4 flex items-center gap-2 px-3 py-2 rounded-lg text-xs"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
          data-testid={`supplier-${supplier.slug}-readonly-notice`}
        >
          <AlertTriangle size={14} />
          Read-only. Ask an admin to change wholesaler credentials or trigger a sync.
        </div>
      )}

      {/* Sync frequency (Phase 54e) */}
      <div className="mt-5 flex items-center gap-3">
        <span className="text-xs" style={{ color: colors.muted }}>
          Sync frequency
        </span>
        <select
          value={syncFreq}
          disabled={readOnly}
          onChange={(e) => patchFrequency(e.target.value)}
          className="px-2 py-1 rounded-md text-sm disabled:opacity-60"
          style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
          data-testid={`supplier-${supplier.slug}-sync-frequency-select`}
        >
          <option value="hourly">Hourly</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly (Sundays)</option>
          <option value="manual">Manual only</option>
        </select>
        <span className="text-xs" style={{ color: colors.muted }}>
          Cron runs at 03:00 UTC unless overridden.
        </span>
      </div>

      {/* Sync history */}
      <div className="mt-6">
        <div className="text-sm font-medium mb-2" style={{ color: colors.onSurface }}>
          Recent syncs
        </div>
        <div
          className="rounded-lg overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
          data-testid={`supplier-${supplier.slug}-history-table`}
        >
          {loadingJobs ? (
            <div className="p-4 text-sm" style={{ color: colors.muted }}>
              Loading history…
            </div>
          ) : jobs.length === 0 ? (
            <div className="p-4 text-sm" style={{ color: colors.muted }}
                 data-testid={`supplier-${supplier.slug}-history-empty`}>
              No syncs yet.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead style={{ backgroundColor: colors.surfaceSecondary }}>
                <tr>
                  <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Started</th>
                  <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Status</th>
                  <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Added</th>
                  <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Updated</th>
                  <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Removed</th>
                  <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Error</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} style={{ borderTop: `1px solid ${colors.border}` }}
                      data-testid={`supplier-${supplier.slug}-history-row-${j.id}`}>
                    <td className="px-3 py-2 whitespace-nowrap">{formatDT(j.started_at)}</td>
                    <td className="px-3 py-2"><StatusPill status={j.status} /></td>
                    <td className="px-3 py-2 text-right">{j.items_added || 0}</td>
                    <td className="px-3 py-2 text-right">{j.items_updated || 0}</td>
                    <td className="px-3 py-2 text-right">{j.items_removed || 0}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: colors.error }}>
                      {j.error_message || ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {creds.updated_at && (
          <div className="mt-2 text-xs" style={{ color: colors.muted }}
               data-testid={`supplier-${supplier.slug}-creds-updated-at`}>
            Credentials last updated {formatDT(creds.updated_at)}
          </div>
        )}
      </div>
      {/* Phase 54h-b · Aug-2026 — Turnstile handoff modal. Opens
          when ``runTest`` sees ``challenge_required: true`` on the
          test-connection response. */}
      {challengeOpen ? (
        <ChallengeHandoffModal
          slug={supplier.slug}
          displayName={displayName}
          loginUrl={meta.login_url}
          onClose={() => setChallengeOpen(false)}
          onRetry={() => { setChallengeOpen(false); runTest(); }}
        />
      ) : null}
    </div>
  );
}

export default function SupplierSettings() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const role = user?.role || "";
  const readOnly = role === "manager";
  const isSuperAdmin = role === "super_admin";

  // Phase 54f · Feb-2026 — "Sync all suppliers" state (super_admin only).
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncAllProgress, setSyncAllProgress] = useState(null);
  //   {current: 2, total: 5, label: "SiteOne"} or null

  useEffect(() => {
    api.get("/suppliers")
      .then((rows) => { setSuppliers(rows || []); setLoading(false); })
      .catch((e) => { setError(e.message || "Failed to load suppliers"); setLoading(false); });
  }, []);

  const wiredSuppliers = suppliers.filter(
    (s) => !SUPPLIER_METADATA[s.slug]?.coming_in);

  const syncAll = async () => {
    if (!isSuperAdmin) return;
    setSyncingAll(true);
    let ok = 0, skipped = 0;
    try {
      for (let i = 0; i < wiredSuppliers.length; i++) {
        const s = wiredSuppliers[i];
        setSyncAllProgress({
          current: i + 1, total: wiredSuppliers.length,
          label: SUPPLIER_METADATA[s.slug]?.display_name || s.slug,
        });
        try {
          await api.post(`/suppliers/${s.slug}/sync`, {});
          ok += 1;
        } catch (e) {
          // 400 no_credentials is expected for un-configured suppliers.
          if (e?.data?.detail?.error === "no_credentials") {
            skipped += 1;
          } else {
            toast.error(`${s.slug}: ${e.message || "sync failed"}`);
          }
        }
      }
      toast.success(
        `Sync-all done — ${ok} launched, ${skipped} skipped (no creds).`);
    } finally {
      setSyncingAll(false);
      setSyncAllProgress(null);
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="supplier-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => nav(-1)}
          className="p-2 rounded-lg hover:brightness-95"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="supplier-settings-back-btn"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <div className="text-xl font-semibold" style={{ color: colors.onSurface }}>
            Wholesale suppliers
          </div>
          <div className="text-sm" style={{ color: colors.muted }}>
            Connect a wholesaler to import pricing into your pricebook.
          </div>
        </div>
        {isSuperAdmin && (
          <button
            onClick={syncAll}
            disabled={syncingAll || wiredSuppliers.length === 0}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: colors.brandPrimary, color: colors.onBrandPrimary }}
            data-testid="supplier-settings-sync-all-btn"
          >
            <PlayCircle size={14} />
            {syncingAll && syncAllProgress
              ? `Syncing ${syncAllProgress.current} of ${syncAllProgress.total} · ${syncAllProgress.label}…`
              : "Sync all suppliers"}
          </button>
        )}
      </div>

      {loading && (
        <div className="p-4 text-sm" style={{ color: colors.muted }}
             data-testid="supplier-settings-loading">
          Loading suppliers…
        </div>
      )}

      {error && !loading && (
        <div
          className="p-4 rounded-lg text-sm"
          style={{ backgroundColor: "#FEE2E2", color: colors.error }}
          data-testid="supplier-settings-error"
        >
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="grid gap-4">
          {suppliers.map((s) =>
            WIRED_SLUGS.has(s.slug)
              ? <WiredSupplierCard key={s.slug} supplier={s} readOnly={readOnly} />
              : <ComingSoonCard key={s.slug} supplier={s} />
          )}
        </div>
      )}
    </div>
  );
}
