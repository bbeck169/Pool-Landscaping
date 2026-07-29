import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { Copy, Check, RefreshCw, ExternalLink } from "lucide-react";
import { useAuth } from "@/auth";

/**
 * MR1+MR2 · Feb-2026 — Widget Embed preview + snippet copier.
 *
 * Admin surface for the public embeddable widget. Shows a live-preview
 * iframe (loading ``/api/widget/preview/{tenant_slug}``) plus an
 * "Embed snippet" panel with a copy-to-clipboard button.
 */
export default function WidgetEmbedPage() {
  const { user } = useAuth();
  const [tenant, setTenant] = React.useState(null);
  const [theme, setTheme] = React.useState("light");
  const [count, setCount] = React.useState(10);
  const [category, setCategory] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const t = await api.get("/tenants/current");
        if (!cancelled) setTenant(t);
      } catch {
        if (!cancelled) setTenant(null);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const backendOrigin = React.useMemo(() => {
    try {
      const u = new URL(process.env.REACT_APP_BACKEND_URL || window.location.origin);
      return u.origin;
    } catch {
      return window.location.origin;
    }
  }, []);

  const slug = tenant?.slug || (user?.tenant?.slug) || "";

  const previewSrc = React.useMemo(() => {
    if (!slug) return null;
    const p = new URLSearchParams();
    p.set("theme", theme);
    p.set("count", String(count));
    if (category) p.set("category", category);
    // Bump reloadKey to force iframe refresh.
    return `${backendOrigin}/api/widget/preview/${encodeURIComponent(slug)}?${p.toString()}#r=${reloadKey}`;
  }, [backendOrigin, slug, theme, count, category, reloadKey]);

  const snippet = React.useMemo(() => {
    if (!slug) return "";
    const attrs = [
      `src="${backendOrigin}/api/widget.js"`,
      `data-tenant="${slug}"`,
      `data-count="${count}"`,
      `data-theme="${theme}"`,
    ];
    if (category) attrs.push(`data-category="${category}"`);
    attrs.push("async");
    return `<script ${attrs.join("\n        ")}></script>`;
  }, [backendOrigin, slug, count, theme, category]);

  const doCopy = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(snippet);
      } else {
        const ta = document.createElement("textarea");
        ta.value = snippet;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* swallow */ }
  };

  return (
    <SafeScrollContainer
      className="px-4 md:px-8 pt-6 space-y-4"
      data-testid="widget-embed-page"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1
            className="text-2xl font-semibold"
            style={{ color: colors.onSurface }}
            data-testid="widget-embed-title"
          >
            Widget Embed
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Public check-in widget for external marketing sites. Shows only
            approved rows; house numbers are hidden automatically.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="widget-embed-reload"
        >
          <RefreshCw size={14} /> Reload preview
        </button>
      </div>

      {/* Controls */}
      <div
        className="rounded-xl p-3 grid grid-cols-1 md:grid-cols-3 gap-3"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
          Theme
          <select
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            data-testid="widget-embed-theme"
            className="h-9 px-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
          Count
          <select
            value={count}
            onChange={(e) => setCount(parseInt(e.target.value, 10))}
            data-testid="widget-embed-count"
            className="h-9 px-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={20}>20</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
          Category filter (optional)
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="e.g. pool_service"
            data-testid="widget-embed-category"
            className="h-9 px-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          />
        </label>
      </div>

      {/* Two-panel: preview + snippet */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <section
          className="lg:col-span-2 rounded-xl overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="widget-embed-preview-panel"
        >
          <div
            className="text-xs font-semibold px-3 py-2 flex items-center justify-between"
            style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
          >
            <span>Live preview</span>
            {previewSrc ? (
              <a
                href={previewSrc}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1"
                style={{ color: colors.muted }}
                data-testid="widget-embed-open-in-tab"
              >
                Open in tab <ExternalLink size={12} />
              </a>
            ) : null}
          </div>
          {previewSrc ? (
            <iframe
              key={reloadKey}
              src={previewSrc}
              title="Widget preview"
              style={{ width: "100%", height: 640, border: 0,
                        display: "block", backgroundColor: theme === "dark" ? "#0F172A" : "#F8FAFC" }}
              data-testid="widget-embed-iframe"
            />
          ) : (
            <div className="p-6 text-sm text-center" style={{ color: colors.muted }}
                  data-testid="widget-embed-noslug">
              Loading tenant…
            </div>
          )}
        </section>

        <aside
          className="rounded-xl"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <div className="text-xs font-semibold px-3 py-2"
                style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
            Embed snippet
          </div>
          <div className="p-3 space-y-3">
            <pre
              className="text-[11px] p-3 rounded-lg overflow-x-auto"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
                whiteSpace: "pre",
              }}
              data-testid="widget-embed-snippet"
            >
              {snippet || "// waiting for tenant…"}
            </pre>
            <button
              type="button"
              onClick={doCopy}
              disabled={!snippet}
              className="w-full inline-flex items-center justify-center gap-2 h-10 rounded-lg text-sm font-semibold text-white"
              style={{
                backgroundColor: copied ? "#10B981" : "#2563EB",
                border: 0,
                opacity: snippet ? 1 : 0.6,
                cursor: snippet ? "pointer" : "not-allowed",
              }}
              data-testid="widget-embed-copy"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              {copied ? "Copied to clipboard" : "Copy snippet"}
            </button>
            <div className="text-[11px]" style={{ color: colors.muted }}>
              The widget uses <strong>shadow DOM</strong>, so its styles
              never leak into the host page. It also injects
              <strong> schema.org LocalBusiness JSON-LD </strong>
              into the host page for local-SEO discoverability.
            </div>
          </div>
        </aside>
      </div>
    </SafeScrollContainer>
  );
}
