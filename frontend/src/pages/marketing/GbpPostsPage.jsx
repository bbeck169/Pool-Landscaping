// Feb-2026 · Phase 20 P1 + Phase B follow-up — GBP post drafter.
//
// Generate, list, edit, copy, schedule, and mark-as-posted drafts.
// No auto-publish to Google — GBP API is gated.
//
// Phase B follow-up (Feb-2026): a per-draft "✨ Generate branded image"
// button opens a composer modal that hits POST /api/media/image/generate
// with surface="gbp", then PATCHes the draft with the new image_url so
// the card refreshes with the branded image. Feature-flagged on the
// Supercool MCP connection status — button is disabled with a tooltip
// when Supercool is disconnected (the composer would still work through
// the Emergent nano-banana fallback, but the brief scopes this to the
// Supercool-connected experience).
import React from "react";
import { toast } from "sonner";
import { Wand2, Copy, Trash2, CheckCircle, Download, Sparkles, Loader2, X } from "lucide-react";
import { api, api_base } from "@/api";
import { colors, gradients } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

const PURPOSES = [
  ["update", "Update"], ["promo", "Promo"], ["event", "Event"],
  ["new_service", "New service"], ["seasonal_tip", "Seasonal tip"],
  ["featured_customer", "Featured customer"],
];
const TONES = [["friendly","Friendly"],["professional","Professional"],["promotional","Promotional"]];
const CTAS  = ["Call now","Book","Learn more","Get offer","None"];

const ASPECT_OPTIONS = [
  { v: "4:5",  label: "Portrait (4:5)" },
  { v: "1:1",  label: "Square (1:1)" },
  { v: "16:9", label: "Wide (16:9)" },
  { v: "9:16", label: "Story (9:16)" },
];


function absoluteMediaUrl(u) {
  if (!u) return "";
  if (u.startsWith("http") || u.startsWith("data:")) return u;
  const base = api_base().replace(/\/api\/?$/, "");
  return base + u;
}


