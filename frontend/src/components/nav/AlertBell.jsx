/**
 * Phase A1 · Feb-2026 · Proactive Intelligence — Alert Bell.
 *
 * Top-nav bell for ``admin`` and ``super_admin`` sessions. Polls
 * ``GET /api/intelligence/alerts?unread_only=true&limit=10`` every
 * 60 seconds; renders a dot / count / "99+" badge; opens a dropdown
 * of the last 10 unread alerts with per-row actions
 * (``View`` deep-link · ``Mark read`` · ``Dismiss``).
 *
 * Poll pattern
 * ------------
 * Uses ``setInterval`` with a cancel on unmount + on-window-focus
 * refresh so operators returning to the tab see the latest count
 * without a 60-second wait. No websocket — HTTP polling is fine
 * for A1.
 *
 * Deep-link
 * ---------
 * Each alert exposes ``customer_id`` and/or ``job_id`` (both
 * optional per the schema). Deep-link priority: job → customer.
 * When neither is set the ``View`` button is disabled (info-only
 * alert; the operator dismisses to acknowledge).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState }
  from "react";
import { Bell, X as XIcon, CheckCheck, ExternalLink, AlertCircle,
         Info as InfoIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import { colors } from "@/theme";


const _POLL_INTERVAL_MS = 60_000;
// Phase A1 Hotfix · Feb-2026 — canonical "admin surface" role set,
// kept in sync with:
//   1. Backend router gate ``insufficient_role_for_alerts`` in
//      ``backend/routers/intelligence_alerts.py``.
//   2. ``hard_rule: "admin_or_super_admin"`` filter branch in the
//      admin nav / topbar / sidebar (see ``adminNav.js`` + friends).
// Every other role — technician, customer, manager, dispatcher,
// marketer, sales, unknown-string, ``null`` (auth loading) —
// falls through the ``has()`` check and the bell short-circuits to
// ``return null``.  Fail-closed: unauthenticated / preview-role /
// loading states never leak the bell surface.
const _FULL_ROLES = new Set(["admin", "super_admin"]);
const _SEV_META = {
  urgent:      { color: "#DC2626", icon: AlertCircle },
  recommended: { color: "#D97706", icon: AlertCircle },
  info:        { color: "#6B7280", icon: InfoIcon },
};


function _relative(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}


function _dot(count) {
  if (count <= 0) return null;
  if (count > 99) return "99+";
  return String(count);
}


export default function AlertBell() {
  // Phase A1 Hotfix · Feb-2026 — respect the "test as..." preview
  // role too. A super_admin previewing as a technician should see
  // the app the way that technician sees it — including the
  // absence of the alert bell. ``effectiveRole`` from
  // ``usePermissions`` is the same source-of-truth used by the
  // admin nav filter, so the surface stays in lock-step. When the
  // permissions provider is missing (test env with no wrapper),
  // ``effectiveRole`` still resolves to "admin" via the built-in
  // fallback, so this doesn't regress unrelated tests.
  const auth = useAuth();
  const { effectiveRole } = usePermissions();
  const rawRole = String(effectiveRole || auth?.user?.role || "").toLowerCase();
  // Fail-closed: if the auth provider is loading, we have no user,
  // or the token was cleared mid-render, ``rawRole`` is "" and
  // ``_FULL_ROLES.has("")`` returns false — bell renders null.
  const enabled = !auth?.loading && !!auth?.user && _FULL_ROLES.has(rawRole);
  const navigate = useNavigate();

  const [open, setOpen]                 = useState(false);
  const [alerts, setAlerts]             = useState([]);
  const [unreadCount, setUnreadCount]   = useState(0);
  const [loading, setLoading]           = useState(false);
  const timerRef  = useRef(null);
  const mountedRef = useRef(true);

  const fetchNow = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const r = await api.get(
        "/intelligence/alerts?unread_only=true&limit=10",
      );
      if (!mountedRef.current) return;
      setAlerts(r?.items || []);
      setUnreadCount(r?.unread_count || 0);
    } catch (e) {
      // Silently swallow — a poll failure should never surface a
      // red banner. The bell just keeps its previous count.
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return undefined;
    fetchNow();
    timerRef.current = setInterval(fetchNow, _POLL_INTERVAL_MS);
    const onFocus = () => fetchNow();
    window.addEventListener("focus", onFocus);
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearInterval(timerRef.current);
      window.removeEventListener("focus", onFocus);
    };
  }, [enabled, fetchNow]);

  const onMarkRead = useCallback(async (alertId) => {
    try {
      await api.post(`/intelligence/alerts/${alertId}/read`);
      setAlerts((prev) => prev.filter((a) => a.id !== alertId));
      setUnreadCount((n) => Math.max(0, n - 1));
    } catch (e) { /* swallow */ }
  }, []);

  const onDismiss = useCallback(async (alertId) => {
    try {
      await api.post(`/intelligence/alerts/${alertId}/dismiss`);
      setAlerts((prev) => prev.filter((a) => a.id !== alertId));
      setUnreadCount((n) => Math.max(0, n - 1));
    } catch (e) { /* swallow */ }
  }, []);

  const onView = useCallback((alert) => {
    if (alert.job_id) navigate(`/jobs/${alert.job_id}`);
    else if (alert.customer_id) navigate(`/customers/${alert.customer_id}`);
    // Also mark read on view — same UX as clicking through Gmail.
    if (alert.id) onMarkRead(alert.id);
    setOpen(false);
  }, [navigate, onMarkRead]);

  const badge = _dot(unreadCount);

  if (!enabled) return null;
  return (
    <div className="relative" data-testid="alert-bell-root">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative inline-flex items-center justify-center h-9 w-9 rounded-full hover:brightness-110"
        style={{ background: "transparent" }}
        aria-label={`Notifications: ${unreadCount} unread`}
        data-testid="alert-bell-btn"
      >
        <Bell size={18} color="#FFFFFF" />
        {badge != null ? (
          <span
            className="absolute -top-0.5 -right-0.5 inline-flex items-center justify-center rounded-full text-[10px] font-bold text-white px-1 min-w-[16px] h-[16px]"
            style={{ background: "#DC2626", lineHeight: 1 }}
            data-testid="alert-bell-badge"
          >
            {badge}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          role="dialog"
          className="absolute right-0 mt-2 w-96 rounded-xl shadow-xl border overflow-hidden z-50"
          style={{ background: colors.surface,
                    borderColor: colors.border, color: colors.onSurface }}
          data-testid="alert-bell-dropdown"
        >
          <div className="flex items-center justify-between px-4 py-2 border-b"
                style={{ borderColor: colors.border }}>
            <span className="text-sm font-semibold">Notifications</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={fetchNow}
                className="text-[11px] font-semibold"
                style={{ color: colors.muted }}
                disabled={loading}
                data-testid="alert-bell-refresh"
              >
                {loading ? "…" : "Refresh"}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close notifications"
                data-testid="alert-bell-close"
              >
                <XIcon size={14} />
              </button>
            </div>
          </div>

          {alerts.length === 0 ? (
            <div className="text-sm text-center py-8"
                  style={{ color: colors.muted }}
                  data-testid="alert-bell-empty">
              You're all caught up. 🎉
            </div>
          ) : (
            <ul className="max-h-96 overflow-y-auto"
                 data-testid="alert-bell-list">
              {alerts.map((a, i) => {
                const meta = _SEV_META[a.severity] || _SEV_META.info;
                const SevIcon = meta.icon;
                const canView = !!(a.job_id || a.customer_id);
                return (
                  <li
                    key={a.id}
                    className="px-4 py-3 border-b"
                    style={{ borderColor: colors.border }}
                    data-testid={`alert-bell-row-${i}`}
                  >
                    <div className="flex items-start gap-2">
                      <SevIcon size={16} color={meta.color}
                                className="mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold truncate"
                              data-testid={`alert-bell-title-${i}`}>
                          {a.title}
                        </div>
                        <div className="text-xs mt-0.5"
                              style={{ color: colors.muted }}>
                          {a.body}
                        </div>
                        <div className="text-[10px] mt-1"
                              style={{ color: colors.muted }}>
                          {_relative(a.created_at)}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-2 justify-end">
                      <button
                        type="button"
                        onClick={() => onView(a)}
                        disabled={!canView}
                        className="text-[11px] font-semibold rounded-full px-2 py-1 disabled:opacity-40"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`alert-bell-view-${i}`}
                      >
                        <ExternalLink size={10} className="inline mr-1" />
                        View
                      </button>
                      <button
                        type="button"
                        onClick={() => onMarkRead(a.id)}
                        className="text-[11px] font-semibold rounded-full px-2 py-1"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`alert-bell-mark-read-${i}`}
                      >
                        <CheckCheck size={10} className="inline mr-1" />
                        Mark read
                      </button>
                      <button
                        type="button"
                        onClick={() => onDismiss(a.id)}
                        className="text-[11px] font-semibold rounded-full px-2 py-1"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`alert-bell-dismiss-${i}`}
                      >
                        <XIcon size={10} className="inline mr-1" />
                        Dismiss
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="px-4 py-2 border-t text-center"
                style={{ borderColor: colors.border }}>
            <button
              type="button"
              onClick={() => { setOpen(false);
                                navigate("/admin/intelligence/alerts"); }}
              className="text-xs font-semibold"
              style={{ color: colors.brand || colors.onSurface }}
              data-testid="alert-bell-see-all"
            >
              See all alerts →
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
