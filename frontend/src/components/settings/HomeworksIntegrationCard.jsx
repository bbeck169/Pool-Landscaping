/**
 * Feb-2026 · Phase 1a — Homeworks (MCP) OAuth integration card.
 *
 * Lives on the Integrations Hub (``/settings/integrations``). Wraps the
 * three routes shipped in Phase 1a:
 *
 *   GET    /api/integrations/homeworks/status       — connected/not
 *   GET    /api/integrations/homeworks/oauth/start  — {authorize_url}
 *   DELETE /api/integrations/homeworks/disconnect
 *   POST   /api/integrations/homeworks/oauth/debug/refresh
 *
 * The MCP tools/list surface is Phase 1b — not part of this card yet.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";

const READ_USER = () => {
  try { return JSON.parse(localStorage.getItem("user") || "null"); }
  catch { return null; }
};

function _fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function HomeworksIntegrationCard() {
  const user = READ_USER();
  const isSuperAdmin = user?.role === "super_admin";
  const isAdminish = ["admin", "super_admin"].includes(user?.role);

  const [status, setStatus] = useState(null);   // null=loading, {} = data
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState(null);   // {kind, msg}

  // On mount / on ?homeworks=… query param → refresh status + surface a
  // one-shot banner (post-callback landing).
  useEffect(() => {
    const usp = new URLSearchParams(window.location.search);
    const hw = usp.get("homeworks");
    const reason = usp.get("reason");
    if (hw === "connected") {
      setBanner({ kind: "ok", msg: "Homeworks connected." });
    } else if (hw === "error") {
      setBanner({ kind: "err",
        msg: `Homeworks connect failed${reason ? ` (${reason})` : ""}.` });
    }
    if (hw) {
      // Drop the query param so a refresh doesn't re-fire the banner.
      usp.delete("homeworks"); usp.delete("reason");
      const nu = window.location.pathname
        + (usp.toString() ? `?${usp.toString()}` : "");
      window.history.replaceState({}, "", nu);
    }
    api.get("/integrations/homeworks/status")
      .then(setStatus)
      .catch(() => setStatus({ connected: false, _err: true }));
  }, []);

  const refresh = useCallback(async () => {
    setStatus(null);
    try {
      const s = await api.get("/integrations/homeworks/status");
      setStatus(s);
    } catch { setStatus({ connected: false, _err: true }); }
  }, []);

  const connect = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.get("/integrations/homeworks/oauth/start");
      if (r?.authorize_url) {
        window.location.assign(r.authorize_url);
      } else {
        setBanner({ kind: "err", msg: "Missing authorize URL from backend." });
        setBusy(false);
      }
    } catch (e) {
      setBanner({ kind: "err", msg: `Failed to start: ${e.message}` });
      setBusy(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    if (!window.confirm(
      "Disconnect Homeworks? The stored access + refresh tokens will "
      + "be deleted. You'll need to re-authorise via the browser to "
      + "reconnect."
    )) return;
    setBusy(true);
    try {
      await api.delete("/integrations/homeworks/disconnect");
      setBanner({ kind: "ok", msg: "Homeworks disconnected." });
      await refresh();
    } catch (e) {
      setBanner({ kind: "err", msg: `Disconnect failed: ${e.message}` });
    } finally { setBusy(false); }
  }, [refresh]);

  const debugRefresh = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.post("/integrations/homeworks/oauth/debug/refresh", {});
      setBanner({
        kind: "ok",
        msg: `Refreshed — new expiry ${_fmtDate(r?.expires_at)}`,
      });
      await refresh();
    } catch (e) {
      setBanner({ kind: "err", msg: `Refresh failed: ${e.message}` });
    } finally { setBusy(false); }
  }, [refresh]);

  if (!isAdminish) return null;

  const connected = !!status?.connected;
  const loading = status === null;

  return (
    <div
      className="rounded-2xl bg-white p-5"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid="homeworks-integration-card"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            Homeworks (via MCP) — Phase 1a
            <span
              className="text-xs font-bold px-2 py-0.5 rounded-full"
              style={{
                background: connected ? "#DCFCE7" : "#F1F5F9",
                color: connected ? "#166534" : "#475569",
              }}
              data-testid="homeworks-status-chip"
            >
              {loading ? "Loading…" : connected ? "Connected" : "Not connected"}
            </span>
          </h2>
          <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
            Phase 1a wires the OAuth 2.1 handshake (Authorization Code + PKCE) against{" "}
            <code>api.home.works</code>. Tools + resources ship in Phase 1b.
          </p>
        </div>
      </div>

      {banner ? (
        <div
          className="mt-3 rounded-xl p-3 text-sm"
          style={{
            backgroundColor: banner.kind === "ok" ? "#DCFCE7" : "#FEE2E2",
            color:           banner.kind === "ok" ? "#166534" : "#991B1B",
          }}
          data-testid={`homeworks-banner-${banner.kind}`}
        >
          {banner.msg}
        </div>
      ) : null}

      {connected ? (
        <div className="mt-4 space-y-2 text-sm" data-testid="homeworks-connected-body">
          <div><span style={{ color: colors.onSurfaceSecondary }}>Connected by:</span>{" "}
            <b>{status.connected_by_email || "(unknown)"}</b></div>
          <div><span style={{ color: colors.onSurfaceSecondary }}>Connected at:</span>{" "}
            {_fmtDate(status.connected_at)}</div>
          <div><span style={{ color: colors.onSurfaceSecondary }}>Access expires:</span>{" "}
            {_fmtDate(status.expires_at)}</div>
          <div><span style={{ color: colors.onSurfaceSecondary }}>Scope:</span>{" "}
            <code>{status.scope || ""}</code></div>
          <div className="flex items-center gap-2 pt-2 flex-wrap">
            <button
              type="button"
              onClick={disconnect}
              disabled={busy}
              className="px-3 py-1.5 rounded-lg text-sm font-bold"
              style={{
                background: "#FEE2E2", color: "#991B1B",
                border: "1px solid #FCA5A5",
                cursor: busy ? "not-allowed" : "pointer",
                opacity: busy ? 0.6 : 1,
              }}
              data-testid="homeworks-disconnect-btn"
            >
              Disconnect
            </button>
            {isSuperAdmin ? (
              <button
                type="button"
                onClick={debugRefresh}
                disabled={busy}
                className="px-3 py-1.5 rounded-lg text-sm font-bold"
                style={{
                  background: "#F1F5F9", color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                  cursor: busy ? "not-allowed" : "pointer",
                  opacity: busy ? 0.6 : 1,
                }}
                data-testid="homeworks-debug-refresh-btn"
              >
                Test refresh
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-2" data-testid="homeworks-disconnected-body">
          <button
            type="button"
            onClick={connect}
            disabled={busy || loading}
            className="px-3 py-2 rounded-lg text-sm font-bold text-white"
            style={{
              background: colors.brand,
              cursor: (busy || loading) ? "not-allowed" : "pointer",
              opacity: (busy || loading) ? 0.6 : 1,
            }}
            data-testid="homeworks-connect-btn"
          >
            Connect Homeworks
          </button>
          {status?._err ? (
            <span className="text-xs" style={{ color: "#991B1B" }}>
              Could not reach status endpoint.
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}