export default function GbpPostsPage() {
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [form, setForm] = React.useState({
    purpose: "update", tone: "friendly", topic_hint: "", cta_type: "Call now",
  });
  const [busy, setBusy] = React.useState(false);
  // Feb-2026 · K55.a — SuperCool connection state removed as part
  // of the sunset.  Composer modal is always available; image
  // generation runs through the Emergent nano-banana-2 fallback
  // unconditionally (see K56).
  const [composer, setComposer] = React.useState(null);  // { draft }

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

  // Feb-2026 · K55.a — SuperCool status polling removed as part of
  // the sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md).

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

  // Called by the composer modal after a successful PATCH. Replaces the
  // draft in-place so React re-renders the card with the new image.
  const onImageAttached = (updatedDraft) => {
    setRows((prev) => prev.map((x) => x.id === updatedDraft.id ? updatedDraft : x));
    setComposer(null);
    toast.success("Branded image attached to draft");
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
                <img src={absoluteMediaUrl(r.image_url)} alt=""
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

                  {/* Phase B follow-up — Generate branded image.
                      Feb-2026 · K55.a — SuperCool connection gate
                      removed; button is always enabled.  Image gen
                      runs through Emergent nano-banana-2 fallback. */}
                  <button
                    type="button"
                    onClick={() => setComposer({ draft: r })}
                    title="Generate a branded image for this post"
                    className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                    style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                    data-testid={`gbp-gen-image-btn-${r.id}`}
                  >
                    <Sparkles size={11} /> Generate branded image
                  </button>

                  {r.image_url ? (
                    <a href={absoluteMediaUrl(r.image_url)} download
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

      <GbpImageComposerModal
        composer={composer}
        onClose={() => setComposer(null)}
        onAttached={onImageAttached}
      />
    </div>
  );
}


/**
 * Phase B follow-up — composer modal.
 *
 * Renders when ``composer.draft`` is truthy. Pre-fills the prompt from
 * the draft's ``image_prompt`` (or body copy as fallback), lets the
 * admin pick an aspect ratio + toggle a "Add brand elements" flag,
 * then POSTs to ``/media/image/generate`` with ``surface="gbp"``.
 *
 * On success PATCHes the draft with ``image_url`` so the parent card
 * refreshes with the new image. Closes on outside click / Cancel /
 * successful attach.
 */
function GbpImageComposerModal({ composer, onClose, onAttached }) {
  const draft = composer?.draft;
  const [prompt, setPrompt] = React.useState("");
  const [aspect, setAspect] = React.useState("4:5");
  const [brand, setBrand] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [preview, setPreview] = React.useState(null);

  React.useEffect(() => {
    if (!draft) return;
    // Reset every time the modal opens for a fresh draft.
    const seed = (draft.image_prompt || draft.body_150w || draft.headline || "").slice(0, 500);
    setPrompt(seed);
    setAspect("4:5");
    setBrand(true);
    setPreview(null);
    setBusy(false);
  }, [draft?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!draft) return null;

  const buildFinalPrompt = () => {
    const base = prompt.trim();
    if (!brand) return base;
    const suffix = " Photorealistic, warm natural light, on-brand for a pool & landscaping service company. High-end residential setting, no logos or watermarks, no text overlays.";
    return base + suffix;
  };

  const doGenerate = async () => {
    if (prompt.trim().length < 3) {
      toast.error("Prompt is too short.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/media/image/generate", {
        prompt: buildFinalPrompt(),
        aspect_ratio: aspect,
        surface: "gbp",
      });
      setPreview(r);
      toast.success(`Image ready · ${r.provider}`);
    } catch (e) {
      const msg = e?.message || "Generation failed";
      if (/daily_limit_reached/i.test(msg)) {
        toast.error("Daily image-generation limit reached. Resets at 00:00 UTC.");
      } else {
        toast.error(msg);
      }
    } finally { setBusy(false); }
  };

  const doAttach = async () => {
    if (!preview?.url) return;
    setBusy(true);
    try {
      const updated = await api.patch(`/marketing/gbp-posts/${draft.id}`, {
        image_url: preview.url,
      });
      onAttached(updated);
    } catch (e) {
      toast.error(`Attach failed: ${e?.message || e}`);
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!draft} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className="max-w-2xl"
        data-testid="gbp-image-composer-modal"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={16} style={{ color: colors.brand }} />
            Generate branded image
          </DialogTitle>
          <DialogDescription>
            AI-generated visual for this Google Business Profile post.
            The image saves into your Content Studio library and attaches
            to this draft when you click "Attach to draft".
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label htmlFor="gbp-composer-prompt"
                   className="text-[11px] font-semibold uppercase tracking-wider"
                   style={{ color: colors.muted }}>Prompt</Label>
            <textarea
              id="gbp-composer-prompt"
              rows={4}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
              data-testid="gbp-composer-prompt-input"
            />
            <p className="text-[11px] mt-1" style={{ color: colors.muted }}>
              Pre-filled from the draft's image prompt — tweak freely.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Aspect ratio</Label>
              <div className="mt-1 grid grid-cols-2 gap-1.5">
                {ASPECT_OPTIONS.map((o) => (
                  <button
                    key={o.v} type="button" onClick={() => setAspect(o.v)}
                    className="px-2 py-1.5 rounded-md text-[11px] font-semibold"
                    style={{
                      backgroundColor: aspect === o.v ? colors.onSurface : colors.surfaceSecondary,
                      color: aspect === o.v ? colors.surface : colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`gbp-composer-aspect-${o.v.replace(":", "x")}`}
                  >{o.label}</button>
                ))}
              </div>
            </div>

            <div>
              <Label className="text-[11px] font-semibold uppercase tracking-wider"
                     style={{ color: colors.muted }}>Options</Label>
              <label className="flex items-center gap-2 mt-2 text-sm select-none cursor-pointer"
                     style={{ color: colors.onSurface }}
                     data-testid="gbp-composer-brand-label">
                <Checkbox
                  checked={brand}
                  onCheckedChange={(v) => setBrand(!!v)}
                  data-testid="gbp-composer-brand-checkbox"
                />
                Add brand elements
              </label>
              <p className="text-[11px] mt-1" style={{ color: colors.muted }}>
                Appends photorealistic, on-brand phrasing to the prompt.
              </p>
            </div>
          </div>

          {preview?.url ? (
            <div className="rounded-lg overflow-hidden"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="gbp-composer-preview">
              <img src={absoluteMediaUrl(preview.url)} alt="Preview"
                   className="w-full max-h-[360px] object-contain"
                   style={{ backgroundColor: "#0F172A" }} />
              <div className="p-2 text-[11px]"
                   style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary }}>
                Provider · <b>{preview.provider}</b>
                {preview.aspect_ratio ? ` · ${preview.aspect_ratio}` : ""}
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button" variant="outline" onClick={onClose}
            data-testid="gbp-composer-cancel"
          >
            <X size={13} /> Cancel
          </Button>
          {preview?.url ? (
            <Button
              type="button" onClick={doAttach} disabled={busy}
              style={{ background: gradients.navyToGreen.css, color: "#fff" }}
              data-testid="gbp-composer-attach-btn"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
              Attach to draft
            </Button>
          ) : (
            <Button
              type="button" onClick={doGenerate} disabled={busy}
              style={{ background: gradients.navyToGreen.css, color: "#fff" }}
              data-testid="gbp-composer-generate-btn"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {busy ? "Generating…" : "Generate"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
