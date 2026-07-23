// Feb-2026 · Phase 20 P4 — GBP completeness checklist admin page.
import React from "react";
import { toast } from "sonner";
import { CheckCircle, Circle, ExternalLink, ClipboardCheck } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function LocalSeoPage() {
  const [data, setData] = React.useState(null);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/local-seo/checklist");
      setData(r);
    } catch (e) { toast.error(`Load failed: ${e.message || e}`); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const toggle = async (key, next) => {
    setSaving(true);
    try {
      // Optimistic update.
      setData((d) => d && ({
        ...d,
        items: d.items.map((it) => it.key === key ? { ...it, ok: next } : it),
      }));
      await api.patch("/local-seo/checklist", {
        toggles: { [key]: next },
      });
      await load();
    } catch (e) {
      toast.error(`Toggle failed: ${e.message || e}`);
      await load();
    } finally { setSaving(false); }
  };

  if (!data) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto space-y-4"
         data-testid="local-seo-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}>
          <ClipboardCheck size={20} className="inline mr-2 -mt-0.5" style={{ color: colors.brand }} />
          Local SEO checklist
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          The GBP hygiene list top-ranking local businesses follow.
        </p>
      </div>

      <div className="rounded-xl p-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Progress: {data.passed} of {data.total} · {data.progress_pct}%
          </div>
        </div>
        <div className="h-2 rounded-full" style={{ backgroundColor: colors.surfaceSecondary }}>
          <div
            className="h-2 rounded-full"
            style={{ width: `${data.progress_pct}%`, backgroundColor: colors.brand,
                       transition: "width 300ms ease" }}
            data-testid="local-seo-progress-bar"
          />
        </div>
      </div>

      <ul className="space-y-1" data-testid="local-seo-list">
        {data.items.map((it) => (
          <li key={it.key}
              className="rounded-md p-3 flex items-center gap-3"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={`local-seo-item-${it.key}`}>
            <button
              type="button"
              disabled={it.kind !== "toggle" || saving}
              onClick={() => toggle(it.key, !it.ok)}
              className="flex-shrink-0"
              title={it.kind === "toggle" ? "Toggle" : "Auto"}
              data-testid={`local-seo-toggle-${it.key}`}
            >
              {it.ok ? (
                <CheckCircle size={18} style={{ color: "#16A34A" }} />
              ) : (
                <Circle size={18} style={{ color: colors.muted }} />
              )}
            </button>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                {it.label}
                <span className="ml-2 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
                  {it.kind}
                </span>
              </div>
              {it.guidance ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  {it.guidance}
                </div>
              ) : null}
            </div>
            {!it.ok ? (
              <a
                href="https://business.google.com/"
                target="_blank" rel="noreferrer"
                className="flex-shrink-0 flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                data-testid={`local-seo-open-gbp-${it.key}`}
              >
                Open GBP <ExternalLink size={10} />
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
