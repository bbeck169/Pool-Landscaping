/**
 * AI Write button · Feb-2026.
 *
 * Sits next to a description textarea. Two modes:
 *
 * 1. **Write** — the current field is either empty or user-authored.
 *    Click posts to ``/checkins/{id}/ai-description``. On success,
 *    the previous field content is stashed and the AI-generated
 *    text overwrites the field. Button caption flips to "Undo AI".
 *
 * 2. **Undo AI** — the field currently shows AI-generated text.
 *    Click restores the stashed pre-AI content and the button flips
 *    back to "AI Write".
 *
 * The parent owns the field state (``value`` + ``onChange``) — this
 * component only pushes new text through ``onChange`` and manages
 * its own ``preAiValue`` stash.
 *
 * Toasts (via sonner):
 *   * 429 → "AI Write rate limit reached. Try again in {N} minutes."
 *   * 500 / network → "AI Write failed. Please write manually."
 *   * success → no toast (the text update IS the feedback)
 */
import React, { useState } from "react";
import { Sparkles, Loader2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";

export default function AIWriteButton({
  checkinId,
  currentValue,
  onGenerated,
  disabled = false,
  size = "sm",
  className = "",
  testid = "checkin-ai-write-btn",
}) {
  const [busy, setBusy] = useState(false);
  const [preAiValue, setPreAiValue] = useState(null);
  const isUndoMode = preAiValue !== null;
  const controlDisabled = disabled || busy || !checkinId;

  const handleClick = async () => {
    if (controlDisabled) return;
    if (isUndoMode) {
      onGenerated?.(preAiValue);
      setPreAiValue(null);
      return;
    }

    setBusy(true);
    try {
      const res = await api.post(
        `/checkins/${encodeURIComponent(checkinId)}/ai-description`,
        { tone: "neutral_factual" },
      );
      const text = (res && res.description) || "";
      if (!text) {
        toast.error("AI Write failed. Please write manually.");
        return;
      }
      setPreAiValue(currentValue || "");
      onGenerated?.(text);
    } catch (e) {
      const status = e?.status || e?.response?.status;
      // The shared fetch wrapper attaches the parsed response body
      // to ``err.data`` (see ``/app/frontend/src/api.js`` — Customer
      // Delete UX overhaul commit). ``err.data.detail`` carries the
      // structured ``{code, retry_after_seconds}`` payload from the
      // backend rate limiter.
      const detail = e?.data?.detail || {};
      const retrySeconds = typeof detail.retry_after_seconds === "number"
        ? detail.retry_after_seconds
        : null;
      const code = String(detail.code || "");

      if (status === 429 || code === "rate_limit_exceeded") {
        const minutes = retrySeconds
          ? Math.max(1, Math.ceil(retrySeconds / 60))
          : 60;
        toast.error(
          `AI Write rate limit reached. Try again in ${minutes} minutes.`,
        );
      } else {
        toast.error("AI Write failed. Please write manually.");
      }
    } finally {
      setBusy(false);
    }
  };

  const paddingCls = size === "xs" ? "px-2 py-1 text-[11px]"
    : size === "lg" ? "px-4 py-2 text-sm"
    : "px-3 py-1.5 text-xs";
  const iconSize = size === "xs" ? 11 : 13;
  const IconComp = busy ? Loader2 : isUndoMode ? Undo2 : Sparkles;
  const label = busy ? "Writing…" : isUndoMode ? "Undo AI" : "AI Write";

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={controlDisabled}
      data-testid={testid}
      data-state={isUndoMode ? "undo" : "write"}
      aria-label={isUndoMode ? "Undo AI-generated description"
                                : "Generate AI description"}
      className={
        `inline-flex items-center gap-1.5 rounded-full font-semibold ` +
        `shadow-sm transition-opacity ${paddingCls} ` +
        `${controlDisabled ? "opacity-50 cursor-not-allowed" : "hover:opacity-90"} ` +
        `${isUndoMode ? "bg-slate-700 text-white" : "text-white"} ` +
        className
      }
      style={isUndoMode ? undefined : {
        background:
          "linear-gradient(135deg, #A855F7 0%, #7C3AED 55%, #2563EB 100%)",
      }}
    >
      <IconComp
        size={iconSize}
        className={busy ? "animate-spin" : ""}
        data-testid={`${testid}-icon`}
      />
      <span>{label}</span>
    </button>
  );
}
