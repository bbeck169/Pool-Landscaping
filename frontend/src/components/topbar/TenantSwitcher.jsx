/**
 * Phase T1.5 · Feb-2026 — top-nav Tenant Switcher.
 *
 * Renders a compact "current tenant + chevron" trigger in the
 * AdminTopBar right cluster. Only visible when the signed-in user
 * has 2+ tenants in ``auth.user.available_tenants`` (single-tenant
 * users see nothing — the topbar stays clean and backwards-
 * compatible with the pre-T1 UX).
 *
 * Click → dropdown listing every tenant with the active one
 * highlighted. Picking another → POST /api/auth/switch-tenant →
 * localStorage token swap → ``window.location.reload()`` so every
 * mounted component re-fetches with the new tenant scope.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronsUpDown, Check, Building2, Loader2 } from "lucide-react";

import { api, TOKEN_KEY } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";


export default function TenantSwitcher() {
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  // Feb-2026 fix — the wide topbar wrap has ``overflow-x-auto`` which
  // clips absolutely-positioned children, so the dropdown must render
  // via a React portal into document.body and self-position from the
  // trigger's client rect.
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 });
  const wrap = useRef(null);
  const menuRef = useRef(null);

  const memberships = auth?.user?.available_tenants || [];
  const activeId    = auth?.user?.active_tenant_id
                        || memberships.find((t) => t.is_active_now)?.id;
  const active      = memberships.find((t) => t.id === activeId)
                        || memberships[0];

  useLayoutEffect(() => {
    if (!open || !wrap.current) return;
    const rect = wrap.current.getBoundingClientRect();
    // Anchor below the trigger, right-aligned to it.
    setMenuPos({
      top:   Math.round(rect.bottom + 8),
      right: Math.round(window.innerWidth - rect.right),
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev) => {
      const insideTrigger = wrap.current && wrap.current.contains(ev.target);
      const insideMenu    = menuRef.current && menuRef.current.contains(ev.target);
      if (!insideTrigger && !insideMenu) setOpen(false);
    };
    const onEsc = (ev) => { if (ev.key === "Escape") setOpen(false); };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  // Single-tenant users get nothing.
  if (!memberships || memberships.length < 2) return null;

  const onPick = async (t) => {
    if (t.id === activeId || switching) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    try {
      const r = await api.post("/auth/switch-tenant", { tenant_id: t.id });
      if (r && r.access_token) {
        localStorage.setItem(TOKEN_KEY, r.access_token);
      }
      // Full page reload — cleanest way to reset every mounted
      // context (react-query caches, route data, admin nav filters,
      // etc.). Preferred over selective invalidation per user brief.
      window.location.reload();
    } catch (e) {
      setSwitching(false);
      setOpen(false);
      // Bubble to console — the user sees the page NOT change so
      // they know something went wrong; a toast primitive would
      // be nicer follow-up.
      // eslint-disable-next-line no-console
      console.error("Tenant switch failed", e);
    }
  };

  return (
    <div className="relative" ref={wrap}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 h-8 px-2 rounded-full text-xs font-medium hover:opacity-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          color: colors.onSurface,
        }}
        data-testid="topbar-tenant-switcher-btn"
        aria-label="Switch tenant"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Building2 size={12} style={{ color: colors.muted }} />
        <span className="truncate max-w-[180px]">
          {active?.name || "Tenant"}
        </span>
        {switching ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <ChevronsUpDown size={12} style={{ color: colors.muted }} />
        )}
      </button>
      {open ? createPortal(
        <div
          ref={menuRef}
          role="menu"
          className="fixed w-64 rounded-xl shadow-lg py-1"
          style={{
            top:   `${menuPos.top}px`,
            right: `${menuPos.right}px`,
            zIndex: 9999,
            background: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="topbar-tenant-switcher-menu"
        >
          <div className="px-3 py-1 text-[10px] uppercase tracking-wide"
                style={{ color: colors.muted }}>
            Switch tenant
          </div>
          {memberships.map((t) => (
            <button
              key={t.id}
              type="button"
              role="menuitem"
              onClick={() => onPick(t)}
              data-testid={`topbar-tenant-switcher-item-${t.id}`}
              className="w-full text-left flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/[.04]"
              style={{ color: colors.onSurface }}
            >
              <Building2 size={14} style={{ color: colors.muted }} />
              <span className="flex-1 truncate">{t.name || t.id}</span>
              {t.id === activeId ? (
                <Check size={14} style={{ color: colors.brand }} />
              ) : null}
            </button>
          ))}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
