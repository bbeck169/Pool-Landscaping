/**
 * Phase 44 · Universal top-right hamburger menu (all roles).
 *
 * Mirrors the mobile Global Dropdown Menu (Phase 43). Renders a
 * hamburger icon pinned to the top-right corner of the authenticated
 * layout; clicking opens a Radix `DropdownMenu` panel that contains:
 *
 *   • Live-filter search box (case-insensitive substring on label).
 *   • Pinned section (localStorage-persisted, per-user scope).
 *   • Recent section (5 most-recent, auto-populated on link tap).
 *   • Category chip filter — one chip per role-nav section + "All".
 *   • Filtered link list — each row has a bookmark toggle mirroring
 *     the mobile pin affordance.
 *
 * Every authenticated role sees this surface:
 *   admin / super_admin — the Phase 35 6-category admin IA.
 *   technician          — the 4-section tech IA (see `TECH_NAV`).
 *   customer            — the 6-section customer portal IA
 *                          (see `CUSTOMER_NAV`).
 *
 * The existing admin sidebar + admin top bar remain untouched. This
 * is a THIRD, universal nav surface with per-user personalization.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Menu, Search, X, Bookmark, BookmarkCheck, LogOut } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import { navForRoleAndDept } from '@/nav/roleNav';
import { colors } from "@/theme";
import NotificationBell from "@/components/NotificationBell";

// Feb-2026 · Raised from 6 → 20 per user request. Pins live in
// localStorage only (no backend cap), so this is a pure UX limit.
// The Universal Menu renders pins in a scrollable strip that stays
// legible up to ~20 entries without cramping other sections.
const MAX_PINS = 20;
const MAX_RECENTS = 5;

function scope(userId, key) { return `${key}::${userId || "unknown"}`; }

function readJSON(key, fallback) {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(key) : null;
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch { return fallback; }
}

function writeJSON(key, value) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(key, JSON.stringify(value));
  } catch { /* storage quota / private mode — best-effort */ }
}

/** Flatten the role's sections into a searchable list with backrefs. */
function useFlatEntries(sections, canFn, effectiveRole) {
  return useMemo(() => {
    const out = [];
    for (const g of sections) {
      for (const e of g.entries) {
        // Reuse existing RBAC where declared. If the entry doesn't
        // carry a `feature` marker, it's role-inherent (the role owns
        // this section) and always visible to that role.
        if (e.hard_rule === "admin_only" && effectiveRole !== "admin") continue;
        if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") continue;
        if (e.feature) {
          const ok = canFn(e.feature, "read") || effectiveRole === "admin";
          if (!ok) continue;
        }
        out.push({ ...e, sectionKey: g.key, sectionLabel: g.label });
      }
    }
    return out;
  }, [sections, canFn, effectiveRole]);
}

