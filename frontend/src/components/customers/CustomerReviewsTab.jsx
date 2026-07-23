// Feb-2026 · Item 8 — Customer profile "Reviews" tab.
//
// Lists every review request for the current customer and lets an
// admin click "Send review request" to fire a new one. Reuses the
// existing /api/reviews/requests endpoints — no new backend surface.
import React from "react";
import { toast } from "sonner";
import { Star, Send } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const OUTCOME_LABEL = {
  pending: "Requested",
  public_posted_intent: "Public",
  private_feedback_captured: "Private feedback",
  expired: "Expired",
  opted_out: "Opted out",
};

export default function CustomerReviewsTab({ customerId, jobs }) {
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [sending, setSending] = React.useState(false);
  const [channel, setChannel] = React.useState("both");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(`/reviews/requests?customer_id=${customerId}`);
      setRows(r?.requests || []);
    } catch (e) {
      toast.error(`Failed to load: ${e.message || e}`);
    } finally { setLoading(false); }
  }, [customerId]);
  React.useEffect(() => { load(); }, [load]);

  const send = async () => {
    setSending(true);
    try {
      // Prefer the customer's most recently completed job so the
      // internal notify email surfaces the right service context.
      const lastCompleted = (jobs || []).find((j) => j.status === "completed");
      await api.post("/reviews/requests", {
        customer_id: customerId,
        job_id: lastCompleted?.id || null,
        sent_via: channel,
      });
      toast.success("Review request queued");
      await load();
    } catch (e) {
      toast.error(`Send failed: ${e.message || e}`);
    } finally { setSending(false); }
  };

  return (
    <div className="space-y-3" data-testid="cd-reviews-tab">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
            Reviews & feedback
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Ask this customer for a review or view their feedback history.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className="text-xs px-2 py-1.5 rounded-md"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="cd-review-channel"
          >
            <option value="both">Email + SMS</option>
            <option value="email">Email only</option>
            <option value="sms">SMS only</option>
          </select>
          <button
            type="button"
            onClick={send}
            disabled={sending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold text-white hover:brightness-95 disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="cd-review-send-btn"
          >
            <Send size={12} /> {sending ? "Sending…" : "Send review request"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="cd-reviews-loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg p-6 text-center text-sm"
             style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px dashed ${colors.border}`,
                        color: colors.muted }}
             data-testid="cd-reviews-empty">
          No review requests yet. Send one above.
        </div>
      ) : (
        <ul className="space-y-2" data-testid="cd-reviews-list">
          {rows.map((r) => {
            const star = r.star_rating_submitted;
            const isLow = star != null && star <= 3;
            const isHigh = star != null && star >= 4;
            const outcome = r.outcome || (star ? (isHigh ? "public_posted_intent" : "private_feedback_captured") : "pending");
            return (
              <li key={r.id}
                  className="rounded-lg p-3 flex items-center gap-3"
                  style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}` }}
                  data-testid={`cd-review-row-${r.id}`}>
                <div className="flex-shrink-0 flex items-center gap-0.5"
                     data-testid={`cd-review-stars-${r.id}`}>
                  {star ? (
                    Array.from({ length: 5 }).map((_, i) => (
                      <Star key={i} size={13}
                             fill={i < star ? (isLow ? "#B91C1C" : "#EAB308") : "none"}
                             color={i < star ? (isLow ? "#B91C1C" : "#EAB308") : colors.muted}
                             strokeWidth={1.5} />
                    ))
                  ) : (
                    <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: colors.brandTertiary,
                                     color: colors.brand }}>
                      Requested
                    </span>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold truncate"
                       style={{ color: colors.onSurface }}>
                    {OUTCOME_LABEL[outcome] || outcome}
                    {isLow ? (
                      <span className="ml-2 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                            style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                            data-testid={`cd-review-followup-chip-${r.id}`}>
                        Follow-up needed
                      </span>
                    ) : null}
                  </div>
                  <div className="text-[10px]" style={{ color: colors.muted }}>
                    Sent {(r.sent_at || "").slice(0, 10)} · via {r.sent_via || "email"}
                  </div>
                </div>
                {isLow ? (
                  <a
                    href={`/admin/reviews/requests?focus=${r.id}`}
                    className="flex-shrink-0 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                    style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                    data-testid={`cd-review-followup-open-${r.id}`}
                  >Follow up →</a>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
