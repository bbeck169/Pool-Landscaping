/**
 * Phase 17A.2 · Content Scorer with AI outline suggestions.
 */
import React, { useState } from "react";
import { Gauge, Sparkles, X, ArrowRight } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const LABEL_MAP = {
  readability:        "Readability",
  keyword_density:    "Keyword Density",
  heading_structure:  "Heading Structure",
  meta:               "Meta Tags",
  internal_links:     "Internal Links",
  image_alt:          "Image Alt Text",
  content_length:     "Content Length",
  semantic_relevance: "AI Semantic Relevance",
};

export default function ContentScorer() {
  const [source, setSource] = useState("html");
  const [url, setUrl] = useState("");
  const [html, setHtml] = useState("");
  const [kw, setKw] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState(null);
  const [outline, setOutline] = useState(null);
  const [suggesting, setSuggesting] = useState(false);
  const [err, setErr] = useState("");

  const analyze = async () => {
    if (!kw.trim() || (!url.trim() && !html.trim())) {
      setErr("Enter a keyword and either a URL or raw HTML.");
      return;
    }
    setErr(""); setAnalyzing(true); setResult(null); setOutline(null);
    try {
      const body = { target_keyword: kw };
      if (source === "url") body.url = url;
      else body.html = html;
      setResult(await api.post("/seo/content-score", body));
    } catch (e) { setErr(e.message); }
    finally { setAnalyzing(false); }
  };

  const suggest = async () => {
    setSuggesting(true);
    try {
      const r = await api.post("/seo/content-suggestions", {
        topic: kw, target_keyword: kw, existing_html: html || "",
      });
      setOutline(r);
    } catch (e) { setErr(e.message); }
    finally { setSuggesting(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="content-scorer-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Gauge size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Content Scorer
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Score any URL or HTML against a target keyword. Live AI critique.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Input side */}
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="content-scorer-input">
          <div className="flex gap-2 mb-3">
            {["html", "url"].map((s) => (
              <button key={s} onClick={() => setSource(s)}
                      className="px-3 py-1.5 text-xs font-semibold rounded-full"
                      style={{
                        backgroundColor: source === s ? colors.brand : colors.background,
                        color: source === s ? "#fff" : colors.onSurface,
                        border: `1px solid ${source === s ? colors.brand : colors.border}`,
                      }}
                      data-testid={`content-scorer-source-${s}`}>
                {s === "url" ? "By URL" : "Paste HTML"}
              </button>
            ))}
          </div>

          {source === "url" ? (
            <input value={url} onChange={(e) => setUrl(e.target.value)}
                   placeholder="https://example.com/blog/post"
                   className="w-full p-2.5 text-sm rounded-lg mb-3"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="content-scorer-url" />
          ) : (
            <textarea value={html} onChange={(e) => setHtml(e.target.value)}
                      rows={10}
                      placeholder="<html>… paste your content …</html>"
                      className="w-full p-2.5 text-sm rounded-lg mb-3 font-mono"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}
                      data-testid="content-scorer-html" />
          )}

          <label className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Target keyword</label>
          <input value={kw} onChange={(e) => setKw(e.target.value)}
                 placeholder="pool cleaning services in Phoenix"
                 className="w-full p-2.5 text-sm rounded-lg mb-3"
                 style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                 data-testid="content-scorer-kw" />

          {err && (
            <div className="text-xs p-2 rounded-lg mb-2"
                 style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                 data-testid="content-scorer-error">
              {err}
            </div>
          )}

          <button onClick={analyze} disabled={analyzing}
                  className="w-full py-2 text-sm font-bold rounded-lg disabled:opacity-60"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="content-scorer-analyze">
            {analyzing ? "Analyzing…" : "Analyze"}
          </button>
        </div>

        {/* Result side */}
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="content-scorer-result">
          {!result ? (
            <div className="h-full flex items-center justify-center text-sm"
                 style={{ color: colors.muted }}>
              Results will appear here.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>Overall score</div>
                  <div className="text-5xl font-bold"
                       style={{ color: result.score >= 80 ? "#059669"
                                       : result.score >= 60 ? "#D97706" : "#DC2626" }}>
                    {result.score}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {result.word_count} words · KW density {result.kw_density_pct}%
                    {result.mocked ? " · AI stubbed" : " · AI live"}
                  </div>
                </div>
                <button onClick={suggest} disabled={suggesting}
                        className="flex items-center gap-1 px-3 py-2 text-sm font-bold rounded-xl disabled:opacity-60"
                        style={{ background: colors.brand, color: "#fff" }}
                        data-testid="content-scorer-suggest">
                  <Sparkles size={14}/> {suggesting ? "Drafting…" : "Improve"}
                </button>
              </div>

              <div className="space-y-2">
                {Object.entries(result.breakdown).map(([k, v]) => (
                  <div key={k} data-testid={`content-scorer-bar-${k}`}>
                    <div className="flex justify-between text-xs mb-1">
                      <span style={{ color: colors.onSurface }}>{LABEL_MAP[k] || k}</span>
                      <span className="font-bold" style={{ color: colors.brand }}>{v}</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full overflow-hidden"
                         style={{ backgroundColor: colors.background }}>
                      <div className="h-full"
                           style={{ width: `${Math.min(100, v)}%`,
                                    background: brandGradientCss }} />
                    </div>
                  </div>
                ))}
              </div>

              {result.recommendations?.length > 0 && (
                <div className="mt-4 pt-4"
                     style={{ borderTop: `1px solid ${colors.border}` }}>
                  <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
                       style={{ color: colors.muted }}>Recommendations</div>
                  <ul className="text-xs space-y-1.5" style={{ color: colors.onSurface }}
                      data-testid="content-scorer-recs">
                    {result.recommendations.map((r, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <ArrowRight size={12} style={{ color: colors.brand, marginTop: 2 }} />
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {outline && (
        <div className="mt-6 rounded-2xl p-5"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="content-scorer-outline">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              AI-drafted outline {outline.mocked && (
                <span className="text-xs font-normal ml-2" style={{ color: colors.muted }}>
                  (LLM key missing — showing stub)
                </span>
              )}
            </h3>
            <button onClick={() => setOutline(null)} style={{ color: colors.muted }}>
              <X size={18}/>
            </button>
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] font-bold uppercase mb-2"
                   style={{ color: colors.muted }}>Sections</div>
              {(outline.outline || []).map((s, i) => (
                <div key={i} className="mb-3">
                  <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                    {s.h2}
                  </div>
                  {s.points && (
                    <ul className="text-xs mt-1 ml-3 space-y-0.5"
                        style={{ color: colors.muted }}>
                      {s.points.map((p, j) => <li key={j}>· {p}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            <div>
              {(outline.faq || []).length > 0 && (
                <>
                  <div className="text-[10px] font-bold uppercase mb-2"
                       style={{ color: colors.muted }}>FAQ</div>
                  {outline.faq.map((f, i) => (
                    <div key={i} className="mb-3">
                      <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                        {f.q}
                      </div>
                      <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                        {f.a}
                      </div>
                    </div>
                  ))}
                </>
              )}
              {(outline.internal_links_suggested || []).length > 0 && (
                <>
                  <div className="text-[10px] font-bold uppercase mb-2 mt-4"
                       style={{ color: colors.muted }}>Internal links</div>
                  <ul className="text-xs space-y-1" style={{ color: colors.brand }}>
                    {outline.internal_links_suggested.map((l, i) => (
                      <li key={i}>· {l}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