export default function UniversalMenu({ variant = "floating" } = {}) {
  const { user, logout } = useAuth();
  const { can, effectiveRole } = usePermissions();
  const role = user?.role || effectiveRole || "";
  const nav = useNavigate();

  // Sections are pulled by role at render time so a role change (e.g.,
  // stop-impersonation) reflects immediately without a remount.
  const sections = useMemo(() => navForRoleAndDept(role, user?.department), [role, user?.department]);
  const flat = useFlatEntries(sections, can, effectiveRole);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [chip, setChip] = useState("all");

  // Per-user persistence keys mirror the mobile scheme
  // (`tools-pins-v1::{userId}`) so the storage layout is
  // recognizable / debuggable across surfaces.
  const pinsKey = scope(user?.id, "web-menu-pins-v1");
  const recentsKey = scope(user?.id, "web-menu-recents-v1");

  const [pins, setPins] = useState([]);
  const [recents, setRecents] = useState([]);

  useEffect(() => {
    setPins(readJSON(pinsKey, []).slice(0, MAX_PINS));
    setRecents(readJSON(recentsKey, []).slice(0, MAX_RECENTS));
  }, [pinsKey, recentsKey]);

  const togglePin = useCallback((path) => {
    setPins((prev) => {
      const next = prev.includes(path)
        ? prev.filter((p) => p !== path)
        : [...prev, path].slice(0, MAX_PINS);
      writeJSON(pinsKey, next);
      return next;
    });
  }, [pinsKey]);

  const markUsed = useCallback((path) => {
    setRecents((prev) => {
      const now = new Date().toISOString();
      const dedup = prev.filter((r) => r.path !== path);
      const next = [{ path, at: now }, ...dedup].slice(0, MAX_RECENTS);
      writeJSON(recentsKey, next);
      return next;
    });
  }, [recentsKey]);

  const byPath = useMemo(() => {
    const m = {};
    for (const e of flat) m[e.to] = e;
    return m;
  }, [flat]);

  const filteredSections = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sections
      .filter((g) => chip === "all" || g.key === chip)
      .map((g) => ({
        ...g,
        entries: g.entries
          // Re-apply the RBAC filter on the section-level list too so
          // section counts match what the flat list would surface.
          .filter((e) => byPath[e.to])
          .filter((e) => !q || e.label.toLowerCase().includes(q)),
      }))
      .filter((g) => g.entries.length > 0);
  }, [sections, chip, query, byPath]);

  const openEntry = useCallback((e) => {
    markUsed(e.to);
    setOpen(false);
    // A tick lets the Radix dismiss animation start before the route
    // change — otherwise the sheet snap looks jarring.
    setTimeout(() => nav(e.to), 40);
  }, [markUsed, nav]);

  // Hide the trigger entirely if this role has no visible nav entries
  // (a defensive guard — shouldn't happen for known roles).
  if (flat.length === 0) return null;

  return (
    <>
      {/* Feb-2026 · Portal Sign-out — mirrors the admin ``header-signout``
          pill in ``AdminTopBar``, but only rendered in the ``floating``
          variant (i.e., the customer-portal shell). The ``inline``
          variant is mounted inside ``AdminTopBar`` which already has
          its own ``header-signout`` — rendering here again would
          duplicate. Positioning math (fixed anchors):
            • hamburger (this component)   right-3
            • NotificationBell (floating)  right-14
            • Portal Sign Out (this pill)  right-[6.5rem] (~100 px)
          The pill is icon-only on mobile (< sm) and icon+label on
          sm+ so the fixed anchor never collides with the bell at
          any viewport. */}
      {variant === "floating" && user ? (
        <button
          type="button"
          onClick={() => {
            try { logout && logout(); } finally {
              nav("/portal/login", { replace: true });
            }
          }}
          // Phase K54 · Feb-2026 — solid destructive red per
          // ``colors.destructive``. Same spec as the admin
          // ``header-signout`` in ``AdminTopBar`` so every
          // Sign-out surface in the app reads identically.
          className="fixed top-3 right-[6.5rem] z-40 inline-flex items-center gap-1 h-10 px-3 rounded-lg text-xs font-semibold shadow-sm text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55"
          data-testid="portal-signout"
          aria-label="Sign out"
        >
          <LogOut size={14} />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      ) : null}
      {/* Feb-2026 · Header cleanup — when mounted inline (inside
          <AdminTopBar>) the bell + hamburger sit in the header row
          instead of the fixed top-right corner, and the bell uses
          the ``inline`` variant so it matches the rest of the
          header buttons in size. Floating variant keeps the
          original positioning for customer roles that don't have
          <AdminTopBar>. */}
      <NotificationBell variant={variant === "inline" ? "inline" : "floating"} />
      <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        className={
          variant === "inline"
            ? "inline-flex items-center justify-center w-9 h-9 rounded-lg border shadow-sm bg-white hover:bg-gray-50 focus:outline-none"
            : "fixed top-3 right-3 z-40 inline-flex items-center justify-center w-10 h-10 rounded-lg border shadow-sm bg-white hover:bg-gray-50 focus:outline-none"
        }
        style={{ borderColor: colors.border }}
        data-testid="web-menu-trigger"
        aria-label="Open menu"
      >
        <Menu size={variant === "inline" ? 16 : 20} style={{ color: colors.onSurface }} />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        className="w-[min(92vw,360px)] p-0 overflow-hidden"
        data-testid="web-menu-sheet"
        // Intercept Enter so it doesn't submit any parent form the
        // menu might be inside on obscure pages.
        onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
      >
        {/* Search */}
        <div
          className="flex items-center gap-2 border-b px-3 h-11"
          style={{ borderColor: colors.border }}
        >
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="flex-1 text-sm bg-transparent focus:outline-none"
            data-testid="web-menu-search"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="p-0.5 rounded hover:bg-gray-100"
              data-testid="web-menu-search-clear"
              aria-label="Clear search"
            >
              <X size={14} style={{ color: colors.muted }} />
            </button>
          ) : null}
        </div>

        <div className="max-h-[70vh] overflow-y-auto">
          {/* Pins — hidden when searching so it doesn't compete with
              the query results. */}
          {!query && pins.length > 0 ? (
            <div className="px-3 pt-3">
              <div className="text-[10px] uppercase tracking-wider opacity-60 mb-1.5">
                Pinned
              </div>
              <div className="flex flex-wrap gap-1.5">
                {pins.map((p) => {
                  const e = byPath[p];
                  if (!e) return null;
                  const Icon = e.icon;
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => openEntry(e)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded border text-xs"
                      style={{ borderColor: colors.border, color: colors.onSurface }}
                      data-testid={`web-menu-pin-${p.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}
                    >
                      {Icon ? <Icon size={12} /> : null}
                      <span className="truncate max-w-[140px]">{e.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* Recents */}
          {!query && recents.length > 0 ? (
            <div className="px-3 pt-3">
              <div className="text-[10px] uppercase tracking-wider opacity-60 mb-1.5">
                Recent
              </div>
              <div className="flex flex-wrap gap-1.5">
                {recents.map((r) => {
                  const e = byPath[r.path];
                  if (!e) return null;
                  const Icon = e.icon;
                  return (
                    <button
                      key={r.path}
                      type="button"
                      onClick={() => openEntry(e)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded border text-xs"
                      style={{ borderColor: colors.border, color: colors.onSurface }}
                      data-testid={`web-menu-recent-${r.path.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}
                    >
                      {Icon ? <Icon size={12} /> : null}
                      <span className="truncate max-w-[140px]">{e.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* Category chips */}
          {sections.length > 1 ? (
            <div className="flex gap-1.5 overflow-x-auto px-3 pt-3 pb-1">
              <button
                type="button"
                onClick={() => setChip("all")}
                className="shrink-0 text-xs px-2 py-1 rounded-full border"
                style={{
                  borderColor: chip === "all" ? colors.brand : colors.border,
                  backgroundColor: chip === "all" ? colors.brand : "transparent",
                  color: chip === "all" ? "#FFFFFF" : colors.onSurface,
                }}
                data-testid="web-menu-chip-all"
              >
                All
              </button>
              {sections.map((g) => (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => setChip(g.key)}
                  className="shrink-0 text-xs px-2 py-1 rounded-full border whitespace-nowrap"
                  style={{
                    borderColor: chip === g.key ? colors.brand : colors.border,
                    backgroundColor: chip === g.key ? colors.brand : "transparent",
                    color: chip === g.key ? "#FFFFFF" : colors.onSurface,
                  }}
                  data-testid={`web-menu-chip-${g.key}`}
                >
                  {g.label}
                </button>
              ))}
            </div>
          ) : null}

          {/* Filtered section list */}
          <div className="p-2">
            {filteredSections.length === 0 ? (
              <div className="p-6 text-center text-sm" style={{ color: colors.muted }} data-testid="web-menu-empty">
                No pages match.
              </div>
            ) : (
              filteredSections.map((g) => (
                <div key={g.key} className="mt-2" data-testid={`web-menu-section-${g.key}`}>
                  <div className="text-[10px] uppercase tracking-wider opacity-60 px-2 mb-1">
                    {g.label}
                  </div>
                  {g.entries.map((e) => {
                    const Icon = e.icon;
                    const pinned = pins.includes(e.to);
                    const slug = e.to.replace(/^\/+/, "").replace(/\//g, "-") || "root";
                    return (
                      <div
                        key={e.to}
                        className="flex items-center gap-2 px-2 py-2 rounded-md hover:bg-gray-50"
                      >
                        <Link
                          to={e.to}
                          onClick={(ev) => { ev.preventDefault(); openEntry(e); }}
                          className="flex items-center gap-2 flex-1 min-w-0"
                          data-testid={`web-menu-link-${slug}`}
                        >
                          {Icon ? <Icon size={14} className="opacity-80 shrink-0" /> : null}
                          <span className="text-sm truncate" style={{ color: colors.onSurface }}>
                            {e.label}
                          </span>
                        </Link>
                        <button
                          type="button"
                          onClick={(ev) => { ev.stopPropagation(); togglePin(e.to); }}
                          className="p-1 rounded hover:bg-gray-100"
                          data-testid={`web-menu-pin-toggle-${slug}`}
                          aria-label={pinned ? `Unpin ${e.label}` : `Pin ${e.label}`}
                        >
                          {pinned ? (
                            <BookmarkCheck size={14} style={{ color: colors.brand }} />
                          ) : (
                            <Bookmark size={14} style={{ color: colors.muted }} />
                          )}
                        </button>
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
    </>
  );
}
