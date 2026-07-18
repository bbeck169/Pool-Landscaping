/**
 * Ship 3 · Item B — Recommendations Queue widget.
 *
 * Surfaces price-increase draft emails older than 7 days so admins can
 * clear the "I saved a draft and forgot" pile. View → opens read-only
 * preview of the draft body. Send → fires via Resend pipeline
 * (graceful fallback). Discard → marks status=discarded.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, ChevronDown, ChevronRight, Send, X, Eye, Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


export default function RecommendationsQueueWidget() {
  const [expand, setExpand] = useState(true);
  const [state, setState] = useState({ loading: true, err: "", rows: [] });
  const [preview, setPreview] = useState(null);   // {row, subject, ...}
  const [busy, setBusy] = useState(null);         // action being fired

  const load = async () => {
    setState({ loading: true, err: "", rows: [] });
    try {
      const r = await api.get("/recommendations-queue?older_than_days=7");
      setState({ loading: false, err: "", rows: r.rows || [] });
    } catch (e) {
      setState({ loading: false, err: e.message || "Failed to load", rows: [] });
    }
  };
  useEffect(() => { load(); }, []);

  const openPreview = (row) => setPreview({ row, action: null, result: null });
  const closePreview = () => setPreview(null);

  const doSend = async (row) => {
    setBusy(`send-${row.id}`);
    try {
      const r = await api.post(`/recommendations-queue/${row.id}/send`, {});
      setPreview({ row, action: "send", result: r });
      await load();
    } catch (e) {
      setPreview({ row, action: "send", result: { error: e.message } });
    }
    setBusy(null);
  };
  const doDiscard = async (row) => {
    if (!window.confirm(`Discard draft for ${row.customer_name}? Row is preserved for audit but hidden from this queue.`)) return;
    setBusy(`discard-${row.id}`);
    try {
      await api.post(`/recommendations-queue/${row.id}/discard`, {});
      await load();
    } catch (e) {
      setState({ ...state, err: e.message });
    }
    setBusy(null);
  };

  const count = state.rows.length;
  return (
    <div className="rounded-2xl p-4 mb-6"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="recs-queue-widget">
      <button type="button" onClick={() => setExpand(!expand)}
              className="w-full flex items-center justify-between text-left"
              style={{ background: "transparent", border: 0, cursor: "pointer" }}
              data-testid="recs-queue-toggle">
        <div className="flex items-center gap-2">
          <TrendingUp size={18} color={colors.brand} />
          <div>
            <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
              Stale price-increase drafts
            </div>
            {state.loading ? (
              <div className="text-xs" style={{ color: colors.muted }}>Loading…</div>
            ) : state.err ? (
              <div className="text-xs" style={{ color: "#DC2626" }}>{state.err}</div>
            ) : count === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }} data-testid="recs-queue-empty">
                No stale price-increase drafts. Nice hygiene.
              </div>
            ) : (
              <div className="text-xs" style={{ color: colors.muted }} data-testid="recs-queue-summary">
                <b>{count}</b> draft{count === 1 ? "" : "s"} older than 7 days · click to review
              </div>
            )}
          </div>
        </div>
        {expand ? <ChevronDown size={14} color={colors.muted} />
                : <ChevronRight size={14} color={colors.muted} />}
      </button>

      {expand && count > 0 ? (
        <div className="mt-3 rounded-md overflow-hidden"
             style={{ border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="recs-queue-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Customer</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Current</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Recommended</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Gap</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Age (d)</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {state.rows.map((r) => (
                <tr key={r.id} data-testid={`recs-queue-row-${r.id}`}>
                  <td className="px-3 py-2 font-bold" style={{ color: colors.onSurface }}>
                    {r.customer_name || "(no name)"}
                    <div className="text-[10px] font-normal" style={{ color: colors.muted }}>
                      {r.customer_email || "no email"}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">${r.current_price?.toFixed?.(2)}</td>
                  <td className="px-3 py-2 text-right">${r.recommended_price?.toFixed?.(2)}</td>
                  <td className="px-3 py-2 text-right font-semibold" style={{ color: "#166534" }}>
                    +{r.gap_pct}%
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>{r.age_days}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button onClick={() => openPreview(r)}
                              className="rounded-md p-1"
                              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                              title="View"
                              data-testid={`recs-queue-view-${r.id}`}>
                        <Eye size={12} color={colors.muted} />
                      </button>
                      <button onClick={() => doSend(r)}
                              disabled={busy === `send-${r.id}`}
                              className="rounded-md p-1"
                              style={{ backgroundColor: colors.brand, opacity: busy === `send-${r.id}` ? 0.6 : 1 }}
                              title="Send"
                              data-testid={`recs-queue-send-${r.id}`}>
                        <Send size={12} color="#fff" />
                      </button>
                      <button onClick={() => doDiscard(r)}
                              disabled={busy === `discard-${r.id}`}
                              className="rounded-md p-1"
                              style={{ backgroundColor: "#FEE2E2", opacity: busy === `discard-${r.id}` ? 0.6 : 1 }}
                              title="Discard"
                              data-testid={`recs-queue-discard-${r.id}`}>
                        <Trash2 size={12} color="#991B1B" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] px-3 py-2 italic"
               style={{ color: colors.muted, background: colors.surfaceAlt }}>
            Drafts older than 7 days · discarded rows are preserved in outbound_emails for audit.
            <Link to="/admin/tools/pricing" className="ml-2"
                  style={{ color: colors.brand, textDecoration: "underline" }}
                  data-testid="recs-queue-manage-link">
              Manage all drafts →
            </Link>
          </div>
        </div>
      ) : null}

      {preview ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-y-auto"
             style={{ backgroundColor: "rgba(0,0,0,0.4)" }}
             data-testid="recs-queue-preview">
          <div className="rounded-2xl max-w-2xl w-full my-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between p-4"
                 style={{ borderBottom: `1px solid ${colors.border}` }}>
              <div>
                <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  {preview.row.customer_name || "(no name)"}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {preview.row.customer_email || "no email"} · draft aged {preview.row.age_days} days
                </div>
              </div>
              <button onClick={closePreview} data-testid="recs-queue-preview-close">
                <X size={18} color={colors.muted} />
              </button>
            </div>
            <div className="p-4 space-y-3 text-sm">
              <div className="grid grid-cols-3 gap-3">
                <div><div className="text-xs" style={{ color: colors.muted }}>Current price</div>
                     <div className="font-bold">${preview.row.current_price?.toFixed?.(2)}</div></div>
                <div><div className="text-xs" style={{ color: colors.muted }}>Recommended</div>
                     <div className="font-bold">${preview.row.recommended_price?.toFixed?.(2)}</div></div>
                <div><div className="text-xs" style={{ color: colors.muted }}>Gap</div>
                     <div className="font-bold" style={{ color: "#166534" }}>+{preview.row.gap_pct}%</div></div>
              </div>
              <div><div className="text-xs" style={{ color: colors.muted }}>Subject</div>
                   <div className="font-semibold">{preview.row.subject}</div></div>
              {preview.row.effective_date ? (
                <div><div className="text-xs" style={{ color: colors.muted }}>Effective date</div>
                     <div>{preview.row.effective_date}</div></div>
              ) : null}
              {preview.row.reason ? (
                <div><div className="text-xs" style={{ color: colors.muted }}>Reason</div>
                     <div>{preview.row.reason}</div></div>
              ) : null}
              {preview.result ? (
                <div className="rounded-lg p-2 text-xs" data-testid="recs-queue-action-result"
                     style={{ backgroundColor: preview.result.error ? "#FEE2E2" : "#DCFCE7",
                              color: preview.result.error ? "#991B1B" : "#166534" }}>
                  {preview.result.error ? `Error: ${preview.result.error}` :
                    preview.result.status === "sent" ? `Sent ✓ (${preview.result.resend_id})` :
                    preview.result.status === "not_sent_missing_key" ? `Row saved as not_sent_missing_key — no RESEND_API_KEY.` :
                    preview.result.status === "failed" ? `Send failed: ${preview.result.error || "unknown"}` :
                    `Status: ${preview.result.status}`}
                </div>
              ) : null}
            </div>
            <div className="p-4 flex items-center justify-end gap-2"
                 style={{ borderTop: `1px solid ${colors.border}` }}>
              <button onClick={closePreview}
                      className="text-sm font-semibold px-3 py-2 rounded-lg"
                      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="recs-queue-preview-cancel">
                Close
              </button>
              <button onClick={() => doSend(preview.row)}
                      className="text-sm font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="recs-queue-preview-send">
                <Send size={13} /> Send Now
              </button>
              <button onClick={() => doDiscard(preview.row)}
                      className="text-sm font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1"
                      style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                      data-testid="recs-queue-preview-discard">
                <Trash2 size={13} /> Discard
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
