/**
 * Phase 26 · Feb-2026 — Supercool AI (Image + Video) integration page.
 *
 * Route: /settings/integrations/supercool  (super_admin only)
 *
 * Provides Connect / Disconnect / Refresh-catalog controls for the
 * Supercool MCP OAuth 2.1 integration. Tokens are handled backend-side
 * — this page only surfaces the connection status and drives the
 * browser through the OAuth handshake.
 */
import React from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Sparkles, Link2, Unplug, RefreshCw, ShieldCheck, AlertTriangle,
  ChevronDown, ChevronRight, Loader2, Info,
} from "lucide-react";

import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";


const SERVER_URL = "https://mcp.supercool.com/mcp";


export default function SupercoolIntegrationPage() {
  const [status, setStatus] = React.useState(null);
  const [catalog, setCatalog] = React.useState(null);
  const [connecting, setConnecting] = React.useState(false);
  const [disconnecting, setDisconnecting] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = React.useState(false);
  const [showCatalog, setShowCatalog] = React.useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadStatus = React.useCallback(async () => {
    try {
      const s = await api.get("/integrations/supercool/status");
      setStatus(s);
    } catch (e) {
      toast.error(`Could not load status: ${e.message || e}`);
    }
  }, []);

  const loadCatalog = React.useCallback(async () => {
    try {
      const c = await api.get("/integrations/supercool/catalog");
      setCatalog(c);
    } catch {
      setCatalog({ tools: [], fetched_at: null });
    }
  }, []);

  React.useEffect(() => { loadStatus(); loadCatalog(); }, [loadStatus, loadCatalog]);

  // Read callback query params exactly once, then strip them.
  React.useEffect(() => {
    if (searchParams.get("connected") === "1") {
      toast.success("Supercool connected!");
      const next = new URLSearchParams(searchParams);
      next.delete("connected");
      setSearchParams(next, { replace: true });
      loadStatus();
    } else if (searchParams.get("error")) {
      toast.error(`Supercool connection failed: ${searchParams.get("error")}`);
      const next = new URLSearchParams(searchParams);
      next.delete("error");
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doConnect = async () => {
    setConnecting(true);
    try {
      const r = await api.post("/integrations/supercool/connect", {});
      if (r?.authorize_url) {
        window.location.href = r.authorize_url;
      } else {
        toast.error("No authorize URL returned.");
      }
    } catch (e) {
      toast.error(e.message || "Connect failed");
    } finally {
      setConnecting(false);
    }
  };

  const doDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.post("/integrations/supercool/disconnect", {});
      toast.success("Supercool disconnected");
      setConfirmDisconnect(false);
      await loadStatus();
      await loadCatalog();
    } catch (e) {
      toast.error(e.message || "Disconnect failed");
    } finally {
      setDisconnecting(false);
    }
  };

  const doRefreshCatalog = async () => {
    setRefreshing(true);
    try {
      const r = await api.post("/integrations/supercool/refresh-catalog", {});
      setCatalog({ tools: r.tools || [], fetched_at: r.fetched_at });
      setShowCatalog(true);
      toast.success(`Catalog refreshed — ${r.tool_count} tools`);
      await loadStatus();
    } catch (e) {
      toast.error(e.message || "Catalog refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const connected = !!status?.connected;
  const connectedAt = status?.connected_at
    ? new Date(status.connected_at).toLocaleString()
    : null;
  const tools = catalog?.tools || [];

  return (
    <SafeScrollContainer
      className="p-4 md:p-8 max-w-4xl mx-auto space-y-4"
      data-testid="supercool-integration-page"
    >
      <header className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
          style={{ background: brandGradientCss, color: "#fff" }}
        >
          <Sparkles size={20} />
        </div>
        <div className="flex-1">
          <h1
            className="text-2xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="supercool-page-title"
          >
            Supercool AI · Image + Video Generation
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Model-agnostic MCP integration — generate images + videos inside
            your marketing flows without wiring individual model APIs.
          </p>
        </div>
      </header>

      {/* Status card */}
      <section
        className="rounded-2xl p-5"
        style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
        data-testid="supercool-status-card"
      >
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3">
            {connected ? (
              <span
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold"
                style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                data-testid="supercool-status-badge-connected"
              >
                <ShieldCheck size={13} /> Connected
              </span>
            ) : (
              <span
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold"
                style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D" }}
                data-testid="supercool-status-badge-disconnected"
              >
                <Unplug size={13} /> Not connected
              </span>
            )}
            <div className="text-sm" style={{ color: colors.onSurface }}>
              {connected ? (
                <>
                  Connected {connectedAt ? `on ${connectedAt}` : ""} ·{" "}
                  <span data-testid="supercool-tool-count">
                    {status?.tool_count || 0}
                  </span>{" "}
                  tools cached
                </>
              ) : (
                <span data-testid="supercool-status-hint">
                  Click <b>Connect Supercool</b> to authorize.
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {!connected ? (
              <button
                type="button" onClick={doConnect} disabled={connecting}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ background: brandGradientCss }}
                data-testid="supercool-connect-btn"
              >
                {connecting ? <Loader2 size={14} className="animate-spin" />
                                  : <Link2 size={14} />}
                {connecting ? "Redirecting…" : "Connect Supercool"}
              </button>
            ) : (
              <>
                <button
                  type="button" onClick={doRefreshCatalog} disabled={refreshing}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                  data-testid="supercool-refresh-catalog-btn"
                >
                  {refreshing ? <Loader2 size={14} className="animate-spin" />
                                    : <RefreshCw size={14} />}
                  {refreshing ? "Refreshing…" : "Refresh Tool Catalog"}
                </button>
                <button
                  type="button" onClick={() => setConfirmDisconnect(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D",
                             border: "1px solid #FCA5A5" }}
                  data-testid="supercool-disconnect-btn"
                >
                  <Unplug size={14} /> Disconnect
                </button>
              </>
            )}
          </div>
        </div>

        {status?.last_error ? (
          <div
            className="mt-3 rounded-lg p-3 flex items-start gap-2 text-sm"
            style={{ backgroundColor: "#FEE2E2", color: "#7F1D1D",
                       border: "1px solid #FCA5A5" }}
            data-testid="supercool-status-error"
          >
            <AlertTriangle size={14} />
            <div><b>Last error:</b> {status.last_error}</div>
          </div>
        ) : null}
      </section>

      {/* Info banner */}
      <section
        className="rounded-xl p-4 flex items-start gap-2"
        style={{ backgroundColor: "#EFF6FF", color: "#1E3A8A",
                   border: "1px solid #BFDBFE" }}
        data-testid="supercool-info-banner"
      >
        <Info size={16} className="mt-0.5" />
        <div className="text-sm">
          <b>How the OAuth handshake works:</b> when you click <i>Connect
          Supercool</i>, you'll be redirected to Supercool to authorize
          this workspace. Tokens are audience-bound, encrypted at rest
          with Fernet, and can be revoked anytime from your{" "}
          <a
            href="https://supercool.com/dashboard" target="_blank" rel="noreferrer"
            className="underline font-semibold"
          >Supercool dashboard</a>
          . MCP endpoint: <code>{SERVER_URL}</code>.
        </div>
      </section>

      {/* Catalog */}
      <section
        className="rounded-2xl"
        style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
        data-testid="supercool-catalog-card"
      >
        <button
          type="button" onClick={() => setShowCatalog((v) => !v)}
          className="w-full flex items-center justify-between px-5 py-3 text-left"
          data-testid="supercool-catalog-toggle"
        >
          <div className="flex items-center gap-2">
            {showCatalog ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <div className="font-bold" style={{ color: colors.onSurface }}>
              Cached tool catalog
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {tools.length} tools
              {catalog?.fetched_at
                ? ` · fetched ${new Date(catalog.fetched_at).toLocaleString()}`
                : ""}
            </div>
          </div>
        </button>
        {showCatalog ? (
          <div
            className="px-5 pb-5 space-y-3"
            data-testid="supercool-catalog-list"
          >
            {tools.length === 0 ? (
              <div className="text-sm" style={{ color: colors.muted }}
                    data-testid="supercool-catalog-empty">
                No cached tools yet. {connected
                  ? "Click Refresh Tool Catalog above."
                  : "Connect Supercool first."}
              </div>
            ) : (
              tools.map((t, i) => (
                <div key={`${t.name}-${i}`}
                      className="rounded-lg p-3"
                      style={{ border: `1px solid ${colors.border}`,
                                 backgroundColor: colors.surfaceSecondary }}
                      data-testid={`supercool-catalog-tool-${i}`}>
                  <div className="font-mono font-bold text-sm"
                        style={{ color: colors.onSurface }}>{t.name}</div>
                  {t.description ? (
                    <div className="text-xs mt-1" style={{ color: colors.muted }}>
                      {t.description}
                    </div>
                  ) : null}
                  {t.input_schema ? (
                    <pre
                      className="text-[11px] mt-2 rounded-md p-2 overflow-auto max-h-40"
                      style={{ backgroundColor: "#0F172A", color: "#E2E8F0" }}
                    >{JSON.stringify(t.input_schema, null, 2).slice(0, 1200)}</pre>
                  ) : null}
                </div>
              ))
            )}
          </div>
        ) : null}
      </section>

      {/* Disconnect confirm modal */}
      {confirmDisconnect ? (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={() => setConfirmDisconnect(false)}
          data-testid="supercool-disconnect-modal"
        >
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl overflow-hidden"
            style={{ backgroundColor: colors.surface,
                       border: `1px solid ${colors.border}` }}
          >
            <div className="px-5 py-4">
              <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                Disconnect Supercool?
              </h2>
              <p className="text-sm mt-1" style={{ color: colors.muted }}>
                Your access + refresh tokens will be cleared. You can
                reconnect anytime — the dynamic client registration is kept
                so re-authorizing is one click.
              </p>
            </div>
            <div
              className="px-5 py-3 flex items-center justify-end gap-2"
              style={{ borderTop: `1px solid ${colors.border}`,
                         backgroundColor: colors.surfaceSecondary }}
            >
              <button
                type="button" onClick={() => setConfirmDisconnect(false)}
                className="px-3 py-2 rounded-lg text-sm font-semibold"
                style={{ backgroundColor: colors.surface,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                data-testid="supercool-disconnect-cancel"
              >Cancel</button>
              <button
                type="button" onClick={doDisconnect} disabled={disconnecting}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="supercool-disconnect-confirm"
              >
                {disconnecting ? <Loader2 size={14} className="animate-spin" />
                                     : <Unplug size={14} />}
                {disconnecting ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </SafeScrollContainer>
  );
}
