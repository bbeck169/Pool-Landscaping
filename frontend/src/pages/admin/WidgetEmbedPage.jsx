import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { Copy, Check, RefreshCw, ExternalLink, LayoutList, Map as MapIcon, Sparkles, X } from "lucide-react";
import { useAuth } from "@/auth";

/**
 * MR1+MR2 · Feb-2026 — Widget Embed preview + snippet copier.
 *
 * F4 (Feb-2026): dual-preview tabs — the original "Card List"
 * preview (``/api/widget/preview/...``) AND the new "Map" preview
 * (``/api/public/checkins/{slug}/map.html``). Each tab has its own
 * copy-to-clipboard snippet so admins can grab either the script
 * embed OR the map iframe.
 */
export default function WidgetEmbedPage() {
  const { user } = useAuth();
  const [tenant, setTenant] = React.useState(null);
  const [theme, setTheme] = React.useState("light");
  const [count, setCount] = React.useState(10);
  const [category, setCategory] = React.useState("");
  const [copied, setCopied] = React.useState(false);         // card-list copy
  const [copiedMap, setCopiedMap] = React.useState(false);   // map iframe copy
  const [reloadKey, setReloadKey] = React.useState(0);
  const [previewMode, setPreviewMode] = React.useState("list"); // "list" | "map"
  // Feb-2026 enhancement — F4 SEO onboarding prompt.
  const [widgetSettings, setWidgetSettings] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await api.get("/tenants/settings/widget-embed");
        if (!cancelled) setWidgetSettings(s);
      } catch {
        if (!cancelled) setWidgetSettings(null);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const seoPromptVisible = !!widgetSettings?.should_show_seo_prompt;

  const enableAutoEnqueue = async () => {
    try {
      const r = await api.patch("/tenants/settings/widget-embed", {
        auto_enqueue_public_checkins: true,
      });
      setWidgetSettings((prev) => ({
        ...(prev || {}),
        ...r,
        should_show_seo_prompt: false,
      }));
    } catch (_err) {
      setWidgetSettings((prev) => ({
        ...(prev || {}), should_show_seo_prompt: false,
      }));
    }
  };

  const dismissSeoPrompt = async () => {
    const nowIso = new Date().toISOString();
    try {
      await api.patch("/tenants/settings/widget-embed", {
        widget_embed_seo_prompt_dismissed_at: nowIso,
      });
    } catch { /* still hide locally */ }
    setWidgetSettings((prev) => ({
      ...(prev || {}),
      widget_embed_seo_prompt_dismissed_at: nowIso,
      should_show_seo_prompt: false,
    }));
  };

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

  // ── Card-list preview src ──────────────────────────────────────────
  const previewSrc = React.useMemo(() => {
    if (!slug) return null;
    const p = new URLSearchParams();
    p.set("theme", theme);
    p.set("count", String(count));
    if (category) p.set("category", category);
    return `${backendOrigin}/api/widget/preview/${encodeURIComponent(slug)}?${p.toString()}#r=${reloadKey}`;
  }, [backendOrigin, slug, theme, count, category, reloadKey]);

  // ── Map preview src (Feb-2026 F4) ──────────────────────────────────
  const mapPreviewSrc = React.useMemo(() => {
    if (!slug) return null;
    return `${backendOrigin}/api/public/checkins/${encodeURIComponent(slug)}/map.html#r=${reloadKey}`;
  }, [backendOrigin, slug, reloadKey]);

  // ── Card-list embed snippet ────────────────────────────────────────
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

  // ── Map iframe embed snippet (Feb-2026 F4) ─────────────────────────
  const mapSnippet = React.useMemo(() => {
    if (!slug) return "";
    const src = `${backendOrigin}/api/public/checkins/${slug}/map.html`;
    return (
`<iframe src="${src}"
        width="100%"
        height="480"
        frameborder="0"
        loading="lazy"
        title="Recent service check-ins"
        style="border:0;border-radius:12px;overflow:hidden"></iframe>`
    );
  }, [backendOrigin, slug]);

  const _writeClipboard = async (text) => {
    // Try the modern Clipboard API first, but fall back to the
    // legacy textarea+execCommand path on rejection (headless
    // browsers or hardened permission policies routinely reject
    // ``writeText`` even when the object exists).
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // fall through to fallback
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch {
      return false;
    }
  };

  const doCopy = async () => {
    if (!(await _writeClipboard(snippet))) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const doCopyMap = async () => {
    if (!(await _writeClipboard(mapSnippet))) return;
    setCopiedMap(true);
    setTimeout(() => setCopiedMap(false), 1500);
  };

  const isMap = previewMode === "map";
  const activeSnippet = isMap ? mapSnippet : snippet;
  const activeCopyHandler = isMap ? doCopyMap : doCopy;
  const activeCopiedFlag = isMap ? copiedMap : copied;

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

      {/* Feb-2026 F4 SEO onboarding prompt — dismissible banner
          nudging admins to turn on the public map for local-SEO. */}
      {seoPromptVisible ? (
        <div
          className="rounded-xl p-3 flex items-start gap-3"
          style={{
            backgroundColor: "#EEF2FF",
            border: "1px solid #C7D2FE",
            color: "#3730A3",
          }}
          data-testid="widget-embed-seo-prompt"
          role="region"
          aria-label="Turn on public map for local SEO"
        >
          <Sparkles size={18} className="shrink-0 mt-0.5" />
          <div className="flex-1 text-sm">
            <div className="font-semibold mb-0.5">
              Turn on the public check-ins map for local SEO
            </div>
            <div className="text-[13px]">
              Approved check-ins render with schema.org structured data
              that search engines can parse. You have recent completed
              jobs — enabling this makes them work for you.
            </div>
          </div>
          <button
            type="button"
            onClick={enableAutoEnqueue}
            className="text-xs font-semibold px-3 py-1.5 rounded-md text-white shrink-0"
            style={{ backgroundColor: "#4338CA", border: 0 }}
            data-testid="widget-embed-seo-prompt-cta"
            aria-label="Turn on public map"
          >
            Turn on public map
          </button>
          <button
            type="button"
            onClick={dismissSeoPrompt}
            className="shrink-0 rounded-md p-1"
            style={{ background: "transparent", border: 0, color: "#3730A3" }}
            data-testid="widget-embed-seo-prompt-dismiss"
            aria-label="Dismiss SEO onboarding prompt"
            title="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      ) : null}

      {/* Preview-mode tab toggle */}
      <div
        className="inline-flex rounded-lg overflow-hidden"
        style={{ border: `1px solid ${colors.border}` }}
        role="tablist"
        aria-label="Preview mode"
        data-testid="widget-embed-preview-tabs"
      >
        <button
          type="button"
          role="tab"
          aria-selected={!isMap}
          onClick={() => setPreviewMode("list")}
          className="inline-flex items-center gap-1.5 h-9 px-3 text-sm font-semibold"
          style={{
            backgroundColor: !isMap ? "#2563EB" : colors.surface,
            color: !isMap ? "#FFFFFF" : colors.onSurface,
            border: 0,
          }}
          data-testid="widget-embed-tab-list"
        >
          <LayoutList size={14} /> Card List Preview
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={isMap}
          onClick={() => setPreviewMode("map")}
          className="inline-flex items-center gap-1.5 h-9 px-3 text-sm font-semibold"
          style={{
            backgroundColor: isMap ? "#2563EB" : colors.surface,
            color: isMap ? "#FFFFFF" : colors.onSurface,
            border: 0,
            borderLeft: `1px solid ${colors.border}`,
          }}
          data-testid="widget-embed-tab-map"
        >
          <MapIcon size={14} /> Map Preview
        </button>
      </div>

      {/* Controls — hidden in map mode since the map endpoint doesn't
          take these params (12-month window, unlimited pins). */}
      {!isMap ? (
        <div
          className="rounded-xl p-3 grid grid-cols-1 md:grid-cols-3 gap-3"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="widget-embed-controls"
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
      ) : (
        <div
          className="rounded-xl p-3 text-xs"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.muted,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="widget-embed-map-info"
        >
          Map shows every <strong>approved</strong> check-in in the last
          12 months. Exact addresses are jittered by ±0.001° to protect
          customer PII. Includes schema.org LocalBusiness JSON-LD for
          local-SEO discoverability.
        </div>
      )}

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
            <span>{isMap ? "Map preview" : "Live preview"}</span>
            {(isMap ? mapPreviewSrc : previewSrc) ? (
              <a
                href={isMap ? mapPreviewSrc : previewSrc}
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
          {isMap ? (
            mapPreviewSrc ? (
              <iframe
                key={`map-${reloadKey}`}
                src={mapPreviewSrc}
                title="Widget map preview"
                style={{ width: "100%", height: 480, border: 0,
                          display: "block", backgroundColor: "#F8FAFC" }}
                data-testid="widget-embed-map-iframe"
              />
            ) : (
              <div className="p-6 text-sm text-center" style={{ color: colors.muted }}
                    data-testid="widget-embed-noslug">
                Loading tenant…
              </div>
            )
          ) : previewSrc ? (
            <iframe
              key={`list-${reloadKey}`}
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
            {isMap ? "Map iframe snippet" : "Embed snippet"}
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
              data-testid={isMap ? "widget-embed-map-snippet" : "widget-embed-snippet"}
            >
              {activeSnippet || "// waiting for tenant…"}
            </pre>
            <button
              type="button"
              onClick={activeCopyHandler}
              disabled={!activeSnippet}
              className="w-full inline-flex items-center justify-center gap-2 h-10 rounded-lg text-sm font-semibold text-white"
              style={{
                backgroundColor: activeCopiedFlag ? "#10B981" : "#2563EB",
                border: 0,
                opacity: activeSnippet ? 1 : 0.6,
                cursor: activeSnippet ? "pointer" : "not-allowed",
              }}
              data-testid={isMap ? "widget-embed-copy-map" : "widget-embed-copy"}
            >
              {activeCopiedFlag ? <Check size={14} /> : <Copy size={14} />}
              {activeCopiedFlag
                ? "Copied to clipboard"
                : (isMap ? "Copy map iframe" : "Copy snippet")}
            </button>
            <div className="text-[11px]" style={{ color: colors.muted }}>
              {isMap ? (
                <>
                  The map iframe uses <strong>Leaflet + OpenStreetMap</strong>
                  {" "}via CDN. Pins are clustered at low zoom. Coordinates are
                  jittered by ±0.001° per job — same job renders at the same
                  spot on every load, but exact addresses cannot be recovered.
                </>
              ) : (
                <>
                  The widget uses <strong>shadow DOM</strong>, so its styles
                  never leak into the host page. It also injects
                  <strong> schema.org LocalBusiness JSON-LD </strong>
                  into the host page for local-SEO discoverability.
                </>
              )}
            </div>
          </div>
        </aside>
      </div>
    </SafeScrollContainer>
  );
}
