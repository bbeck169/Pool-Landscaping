import React from "react";
import { AlertTriangle, RefreshCw, Copy, Check } from "lucide-react";
import { colors } from "@/theme";

/**
 * Feb-2026 · Diagnostic Error Boundary.
 *
 * Wraps the Dispatch Board (and its heavy children like the Google Map)
 * so a runtime crash in production shows a friendly mobile-first panel
 * instead of a blank screen. The error + stack are POST-ed to
 * ``/api/client-errors`` so admins can see what actually failed on a
 * real device without having to reproduce it locally.
 *
 * Also exposes a "Copy error details" button which drops the full
 * message + stack + user-agent + URL onto the clipboard, and a
 * "Reload" button that forces a fresh mount.
 */
export default class DispatchErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null, copied: false, reported: false };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Fire-and-forget report — do not await; if the endpoint is down we
    // still show the fallback UI. Use fetch directly (bypass api.js so
    // we don't accidentally re-throw inside a broken app).
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
      fetch(`${backend}/api/client-errors`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: (error && (error.message || String(error))) || "Unknown error",
          stack: (error && error.stack) || (info && info.componentStack) || null,
          url: typeof window !== "undefined" ? window.location.href : null,
          user_agent: typeof navigator !== "undefined" ? navigator.userAgent : null,
          component: this.props.component || "DispatchBoard",
          extra: {
            componentStack: info && info.componentStack ? String(info.componentStack).slice(0, 4000) : null,
          },
        }),
      }).then(() => {
        this.setState({ reported: true });
      }).catch(() => { /* swallow */ });
    } catch { /* swallow */ }
  }

  onCopy = async () => {
    const { error, info } = this.state;
    const parts = [
      `Message: ${(error && (error.message || String(error))) || ""}`,
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
        // Fallback for older mobile browsers.
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
    const { error, copied, reported } = this.state;
    if (!error) return this.props.children;

    const msg = (error && (error.message || String(error))) || "Unknown error";
    const truncated = msg.length > 200 ? msg.slice(0, 200) + "…" : msg;
    const compLabel = this.props.componentLabel || "Dispatch Board";

    return (
      <div
        className="min-h-screen w-full flex items-start justify-center px-4 py-10"
        style={{ backgroundColor: colors.surfaceSecondary }}
        data-testid="dispatch-error-boundary"
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
                data-testid="dispatch-error-title"
              >
                Something went wrong loading {compLabel}
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
            data-testid="dispatch-error-message"
          >
            {truncated}
          </div>

          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={this.onReload}
              className="w-full h-10 rounded-lg text-sm font-semibold flex items-center justify-center gap-2 transition hover:brightness-95"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="dispatch-error-reload"
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
              data-testid="dispatch-error-copy"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
              {copied ? "Copied" : "Copy error details"}
            </button>
          </div>

          <div
            className="mt-3 text-[11px] flex items-center justify-between"
            style={{ color: colors.muted }}
          >
            <span data-testid="dispatch-error-reported">
              {reported ? "Reported to admin log" : "Reporting…"}
            </span>
            <span>{compLabel}</span>
          </div>
        </div>
      </div>
    );
  }
}
