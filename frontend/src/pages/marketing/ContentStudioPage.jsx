/**
 * Feb-2026 · Phase B · Marketing Content Studio.
 *
 * Route: /marketing/content-studio  (admin+)
 *
 * Prompt textarea + aspect ratio selector + optional reference image
 * URL → POSTs `/api/media/image/generate` (or `/edit` when a reference
 * image is provided). Renders the returned image + a "recent
 * generations" grid from `/api/media/library`.
 *
 * Feature-flagged on Supercool connection status. When disconnected we
 * still render the studio (the backend picks the Emergent nano-banana
 * fallback), but we show an inline banner explaining the degraded mode
 * and linking to the Supercool settings page.
 */
import React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Sparkles, Loader2, Trash2, Copy as CopyIcon, Wand2, ChevronRight } from "lucide-react";
import { api, api_base } from "@/api";
import { colors, gradients } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";


const ASPECT_OPTIONS = [
  { v: "1:1",  label: "Square (1:1)" },
  { v: "16:9", label: "Wide (16:9)" },
  { v: "4:5",  label: "Portrait (4:5)" },
  { v: "9:16", label: "Story (9:16)" },
  { v: "4:3",  label: "Landscape (4:3)" },
  { v: "3:4",  label: "Card (3:4)" },
];


function absoluteMediaUrl(u) {
  if (!u) return "";
  if (u.startsWith("http") || u.startsWith("data:")) return u;
  const base = api_base().replace(/\/api\/?$/, "");
  return base + u;
}


