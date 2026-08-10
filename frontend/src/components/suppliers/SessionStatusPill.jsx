/**
 * Phase 54h-d · Aug-2026 — Supplier session status pill + Clear action.
 *
 * Rendered inline next to the Test Login button on each opt-in
 * supplier row (Pool360 / SiteOne / Heritage). Polls
 * ``GET /api/suppliers/{slug}/sessions/status`` on mount + every 60s
 * so the badge is always fresh without hammering the endpoint.
 *
 * Tier logic (locked in scope §1):
 *   * ``has_active_session: false``       → no pill (silent).
 *   * ``minutes_remaining >  10``         → green pill.
 *   * ``0 < minutes_remaining <= 10``     → amber pill + Retry link.
 *   * ``minutes_remaining <= 0``          → no pill (soft-expired
 *                                            server-side, next call
 *                                            will re-challenge).
 *
 * Also renders a tiny "Clear cached session" trash action next to
 * the pill (admin/super_admin/manager only) that DELETEs the row
 * after a confirmation prompt. Useful to force-refresh a stale
 * session before expiry (e.g. Heritage rotated IP + cookies are dead).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Trash2, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


const POLL_INTERVAL_MS = 60_000;   // 60s — locked (scope §Rules).
const AMBER_THRESHOLD_MIN = 10;


export default function SessionStatusPill({
  slug, displayName, canManage, onRetry,
}) {
  const [status, setStatus] = useState(null); // {has_active_session, minutes_remaining}
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const timerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get(`/suppliers/${slug}/sessions/status`);
      setStatus(r);
    } catch {
      // Silent — a 403 or 500 shouldn't spam the settings page.
      setStatus(null);
    }
  }, [slug]);

  // Poll on mount + every 60s. Interval is a hard lock — anything
  // shorter creates network noise for zero UX gain.
  useEffect(() => {
    load();
    timerRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  const doClear = async () => {
    if (clearing) return;
    setClearing(true);
    try {
      await api.del(`/suppliers/${slug}/sessions`);
      await load();                                   // pill flips to hidden
      setConfirmClear(false);
    } finally { setClearing(false); }
  };

  const isActive = Boolean(status?.has_active_session);
  const minutesLeft = Number(status?.minutes_remaining ?? 0);
  if (!isActive || minutesLeft <= 0) {
    return null;
  }
  const isAmber = minutesLeft <= AMBER_THRESHOLD_MIN;
  const palette = isAmber
    ? { bg: "#FEF3C7", fg: "#92400E", border: "#FCD34D" }
    : { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC" };

  return (
    <span className="inline-flex items-center gap-1"
           data-testid={`session-status-${slug}`}>
      <span
        className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
        style={{ backgroundColor: palette.bg, color: palette.fg,
                  border: `1px solid ${palette.border}` }}
        data-testid={`session-status-pill-${slug}`}
        data-tier={isAmber ? "amber" : "green"}
      >
        {isAmber
          ? `Session expiring in ${minutesLeft}m`
          : `Session cached · ${minutesLeft}m left`}
      </span>
      {isAmber && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-0.5 text-[10px] font-bold"
          style={{ color: colors.brand, textDecoration: "underline" }}
          data-testid={`session-status-retry-${slug}`}
        >
          <RotateCcw size={10} /> Retry
        </button>
      ) : null}
      {canManage ? (
        <button
          type="button"
          onClick={() => setConfirmClear(true)}
          title="Clear cached session"
          aria-label={`Clear cached session for ${displayName}`}
          className="p-1 rounded hover:bg-slate-100"
          style={{ color: colors.muted }}
          data-testid={`session-status-clear-${slug}`}
        >
          <Trash2 size={10} />
        </button>
      ) : null}
      {confirmClear ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget)
                                    setConfirmClear(false); }}
          data-testid={`session-status-clear-confirm-${slug}`}
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white"
            style={{ border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}>
              Clear cached {displayName} session?
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              The next Test Login will re-hit the Turnstile challenge
              and prompt for a fresh cookie handoff.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmClear(false)}
                disabled={clearing}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-slate-100"
                data-testid={`session-status-clear-cancel-${slug}`}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doClear}
                disabled={clearing}
                className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid={`session-status-clear-confirm-btn-${slug}`}
              >
                {clearing ? "Clearing…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </span>
  );
}
