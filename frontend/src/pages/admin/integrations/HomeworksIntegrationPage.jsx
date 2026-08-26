/**
 * Phase 0 POC · Feb-2026 — Homeworks (home.works MCP) BYO-creds page.
 *
 * Route: /admin/integrations/homeworks  (super_admin only)
 *
 * Four cards:
 *   1. Credentials — user pastes OAuth client_id, secret, URLs, scopes.
 *   2. Connection  — status chip + Connect / Disconnect buttons.
 *   3. Smoke test  — tools/list + fetch_sample_customer (read-only).
 *   4. Status log  — last_error + last connected_at.
 *
 * Every interactive element carries a stable data-testid so the QA
 * agent can drive the UI without brittle selector chains.
 */
import React from "react";
import { toast } from "sonner";
import {
  ShieldCheck, Unplug, Link2, RefreshCw, AlertTriangle, Loader2, Info,
  Settings2, PlugZap, Zap,
} from "lucide-react";

import { api } from "@/api";

const API_ROOT = "/admin/integrations/homeworks";
const DEFAULT_MCP_URL = "https://www.home.works/connect/mcp";


function StatusChip({ status }) {
  const map = {
    connected:    { bg: "#DCFCE7", fg: "#166534", icon: <ShieldCheck size={13} /> },
    disconnected: { bg: "#F3F4F6", fg: "#374151", icon: <Unplug size={13} /> },
    error:        { bg: "#FEE2E2", fg: "#7F1D1D", icon: <AlertTriangle size={13} /> },
  };
  const cfg = map[status] || map.disconnected;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold"
      style={{ backgroundColor: cfg.bg, color: cfg.fg }}
      data-testid={`homeworks-status-${status || "disconnected"}`}
    >
      {cfg.icon} {String(status || "disconnected").replace(/^\w/, (c) => c.toUpperCase())}
    </span>
  );
}


