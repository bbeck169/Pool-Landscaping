/**
 * Phase S2 · Feb-2026 — Review Queue tab.
 *
 * Lists Soshie actions that need human review — those past the
 * 24hr window still pending, OR flagged for review by moderation
 * or by a low AI-image brand-score.  Per row:
 *
 *   * Publish now  (POST /ai-employees/actions/{aid}/approve
 *                     ?confirm_flags=1)
 *   * Reject       (POST /ai-employees/actions/{aid}/reject)
 *   * Edit draft   (PATCH /ai-employees/actions/{aid}/draft, then
 *                     re-fetches so re-moderation is reflected)
 *
 * Empty state: friendly "all caught up" message.
 */
import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { AlertTriangle, Bot, Camera, Check, Edit3, Loader2,
           ClipboardCopy, Send, Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, Skeleton, Chip, EmptyState, Modal, TextInput }
  from "@/components/ui-kit";


function Card({ children, className = "", testId }) {
  return (
    <div className={`rounded-2xl p-5 ${className}`}
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      {children}
    </div>
  );
}


function EditModal({ open, onClose, action, onDone }) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (action) {
      setText(action.draft?.text || "");
      setTitle(action.draft?.title || action.title || "");
    }
  }, [action]);

  const submit = async () => {
    if (!text.trim()) {
      toast.error("Draft text can't be empty");
      return;
    }
    setBusy(true);
    try {
      const next = await api.patch(
        `/ai-employees/actions/${action.id}/draft`,
        { text, title });
      const flags = (next?.moderation_flags || []).length;
      toast.success(
        flags
          ? `Draft saved · ${flags} moderation flag(s) still present`
          : "Draft saved — moderation clean",
      );
      onDone(next);
      onClose();
    } catch (e) {
      toast.error(e?.message || "Edit failed");
    } finally {
      setBusy(false);
    }
  };

  if (!action) return null;
  return (
    <Modal open={open} onClose={onClose}
             wide title="Edit draft"
             testid="review-queue-edit-modal"
             footer={
               <div className="flex gap-2 justify-end">
                 <Button variant="ghost" onClick={onClose}
                            disabled={busy}
                            testid="edit-cancel">Cancel</Button>
                 <Button onClick={submit} disabled={busy}
                            testid="edit-submit">
                   {busy ? <><Loader2 className="animate-spin mr-1.5"
                                        size={14} />Saving…</>
                             : "Save + re-moderate"}
                 </Button>
               </div>
             }>
      <div className="space-y-3">
        <TextInput label="Title" id="edit-title"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        testid="edit-title-input" />
        <div>
          <label className="block text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}
                    htmlFor="edit-text">Draft body</label>
          <textarea id="edit-text"
                        className="w-full px-3 py-2 rounded-lg text-sm"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface,
                                    minHeight: 200 }}
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        data-testid="edit-text-input" />
        </div>
      </div>
    </Modal>
  );
}


