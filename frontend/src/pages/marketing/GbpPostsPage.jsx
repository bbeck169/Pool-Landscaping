// Feb-2026 · Phase 20 P1 — GBP post drafter admin page.
//
// Generate, list, edit, copy, schedule, and mark-as-posted drafts.
// No auto-publish to Google — GBP API is gated.
import React from "react";
import { toast } from "sonner";
import {
  Wand2, Copy, Trash2, RefreshCw, Calendar, CheckCircle, Download,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";

const PURPOSES = [
  ["update", "Update"], ["promo", "Promo"], ["event", "Event"],
  ["new_service", "New service"], ["seasonal_tip", "Seasonal tip"],
  ["featured_customer", "Featured customer"],
];
const TONES = [["friendly","Friendly"],["professional","Professional"],["promotional","Promotional"]];
const CTAS  = ["Call now","Book","Learn more","Get offer","None"];

export default function GbpPostsPage() {
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [form, setForm] = React.useState({
    purpose: "update", tone: "friendly", topic_hint: "", cta_type: "Call now",
  });
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/marketing/gbp-posts");
      setRows(r?.items || []);
    } catch (e) {
      toast.error(`Load failed: ${e.message || e}`);
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    try {
      const draft = await api.post("/marketing/gbp-posts/generate", {
        ...form, cta_type: form.cta_type === "None" ? null : form.cta_type,
      });
      setRows((prev) => [draft, ...prev]);
      toast.success("Draft generated");
    } catch (e) {
      toast.error(`Generate failed: ${e.message || e}`);
    } finally { setBusy(false); }
  };

  const copy = (r) => {
    const text = `${r.headline}\n\n${r.body_150w}\n\n${r.cta_text}`;
    navigator.clipboard?.writeText(text);
    toast.success("Copied — paste into GBP");
  };

  const markPosted = async (r) => {
    try {
      await api.patch(`/marketing/gbp-posts/${r.id}`, { status: "posted" });
      await load();
      toast.success("Marked as posted");
    } catch (e) { toast.error(`Update failed: ${e.message || e}`); }
  };

  const del = async (r) => {
    const ok = await mustConfirm({
      title: `Delete draft "${r.headline}"?`,
      description: "This draft will be removed. Posts already published to GBP are unaffected.",
      tone: "danger", confirmText: "Delete", requireTypeConfirm: true,
    });
    if (!ok) return;
    try {
      await api.del(`/marketing/gbp-posts/${r.id}`);
      setRows((prev) => prev.filter((x) => x.id !== r.id));
    } catch (e) { toast.error(`Delete failed: ${e.message || e}`); }
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4"
         data-testid="gbp-posts-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}>
          <Wand2 size={20} className="inline mr-2 -mt-0.5" style={{ color: colors.brand }} />
          Google Business Profile · Post drafter
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Generate ready-to-paste GBP posts. Google's API doesn't allow auto-posting — copy the
          draft into your GBP dashboard.
        </p>
      </div>

      <div className="rounded-xl p-4 space-y-3"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="gbp-generate-form">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            ["purpose", "Purpose", PURPOSES],
            ["tone", "Tone", TONES],
          ].map(([k, label, opts]) => (
            <div key={k}>
              <label className="text-[11px] uppercase tracking-wide font-semibold"
                     style={{ color: colors.muted }}>{label}</label>
              <select
                value={form[k]}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                className="mt-1 w-full px-2 py-1.5 text-sm rounded"
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                data-testid={`gbp-select-${k}`}
              >
                {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          ))}
          <div>
            <label className="text-[11px] uppercase tracking-wide font-semibold"
                   style={{ color: colors.muted }}>CTA</label>
            <select
              value={form.cta_type}
              onChange={(e) => setForm({ ...form, cta_type: e.target.value })}
              className="mt-1 w-full px-2 py-1.5 text-sm rounded"
              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
              data-testid="gbp-select-cta"
            >
              {CTAS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="md:col-span-1">
            <label className="text-[11px] uppercase tracking-wide font-semibold"
                   style={{ color: colors.muted }}>Topic hint</label>
            <input
              type="text"
              placeholder="e.g. algae bloom season"
              value={form.topic_hint}
              onChange={(e) => setForm({ ...form, topic_hint: e.target.value })}
              className="mt-1 w-full px-2 py-1.5 text-sm rounded"
              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
              data-testid="gbp-input-topic"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={generate}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold text-white hover:brightness-95 disabled:opacity-60"
          style={{ backgroundColor: colors.brand }}
          data-testid="gbp-generate-btn"
        >
          <Wand2 size={13} /> {busy ? "Generating…" : "Generate post"}
        </button>
      </div>

      <div className="text-sm font-semibold" style={{ color: colors.muted }}>
        Drafts ({rows.length})
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="gbp-loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl p-6 text-center text-sm"
             style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
             data-testid="gbp-empty">
          No drafts yet. Generate your first post above.
        </div>
      ) : (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-4"
            data-testid="gbp-drafts-list">
          {rows.map((r) => (
            <li key={r.id}
                className="rounded-xl overflow-hidden flex flex-col"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`gbp-draft-${r.id}`}>
              {r.image_url ? (
                <img src={r.image_url} alt=""
                       className="w-full aspect-square object-cover" />
              ) : (
                <div className="w-full aspect-square flex items-center justify-center text-xs"
                     style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
                  (no image)
                </div>
              )}
              <div className="p-3 space-y-2 flex-1">
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {r.headline}
                </div>
                <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
                  {r.body_150w}
                </div>
                <div className="text-[11px] font-bold uppercase" style={{ color: colors.brand }}>
                  {r.cta_text}
                </div>
                <div className="flex items-center gap-1 pt-1 flex-wrap">
                  <button type="button" onClick={() => copy(r)}
                          className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                          style={{ backgroundColor: colors.brand, color: "#fff" }}
                          data-testid={`gbp-copy-${r.id}`}>
                    <Copy size={11} /> Copy
                  </button>
                  {r.image_url ? (
                    <a href={r.image_url} download
                       className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                       style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                       data-testid={`gbp-download-${r.id}`}>
                      <Download size={11} /> Image
                    </a>
                  ) : null}
                  {r.status !== "posted" ? (
                    <button type="button" onClick={() => markPosted(r)}
                            className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                            data-testid={`gbp-mark-posted-${r.id}`}>
                      <CheckCircle size={11} /> Mark posted
                    </button>
                  ) : (
                    <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>
                      Posted
                    </span>
                  )}
                  <button type="button" onClick={() => del(r)}
                          className="p-1 rounded-md hover:bg-red-50 ml-auto"
                          data-testid={`gbp-delete-${r.id}`}>
                    <Trash2 size={12} style={{ color: "#B91C1C" }} />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
