// Feb-2026 · Optimize Route (sub-phase C) — admin approval modal.
//
// Renders a Radix Dialog with the tech's name + date, the compact
// savings summary, and a two-column before/after visualization built
// from the request's ``before_order`` + ``after_order`` fields.
//
// Actions:
//   • Approve  → POST /api/jobs/route-optimization/{id}/approve
//   • Reject   → prompt for optional 1-line reason (max 200 chars) →
//                POST /api/jobs/route-optimization/{id}/reject
//   • Dismiss  → closes without an API call (request stays pending)
//
// Reused primitives:
//   • Dialog / DialogContent / DialogHeader … from @/components/ui/dialog
//   • toast from sonner
//   • api from @/api
//
// Contract with the parent (``PendingRouteOptimizations``):
//   • ``request``          — full row from GET /pending
//   • ``open``             — visible flag
//   • ``onClose``          — Dismiss / X handler
//   • ``onResolved(kind)`` — fired on approve/reject success so the
//                            parent can refetch its list + bell count
import React from "react";
import { toast } from "sonner";
import { Route as RouteIcon, Check, X, ChevronDown, ChevronUp } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const REASON_MAX = 200;

function _fmtDate(iso) {
  if (!iso) return "—";
  // ``route_date`` is stored as YYYY-MM-DD; render as a friendly local date.
  const [y, m, d] = iso.slice(0, 10).split("-").map((n) => parseInt(n, 10));
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric", year: "numeric",
  });
}

function _displayName(row) {
  return row?.tech_name || row?.requested_by_name || row?.tech_user_id || "Unknown tech";
}