function ActionRow({ action, onDone }) {
  const [busy, setBusy] = useState(null);   // "publish"|"reject"|"edit"|"copy"|"posted"
  const [editOpen, setEditOpen] = useState(false);
  // Phase H5.5 · Feb-2026 — manual-only affordance. A row is
  // "manual-only" when the autopilot scheduler stamped it
  // ``awaiting_manual`` (the scheduler skips the wire dispatch
  // for platforms whose autopilot_config carries ``manual_only``:
  // Facebook, Instagram, LinkedIn, YouTube, TikTok, GBP, Reddit).
  // Copy + Mark Posted replace the "Publish now" button so
  // operators can hand-paste into the target platform.
  const isManualOnly = action.status === "awaiting_manual"
                          || !!action.manual_only_platform;
  const alreadyPosted = action.status === "published_manual"
                             || action.manual_posted_at;
  const flags = action.moderation_flags || [];
  const humanReq = !!action.requires_human_approval;
  const created = action.created_at
    ? new Date(action.created_at) : null;
  const ageHours = created
    ? Math.max(0,
        Math.floor((Date.now() - created.getTime()) / 3_600_000))
    : null;

  const publishNow = async () => {
    setBusy("publish");
    try {
      const r = await api.post(
        `/ai-employees/actions/${action.id}/approve?confirm_flags=1`);
      if (r?.status === "published") {
        toast.success("Published");
      } else if (r?.status === "failed") {
        toast.error(
          r?.result?.error || "Publisher returned failure");
      } else {
        toast.success(`Approved · ${r?.status}`);
      }
      onDone();
    } catch (e) {
      toast.error(e?.message || "Publish failed");
    } finally {
      setBusy(null);
    }
  };

  const copyToClipboard = async () => {
    setBusy("copy");
    try {
      const text = action.draft?.text
                       || action.draft_text
                       || action.summary
                       || "";
      const mediaUrl = action.media_url
                            || action.draft?.media_url
                            || "";
      const payload = mediaUrl ? `${text}\n\n${mediaUrl}` : text;
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(payload);
      } else {
        // Legacy fallback for jsdom / older browsers.
        const ta = document.createElement("textarea");
        ta.value = payload;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      toast.success("Copied to clipboard");
    } catch (e) {
      toast.error(e?.message || "Copy failed");
    } finally {
      setBusy(null);
    }
  };

  const markPosted = async () => {
    setBusy("posted");
    try {
      const r = await api.post(
        `/soshie/moderation/${action.id}/mark-posted`, {});
      if (r?.already_posted) {
        toast.info?.("Already marked as posted");
      } else {
        toast.success("Marked as posted");
      }
      onDone();
    } catch (e) {
      toast.error(e?.message || "Mark posted failed");
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    setBusy("reject");
    try {
      await api.post(
        `/ai-employees/actions/${action.id}/reject`,
        { note: "Rejected from review queue" });
      toast.success("Rejected");
      onDone();
    } catch (e) {
      toast.error(e?.message || "Reject failed");
    } finally {
      setBusy(null);
    }
  };

  const platform = (action.params?.platform)
                      || (action.draft?.platform)
                      || action.manual_only_platform
                      || (action.action?.startsWith("soshie.publish_blog")
                            ? "wordpress" : "—");
  const previewText = (action.draft?.text || action.summary || "")
                          .slice(0, 200);

  return (
    <div className="rounded-xl p-4"
         style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}` }}
         data-testid={`review-row-${action.id}`}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-sm font-semibold"
                     style={{ color: colors.onSurface }}
                     data-testid={`review-platform-${action.id}`}>
              {platform}
            </span>
            <span className="text-xs" style={{ color: colors.muted }}>
              · {action.action}
            </span>
            {ageHours != null ? (
              <Chip label={`${ageHours}h`} tone="neutral"
                       testid={`review-age-${action.id}`} />
            ) : null}
            {flags.length ? (
              <Chip label={`${flags.length} flag(s)`} tone="warning"
                       testid={`review-flag-chip-${action.id}`} />
            ) : null}
            {humanReq ? (
              <Chip label="Needs human review" tone="danger"
                       testid={`review-human-chip-${action.id}`} />
            ) : null}
            {action.status === "deferred_no_credits" ? (
              <Chip label="No credits" tone="warning"
                       testid={`review-nocred-${action.id}`} />
            ) : null}
          </div>
          <p className="text-sm whitespace-pre-wrap"
                style={{ color: colors.onSurface }}
                data-testid={`review-preview-${action.id}`}>
            {previewText}
            {previewText.length >= 200 ? "…" : ""}
          </p>
          {flags.length ? (
            <div className="mt-2 text-xs"
                    style={{ color: colors.warning }}
                    data-testid={`review-flags-detail-${action.id}`}>
              <AlertTriangle size={12} className="inline mr-1" />
              {flags.map((f) => f.match || f.type).join(", ")}
            </div>
          ) : null}
        </div>
        {action.media_url ? (
          <div className="flex-shrink-0">
            <img src={action.media_url} alt="media"
                    className="w-20 h-20 rounded-lg object-cover"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid={`review-media-${action.id}`} />
            <div className="mt-1 flex items-center gap-1 justify-center">
              {action.media_source === "ai_generated" ? (
                <>
                  <Bot size={12} style={{ color: colors.muted }} />
                  <span className="text-xs"
                           style={{ color: colors.muted }}
                           data-testid={`review-media-source-${action.id}`}>
                    AI · {(action.brand_score ?? 0).toFixed(2)}
                  </span>
                </>
              ) : (
                <>
                  <Camera size={12} style={{ color: colors.muted }} />
                  <span className="text-xs"
                           style={{ color: colors.muted }}
                           data-testid={`review-media-source-${action.id}`}>
                    Real photo
                  </span>
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>
      <div className="mt-3 flex gap-2 flex-wrap">
        {isManualOnly ? (
          <>
            {/* Phase H5.5 · Feb-2026 — Manual-only affordance
                for platforms whose autopilot_config carries
                ``manual_only``. Copy + Mark Posted replace the
                "Publish now" wire path. */}
            <Button variant="primary" onClick={copyToClipboard}
                       disabled={busy != null}
                       testid={`review-copy-${action.id}`}>
              {busy === "copy"
                ? <><Loader2 className="animate-spin mr-1.5" size={14} />Copying…</>
                : <><ClipboardCopy size={14} className="mr-1.5" />Copy post to clipboard</>}
            </Button>
            <Button variant="ghost" onClick={markPosted}
                       disabled={busy != null || !!alreadyPosted}
                       testid={`review-mark-posted-${action.id}`}>
              {busy === "posted"
                ? <><Loader2 className="animate-spin mr-1.5" size={14} />Marking…</>
                : (alreadyPosted
                    ? <><Check size={14} className="mr-1.5" />Posted</>
                    : <><Send size={14} className="mr-1.5" />Mark as posted</>)}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={publishNow}
                     disabled={busy != null}
                     testid={`review-publish-${action.id}`}>
            {busy === "publish"
              ? <><Loader2 className="animate-spin mr-1.5" size={14} />Publishing…</>
              : <><Check size={14} className="mr-1.5" />Publish now</>}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setEditOpen(true)}
                   disabled={busy != null}
                   testid={`review-edit-${action.id}`}>
          <Edit3 size={14} className="mr-1.5" />Edit
        </Button>
        <Button variant="danger" onClick={reject}
                   disabled={busy != null}
                   testid={`review-reject-${action.id}`}>
          {busy === "reject"
            ? <><Loader2 className="animate-spin mr-1.5" size={14} />Rejecting…</>
            : <><Trash2 size={14} className="mr-1.5" />Reject</>}
        </Button>
      </div>
      <EditModal open={editOpen} action={action}
                     onClose={() => setEditOpen(false)}
                     onDone={onDone} />
    </div>
  );
}


export default function ReviewQueueTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Pull every Soshie action row and filter client-side; the
      // review-queue definition (age ≥ 24hr OR flagged OR
      // requires_human_approval OR deferred_no_credits) is small
      // enough that a filter here beats adding a specialised
      // endpoint.
      const r = await api.get(
        "/ai-employees/actions?employee_key=soshie&status=pending&limit=100");
      const all = r?.items || r || [];
      const filtered = all.filter((a) => {
        const ageMs = a.created_at
          ? Date.now() - new Date(a.created_at).getTime() : 0;
        const past24h = ageMs >= 24 * 3_600_000;
        const flagged = (a.moderation_flags || []).length > 0;
        const humanReq = !!a.requires_human_approval;
        return past24h || flagged || humanReq;
      });
      // Also pull deferred_no_credits.
      const r2 = await api.get(
        "/ai-employees/actions?employee_key=soshie&status=deferred_no_credits&limit=100");
      const deferred = r2?.items || r2 || [];
      // Phase H5.5 · Feb-2026 — pull ``awaiting_manual`` rows so the
      // manual-only draft flow lands in the same review queue as the
      // wire-path items. Copy + Mark Posted affordances are gated
      // in ActionRow by the row's status.
      const r3 = await api.get(
        "/ai-employees/actions?employee_key=soshie&status=awaiting_manual&limit=100");
      const manualReady = r3?.items || r3 || [];
      const merged = [...filtered, ...deferred, ...manualReady];
      merged.sort((a, b) =>
        (a.created_at || "").localeCompare(b.created_at || ""));
      setRows(merged);
    } catch (e) {
      toast.error(e?.message || "Couldn't load review queue");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="space-y-3" data-testid="review-queue-loading">
        <Skeleton className="h-32 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
      </div>
    );
  }
  if (!rows.length) {
    return (
      <Card testId="review-queue-empty">
        <EmptyState
          icon={Check}
          title="Nothing to review"
          hint="You're all caught up — Soshie will let you know when the next draft needs attention."
        />
      </Card>
    );
  }
  return (
    <div className="space-y-3" data-testid="review-queue-list">
      {rows.map((a) => (
        <ActionRow key={a.id} action={a} onDone={load} />
      ))}
    </div>
  );
}
