/**
 * Feb-2026 · Chase Stalled Invites — confirm + summary modal.
 *
 * Two-phase modal:
 *   1. Confirm — preview list of the top-N stalest never-logged-in
 *      customers + Cancel / "Send N invites" buttons.
 *   2. Summary — after the bulk POST resolves, replace the confirm
 *      body with "Sent N. Rate-limited M. Failed K." + Done button.
 *
 * Data source:
 *   * Preview list: ``GET /api/customers?first_access=never&sort=stalest_first&limit=N``
 *   * Send:         ``POST /api/admin/customers/portal-invite/bulk``
 *                   with ``{customer_ids, reason: "chase_stalled_invites"}``
 *
 * Response shape (Feb-2026 · Chase Stalled Invites ship — bulk
 * endpoint returns both the legacy counters AND the spec-shape
 * ``{enqueued, rate_limited: [ids], failed: [{id, reason}]}``):
 *
 *     {
 *       enqueued: 8, rate_limited: ["cust_id_1"], failed: [{id, reason}],
 *       sent, failed_send, skipped_*, batch_id, failures[]
 *     }
 *
 * Test-ids:
 *   * ``chase-stalled-invites-modal``
 *   * ``chase-invites-preview-list``
 *   * ``chase-invites-preview-row``      (each row)
 *   * ``chase-invites-batch-size-select``
 *   * ``chase-invites-cancel-btn``
 *   * ``chase-invites-send-btn``
 *   * ``chase-invites-summary``          (post-send state)
 *   * ``chase-invites-done-btn``         (summary state)
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";


const _DEFAULT_N = 10;
const _BATCH_OPTIONS = [5, 10, 25];


export default function ChaseStalledInvitesModal({ open, onClose, onSent }) {
  const [batchN, setBatchN] = useState(_DEFAULT_N);
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [sending, setSending] = useState(false);
  const [summary, setSummary] = useState(null);

  // Reset every field on open transitions so the modal is fresh.
  useEffect(() => {
    if (open) {
      setBatchN(_DEFAULT_N);
      setPreview(null);
      setLoadingPreview(false);
      setSending(false);
      setSummary(null);
    }
  }, [open]);

  // Refetch the preview when N changes (or on open).
  useEffect(() => {
    if (!open) return;
    if (summary) return; // don't refetch once we've sent
    let cancelled = false;
    setLoadingPreview(true);
    (async () => {
      try {
        const url = `/customers?first_access=never&sort=stalest_first&limit=${batchN}`;
        const r = await api.get(url);
        if (cancelled) return;
        const items = Array.isArray(r) ? r : (r?.items || []);
        setPreview(items.slice(0, batchN));
      } catch (e) {
        if (!cancelled) {
          toast.error("Could not load stalest customers");
          setPreview([]);
        }
      } finally {
        if (!cancelled) setLoadingPreview(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, batchN, summary]);

  const handleSend = async () => {
    if (!preview || preview.length === 0) return;
    setSending(true);
    try {
      const customer_ids = preview
        .map((c) => c?.id)
        .filter((x) => typeof x === "string" && x.length > 0);
      const r = await api.post(
        "/admin/customers/portal-invite/bulk",
        { customer_ids, reason: "chase_stalled_invites" },
      );
      const enqueued = typeof r?.enqueued === "number"
        ? r.enqueued
        : (r?.sent || 0);
      const rate_limited = Array.isArray(r?.rate_limited)
        ? r.rate_limited.length
        : 0;
      const failed = Array.isArray(r?.failed)
        ? r.failed.length
        : 0;
      setSummary({ enqueued, rate_limited, failed });
      if (enqueued > 0) {
        toast.success(`Sent ${enqueued} portal invite${enqueued === 1 ? "" : "s"}`);
      }
    } catch (e) {
      const msg = (e && e.message) || "Bulk invite failed";
      toast.error(msg);
      setSummary({ enqueued: 0, rate_limited: 0, failed: preview.length });
    } finally {
      setSending(false);
    }
  };

  const handleClose = () => {
    // Fire the parent refetch on close so the tile shows the shrunken
    // Never cohort after invites landed. Also fires on cancel — the
    // parent tile refetch is idempotent (60s server cache).
    onSent?.();
    onClose?.();
  };

  if (!open) return null;

  const isSummary = summary !== null;
  const canSend = !loadingPreview && !sending && Boolean(preview && preview.length);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
      onClick={sending ? undefined : handleClose}
      data-testid="chase-stalled-invites-modal"
    >
      <div
        className="w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl"
        style={{ backgroundColor: colors.surface }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="px-5 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div
            className="text-base font-semibold"
            style={{ color: colors.onSurface }}
          >
            {isSummary
              ? "Chase results"
              : "Chase stalled invites"}
          </div>
          {!isSummary ? (
            <div
              className="text-xs mt-0.5"
              style={{ color: colors.muted }}
            >
              Re-send portal invites to the customers who were invited
              the longest ago and still haven't logged in.
            </div>
          ) : null}
        </header>

        {isSummary ? (
          <div className="p-5" data-testid="chase-invites-summary">
            <div
              className="text-sm mb-4"
              style={{ color: colors.onSurface }}
            >
              <div>
                <span className="font-semibold" data-testid="chase-invites-summary-enqueued">
                  Sent {summary.enqueued}
                </span>.
              </div>
              <div>
                <span data-testid="chase-invites-summary-rate-limited">
                  Rate-limited {summary.rate_limited}
                </span>.
              </div>
              <div>
                <span data-testid="chase-invites-summary-failed">
                  Failed {summary.failed}
                </span>.
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleClose}
                data-testid="chase-invites-done-btn"
                className="inline-flex items-center px-4 py-2 rounded-lg text-sm font-semibold hover:brightness-95"
                style={{
                  backgroundColor: colors.brand,
                  color: "#fff",
                }}
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <div className="p-5">
            <div className="flex items-center justify-between mb-3">
              <label
                htmlFor="chase-invites-batch-size-select"
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: colors.muted }}
              >
                Batch size
              </label>
              <select
                id="chase-invites-batch-size-select"
                data-testid="chase-invites-batch-size-select"
                value={batchN}
                onChange={(e) => setBatchN(Number(e.target.value))}
                disabled={sending}
                className="rounded-md text-sm px-2 py-1"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
              >
                {_BATCH_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>

            <div
              data-testid="chase-invites-preview-list"
              className="rounded-lg overflow-y-auto"
              style={{
                border: `1px solid ${colors.border}`,
                maxHeight: 320,
                backgroundColor: colors.background,
              }}
            >
              {loadingPreview ? (
                <div
                  className="p-4 text-sm"
                  style={{ color: colors.muted }}
                  data-testid="chase-invites-preview-loading"
                >
                  Loading…
                </div>
              ) : (preview && preview.length > 0) ? (
                preview.map((c) => (
                  <div
                    key={c.id}
                    data-testid="chase-invites-preview-row"
                    className="px-3 py-2 text-sm flex items-center justify-between"
                    style={{
                      borderBottom: `1px solid ${colors.border}`,
                      color: colors.onSurface,
                    }}
                  >
                    <span
                      className="truncate mr-3"
                      title={c.name || c.email || c.id}
                    >
                      {c.name || c.email || c.id}
                    </span>
                    <span
                      className="text-xs shrink-0"
                      style={{ color: colors.muted }}
                    >
                      {c.email || c.phone || "no contact"}
                    </span>
                  </div>
                ))
              ) : (
                <div
                  className="p-4 text-sm"
                  style={{ color: colors.muted }}
                  data-testid="chase-invites-preview-empty"
                >
                  No stalled invites — nice work.
                </div>
              )}
            </div>

            <div
              className="text-xs mt-3"
              style={{ color: colors.muted }}
            >
              This will re-send portal invite emails/SMS. Existing rate limits apply.
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={handleClose}
                disabled={sending}
                data-testid="chase-invites-cancel-btn"
                className="inline-flex items-center px-4 py-2 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-60"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSend}
                disabled={!canSend}
                data-testid="chase-invites-send-btn"
                className="inline-flex items-center px-4 py-2 rounded-lg text-sm font-semibold hover:brightness-95 disabled:opacity-60"
                style={{
                  backgroundColor: colors.brand,
                  color: "#fff",
                }}
              >
                {sending
                  ? "Sending…"
                  : `Send ${preview ? preview.length : batchN} invite${(preview ? preview.length : batchN) === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
