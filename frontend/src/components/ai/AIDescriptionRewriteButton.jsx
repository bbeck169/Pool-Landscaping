/**
 * AI Description Rewrite button · Feb-2026.
 *
 * Reusable pill-shaped button that sits next to any textarea whose
 * content you want to polish via Emergent LLM. Drop in like::
 *
 *   <AIDescriptionRewriteButton
 *     draft={desc}
 *     onRewritten={(text) => setDesc(text)}
 *     context={{ service_category: "…", business_name: "…" }}
 *   />
 *
 * The button:
 *   * Is disabled when ``draft`` is empty (post-trim).
 *   * Shows a spinner while the POST is in flight.
 *   * Toasts success / rate-limit / generic-error via ``sonner``.
 *
 * The parent decides what to do with the returned text — this
 * component never mutates the source of truth on its own.
 */
import React, { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";

export default function AIDescriptionRewriteButton({
  draft,
  context,
  onRewritten,
  size = "sm",
  className = "",
  testid = "ai-rewrite-description-btn",
}) {
  const [busy, setBusy] = useState(false);
  const trimmed = (draft || "").trim();
  const disabled = busy || trimmed.length === 0;

  const handleClick = async () => {
    if (disabled) return;
    setBusy(true);
    try {
      const res = await api.post("/checkins/rewrite-description", {
        draft_description: trimmed,
        context: context || {},
      });
      const rewritten = (res && res.rewritten) || "";
      if (!rewritten) {
        toast.error("AI rewrite failed. Your draft is unchanged.");
        return;
      }
      onRewritten?.(rewritten);
      toast.success("AI rewrite applied — you can still edit.");
    } catch (e) {
      const status = e?.status || e?.response?.status;
      // Our fetch wrapper serializes the detail into e.message.
      const msg = String(e?.message || "");
      if (status === 429 || /rate_limited/i.test(msg)) {
        toast.error("You've hit the rewrite limit. Try again in an hour.");
      } else if (status === 400 || /empty_draft/i.test(msg)) {
        toast.error("Add a short draft first, then let AI polish it.");
      } else {
        toast.error("AI rewrite failed. Your draft is unchanged.");
      }
    } finally {
      setBusy(false);
    }
  };

  const paddingCls = size === "xs" ? "px-2 py-1 text-[11px]"
    : size === "lg" ? "px-4 py-2 text-sm"
    : "px-3 py-1.5 text-xs";

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      data-testid={testid}
      aria-label="Rewrite description with AI"
      className={
        `inline-flex items-center gap-1.5 rounded-full font-semibold ` +
        `text-white shadow-sm transition-opacity ` +
        `${paddingCls} ` +
        `${disabled ? "opacity-50 cursor-not-allowed" : "hover:opacity-90"} ` +
        `${className}`
      }
      style={{
        background:
          "linear-gradient(135deg, #2563EB 0%, #7C3AED 55%, #A855F7 100%)",
      }}
    >
      {busy ? (
        <Loader2
          size={size === "xs" ? 11 : 13}
          className="animate-spin"
          data-testid={`${testid}-spinner`}
        />
      ) : (
        <Sparkles
          size={size === "xs" ? 11 : 13}
          data-testid={`${testid}-icon`}
        />
      )}
      <span>{busy ? "Rewriting…" : "Rewrite with AI"}</span>
    </button>
  );
}
