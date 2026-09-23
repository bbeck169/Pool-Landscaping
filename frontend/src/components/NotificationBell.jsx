/**
 * Phase 55 · Unified Notification Bell.
 *
 * Rendered in two spots so every role gets it:
 *   • AdminTopBar        — inline pill (right-aligned).
 *   • UniversalMenu host — fixed top-right, offset to the LEFT of the
 *                          existing hamburger so both are visible.
 *
 * Behavior:
 *   • Polls  /api/notifications/unread-count every 30s.
 *   • Also refreshes on realtime "notification" fan-out (WS/SSE).
 *   • Dropdown lists the latest 10 rows.
 *   • Row click → mark read + navigate to href (if any) or the item's
 *     natural source ref.
 *   • Footer link → /notifications (full page).
 *   • Body strings are already server-truncated to 500 chars.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bell, Check, ChevronRight, Inbox } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
} from "@/components/ui/dropdown-menu";
import { useRealtime } from "@/realtime/NotificationSocket";

const POLL_MS = 30_000;

function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const s = Math.max(1, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  const day = Math.round(h / 24);
  if (day < 7) return `${day}d`;
  return d.toLocaleDateString();
}

/**
 * variant: "inline"  → renders as an inline button (AdminTopBar).
 *          "floating" → fixed top-3 right-14 (sits to the LEFT of the
 *                       hamburger which is at right-3).
 */
export default function NotificationBell({ variant = "inline" }) {
  const [count, setCount] = useState(0);
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const { subscribe } = useRealtime();

  const loadCount = useCallback(async () => {
    try {
      const r = await api.get("/notifications/unread-count");
      setCount(Number(r?.count || 0));
    } catch { /* silent — bell is best-effort */ }
  }, []);

  const loadRows = useCallback(async () => {
    try {
      const r = await api.get("/notifications?limit=10");
      setRows(Array.isArray(r) ? r : []);
    } catch { setRows([]); }
  }, []);

  useEffect(() => {
    loadCount();
    const t = setInterval(loadCount, POLL_MS);
    return () => clearInterval(t);
  }, [loadCount]);

  useEffect(() => {
    if (!subscribe) return;
    const off = subscribe("notification", () => { loadCount(); if (open) loadRows(); });
    return off;
  }, [subscribe, loadCount, loadRows, open]);

  useEffect(() => { if (open) loadRows(); }, [open, loadRows]);

  const onRowClick = async (n) => {
    setOpen(false);
    try { if (!n.read) await api.post(`/notifications/${n.id}/read`, {}); } catch {}
    loadCount();
    if (n.href) nav(n.href);
    else nav("/notifications");
  };

  const markAll = async (ev) => {
    ev?.preventDefault?.();
    ev?.stopPropagation?.();
    try { await api.post("/notifications/mark-all-read", {}); } catch {}
    setCount(0);
    setRows((prev) => prev.map((r) => ({ ...r, read: true })));
  };

  // Phase P38 · Feb-2026 — the ``floating`` variant no longer self-
  // positions; its parent (``UniversalMenu`` floating cluster) wraps
  // it in a single ``fixed top-3 right-3 z-40 flex`` container along
  // with the Sign Out pill + hamburger trigger.  The bell now
  // renders as an inline-flex sibling in both variants; only the
  // sizing (10x10 for floating, 9x9 for inline) differs.
  const triggerStyle = variant === "floating"
    ? "inline-flex items-center justify-center w-10 h-10 rounded-lg border shadow-sm bg-white hover:bg-gray-50 focus:outline-none"
    : "relative inline-flex items-center justify-center w-9 h-9 rounded-lg hover:brightness-95 focus:outline-none";

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        className={triggerStyle}
        style={variant === "floating" ? { borderColor: colors.border } : {}}
        data-testid="notification-bell"
        aria-label="Notifications"
        title="Team & job notifications"
      >
        <Bell size={variant === "floating" ? 18 : 16} style={{ color: colors.onSurface }} />
        {count > 0 ? (
          <span
            className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center"
            style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
            data-testid="notification-bell-badge"
          >
            {count > 99 ? "99+" : count}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={8}
        className="w-[min(96vw,380px)] p-0 overflow-hidden"
        data-testid="notification-bell-menu"
      >
        <div
          className="flex items-center justify-between border-b px-3 h-11"
          style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        >
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
            Notifications
          </div>
          <button
            type="button"
            onClick={markAll}
            className="text-xs font-semibold px-2 py-1 rounded hover:bg-gray-100 inline-flex items-center gap-1"
            style={{ color: colors.brand }}
            data-testid="notification-bell-mark-all"
          >
            <Check size={12} /> Mark all read
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {rows.length === 0 ? (
            <div
              className="p-8 text-center text-sm flex flex-col items-center gap-2"
              style={{ color: colors.muted }}
              data-testid="notification-bell-empty"
            >
              <Inbox size={28} className="opacity-50" />
              You're all caught up.
            </div>
          ) : (
            rows.map((n) => (
              <button
                key={n.id}
                type="button"
                onClick={() => onRowClick(n)}
                className="w-full text-left px-3 py-3 border-b hover:bg-gray-50 flex items-start gap-2"
                style={{ borderColor: colors.border }}
                data-testid={`notification-bell-row-${n.id}`}
              >
                <div
                  className="w-2 h-2 rounded-full mt-1.5 shrink-0"
                  style={{ backgroundColor: n.read ? "transparent" : "#DC2626" }}
                  aria-hidden
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <div
                      className="text-sm font-semibold truncate"
                      style={{ color: colors.onSurface }}
                    >
                      {n.title || n.label || "Notification"}
                    </div>
                    <div className="text-[10px] shrink-0" style={{ color: colors.muted }}>
                      {relTime(n.created_at)}
                    </div>
                  </div>
                  {n.body ? (
                    <div
                      className="text-xs mt-0.5 line-clamp-2"
                      style={{ color: colors.muted }}
                    >
                      {n.body}
                    </div>
                  ) : null}
                  {n.label && n.kind ? (
                    <div className="text-[10px] mt-1 font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>
                      {n.label}
                    </div>
                  ) : null}
                </div>
              </button>
            ))
          )}
        </div>
        <Link
          to="/notifications"
          onClick={() => setOpen(false)}
          className="flex items-center justify-between px-3 h-10 border-t text-sm font-semibold hover:bg-gray-50"
          style={{ borderColor: colors.border, color: colors.brand, backgroundColor: colors.surface }}
          data-testid="notification-bell-see-all"
        >
          <span>See all notifications</span>
          <ChevronRight size={14} />
        </Link>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
