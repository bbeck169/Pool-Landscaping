/**
 * Ticket KK · Feb-2026 — Mass Text modal.
 *
 * Opened from the Customers list bulk action bar. The operator has
 * already selected N customers via the row checkboxes; this modal
 * composes the SMS body (free-text + optional template pick) and
 * fires ``POST /customers/bulk-sms`` with the explicit customer_ids
 * array.
 *
 * Scope decisions (locked in the KK pre-audit receipt):
 *   * No two-step preview/confirm — the Mass Text modal lives
 *     downstream of an explicit checkbox selection, so a
 *     client-side destructive confirm (Confirm / Cancel footer)
 *     is sufficient. Server stays the security boundary via admin
 *     RBAC + K72 safety guards + per-tenant rate limit.
 *   * Templates reused from the existing marketing SMS library
 *     (`GET /api/marketing/templates/sms`) — the same collection
 *     the backend's ``_load_template`` helper hydrates on resolve.
 *   * LL inert placeholder slot — a disabled "AI rewrite" button
 *     sits in the textarea toolbar so Ticket LL can wire it in
 *     retroactively without re-shaping the modal's layout.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Modal, Button } from "@/components/ui-kit";
import { Sparkles, Hash } from "lucide-react";
import AiRewriteButton from "@/components/ai/AiRewriteButton";
import { MergeTagPalette } from "@/components/marketing/MergeTagPalette";
import { colors } from "@/theme";
import { api } from "@/api";
import { toast as sonnerToast } from "sonner";

// ─── SMS segment estimator ───────────────────────────────────────
// GSM-7 segments: 160 chars per segment; multi-segment UDH packs
// drop the limit to 153 chars after the first segment. Characters
// outside the GSM-7 set bump the whole message to UCS-2 (70 chars
// per segment, 67 after the first). We approximate: any non-ASCII
// char forces UCS-2. The estimator powers an inline "N chars · M
// segment(s)" readout; it does NOT block Send.
function estimateSmsSegments(text) {
  const t = text || "";
  if (!t) return { chars: 0, segments: 0, encoding: "GSM-7" };
  const ucs2 = /[^\x00-\x7F]/.test(t);
  const first = ucs2 ? 70 : 160;
  const multi = ucs2 ? 67 : 153;
  if (t.length <= first) {
    return { chars: t.length, segments: 1, encoding: ucs2 ? "UCS-2" : "GSM-7" };
  }
  const segments = Math.ceil(t.length / multi);
  return { chars: t.length, segments, encoding: ucs2 ? "UCS-2" : "GSM-7" };
}

export default function MassTextModal({ open, customerIds, onClose, onSent }) {
  const [message, setMessage] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmArmed, setConfirmArmed] = useState(false);
  // TD-mass-text-merge-tag-toolbar · Feb-2026 — Insert-tag toolbar.
  // Palette open/close is local to this modal. ``textareaRef`` lets
  // the insert handler splice at the current selection instead of
  // dumb-appending, so a mid-message insert is non-destructive.
  const [paletteOpen, setPaletteOpen] = useState(false);
  const textareaRef = useRef(null);

  const recipientCount = (customerIds || []).length;
  const estimate = useMemo(() => estimateSmsSegments(message), [message]);

  // Reset modal state whenever it re-opens so a prior session's
  // body doesn't bleed into a fresh selection.
  useEffect(() => {
    if (!open) return;
    setMessage("");
    setTemplateId("");
    setConfirmArmed(false);
    setPaletteOpen(false);
  }, [open]);

  // Load SMS marketing templates (reused across the KK modal + the
  // mass_messaging compose dialog + Marketing Studio). Fire-and-
  // forget — empty list is a valid state (admin can type a
  // free-text message instead).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setTemplatesLoading(true);
    api.get("/marketing/templates/sms")
      .then((res) => {
        if (!alive) return;
        const rows = Array.isArray(res) ? res : (res?.items || []);
        setTemplates(rows);
      })
      .catch(() => { if (alive) setTemplates([]); })
      .finally(() => { if (alive) setTemplatesLoading(false); });
    return () => { alive = false; };
  }, [open]);

  const onPickTemplate = (tid) => {
    setTemplateId(tid);
    const tpl = templates.find((t) => t.id === tid);
    if (tpl) {
      setMessage((tpl.body || "").trim());
    }
  };

  // TD-mass-text-merge-tag-toolbar · Feb-2026 — splice a merge-tag
  // token (already ``{{WRAPPED}}`` by MergeTagPalette.onInsert) at
  // the textarea's current selection. Falls back to appending when
  // the ref isn't attached yet (shouldn't happen post-mount, but
  // keeps the handler defensive). Refocuses the textarea and parks
  // the caret immediately after the inserted token so the operator
  // can keep typing.
  const insertAtCursor = useCallback((wrappedToken) => {
    if (typeof wrappedToken !== "string" || !wrappedToken) return;
    setMessage((prev) => {
      const el = textareaRef.current;
      const prior = prev || "";
      if (!el || typeof el.selectionStart !== "number") {
        return prior + wrappedToken;
      }
      const start = el.selectionStart;
      const end = el.selectionEnd;
      const next = prior.slice(0, start) + wrappedToken + prior.slice(end);
      const caret = start + wrappedToken.length;
      // Restore focus + caret after React has flushed the new value.
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          textareaRef.current.focus();
          try {
            textareaRef.current.setSelectionRange(caret, caret);
          } catch { /* jsdom / older browsers — non-fatal */ }
        }
      });
      return next;
    });
  }, []);

  const canSend = recipientCount > 0 && (message || "").trim().length > 0 && !busy;

  const doSend = async () => {
    if (!canSend) return;
    setBusy(true);
    try {
      const res = await api.post("/customers/bulk-sms", {
        customer_ids: customerIds,
        message: (message || "").trim(),
        template_id: templateId || undefined,
      });
      const queued = res?.queued ?? 0;
      const skippedOptOut = res?.skipped_opt_out ?? 0;
      const skippedNoPhone = res?.skipped_no_phone ?? 0;
      const descBits = [];
      if (skippedOptOut > 0) descBits.push(`${skippedOptOut} opted-out`);
      if (skippedNoPhone > 0) descBits.push(`${skippedNoPhone} no phone`);
      sonnerToast.success(
        `Mass Text queued to ${queued} customer${queued === 1 ? "" : "s"}`,
        descBits.length ? { description: `Skipped: ${descBits.join(" · ")}` } : undefined,
      );
      if (onSent) onSent(res);
      if (onClose) onClose();
    } catch (e) {
      const code = e?.detail?.code || e?.response?.data?.detail?.code;
      if (code === "RATE_LIMITED") {
        sonnerToast.error("Please wait a few minutes before sending another mass text.");
      } else {
        sonnerToast.error(e?.message || "Mass Text failed");
      }
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <Modal
      open={open}
      onClose={() => { if (!busy) onClose && onClose(); }}
      title="Mass Text"
      testid="mass-text-modal"
      wide
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => { if (!busy) onClose && onClose(); }}
            testid="mass-text-cancel"
          >
            Cancel
          </Button>
          {confirmArmed ? (
            <button
              type="button"
              onClick={doSend}
              disabled={!canSend}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
              style={{ backgroundColor: "#DC2626" }}
              data-testid="mass-text-send-confirm"
            >
              {busy ? "Sending…" : `Yes, send to ${recipientCount}`}
            </button>
          ) : (
            <Button
              variant="primary"
              onClick={() => setConfirmArmed(true)}
              disabled={!canSend}
              testid="mass-text-send"
            >
              Send to {recipientCount} customer{recipientCount === 1 ? "" : "s"}
            </Button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {/* Recipient count — surfaces the selection the operator is
            about to blast. Doubles as a defensive readout when the
            selection changes while the modal is open (shouldn't
            happen in the current CustomersList flow, but harmless). */}
        <div
          className="rounded-lg px-3 py-2 text-sm font-semibold"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
          data-testid="mass-text-recipient-count"
        >
          Sending to {recipientCount} customer{recipientCount === 1 ? "" : "s"}
        </div>

        {/* Template picker — tenant-scoped SMS marketing templates.
            Picking one fills the textarea; the operator can still
            edit afterwards. The template_id is bound to the request
            so the backend logs which template a KK broadcast used. */}
        <div>
          <label
            className="block text-xs font-semibold mb-1.5"
            style={{ color: colors.muted }}
            htmlFor="mass-text-template-picker"
          >
            Start from a template (optional)
          </label>
          <select
            id="mass-text-template-picker"
            value={templateId}
            onChange={(e) => onPickTemplate(e.target.value)}
            disabled={templatesLoading || busy}
            className="w-full text-sm px-3 py-2 rounded-lg"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="mass-text-template-picker"
          >
            <option value="">
              {templatesLoading ? "Loading templates…" : "— Write a custom message —"}
            </option>
            {templates.map((t) => (
              <option
                key={t.id}
                value={t.id}
                data-testid={`mass-text-template-option-${t.id}`}
              >
                {t.name || t.code || t.id}
              </option>
            ))}
          </select>
        </div>

        {/* Compose textarea + inert LL rewrite slot. The slot is a
            disabled button today; Ticket LL will swap in the
            AiRewriteButton without reshaping the toolbar. */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              className="block text-xs font-semibold"
              style={{ color: colors.muted }}
              htmlFor="mass-text-body"
            >
              Message
            </label>
            <div
              className="inline-flex items-center gap-1"
              data-testid="mass-text-rewrite-slot"
            >
              {/* TD-mass-text-merge-tag-toolbar · Feb-2026 — Insert
                  merge-tag opener.  Reuses the existing
                  <MergeTagPalette> catalog (shared with email
                  compose surfaces); on insert the handler splices
                  the canonical ``{{UPPER_CASE_TAG}}`` at the
                  textarea's current selection. */}
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                disabled={busy}
                className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full disabled:opacity-60"
                style={{
                  backgroundColor: colors.surfaceTertiary,
                  color: colors.onSurfaceSecondary,
                }}
                data-testid="mass-text-insert-tag-btn"
                aria-label="Insert merge tag"
              >
                <Hash className="w-3 h-3" />
                Insert tag
              </button>
              {/* Ticket LL · Feb-2026 — reserved rewrite slot now
                  carries the live <AiRewriteButton>.  Replaces the
                  Ticket KK inert placeholder.  Visual size matches
                  the placeholder's 11px chip so the swap is
                  byte-identical. */}
              <AiRewriteButton
                value={message}
                onReplace={setMessage}
                disabled={busy}
                dataTestid="mass-text-rewrite-btn"
              />
            </div>
          </div>
          <textarea
            id="mass-text-body"
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={busy}
            rows={6}
            placeholder="Type your SMS message here — merge tags like {{first_name}} are supported."
            className="w-full text-sm px-3 py-2 rounded-lg"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="mass-text-body"
          />
          <div
            className="mt-1 text-xs"
            style={{ color: colors.muted }}
            data-testid="mass-text-segments"
          >
            {estimate.chars} char{estimate.chars === 1 ? "" : "s"} ·{" "}
            {estimate.segments} segment{estimate.segments === 1 ? "" : "s"}
            {estimate.encoding === "UCS-2" ? " · UCS-2 (unicode)" : ""}
          </div>
        </div>

        {confirmArmed ? (
          <div
            className="rounded-lg px-3 py-2 text-sm"
            style={{
              backgroundColor: "#FEE2E2",
              color: "#991B1B",
              border: "1px solid #FCA5A5",
            }}
            data-testid="mass-text-confirm-banner"
            role="alert"
          >
            This will send to {recipientCount} customer
            {recipientCount === 1 ? "" : "s"}. Opted-out and
            no-phone customers are skipped automatically.
          </div>
        ) : null}

        {/* TD-mass-text-merge-tag-toolbar · Feb-2026 — shared
            MergeTagPalette.  Conditionally mounted on ``paletteOpen``
            so the catalog fetch only fires when the operator opts
            in, and the Radix Dialog portal is torn down between
            opens.  ``onInsert`` receives a pre-wrapped ``{{TOKEN}}``
            string from the palette. */}
        <MergeTagPalette
          open={paletteOpen}
          onOpenChange={setPaletteOpen}
          onInsert={insertAtCursor}
        />
      </div>
    </Modal>
  );
}
