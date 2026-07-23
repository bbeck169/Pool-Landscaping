// Feb-2026 · Phase 20 P3 — Website SEO analyzer admin page.
//
// Runs POST /api/seo/analyze against the tenant's website (from
// business_card.website_url by default). Renders a scorecard /100
// + a prioritized "Fix these" list with rationale per miss.
import React from "react";
import { toast } from "sonner";
import { RefreshCw, Search, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function WebsiteSeoPage() {
  const [url, setUrl] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [history, setHistory] = React.useState([]);
  const [expanded, setExpanded] = React.useState(null);

  const loadHistory = React.useCallback(async () => {
    try {
      const r = await api.get("/seo/scans?limit=20");
      setHistory(r?.scans || []);
    } catch (_e) { /* empty */ }
  }, []);

  React.useEffect(() => {
    loadHistory();
    api.get("/tenants/business-card").then((c) => {
      if (c?.website_url && !url) setUrl(c.website_url);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.post("/seo/analyze", { url });
      setResult(r);
      await loadHistory();
      toast.success(`Score: ${r.score}/100 · ${(r.fixes || []).length} fixes`);
    } catch (e) {
      toast.error(`Analyze failed: ${e.message || e}`);
    } finally { setRunning(false); }
  };

  const scoreColor = (s) => s >= 85 ? "#16A34A" : s >= 60 ? "#EAB308" : "#B91C1C";

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4"
         data-testid="website-seo-page">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
              style={{ color: colors.onSurface }}>
            <Search size={20} className="inline mr-2 -mt-0.5" style={{ color: colors.brand }} />
            Website SEO
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            On-page SEO scorecard for your website. Re-run any time.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            className="px-3 py-1.5 text-sm rounded-md w-72"
            style={{ backgroundColor: colors.surfaceSecondary,
                       border: `1px solid ${colors.border}`,
                       color: colors.onSurface }}
            data-testid="seo-url-input"
          />
          <button
            type="button"
            onClick={run}
            disabled={running || !url}
            className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold text-white hover:brightness-95 disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="seo-run-btn"
          >
            <RefreshCw size={13} className={running ? "animate-spin" : ""} />
            {running ? "Analyzing…" : "Run analysis"}
          </button>
        </div>
      </div>

      {result ? (
        <div className="grid md:grid-cols-3 gap-4">
          <div className="rounded-xl p-4"
               style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
               data-testid="seo-scorecard">
            <div className="text-[11px] uppercase tracking-wide font-semibold"
                 style={{ color: colors.muted }}>Score</div>
            <div className="text-6xl font-bold mt-1"
                 style={{ color: scoreColor(result.score || 0) }}
                 data-testid="seo-score-value">
              {result.score ?? "—"}
              <span className="text-2xl" style={{ color: colors.muted }}>/100</span>
            </div>
            <div className="text-xs mt-2" style={{ color: colors.muted }}>
              {result.url}
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              {result.word_count || 0} words · {result.internal_link_count || 0} internal links · {result.image_count || 0} images
            </div>
          </div>

          <div className="md:col-span-2 rounded-xl p-4"
               style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
               data-testid="seo-fixes-panel">
            <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>
              Fix these {(result.fixes || []).length ? `(${result.fixes.length})` : ""}
            </div>
            {(result.fixes || []).length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="seo-fixes-empty">
                Nothing critical. Everything checked.
              </div>
            ) : (
              <ul className="space-y-1" data-testid="seo-fixes-list">
                {result.fixes.map((f, idx) => (
                  <li key={idx}
                      className="rounded-md p-2"
                      style={{ backgroundColor: colors.surfaceSecondary,
                                 border: `1px solid ${colors.border}` }}
                      data-testid={`seo-fix-row-${idx}`}>
                    <button
                      type="button"
                      onClick={() => setExpanded(expanded === idx ? null : idx)}
                      className="w-full text-left flex items-center justify-between gap-2"
                      data-testid={`seo-fix-toggle-${idx}`}
                    >
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                              style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
                          −{f.weight}
                        </span>
                        <span className="text-xs font-semibold truncate"
                              style={{ color: colors.onSurface }}>
                          {f.key.replace(/_/g, " ")}
                        </span>
                      </div>
                      {expanded === idx ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    </button>
                    {expanded === idx ? (
                      <div className="text-xs mt-2 pl-1"
                           style={{ color: colors.onSurfaceSecondary }}
                           data-testid={`seo-fix-hint-${idx}`}>
                        {f.fix_hint}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-xl p-6 text-center text-sm"
             style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
             data-testid="seo-empty">
          Enter a URL above and click "Run analysis" to score your site.
        </div>
      )}

      {history.length > 0 ? (
        <div className="rounded-xl p-4"
             style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
             data-testid="seo-history-panel">
          <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>
            Recent scans
          </div>
          <ul className="space-y-1" data-testid="seo-history-list">
            {history.slice(0, 20).map((s) => (
              <li key={s.id} className="flex items-center justify-between text-xs py-1">
                <span className="truncate" style={{ color: colors.muted }}>
                  {(s.run_at || "").slice(0, 19).replace("T", " ")}
                </span>
                <span className="font-bold" style={{ color: scoreColor(s.score) }}>
                  {s.score}/100
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
