// Phase 6 · Feb-2026 — Response Draft modal.
//
// Renders a Claude-drafted public reply to a negative brand mention.
// Tone knob (empathetic/professional/apologetic/assertive), platform
// badge, character-count vs platform hint, Copy / Mark posted /
// Discard, status footer.
import React from "react";
import { toast } from "sonner";
import { X, Sparkles, Copy, Send, Trash2, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TONES = ["empathetic", "professional", "apologetic", "assertive"];
const LENGTH_HINTS = {
  yelp: 750, google_reviews: 600, nextdoor: 500, reddit: 400,
  facebook: 500, bbb: 700, generic: 500,
};

const STATUS_STYLES = {
  draft:     { bg: "#F1F5F9", fg: "#334155", border: "#E2E8F0" },
  copied:    { bg: "#DBEAFE", fg: "#1E40AF", border: "#BFDBFE" },
  posted:    { bg: "#DCFCE7", fg: "#166534", border: "#BBF7D0" },
  discarded: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
};

export default function ResponseDraftModal({
  open, onClose, mention, onChange,
}) {
  const [tone, setTone] = React.useState("empathetic");
  const [busy, setBusy] = React.useState(false);
  const [draft, setDraft] = React.useState(null);   // latest draft object
  const [text, setText] = React.useState("");
  const [error, setError] = React.useState(null);

  const platform = draft?.platform || _detectPlatform(mention);
  const hint = LENGTH_HINTS[platform] || LENGTH_HINTS.generic;

  const loadLatest = React.useCallback(async () => {
    if (!mention) return;
    try {
      const r = await api.get(`/aeo/mentions/${mention.mention_id}/response/drafts`);
      const latest = (r.items || [])[0] || null;
      setDraft(latest);
      setText((latest?.edited_text ?? latest?.draft_text) || "");
    } catch {}
  }, [mention]);

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setTone("empathetic");
    setDraft(null);
    setText("");
    loadLatest();
  }, [open, loadLatest]);

  const generate = async (regenerate = false) => {
    if (!mention) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post(
        `/aeo/mentions/${mention.mention_id}/response/draft`,
        { tone, regenerate });
      setDraft(r);
      setText(r.edited_text || r.draft_text || "");
      onChange?.();
    } catch (e) {
      const msg = String(e?.message || e?.body?.detail || "");
      if (msg.includes("503") || msg.includes("llm_unavailable")) {
        setError("AI drafting is temporarily unavailable — please try again shortly.");
      } else if (msg.includes("429") || msg.includes("rate_limited")) {
        toast.error("Rate limit — try in an hour.");
      } else {
        toast.error(msg || "Draft failed");
      }
    } finally { setBusy(false); }
  };

  const saveText = async () => {
    if (!draft) return;
    if (text === (draft.edited_text ?? draft.draft_text)) return;
    try {
      const r = await api.post(`/aeo/response/drafts/${draft.draft_id}`,
                                  { edited_text: text });
      setDraft(r);
      onChange?.();
    } catch {}
  };

  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
      if (draft?.status === "draft") {
        const r = await api.post(`/aeo/response/drafts/${draft.draft_id}`,
                                    { status: "copied" });
        setDraft(r);
        onChange?.();
      }
    } catch {
      toast.error("Copy failed");
    }
  };

  const markPosted = async () => {
    if (!draft) return;
    try {
      const r = await api.post(`/aeo/response/drafts/${draft.draft_id}`,
                                  { status: "posted" });
      setDraft(r);
      toast.success("Marked as posted");
      onChange?.();
    } catch (e) { toast.error(e?.message || "Failed"); }
  };

  const discard = async () => {
    if (!draft) return;
    try {
      await api.del(`/aeo/response/drafts/${draft.draft_id}`);
      toast.success("Draft discarded");
      setDraft({ ...draft, status: "discarded" });
      onChange?.();
    } catch (e) { toast.error(e?.message || "Failed"); }
  };

  if (!open || !mention) return null;
  const sTone = STATUS_STYLES[draft?.status] || STATUS_STYLES.draft;
  const overLimit = text.length > hint;

  return (
    <div data-testid="response-draft-modal"
          role="dialog"
          style={{ position: "fixed", inset: 0, zIndex: 5000,
                    background: "rgba(15,23,42,0.6)", display: "flex",
                    alignItems: "center", justifyContent: "center" }}
          onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div style={{ background: colors.surface, borderRadius: 14,
                     width: "min(680px, 96vw)", padding: 24,
                     boxShadow: "0 20px 48px rgba(15,23,42,0.24)",
                     maxHeight: "90vh", overflow: "auto" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Sparkles size={18} color={colors.brand} />
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700,
                             color: colors.onSurface }}>
                Draft response
              </h2>
              <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px",
                                borderRadius: 999, background: colors.surfaceSecondary,
                                color: colors.onSurface,
                                border: `1px solid ${colors.border}` }}>
                {platform}
              </span>
              <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px",
                                borderRadius: 999, background: "#FEE2E2",
                                color: "#991B1B", border: "1px solid #FECACA" }}>
                {mention.sentiment || "neutral"}
              </span>
            </div>
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>
              {mention.title || mention.url}
            </div>
          </div>
          <button onClick={onClose} data-testid="response-draft-close"
                   style={{ background: "transparent", border: "none",
                             cursor: "pointer", color: colors.muted }}
                   aria-label="Close"><X size={18} /></button>
        </div>

        {/* Snippet quote */}
        <div style={{ background: colors.surfaceSecondary, borderLeft: `3px solid ${colors.muted}`,
                        padding: "8px 12px", borderRadius: 6, fontSize: 13,
                        color: colors.onSurface, marginBottom: 14 }}
              data-testid="response-draft-snippet">
          {mention.snippet || "(no snippet)"}
        </div>

        {/* Tone pills */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
                        marginBottom: 12 }}>
          {TONES.map((t) => {
            const active = tone === t;
            return (
              <button key={t} type="button" onClick={() => setTone(t)}
                       className="px-2.5 py-1 rounded-full text-xs font-semibold"
                       style={{
                         backgroundColor: active ? colors.brand : colors.surfaceSecondary,
                         color: active ? "#fff" : colors.onSurface,
                         border: `1px solid ${active ? colors.brand : colors.border}`,
                       }}
                       data-testid={`response-draft-tone-${t}`}>
                {t}
              </button>
            );
          })}
        </div>

        {/* Generate button */}
        <button type="button" onClick={() => generate(!!draft)}
                 disabled={busy}
                 className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.brand, color: "#fff",
                           marginBottom: 12 }}
                 data-testid="response-draft-generate">
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {draft ? "Regenerate" : "Generate draft"}
        </button>

        {error ? (
          <div style={{ background: "#FEF3C7", color: "#92400E",
                          border: "1px solid #FDE68A", borderRadius: 8,
                          padding: 10, fontSize: 12, marginBottom: 12 }}
                data-testid="response-draft-error">
            {error}
          </div>
        ) : null}

        {/* Result area */}
        {draft ? (
          <>
            <textarea value={text}
                       onChange={(e) => setText(e.target.value)}
                       onBlur={saveText}
                       rows={7}
                       className="w-full rounded-lg p-3 text-sm"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${overLimit ? "#DC2626" : colors.border}`,
                                 fontFamily: "inherit" }}
                       data-testid="response-draft-textarea" />
            <div style={{ display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginTop: 4, fontSize: 11,
                            color: overLimit ? "#DC2626" : colors.muted }}
                  data-testid="response-draft-counter">
              <span>{text.length} / {hint} chars</span>
              <span>Drafted via {draft.model_used} · ~${Number(draft.cost_est_usd || 0).toFixed(4)}
                {draft.cached ? " · cached" : ""}</span>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                            marginTop: 12 }}>
              <button type="button" onClick={doCopy}
                       className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold"
                       style={{ backgroundColor: colors.brand, color: "#fff" }}
                       data-testid="response-draft-copy">
                <Copy size={12} /> Copy to clipboard
              </button>
              <button type="button" onClick={markPosted}
                       disabled={draft.status === "posted"}
                       className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-50"
                       style={{ backgroundColor: colors.surfaceSecondary,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid="response-draft-mark-posted">
                <Send size={12} /> Mark as posted
              </button>
              <button type="button" onClick={discard}
                       disabled={draft.status === "discarded"}
                       className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-50"
                       style={{ backgroundColor: "transparent",
                                 color: "#DC2626",
                                 border: "1px solid #FECACA" }}
                       data-testid="response-draft-discard">
                <Trash2 size={12} /> Discard
              </button>
              <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 700,
                                padding: "3px 10px", borderRadius: 999,
                                background: sTone.bg, color: sTone.fg,
                                border: `1px solid ${sTone.border}` }}
                     data-testid="response-draft-status">
                {draft.status}
              </span>
            </div>
          </>
        ) : (
          <div style={{ textAlign: "center", padding: 20, fontSize: 12,
                          color: colors.muted, border: `1px dashed ${colors.border}`,
                          borderRadius: 8 }}>
            Pick a tone and click Generate draft.
          </div>
        )}
      </div>
    </div>
  );
}

function _detectPlatform(m) {
  const d = (m?.domain || "").toLowerCase();
  const u = m?.url || "";
  if (d.includes("yelp.com")) return "yelp";
  if (d.includes("nextdoor.com")) return "nextdoor";
  if (d.includes("reddit.com")) return "reddit";
  if (d.includes("facebook.com")) return "facebook";
  if (d.includes("bbb.org")) return "bbb";
  if (d.includes("google.com") && u.includes("/maps/")) return "google_reviews";
  return "generic";
}