export default function HomeworksIntegrationPage() {
  const [config, setConfig] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [connecting, setConnecting] = React.useState(false);
  const [disconnecting, setDisconnecting] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [testResult, setTestResult] = React.useState(null);
  const [confirmDisconnect, setConfirmDisconnect] = React.useState(false);

  // Local form state — populated once config loads.
  const [form, setForm] = React.useState({
    client_id: "",
    client_secret: "",  // blank means "keep existing"
    authorize_url: "",
    token_url: "",
    redirect_uri: "",
    scopes: "",  // one per line
    mcp_server_url: DEFAULT_MCP_URL,
  });

  const defaultRedirect = React.useMemo(() => {
    if (typeof window === "undefined") return "";
    return `${window.location.origin}/admin/integrations/homeworks/oauth/callback`;
  }, []);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const doc = await api.get(API_ROOT);
      setConfig(doc);
      setForm((prev) => ({
        ...prev,
        client_id: doc.client_id || "",
        client_secret: "",  // never populated from server
        authorize_url: doc.authorize_url || "",
        token_url: doc.token_url || "",
        redirect_uri: doc.redirect_uri || defaultRedirect,
        scopes: (doc.scopes || []).join("\n"),
        mcp_server_url: doc.mcp_server_url || DEFAULT_MCP_URL,
      }));
    } catch (e) {
      toast.error(e.message || "Failed to load Homeworks config");
    } finally {
      setLoading(false);
    }
  }, [defaultRedirect]);

  React.useEffect(() => { reload(); }, [reload]);

  const doSave = async () => {
    setSaving(true);
    try {
      const payload = {
        client_id: form.client_id.trim(),
        // Empty string means "keep existing" per backend contract.
        client_secret: form.client_secret,
        authorize_url: form.authorize_url.trim(),
        token_url: form.token_url.trim(),
        redirect_uri: form.redirect_uri.trim(),
        scopes: form.scopes.split("\n").map((s) => s.trim()).filter(Boolean),
        mcp_server_url: form.mcp_server_url.trim() || DEFAULT_MCP_URL,
      };
      const updated = await api.put(API_ROOT, payload);
      setConfig(updated);
      // Reset the secret field so the user sees "unchanged" for the
      // next save cycle.
      setForm((prev) => ({ ...prev, client_secret: "" }));
      toast.success("Credentials saved");
    } catch (e) {
      toast.error(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const doConnect = async () => {
    setConnecting(true);
    try {
      const r = await api.post(`${API_ROOT}/connect`, {});
      if (r?.authorize_url) {
        window.open(r.authorize_url, "_blank", "noopener");
        toast.success("Opened Homeworks authorize page in a new tab");
      } else {
        toast.error("No authorize URL returned");
      }
    } catch (e) {
      toast.error(e.message || "Connect failed — verify credentials first");
    } finally {
      setConnecting(false);
    }
  };

  const doDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.post(`${API_ROOT}/disconnect`, {});
      setTestResult(null);
      setConfirmDisconnect(false);
      toast.success("Homeworks disconnected");
      await reload();
    } catch (e) {
      toast.error(e.message || "Disconnect failed");
    } finally {
      setDisconnecting(false);
    }
  };

  const doSmokeTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.post(`${API_ROOT}/test`, {});
      setTestResult(r);
      toast.success(`Smoke test OK — ${(r.tools || []).length} tools`);
      await reload();
    } catch (e) {
      toast.error(e.message || "Smoke test failed");
      await reload();
    } finally {
      setTesting(false);
    }
  };

  const connected = config?.connection_status === "connected";

  return (
    <div
      className="p-4 md:p-8 max-w-5xl mx-auto space-y-4"
      data-testid="homeworks-integration-page"
    >
      <header className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
          style={{ background: "#0F172A", color: "#F8FAFC" }}
        >
          <PlugZap size={20} />
        </div>
        <div className="flex-1">
          <h1
            className="text-2xl font-bold text-slate-900"
            data-testid="homeworks-page-title"
          >
            Homeworks (home.works) MCP · Phase 0 POC
          </h1>
          <p className="text-sm text-slate-500">
            Bring-your-own OAuth credentials + MCP smoke test. No data is
            written to your CRM yet — this surface only verifies the
            handshake + read-only tool catalog.
          </p>
        </div>
        {config?.connection_status ? (
          <StatusChip status={config.connection_status} />
        ) : null}
      </header>

      {loading ? (
        <div
          className="rounded-xl border p-6 text-sm text-slate-500 flex items-center gap-2"
          data-testid="homeworks-loading"
        >
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : (
        <>
          {/* Card 1 · Credentials ───────────────────────────────── */}
          <section
            className="rounded-2xl border border-slate-200 bg-white p-5"
            data-testid="homeworks-card-credentials"
          >
            <div className="flex items-center gap-2 mb-3">
              <Settings2 size={16} className="text-slate-500" />
              <h2 className="font-bold text-slate-900">Credentials</h2>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              Paste values from your{" "}
              <a
                href="https://www.home.works/connect"
                target="_blank" rel="noreferrer"
                className="underline"
              >home.works/connect</a> dashboard. Secrets are Fernet-
              encrypted at rest and never returned to the browser.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Client ID" testId="homeworks-client-id"
                     value={form.client_id}
                     onChange={(v) => setForm((p) => ({ ...p, client_id: v }))}
                     placeholder="1a2b3c-abc-…" />
              <Field label="Client Secret" testId="homeworks-client-secret"
                     type="password" value={form.client_secret}
                     onChange={(v) => setForm((p) => ({ ...p, client_secret: v }))}
                     placeholder={config?.has_client_secret ? "•••• (leave blank to keep existing)" : "Paste the client secret"} />
              <Field label="Authorize URL" testId="homeworks-authorize-url"
                     value={form.authorize_url}
                     onChange={(v) => setForm((p) => ({ ...p, authorize_url: v }))}
                     placeholder="https://www.home.works/connect/oauth/authorize (verify in dashboard)" />
              <Field label="Token URL" testId="homeworks-token-url"
                     value={form.token_url}
                     onChange={(v) => setForm((p) => ({ ...p, token_url: v }))}
                     placeholder="https://www.home.works/connect/oauth/token (verify in dashboard)" />
              <Field label="Redirect URI" testId="homeworks-redirect-uri"
                     value={form.redirect_uri}
                     onChange={(v) => setForm((p) => ({ ...p, redirect_uri: v }))}
                     placeholder={defaultRedirect} />
              <Field label="MCP Server URL" testId="homeworks-mcp-url"
                     value={form.mcp_server_url}
                     onChange={(v) => setForm((p) => ({ ...p, mcp_server_url: v }))}
                     placeholder={DEFAULT_MCP_URL} />
              <div className="md:col-span-2">
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Scopes (one per line)
                </label>
                <textarea
                  rows={3}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-mono"
                  data-testid="homeworks-scopes"
                  value={form.scopes}
                  onChange={(e) => setForm((p) => ({ ...p, scopes: e.target.value }))}
                  placeholder={"read:customers\nread:jobs"}
                />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button" onClick={doSave} disabled={saving}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#0F172A" }}
                data-testid="homeworks-save"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                {saving ? "Saving…" : "Save credentials"}
              </button>
            </div>
          </section>

          {/* Card 2 · Connection ─────────────────────────────────── */}
          <section
            className="rounded-2xl border border-slate-200 bg-white p-5"
            data-testid="homeworks-card-connection"
          >
            <div className="flex items-center gap-2 mb-3">
              <Link2 size={16} className="text-slate-500" />
              <h2 className="font-bold text-slate-900">Connection</h2>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-slate-700">
                {connected ? (
                  <>
                    Connected{" "}
                    {config?.last_connected_at ? (
                      <span data-testid="homeworks-last-connected-at">
                        on {new Date(config.last_connected_at).toLocaleString()}
                      </span>
                    ) : null}
                    {config?.token_expires_at ? (
                      <span className="text-slate-500">
                        {" "}· access token expires{" "}
                        {new Date(config.token_expires_at).toLocaleString()}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <span data-testid="homeworks-connection-hint">
                    Not connected. Save credentials first, then click Connect.
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {!connected ? (
                  <button
                    type="button" onClick={doConnect} disabled={connecting}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                    style={{ backgroundColor: "#0F172A" }}
                    data-testid="homeworks-connect"
                  >
                    {connecting ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                    {connecting ? "Opening…" : "Connect Homeworks"}
                  </button>
                ) : (
                  <button
                    type="button" onClick={() => setConfirmDisconnect(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold border"
                    style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D", borderColor: "#FCA5A5" }}
                    data-testid="homeworks-disconnect"
                  >
                    <Unplug size={14} /> Disconnect
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Card 3 · Smoke test (only when connected) ────────────── */}
          {connected ? (
            <section
              className="rounded-2xl border border-slate-200 bg-white p-5"
              data-testid="homeworks-card-smoketest"
            >
              <div className="flex items-center gap-2 mb-3">
                <Zap size={16} className="text-slate-500" />
                <h2 className="font-bold text-slate-900">Smoke test</h2>
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Runs <code>tools/list</code> + a best-effort{" "}
                <code>list_customers</code> probe.{" "}
                <b>Read-only. No data written.</b>
              </p>
              <div className="flex items-center gap-2 mb-3">
                <button
                  type="button" onClick={doSmokeTest} disabled={testing}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60 border"
                  style={{ backgroundColor: "#F1F5F9", color: "#0F172A",
                             borderColor: "#CBD5E1" }}
                  data-testid="homeworks-smoketest"
                >
                  {testing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  {testing ? "Running…" : "Run smoke test"}
                </button>
              </div>
              {testResult ? (
                <div className="space-y-3" data-testid="homeworks-smoketest-result">
                  <div className="text-xs text-slate-500">
                    <b>Hint:</b>{" "}
                    <span data-testid="homeworks-smoketest-hint">
                      {testResult.hint || "n/a"}
                    </span>
                  </div>
                  <div>
                    <div className="text-xs font-bold text-slate-700 mb-1">
                      Tools ({(testResult.tools || []).length}):
                    </div>
                    <pre
                      className="text-[11px] rounded-md p-3 overflow-auto max-h-64"
                      style={{ backgroundColor: "#0F172A", color: "#E2E8F0" }}
                      data-testid="homeworks-smoketest-tools"
                    >
                      {JSON.stringify(testResult.tools || [], null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="text-xs font-bold text-slate-700 mb-1">
                      Sample customer:
                    </div>
                    <pre
                      className="text-[11px] rounded-md p-3 overflow-auto max-h-64"
                      style={{ backgroundColor: "#0F172A", color: "#E2E8F0" }}
                      data-testid="homeworks-smoketest-sample"
                    >
                      {JSON.stringify(testResult.sample_customer, null, 2)}
                    </pre>
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}

          {/* Card 4 · Status log ────────────────────────────────── */}
          <section
            className="rounded-2xl border border-slate-200 bg-white p-5"
            data-testid="homeworks-card-status"
          >
            <div className="flex items-center gap-2 mb-3">
              <Info size={16} className="text-slate-500" />
              <h2 className="font-bold text-slate-900">Status log</h2>
            </div>
            <div className="text-sm text-slate-700 space-y-1">
              <div>
                <b>Connection status:</b>{" "}
                <span data-testid="homeworks-status">
                  {config?.connection_status || "disconnected"}
                </span>
              </div>
              <div>
                <b>Last connected at:</b>{" "}
                {config?.last_connected_at
                  ? new Date(config.last_connected_at).toLocaleString()
                  : <span className="text-slate-400">never</span>}
              </div>
              {config?.last_error ? (
                <div
                  className="mt-2 rounded-lg p-3 flex items-start gap-2 text-sm"
                  style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D",
                             border: "1px solid #FCA5A5" }}
                  data-testid="homeworks-last-error"
                >
                  <AlertTriangle size={14} />
                  <div><b>Last error:</b> {config.last_error}</div>
                </div>
              ) : null}
            </div>
          </section>
        </>
      )}

      {confirmDisconnect ? (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={() => setConfirmDisconnect(false)}
          data-testid="homeworks-disconnect-modal"
        >
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl overflow-hidden bg-white border border-slate-200"
          >
            <div className="px-5 py-4">
              <h3 className="text-lg font-bold text-slate-900">
                Disconnect Homeworks?
              </h3>
              <p className="text-sm text-slate-500 mt-1">
                Your access + refresh tokens will be cleared. Client
                credentials stay saved — you can reconnect without
                re-typing them.
              </p>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50">
              <button
                type="button" onClick={() => setConfirmDisconnect(false)}
                className="px-3 py-2 rounded-lg text-sm font-semibold border border-slate-300 text-slate-700"
                data-testid="homeworks-disconnect-cancel"
              >Cancel</button>
              <button
                type="button" onClick={doDisconnect} disabled={disconnecting}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="homeworks-disconnect-confirm"
              >
                {disconnecting ? <Loader2 size={14} className="animate-spin" /> : <Unplug size={14} />}
                {disconnecting ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


function Field({ label, value, onChange, placeholder, type = "text", testId }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-slate-700 mb-1">
        {label}
      </label>
      <input
        type={type}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
    </div>
  );
}
