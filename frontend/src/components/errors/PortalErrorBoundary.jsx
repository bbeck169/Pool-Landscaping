/**
 * K37 · Portal Error Boundary.
 *
 * Two mount sites (see `src/index.js` + `layouts/AppLayout.jsx`):
 *   - `label="app-root"`     — wraps `<App />` in `index.js`. Catches
 *                              the K13 impersonation preamble side-
 *                              effects and public deep-link routes.
 *   - `label="portal-shell"` — wraps `<APIProvider><AppLayout/>` in
 *                              `ProtectedShell` so an invalid Google
 *                              Maps key throws a scoped error card
 *                              instead of blanking the whole app.
 *
 * Modeled on `components/errors/DispatchErrorBoundary.jsx` — same
 * fallback vocabulary, same `/api/client-errors` sink, same testIDs
 * pattern. Kept dependency-light on purpose: no theme colors imported
 * except `colors` (already used across the app) so a broken theme
 * module doesn't cascade into the boundary render itself.
 *
 * `resetKey` prop: when it changes, the boundary clears its error
 * state. Callers inside a Router pass `resetKey={location.pathname}`
 * so navigating away and back doesn't leave the user stuck on a
 * stale error screen.
 */
import React from "react";
import { AlertTriangle, RefreshCw, Copy, Check } from "lucide-react";
import { colors } from "@/theme";

export default class PortalErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      error: null,
      info: null,
      copied: false,
      reported: false,
      errorAt: null,          // ISO string, used as the "Error ID" tag
      resetKey: props.resetKey ?? null,
    };
  }

  static getDerivedStateFromError(error) {
    return { error, errorAt: new Date().toISOString() };
  }

  static getDerivedStateFromProps(props, state) {
    // K37 · reset when the caller-supplied key changes (typically the
    // current route). Only meaningful when `resetKey` is provided.
    if (
      state.error &&
      props.resetKey !== undefined &&
      props.resetKey !== state.resetKey
    ) {
      return {
        error: null,
        info: null,
        copied: false,
        reported: false,
        errorAt: null,
        resetKey: props.resetKey,
      };
    }
    if (props.resetKey !== state.resetKey) {
      return { resetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Fire-and-forget report. `keepalive: true` lets the browser
    // flush the POST even if the tab is unloading right after the
    // throw. Bypass the app's `api.js` client so a broken axios/api
    // module can't re-throw inside a component that just threw.
    try {
      const backend = process.env.REACT_APP_BACKEND_URL || "";
      const token = (() => {
        try { return localStorage.getItem("token") || ""; } catch { return ""; }
      })();
      const tenantSlug = (() => {
        try { return localStorage.getItem("tenant_slug") || ""; } catch { return ""; }
      })();
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      if (tenantSlug) headers["X-Tenant-Slug"] = tenantSlug;
      const route = (() => {
        try { return window.location.pathname + (window.location.search || ""); }
        catch { return null; }
      })();
      fetch(`${backend}/api/client-errors`, {
        method: "POST",
        headers,
        keepalive: true,
        body: JSON.stringify({
          message: (error && (error.message || String(error))) || "Unknown error",
          stack: (error && error.stack) || null,
          url: typeof window !== "undefined" ? window.location.href : null,
          user_agent: typeof navigator !== "undefined" ? navigator.userAgent : null,
          component: "Portal",
          platform: "web",
          route,
          extra: {
            label: this.props.label || "portal",
            componentStack: info && info.componentStack
              ? String(info.componentStack).slice(0, 4000)
              : null,
            timestamp: this.state.errorAt || new Date().toISOString(),
          },
        }),
      }).then(() => {
        this.setState({ reported: true });
      }).catch(() => { /* swallow — never rethrow from telemetry */ });
    } catch { /* swallow — telemetry must never re-throw */ }
  }

  onCopy = async () => {
    const { error, info, errorAt } = this.state;
    const parts = [
      `Message: ${(error && (error.message || String(error))) || ""}`,
      `Error ID: ${errorAt || ""}`,
      `Route: ${typeof window !== "undefined" ? window.location.pathname : ""}`,
      `URL: ${typeof window !== "undefined" ? window.location.href : ""}`,
      `User-Agent: ${typeof navigator !== "undefined" ? navigator.userAgent : ""}`,
      `Stack:\n${(error && error.stack) || ""}`,
      `ComponentStack:\n${(info && info.componentStack) || ""}`,
    ];
    const payload = parts.join("\n\n");
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(payload);
      } else {
        // Fallback for older browsers / restrictive contexts.
        const ta = document.createElement("textarea");
        ta.value = payload;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      this.setState({ copied: true });
      setTimeout(() => this.setState({ copied: false }), 1500);
    } catch { /* swallow */ }
  };

  onReload = () => {
    if (typeof window !== "undefined") window.location.reload();
  };

  render() {
    const { error, copied, reported, errorAt } = this.state;
    if (!error) return this.props.children;

    const msg = (error && (error.message || String(error))) || "Unknown error";
    const truncated = msg.length > 200 ? msg.slice(0, 200) + "…" : msg;
    const label = this.props.label || "portal";

    return (
      <div
        className="min-h-screen w-full flex items-start justify-center px-4 py-10"
        style={{ backgroundColor: colors.surfaceSecondary }}
        data-testid="portal-error-boundary"
        data-boundary-label={label}
      >
        <div
          className="w-full max-w-md rounded-2xl shadow-sm"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            padding: 20,
          }}
        >
          <div className="flex items-center gap-3 mb-3">
            <div
              className="w-10 h-10 rounded-full flex items-center justify-center"
              style={{ backgroundColor: "#FEF3C7", color: "#B45309" }}
              aria-hidden="true"
            >
              <AlertTriangle size={20} />
            </div>
            <div className="min-w-0">
              <div
                className="text-base font-semibold"
                style={{ color: colors.onSurface }}
                data-testid="portal-error-title"
              >
                Something went wrong loading this page.
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                We logged the details so we can fix it.
              </div>
            </div>
          </div>

          <div
            className="rounded-lg px-3 py-2 mb-4 text-xs font-mono"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
              wordBreak: "break-word",
            }}
            data-testid="portal-error-message"
          >
            {truncated}
          </div>

          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={this.onReload}
              className="w-full h-10 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition hover:brightness-95"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="portal-error-reload"
            >
              <RefreshCw size={16} /> Reload
            </button>
            <button
              type="button"
              onClick={this.onCopy}
              className="w-full h-10 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition hover:brightness-95"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="portal-error-copy"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
              {copied ? "Copied" : "Copy details"}
            </button>
          </div>

          <div
            className="mt-3 text-[11px] flex items-center justify-between"
            style={{ color: colors.muted }}
          >
            <span data-testid="portal-error-report-status">
              {reported ? "Reported" : "Reporting…"}
            </span>
            <span data-testid="portal-error-id">
              Error ID: {errorAt || "-"}
            </span>
          </div>
        </div>
      </div>
    );
  }
}
