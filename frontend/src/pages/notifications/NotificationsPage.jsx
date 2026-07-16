/**
 * Phase 55 · Notifications page (full history).
 *
 * Renders every bell-channel notification the current user can see,
 * grouped by Today / Yesterday / Earlier. Filter chips let the user
 * narrow by kind. "Mark all read" clears every unread row; per-row
 * "Delete" drops one from history; row click routes to the deep link
 * or the source ref.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Bell, Check, Trash2, Filter, ExternalLink, Settings as SettingsIcon } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useRealtime } from "@/realtime/NotificationSocket";

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
  const [kindFilter, setKindFilter] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const { connected, transport, subscribe } = useRealtime();
  const nav = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      q.set("limit", "200");
      if (kindFilter) q.set("kind", kindFilter);
      if (unreadOnly) q.set("unread_only", "true");
      const r = await api.get(`/notifications?${q.toString()}`);
      setRows(Array.isArray(r) ? r : []);
    } catch { setRows([]); }
    setLoading(false);
  }, [kindFilter, unreadOnly]);

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

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>
          <Filter size={12} /> Filter
        </span>
        <button
          onClick={() => setKindFilter("")}
          className="text-xs px-2.5 py-1 rounded-full border"
          style={{
            borderColor: !kindFilter ? colors.brand : colors.border,
            backgroundColor: !kindFilter ? colors.brand : "transparent",
            color: !kindFilter ? "#fff" : colors.onSurface,
          }}
          data-testid="notif-filter-all"
        >
          All
        </button>
        {kinds.map((k) => (
          <button
            key={k.key}
            onClick={() => setKindFilter(k.key)}
            className="text-xs px-2.5 py-1 rounded-full border"
            style={{
              borderColor: kindFilter === k.key ? colors.brand : colors.border,
              backgroundColor: kindFilter === k.key ? colors.brand : "transparent",
              color: kindFilter === k.key ? "#fff" : colors.onSurface,
            }}
            data-testid={`notif-filter-${k.key}`}
          >
            {k.label}
          </button>
        ))}
        <label className="ml-2 inline-flex items-center gap-1.5 text-xs font-semibold" style={{ color: colors.onSurface }}>
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
