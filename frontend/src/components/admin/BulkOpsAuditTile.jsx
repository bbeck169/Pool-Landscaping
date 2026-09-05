/**
 * Phase K41d · Feb-2026 — Bulk Operations audit tile.
 *
 * Renders a compact "Last 24h" summary of bulk admin actions on the
 * admin dashboard, wired against the existing ``bulk_actions_24h``,
 * ``bulk_actions_undone_24h`` and ``bulk_actions_expired_24h`` fields
 * on the admin ``/api/dashboard`` response.
 *
 * Data source (zero new endpoints):
 *   * ``dashboard_drilldown_edit`` audit events, indexed by
 *     ``event_type + timestamp + tenant_id + bulk_batch_id``.
 *   * ``dashboard_drilldown_bulk_undone`` companion events.
 *
 * Design intent — give admins fast visibility over how many bulk
 * actions the team is running, how many were reversed, and how many
 * have aged past the 10-minute undo window (i.e. are now permanent
 * and could indicate a training or workflow issue).
 */
import React from "react";
import { Activity, RotateCcw, Clock } from "lucide-react";

export default function BulkOpsAuditTile({ data }) {
  // Defensive read — the fields are additive, so an older backend
  // build that hasn't shipped K41d yet returns ``undefined``. When
  // any of the three is missing we render nothing rather than a
  // "0 · 0 · 0" tile that would misrepresent the truth.
  if (
    data == null ||
    data.bulk_actions_24h == null ||
    data.bulk_actions_undone_24h == null ||
    data.bulk_actions_expired_24h == null
  ) {
    return null;
  }

  const total = Number(data.bulk_actions_24h) || 0;
  const undone = Number(data.bulk_actions_undone_24h) || 0;
  const expired = Number(data.bulk_actions_expired_24h) || 0;

  return (
    <div
      className="mb-6 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm"
      data-testid="bulk-ops-audit-tile"
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-slate-500" aria-hidden />
          <span
            className="text-xs font-semibold tracking-wide uppercase text-slate-500"
            data-testid="bulk-ops-audit-tile-label"
          >
            Bulk operations · last 24h
          </span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span
            className="inline-flex items-center gap-1 text-slate-800"
            data-testid="bulk-ops-audit-tile-total"
          >
            <span className="font-semibold" data-testid="bulk-ops-audit-tile-total-value">
              {total}
            </span>
            <span className="text-slate-500">bulk actions</span>
          </span>
          <span
            className="inline-flex items-center gap-1 text-slate-800"
            data-testid="bulk-ops-audit-tile-undone"
          >
            <RotateCcw className="h-3.5 w-3.5 text-slate-400" aria-hidden />
            <span className="font-semibold" data-testid="bulk-ops-audit-tile-undone-value">
              {undone}
            </span>
            <span className="text-slate-500">undone</span>
          </span>
          <span
            className={
              "inline-flex items-center gap-1 " +
              (expired > 0 ? "text-amber-700" : "text-slate-800")
            }
            data-testid="bulk-ops-audit-tile-expired"
          >
            <Clock className="h-3.5 w-3.5 text-slate-400" aria-hidden />
            <span
              className="font-semibold"
              data-testid="bulk-ops-audit-tile-expired-value"
            >
              {expired}
            </span>
            <span className="text-slate-500">expired</span>
          </span>
        </div>
      </div>
    </div>
  );
}