export default function ContentStudioPage() {
  const [prompt, setPrompt] = React.useState("");
  const [aspect, setAspect] = React.useState("1:1");
  const [refUrl, setRefUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  // Feb-2026 · K55.a — SuperCool connection status check removed as
  // part of the sunset.  Image generation now runs unconditionally
  // through Emergent's gemini-3.1-flash-image-preview (see K56).  The
  // degraded-mode banner + "connect Supercool" link are gone; if
  // the endpoint is added back later, restore the state + banner.
  const [library, setLibrary] = React.useState({ items: [], total: 0, quota: null });

  const loadLibrary = React.useCallback(async () => {
    try {
      const r = await api.get("/media/library?limit=12");
      setLibrary(r || { items: [], total: 0, quota: null });
    } catch { setLibrary({ items: [], total: 0, quota: null }); }
  }, []);

  React.useEffect(() => { loadLibrary(); }, [loadLibrary]);

  const doGenerate = async () => {
    if (!prompt.trim() || prompt.trim().length < 3) {
      toast.error("Prompt is too short.");
      return;
    }
    setBusy(true); setResult(null);
    try {
      const path = refUrl.trim()
        ? "/media/image/edit" : "/media/image/generate";
      const body = refUrl.trim()
        ? { prompt: prompt.trim(),
             source_image_url: refUrl.trim(),
             aspect_ratio: aspect, surface: "marketing" }
        : { prompt: prompt.trim(),
             aspect_ratio: aspect, surface: "marketing" };
      const r = await api.post(path, body);
      setResult(r);
      toast.success(`Image ready · ${r.provider}`);
      loadLibrary();
    } catch (e) {
      const msg = e?.message || "Generation failed";
      if (/daily_limit_reached/i.test(msg)) {
        toast.error("Daily image-generation limit reached. Resets at 00:00 UTC.");
      } else {
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (image_id) => {
    try {
      await api.del(`/media/library/${image_id}`);
      toast.success("Removed from library");
      loadLibrary();
    } catch (e) { toast.error(e?.message || "Delete failed"); }
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
    } catch { toast.error("Copy failed"); }
  };

  const quota = library.quota;

  return (
    <SafeScrollContainer
      className="p-4 md:p-8 max-w-6xl mx-auto space-y-5"
      data-testid="content-studio-page"
    >
      <header className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
          style={{ background: gradients.navyToGreen.css, color: "#fff" }}
        >
          <Wand2 size={20} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}
              data-testid="content-studio-title">
            Marketing Content Studio
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Generate branded imagery for social posts, GBP, emails, and
            landing pages — powered by AI image generation.
          </p>
        </div>
        {quota ? (
          <div
            className="text-xs px-3 py-2 rounded-xl"
            style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
            data-testid="content-studio-quota"
          >
            <b>{quota.used}/{quota.limit}</b> today
          </div>
        ) : null}
      </header>

      {/* Feb-2026 · K55.a — SuperCool degraded-mode banner removed
          as part of the sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md).
          Image generation now runs unconditionally through the
          Emergent gemini-3.1-flash-image-preview provider (see K56). */}

      <section
        className="rounded-2xl p-5 grid grid-cols-1 md:grid-cols-3 gap-4"
        style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
        data-testid="content-studio-prompt-card"
      >
        <div className="md:col-span-2 space-y-3">
          <label className="text-xs font-bold" style={{ color: colors.muted }}>
            Prompt
          </label>
          <textarea
            value={prompt} onChange={(e) => setPrompt(e.target.value)}
            rows={4} placeholder="Aqua-blue backyard pool at sunset, palms, warm golden light, luxury Vistancia estate…"
            className="w-full px-3 py-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
            data-testid="content-studio-prompt-input"
          />
          <div className="space-y-1">
            <label className="text-xs font-bold" style={{ color: colors.muted }}>
              Reference image URL (optional — enables edit mode)
            </label>
            <input
              value={refUrl} onChange={(e) => setRefUrl(e.target.value)}
              placeholder="https://…/pool_before.jpg"
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
              data-testid="content-studio-refurl-input"
            />
          </div>
        </div>
        <div className="space-y-3">
          <label className="text-xs font-bold" style={{ color: colors.muted }}>
            Aspect ratio
          </label>
          <div className="grid grid-cols-2 gap-2">
            {ASPECT_OPTIONS.map((o) => (
              <button
                key={o.v} type="button" onClick={() => setAspect(o.v)}
                className="px-2 py-2 rounded-lg text-xs font-semibold"
                style={{
                  backgroundColor: aspect === o.v ? colors.onSurface : colors.surfaceSecondary,
                  color: aspect === o.v ? colors.surface : colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`content-studio-aspect-${o.v.replace(":","x")}`}
              >{o.label}</button>
            ))}
          </div>
          <button
            type="button" onClick={doGenerate} disabled={busy}
            className="w-full inline-flex items-center justify-center gap-1.5 px-4 py-3 rounded-lg text-sm font-bold text-white disabled:opacity-60"
            style={{ background: gradients.navyToGreen.css }}
            data-testid="content-studio-generate-btn"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {busy ? "Generating…" : refUrl.trim() ? "Edit image" : "Generate"}
          </button>
        </div>
      </section>

      {result ? (
        <section
          className="rounded-2xl p-4"
          style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}
          data-testid="content-studio-result-card"
        >
          <div className="flex items-start gap-4 flex-wrap">
            <img src={absoluteMediaUrl(result.url)} alt="Generated"
                  className="rounded-lg max-w-[420px] w-full"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid="content-studio-result-image" />
            <div className="flex-1 min-w-[240px] space-y-2">
              <div className="text-xs" style={{ color: colors.muted }}>
                Provider · <b>{result.provider}</b> · {result.tool_used}
                {result.aspect_ratio ? ` · ${result.aspect_ratio}` : ""}
              </div>
              <div className="text-sm" style={{ color: colors.onSurface }}>
                {result.prompt}
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => copyToClipboard(absoluteMediaUrl(result.url))}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                  data-testid="content-studio-copy-url-btn"
                >
                  <CopyIcon size={12} /> Copy URL
                </button>
                <Link
                  to={`/marketing?attach_image=${encodeURIComponent(result.url)}`}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                  data-testid="content-studio-to-marketing-btn"
                >Send to Mass Messaging <ChevronRight size={12} /></Link>
                <Link
                  to={`/marketing/gbp-posts?attach_image=${encodeURIComponent(result.url)}`}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                  data-testid="content-studio-to-gbp-btn"
                >Send to GBP <ChevronRight size={12} /></Link>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      <section data-testid="content-studio-library">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Recent generations
          </h2>
          <div className="text-xs" style={{ color: colors.muted }}>
            {library.total} total
          </div>
        </div>
        {library.items.length === 0 ? (
          <div
            className="text-sm p-6 rounded-xl text-center"
            style={{ backgroundColor: colors.surface,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
            data-testid="content-studio-library-empty"
          >
            No images yet. Generate your first one above.
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {library.items.map((it, i) => (
              <div key={it.id || i}
                    className="rounded-xl overflow-hidden group relative"
                    style={{ border: `1px solid ${colors.border}`,
                                backgroundColor: colors.surface }}
                    data-testid={`content-studio-library-item-${i}`}>
                <img src={absoluteMediaUrl(it.url)} alt={it.prompt || ""}
                      className="w-full aspect-square object-cover" />
                <div className="p-2">
                  <div className="text-[11px] truncate" style={{ color: colors.muted }}
                        title={it.prompt}>
                    {it.prompt}
                  </div>
                  <div className="text-[10px] uppercase tracking-wide mt-1"
                        style={{ color: colors.muted }}>
                    {it.provider} · {it.surface}
                  </div>
                </div>
                <button
                  type="button" onClick={() => doDelete(it.id)}
                  className="absolute top-1.5 right-1.5 w-7 h-7 rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ backgroundColor: "rgba(220,38,38,0.9)", color: "#fff" }}
                  aria-label="Delete image"
                  data-testid={`content-studio-library-delete-${i}`}
                ><Trash2 size={12} /></button>
              </div>
            ))}
          </div>
        )}
      </section>
    </SafeScrollContainer>
  );
}
