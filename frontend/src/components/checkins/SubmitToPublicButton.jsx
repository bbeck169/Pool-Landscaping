import React from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Send, X, Camera } from "lucide-react";

/**
 * MR0 · Feb-2026 — Submit a check-in to the public moderation queue.
 *
 * Renders a small button; clicking opens a modal with the two required
 * checkboxes. Both must be ticked before the "Submit for review"
 * button is enabled. On success we toast + call the ``onSubmitted``
 * callback with the created ``public_checkin_id``.
 *
 * Backing endpoint: ``POST /api/checkins/{checkin_id}/submit-public``
 *
 * The endpoint enforces the same gate server-side — this component is
 * a UX safety net, not the source of truth for the rules.
 */
export default function SubmitToPublicButton({
  checkinId,
  defaultDescription = "",
  onSubmitted = () => {},
  disabled = false,
}) {
  const [open, setOpen] = React.useState(false);
  const [publish, setPublish] = React.useState(false);
  const [ack, setAck] = React.useState(false);
  const [description, setDescription] = React.useState(defaultDescription);
  const [busy, setBusy] = React.useState(false);

  const canSubmit = publish && ack && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      const res = await api.post(
        `/checkins/${encodeURIComponent(checkinId)}/submit-public`,
        {
          publish_to_website: publish,
          photo_license_ack: ack,
          description: description || undefined,
        },
      );
      if (res?.submitted) {
        toast.success("Submitted for review", {
          description: "An admin will review this check-in before it goes public.",
        });
        onSubmitted(res.public_checkin_id);
        setOpen(false);
      } else {
        toast.info("Not submitted", {
          description: "Both boxes must be ticked to publish.",
        });
      }
    } catch (e) {
      const msg = e?.response?.data?.error || e?.message || "Failed";
      if (msg === "already_submitted") {
        toast.info("Already in the queue", {
          description: "This check-in has already been submitted for review.",
        });
        setOpen(false);
      } else {
        toast.error("Could not submit", { description: msg });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-md"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        data-testid="submit-public-open"
        aria-label="Submit check-in to public review"
      >
        <Camera size={12} /> Publish to website…
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ backgroundColor: "rgba(15,23,42,0.5)" }}
          role="dialog"
          aria-modal="true"
          data-testid="submit-public-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-5"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <div
                className="text-base font-semibold"
                style={{ color: colors.onSurface }}
              >
                Submit for public display
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="p-1"
                aria-label="Close"
                data-testid="submit-public-close"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs mb-3" style={{ color: colors.muted }}>
              Both boxes must be checked. Submissions land in the moderation
              queue and are reviewed by an admin before appearing publicly.
              Street numbers are automatically hidden on publish.
            </p>

            <label
              className="flex items-start gap-2 text-sm cursor-pointer p-2 rounded-lg"
              style={{ color: colors.onSurface, backgroundColor: publish ? "#ECFDF5" : "transparent" }}
            >
              <input
                type="checkbox"
                checked={publish}
                onChange={(e) => setPublish(e.target.checked)}
                data-testid="submit-public-publish"
                className="mt-1"
              />
              <span>
                <span className="font-semibold">Publish to website</span>
                <span
                  className="block text-xs mt-0.5"
                  style={{ color: colors.muted }}
                >
                  Send this check-in to the public moderation queue.
                </span>
              </span>
            </label>

            {publish ? (
              <label
                className="flex items-start gap-2 text-sm cursor-pointer p-2 rounded-lg mt-1"
                style={{ color: colors.onSurface, backgroundColor: ack ? "#ECFDF5" : "transparent" }}
              >
                <input
                  type="checkbox"
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                  data-testid="submit-public-ack"
                  className="mt-1"
                />
                <span>
                  <span className="font-semibold">Cleared for public display</span>
                  <span
                    className="block text-xs mt-0.5"
                    style={{ color: colors.muted }}
                  >
                    I have the customer's permission to publish the photos + notes.
                  </span>
                </span>
              </label>
            ) : null}

            <label className="block mt-3 text-xs font-semibold" style={{ color: colors.muted }}>
              Description (optional)
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                data-testid="submit-public-description"
                className="mt-1 w-full rounded-lg p-2 text-sm"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
              />
            </label>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="h-9 px-3 rounded-lg text-sm font-semibold"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="submit-public-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={!canSubmit}
                className="h-9 px-3 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                style={{
                  backgroundColor: canSubmit ? "#10B981" : "#94A3B8",
                  color: "#fff",
                  border: 0,
                  cursor: canSubmit ? "pointer" : "not-allowed",
                }}
                data-testid="submit-public-submit"
              >
                <Send size={14} />
                {busy ? "Submitting…" : "Submit for review"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
