/**
 * Ticket LL · Feb-2026 — shared AI Rewrite button.
 *
 * Drop next to any operator-authored compose textarea. Click
 * polishes the current draft in a professional tone and replaces
 * the field content in-place; the operator sees a 10-second
 * "Undo" affordance that restores the pre-rewrite text if they
 * don't like the result.
 *
 * Props:
 *   value: string — the current draft text (controlled by parent).
 *   onReplace: (newText) => void — parent setter; called on
 *     successful rewrite AND on Undo.
 *   disabled?: boolean — external disable (busy parent, send-in-
 *     flight, etc).  The button also disables itself when
 *     ``value.trim().length < minLength`` (default 10).
 *   minLength?: number = 10 — mirrors the backend's defense-in-
 *     depth ``REWRITE_TOO_SHORT`` gate.
 *   dataTestid?: string = "ai-rewrite-btn" — a per-surface
 *     override lets each compose surface's smoke test target the
 *     button without ambiguity when multiple rewrite buttons are
 *     visible (e.g. mass-text modal vs lead compose modal
 *     rendered in a shared storybook).
 *
 * Internal states:
 *   idle            — ready to rewrite.
 *   rewriting       — POST in flight, spinner shown.
 *   undo-available  — rewrite succeeded, 10-sec Undo window
 *                     active; the ORIGINAL text is stashed in
 *                     ``originalRef`` so Undo restores exactly
 *                     what the operator had before the click.
 *                     The Undo window is cleared early if the
 *                     operator edits the output (``value`` prop
 *                     changes to something different from the
 *                     stashed ``rewrittenRef``).
 *
 * Error handling (via sonner toast):
 *   * 429 ``REWRITE_COOLDOWN`` → "Slow down between rewrites."
 *   * 429 ``REWRITE_HOURLY_CAP`` → "You've hit this hour's
 *     rewrite limit — try again at the top of the hour."
 *   * 503 ``REWRITE_UPSTREAM_UNAVAILABLE`` /
 *     ``REWRITE_EMPTY_RESULT`` → "AI service unavailable."
 *   * 400 ``REWRITE_TOO_SHORT`` (shouldn't fire — the FE gate
 *     mirrors the BE gate — but handled defensively) → inline
 *     tooltip, no toast.
 *   * everything else → "Rewrite failed."
 *
 * No merge-tag resolution happens here — that's Ticket NN's
 * server-side resolver which runs AFTER the operator sends.  The
 * rewrite endpoint's system prompt is explicitly instructed to
 * preserve ``{{MERGE_TAG}}`` tokens verbatim so the Ticket NN
 * resolver still works unchanged.
 */
import React, { useEffect, useRef, useState } from "react";
import { Sparkles, Loader2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";

const _UNDO_WINDOW_MS = 10_000;

export default function AiRewriteButton({
  value,
  onReplace,
  disabled = false,
  minLength = 10,
  dataTestid = "ai-rewrite-btn",
}) {
  const [state, setState] = useState("idle"); // idle | rewriting | undo-available
  const originalRef = useRef("");             // text BEFORE rewrite
  const rewrittenRef = useRef("");            // text immediately AFTER rewrite
  const undoTimerRef = useRef(null);          // setTimeout id
  const trimmedLen = (value || "").trim().length;
  const belowThreshold = trimmedLen < minLength;
  const canClick = !disabled && state !== "rewriting" && !belowThreshold;

  // Clear the Undo window if the operator edits the output text
  // (any change away from ``rewrittenRef``).  Also fires on
  // unmount so a modal close doesn't leave a dangling timer.
  useEffect(() => {
    if (state !== "undo-available") return;
    if ((value || "") !== rewrittenRef.current) {
      // Operator edited the output — Undo is no longer meaningful.
      if (undoTimerRef.current) {
        clearTimeout(undoTimerRef.current);
        undoTimerRef.current = null;
      }
      setState("idle");
    }
  }, [value, state]);

  useEffect(() => () => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
  }, []);

  const handleRewrite = async () => {
    if (!canClick) return;
    const draft = (value || "").trim();
    originalRef.current = value || "";
    setState("rewriting");
    try {
      const res = await api.post("/ai/rewrite", { text: draft });
      const rewritten = (res && res.rewritten) || "";
      if (!rewritten) {
        toast.error("AI service unavailable.");
        setState("idle");
        return;
      }
      rewrittenRef.current = rewritten;
      onReplace?.(rewritten);
      setState("undo-available");
      // Start the Undo window.
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
      undoTimerRef.current = setTimeout(() => {
        undoTimerRef.current = null;
        setState("idle");
      }, _UNDO_WINDOW_MS);
    } catch (e) {
      const detail = e?.data?.detail || {};
      const code = String(detail.code || "");
      if (code === "REWRITE_COOLDOWN") {
        toast.error("Slow down between rewrites.");
      } else if (code === "REWRITE_HOURLY_CAP") {
        toast.error(
          "You've hit this hour's rewrite limit — try again at the top of the hour.",
        );
      } else if (code === "REWRITE_UPSTREAM_UNAVAILABLE"
                   || code === "REWRITE_EMPTY_RESULT") {
        toast.error("AI service unavailable.");
      } else if (code === "REWRITE_TOO_SHORT") {
        // FE gate already prevents this — defensive no-op toast.
      } else {
        toast.error("Rewrite failed.");
      }
      setState("idle");
    }
  };

  const handleUndo = () => {
    if (state !== "undo-available") return;
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
    onReplace?.(originalRef.current);
    setState("idle");
  };

  if (state === "undo-available") {
    return (
      <button
        type="button"
        onClick={handleUndo}
        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold text-white hover:brightness-95"
        style={{ backgroundColor: "#475569" }}
        title="Undo AI rewrite (10s)"
        data-testid={`${dataTestid}-undo`}
      >
        <Undo2 size={11} /> Undo
      </button>
    );
  }

  const label = state === "rewriting" ? "Rewriting…" : "Rewrite with AI";
  const title = belowThreshold
    ? `Draft at least ${minLength} characters first`
    : "Rewrite in a professional tone";
  return (
    <button
      type="button"
      onClick={handleRewrite}
      disabled={!canClick}
      className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
      style={{
        backgroundColor: "#F1F5F9",
        color: "#0F172A",
        border: "1px solid #CBD5E1",
      }}
      title={title}
      data-testid={dataTestid}
    >
      {state === "rewriting"
        ? <Loader2 size={11} className="animate-spin" />
        : <Sparkles size={11} />}
      {label}
    </button>
  );
}
