/**
 * Phase 55 · Notifications page (full history).
 *
 * Renders every bell-channel notification the current user can see,
 * grouped by Today / Yesterday / Earlier.
 *
 * Feb-2026 · UX cleanup — the ~40-chip filter wall was replaced with a
 * single grouped multi-select dropdown (:file:``NotificationsFilterDropdown``).
 * Filter state:
 *   * ``kindFilters`` (``string[]``) — selected notification kinds.
 *     Empty array == "All". Persisted to the ``?kind=`` URL query so
 *     back/forward navigation preserves the filter.
 *   * ``unreadOnly`` (``boolean``) — orthogonal toggle beside the
 *     dropdown, ``?unread=1`` in the URL.
 * Backend accepts ``?kind=a,b,c`` (comma-joined) → Mongo ``$in``.
 *
 * "Mark all read" clears every unread row; per-row "Delete" drops one
 * from history; row click routes to the deep link or the source ref.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Bell, Check, Trash2, ExternalLink, Settings as SettingsIcon } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useRealtime } from "@/realtime/NotificationSocket";
import NotificationsFilterDropdown from "@/components/notifications/NotificationsFilterDropdown";

function dayBucket(iso) {
  if (!iso) return "Earlier";
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date(); yest.setDate(today.getDate() - 1);
  const eq = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (eq(d, today)) return "Today";
  if (eq(d, yest)) return "Yesterday";
  return "Earlier";
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function NotificationsPage() {
  const [rows, setRows] = useState([]);
  const [kinds, setKinds] = useState([]);
  const [searchParams, setSearchParams] = useSearchParams();
  // Feb-2026 · UX cleanup — array-typed filter. Seeded from ``?kind=``
  // URL param (comma-joined) so deep-links + back button preserve the
  // selection.  Empty array == "All".
  const [kindFilters, setKindFilters] = useState(() => {
    const raw = searchParams.get("kind") || "";
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [unreadOnly, setUnreadOnly] = useState(() => searchParams.get("unread") === "1");
  const [loading, setLoading] = useState(true);
  const { connected, transport, subscribe } = useRealtime();
  const nav = useNavigate();

  // Sync filter state → URL so back/forward buttons and shareable
  // links round-trip the current filter.  ``replace: true`` avoids
  // creating a history entry per checkbox click.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (kindFilters.length > 0) next.set("kind", kindFilters.join(","));
    else next.delete("kind");
    if (unreadOnly) next.set("unread", "1");
    else next.delete("unread");
    // Avoid pushing an identical string — React-Router will still
    // re-render but it keeps the history clean.
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindFilters, unreadOnly]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      q.set("limit", "200");
      if (kindFilters.length > 0) q.set("kind", kindFilters.join(","));
      if (unreadOnly) q.set("unread_only", "true");
      const r = await api.get(`/notifications?${q.toString()}`);
      setRows(Array.isArray(r) ? r : []);
    } catch { setRows([]); }
    setLoading(false);
  }, [kindFilters, unreadOnly]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.get("/notifications/kinds").then((r) => setKinds(r?.kinds || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!subscribe) return;
    const off = subscribe("notification", () => load());
    return off;
  }, [subscribe, load]);

  const grouped = useMemo(() => {
    const buckets = { Today: [], Yesterday: [], Earlier: [] };
    for (const n of rows) buckets[dayBucket(n.created_at)].push(n);
    return buckets;
  }, [rows]);

  const markAll = async () => {
    try { await api.post("/notifications/mark-all-read", {}); } catch {}
    load();
  };
  const markOne = async (n) => {
    try { await api.post(`/notifications/${n.id}/read`, {}); } catch {}
    setRows((prev) => prev.map((r) => (r.id === n.id ? { ...r, read: true } : r)));
  };
  const del = async (n) => {
    try { await api.del(`/notifications/${n.id}`); } catch {}
    setRows((prev) => prev.filter((r) => r.id !== n.id));
  };
  const open = async (n) => {
    if (!n.read) await markOne(n);
    if (n.href) nav(n.href);
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="notifications-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav(-1)} className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="notifications-back">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
              <Bell size={22} /> Notifications
            </h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Everything routed through your unified inbox
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded"
                style={{
                  backgroundColor: connected ? "#DCFCE7" : colors.surfaceSecondary,
                  color: connected ? "#166534" : colors.muted,
                }}
                data-testid="realtime-status">
            {connected ? `Live · ${transport}` : "Offline"}
          </span>
          <Link to="/settings/notifications"
                className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="notifications-open-prefs">
            <SettingsIcon size={14} /> Preferences
          </Link>
          <button onClick={markAll}
                  className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="notifications-mark-all">
            <Check size={14} /> Mark all read
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4 flex-wrap" data-testid="notif-filter-bar">
        <NotificationsFilterDropdown
          kinds={kinds}
          selected={kindFilters}
          onChange={setKindFilters}
          testId="notif-filter-dropdown"
        />
        {kindFilters.length > 0 ? (
          <button
            type="button"
            onClick={() => setKindFilters([])}
            className="text-xs font-semibold underline"
            style={{ color: colors.brand }}
            data-testid="notif-filter-reset"
          >
            Reset ({kindFilters.length})
          </button>
        ) : null}
        <label
          className="ml-auto inline-flex items-center gap-1.5 text-xs font-semibold cursor-pointer"
          style={{ color: colors.onSurface }}
        >
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            data-testid="notif-filter-unread"
          />
          Unread only
        </label>
      </div>

      {loading ? (
        <div className="p-6 text-sm text-center" style={{ color: colors.muted }} data-testid="notif-loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div
          className="p-10 text-center rounded-2xl"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}
          data-testid="notifications-empty"
        >
          <Bell size={36} className="mx-auto opacity-40 mb-2" />
          <div className="font-semibold">You're all caught up.</div>
          <div className="text-xs mt-1">Nothing matches this filter.</div>
        </div>
      ) : (
        <>
          {["Today", "Yesterday", "Earlier"].map((bucket) => (
            grouped[bucket].length === 0 ? null : (
              <div key={bucket} className="mb-6" data-testid={`notif-bucket-${bucket.toLowerCase()}`}>
                <div className="text-[11px] font-bold uppercase tracking-wider mb-2 px-1" style={{ color: colors.muted }}>
                  {bucket}
                </div>
                <div className="space-y-2">
                  {grouped[bucket].map((n) => (
                    <div
                      key={n.id}
                      className="rounded-2xl p-4 flex items-start gap-3"
                      style={{
                        backgroundColor: colors.surface,
                        border: `1px solid ${n.read ? colors.border : colors.brand}`,
                      }}
                      data-testid={`notif-row-${n.id}`}
                    >
                      <div
                        className="w-2 h-2 rounded-full mt-2 shrink-0"
                        style={{ backgroundColor: n.read ? colors.surfaceTertiary || "#e5e7eb" : "#DC2626" }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                            {n.title || "Notification"}
                          </div>
                          <div className="text-[11px]" style={{ color: colors.muted }}>{fmtTime(n.created_at)}</div>
                        </div>
                        {n.label ? (
                          <div className="text-[10px] font-semibold uppercase tracking-wider mt-0.5" style={{ color: colors.muted }}>
                            {n.label}
                          </div>
                        ) : null}
                        {n.body ? (
                          <div className="text-sm mt-2" style={{ color: colors.onSurface }}>{n.body}</div>
                        ) : null}
                        <div className="mt-2 flex items-center gap-2 flex-wrap">
                          {n.href ? (
                            <button
                              type="button"
                              onClick={() => open(n)}
                              className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1"
                              style={{ backgroundColor: colors.brand, color: "#fff" }}
                              data-testid={`notif-open-${n.id}`}
                            >
                              <ExternalLink size={12} /> Open
                            </button>
                          ) : null}
                          {!n.read ? (
                            <button
                              type="button"
                              onClick={() => markOne(n)}
                              className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1"
                              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                              data-testid={`notif-mark-${n.id}`}
                            >
                              <Check size={12} /> Mark read
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => del(n)}
                            className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1"
                            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                            data-testid={`notif-delete-${n.id}`}
                          >
                            <Trash2 size={12} /> Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          ))}
        </>
      )}
    </div>
  );
}