export default function RouteOptimizationApprovalModal({
  request,
  open,
  onClose,
  onResolved,
}) {
  const [busy, setBusy] = React.useState(false);
  const [rejectMode, setRejectMode] = React.useState(false);
  const [reason, setReason] = React.useState("");

  React.useEffect(() => {
    if (!open) { setRejectMode(false); setReason(""); }
  }, [open]);

  if (!request) return null;

  const beforeOrder = Array.isArray(request.before_order) ? request.before_order : [];
  const afterOrder = Array.isArray(request.after_order) ? request.after_order : [];
  const miles = Number(request.estimated_miles_saved || 0);
  const minutes = Number(request.estimated_minutes_saved || 0);
  const stopsAffected = Number(request.stops_affected || 0);

  // Build a stable id→display map from any hints on the row (customer_name /
  // address). Falls back to a short-hash of the id so the columns stay
  // readable even when the parent doesn't hydrate names.
  const jobHint = (jid) => {
    const meta = (request.job_meta || {})[jid] || {};
    return meta.customer_name || meta.title || `#${String(jid).slice(-6)}`;
  };

  const onApprove = async () => {
    setBusy(true);
    try {
      await api.post(`/jobs/route-optimization/${request.id}/approve`, {});
      toast.success("Route optimization approved");
      onResolved?.("approved");
      onClose?.();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Approve failed");
    } finally {
      setBusy(false);
    }
  };

  const onReject = async () => {
    setBusy(true);
    try {
      const body = reason.trim() ? { reason: reason.trim().slice(0, REASON_MAX) } : {};
      await api.post(`/jobs/route-optimization/${request.id}/reject`, body);
      toast.success("Route optimization rejected");
      onResolved?.("rejected");
      onClose?.();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Reject failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !busy) onClose?.(); }}>
      <DialogContent
        className="max-w-2xl"
        data-testid="route-optimization-approval-modal"
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <RouteIcon size={18} style={{ color: colors.brand }} />
            <DialogTitle
              className="text-lg font-bold"
              data-testid="route-optimization-approval-tech"
            >
              Optimize route · {_displayName(request)}
            </DialogTitle>
          </div>
          <DialogDescription
            className="text-xs mt-1"
            data-testid="route-optimization-approval-date"
          >
            {_fmtDate(request.route_date)}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-3 gap-3 mt-2">
          <SummaryTile label="Stops"
                        value={String(stopsAffected)}
                        testid="route-optimization-approval-summary-stops" />
          <SummaryTile label="Miles saved"
                        value={miles.toFixed(1)}
                        testid="route-optimization-approval-summary-miles" />
          <SummaryTile label="Min saved"
                        value={String(Math.round(minutes))}
                        testid="route-optimization-approval-summary-minutes" />
        </div>

        <div className="grid grid-cols-2 gap-3 mt-4">
          <OrderColumn title="Before"
                        order={beforeOrder}
                        hint={jobHint}
                        testid="route-optimization-approval-before" />
          <OrderColumn title="After"
                        order={afterOrder}
                        hint={jobHint}
                        highlight
                        testid="route-optimization-approval-after" />
        </div>

        {rejectMode ? (
          <div className="mt-4 space-y-2">
            <label
              className="text-xs font-semibold"
              style={{ color: colors.onSurface }}
            >
              Optional reason (visible to tech)
            </label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
              maxLength={REASON_MAX}
              placeholder="e.g. Keeping current order for the storm route…"
              rows={2}
              data-testid="route-optimization-approval-reject-reason"
            />
            <div className="text-[11px]" style={{ color: colors.muted }}>
              {reason.length}/{REASON_MAX}
            </div>
          </div>
        ) : null}

        <DialogFooter className="mt-4 gap-2 flex-row justify-end">
          {rejectMode ? (
            <>
              <Button
                variant="outline"
                onClick={() => { setRejectMode(false); setReason(""); }}
                disabled={busy}
                data-testid="route-optimization-approval-reject-cancel"
              >
                Back
              </Button>
              <Button
                variant="destructive"
                onClick={onReject}
                disabled={busy}
                data-testid="route-optimization-approval-reject-confirm"
              >
                <X size={14} className="mr-1" /> Confirm reject
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={onClose}
                disabled={busy}
                data-testid="route-optimization-approval-dismiss"
              >
                Dismiss
              </Button>
              <Button
                variant="outline"
                onClick={() => setRejectMode(true)}
                disabled={busy}
                data-testid="route-optimization-approval-reject"
              >
                Reject
              </Button>
              <Button
                onClick={onApprove}
                disabled={busy}
                data-testid="route-optimization-approval-approve"
              >
                <Check size={14} className="mr-1" /> Approve
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SummaryTile({ label, value, testid }) {
  return (
    <div
      className="rounded-md border p-3"
      style={{ borderColor: colors.border, backgroundColor: colors.surfaceSecondary }}
      data-testid={testid}
    >
      <div className="text-[10px] font-bold uppercase tracking-wide"
            style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }}>
        {value}
      </div>
    </div>
  );
}

function OrderColumn({ title, order, hint, testid, highlight = false }) {
  return (
    <div
      className="rounded-md border overflow-hidden"
      style={{
        borderColor: highlight ? colors.brand : colors.border,
        backgroundColor: colors.surface,
      }}
      data-testid={testid}
    >
      <div
        className="px-3 py-2 text-xs font-bold border-b"
        style={{
          borderColor: colors.border,
          backgroundColor: highlight ? "#EFF6FF" : colors.surfaceSecondary,
          color: colors.onSurface,
        }}
      >
        {title}
      </div>
      <ol className="divide-y" style={{ borderColor: colors.border }}>
        {order.length === 0 ? (
          <li className="px-3 py-3 text-xs"
                style={{ color: colors.muted }}>—</li>
        ) : order.map((jid, i) => (
          <li
            key={`${title}-${jid}`}
            className="flex items-center gap-2 px-3 py-2 text-sm"
            data-testid={`${testid}-row-${i}`}
          >
            <span
              className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-bold"
              style={{
                backgroundColor: highlight ? colors.brand : colors.muted,
                color: "#fff",
              }}
              data-testid={`${testid}-num-${i}`}
            >
              {i + 1}
            </span>
            <span
              className="truncate"
              style={{ color: colors.onSurface }}
              data-testid={`${testid}-name-${i}`}
            >
              {hint(jid)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
