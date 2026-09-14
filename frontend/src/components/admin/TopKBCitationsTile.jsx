/**
 * TopKBCitationsTile · Feb-2026 · Polish bundle Item 2
 *
 * Compact tile for the AI Brain admin page. Renders the top-5
 * most-cited KB docs over the last 7 days by querying
 * ``GET /api/ai/kb/citations/top?days=7&limit=10``. Read-only
 * observability — see FIX_POLISH_BUNDLE_FEB_2026.md.
 */
import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { BookOpen } from "lucide-react";

function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, {
      month: "short", day: "numeric",
    });
  } catch {
    return "—";
  }
}

export default function TopKBCitationsTile() {
  const [loading, setLoading] = React.useState(true);
  const [items, setItems] = React.useState([]);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.get("/ai/kb/citations/top?days=7&limit=10")
      .then((r) => { if (!cancelled) setItems((r?.items || []).slice(0, 5)); })
      .catch((e) => { if (!cancelled) setErr(e?.message || "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div
      className="bg-white rounded-lg border p-4"
      style={{ borderColor: colors.border }}
      data-testid="ai-kb-citations-tile"
    >
      <div className="flex items-center gap-2 mb-3">
        <BookOpen size={16} style={{ color: colors.brand }} />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Top KB docs cited (7d)
        </div>
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="ai-kb-citations-loading">Loading…</div>
      ) : err ? (
        <div className="text-xs text-red-600"
             data-testid="ai-kb-citations-error">{String(err)}</div>
      ) : items.length === 0 ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="ai-kb-citations-empty">
          No citations yet. Ask questions in the AI Dock to populate.
        </div>
      ) : (
        <div className="space-y-1.5 text-sm">
          {items.map((it, i) => (
            <div
              key={it.doc_id || i}
              className="flex justify-between gap-3"
              data-testid={`ai-kb-citation-row-${i}`}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium"
                     style={{ color: colors.onSurface }}
                     title={it.doc_title || it.doc_id}>
                  {it.doc_title || "(untitled)"}
                </div>
                <div className="text-[11px]" style={{ color: colors.muted }}>
                  last cited {_fmtDate(it.last_cited_at)}
                </div>
              </div>
              <div className="text-right shrink-0">
                <span className="text-xs font-semibold"
                      style={{ color: colors.brand }}>
                  {it.citations}
                </span>
                <span className="text-[11px] ml-1"
                      style={{ color: colors.muted }}>
                  cite{it.citations === 1 ? "" : "s"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
