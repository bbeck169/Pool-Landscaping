/**
 * Feb-2026 · ResponsiveTabs
 * ─────────────────────────────────────────────────────────────────────
 * Detail-page tab strip that switches trigger surfaces based on
 * viewport width:
 *   • ≥ md (768px)  — familiar horizontal strip, one button per tab,
 *                     underline on active. Matches the pre-existing
 *                     inline pattern in ``CustomerDetail.jsx`` and
 *                     ``PropertyDrawer.jsx`` byte-for-byte, so the
 *                     desktop UX is unchanged.
 *   • <  md         — full-width DropdownMenu trigger showing the
 *                     active tab's icon + label + caret; items keep
 *                     their icons so the visual language is
 *                     consistent with the desktop strip.
 *
 * Both surfaces render simultaneously in the DOM; CSS (`md:hidden` /
 * `hidden md:flex`) toggles visibility.  No JS media query, no
 * hydration flicker, no dependency on window size at mount time.
 *
 * API — accepts BOTH shapes to accommodate the two Group-A callers:
 *
 *   1. Rich (CustomerDetail):
 *        [{ k: "overview", label: "Overview", icon: MapPin }, ...]
 *   2. Plain string list (PropertyDrawer):
 *        ["Info", "Contact", "Service Notes", ...]
 *      — normalized internally to ``{ k: str, label: str }``.
 *
 * Parent still owns the ``active`` state + ``onChange`` closure, so
 * URL query-param sync, deep-linking, and existing wiring survive
 * with zero migration churn.
 *
 * Accessibility notes:
 *   • Horizontal strip renders as `<nav>` with `<button>`s — matches
 *     the pre-existing shape (which also does NOT use ARIA tab
 *     roles). Kept intentionally to avoid changing keyboard-nav
 *     semantics under a UX-only refactor.
 *   • Dropdown branch inherits Radix DropdownMenu ARIA
 *     (aria-haspopup, aria-expanded, roving focus among items,
 *     Enter/Space to activate).
 */

import React from "react";
import { ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { colors } from "@/theme";

function _normalize(tabs) {
  return (tabs || []).map((t) =>
    typeof t === "string"
      ? { k: t, label: t, icon: null }
      : { k: t.k ?? t.key ?? t.value ?? t.label, label: t.label ?? t.k, icon: t.icon || null },
  );
}

function _safeTestid(prefix, k) {
  const slug = String(k || "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase();
  return `${prefix}-${slug}`;
}

// Phase J1 · Feb-2026 — LRU-3 recent-tabs helper.  Persists to
// ``localStorage[recentStorageKey]`` when the parent passes the
// prop.  Reading is fault-tolerant (private-mode / quota-exceeded /
// non-JSON payload all short-circuit to an empty list) so the
// dropdown never blocks rendering because of storage weirdness.
function _readRecent(storageKey) {
  if (!storageKey || typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((k) => typeof k === "string") : [];
  } catch {
    return [];
  }
}

function _writeRecent(storageKey, keys) {
  if (!storageKey || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(keys));
  } catch {
    /* private-mode / quota — best-effort */
  }
}

function _pushRecent(storageKey, nextKey) {
  const prev = _readRecent(storageKey);
  const dedup = [nextKey, ...prev.filter((k) => k !== nextKey)].slice(0, 3);
  _writeRecent(storageKey, dedup);
  return dedup;
}

export function ResponsiveTabs({
  tabs,
  active,
  onChange,
  testidPrefix = "rt-tab",
  ariaLabel = "Sections",
  forceDropdown = false,
  recentStorageKey = null,
}) {
  const items = _normalize(tabs);
  const activeItem = items.find((t) => t.k === active) || items[0] || null;
  const ActiveIcon = activeItem?.icon || null;

  // Phase J1 · Feb-2026 — recent-tabs subheader.  Only rendered
  // when ``recentStorageKey`` is provided AND at least one recent
  // key still resolves to a valid tab entry in the current tabs
  // list (belt-and-suspenders against stale localStorage after a
  // tab rename or removal).
  const [recentKeys, setRecentKeys] = React.useState(
    () => _readRecent(recentStorageKey),
  );
  React.useEffect(() => {
    setRecentKeys(_readRecent(recentStorageKey));
  }, [recentStorageKey]);
  const recentItems = recentKeys
    .map((k) => items.find((t) => t.k === k))
    .filter(Boolean);

  const handleSelect = (k) => {
    if (recentStorageKey) {
      setRecentKeys(_pushRecent(recentStorageKey, k));
    }
    onChange(k);
  };

  // Phase I6 · Feb-2026 — ``forceDropdown`` collapses the ≥md
  // horizontal strip into the same dropdown variant used on small
  // screens.  Turns a 10-tab overflow-x-auto scroll into a single
  // width-bounded select on the customer detail page.  Other
  // consumers (e.g. PropertyDrawer) keep their responsive behavior
  // by leaving the prop unset.
  const dropdownShellClass = forceDropdown ? "" : "md:hidden";
  const stripClass = forceDropdown
    ? "hidden"
    : "hidden md:flex overflow-x-auto";

  return (
    <>
      {/* ── Dropdown (< md, OR forceDropdown) ─────────────────── */}
      <div
        className={dropdownShellClass}
        style={{ borderBottom: `1px solid ${colors.border}` }}
        data-testid={`${testidPrefix}-dropdown-shell`}
      >
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-semibold"
              style={{ color: colors.brand, backgroundColor: colors.surface }}
              data-testid={`${testidPrefix}-dropdown-trigger`}
              aria-label={ariaLabel}
            >
              <span className="flex items-center gap-2 min-w-0 truncate">
                {ActiveIcon ? <ActiveIcon size={14} /> : null}
                <span className="truncate">{activeItem?.label ?? "Select…"}</span>
              </span>
              <ChevronDown size={16} aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            sideOffset={4}
            className="w-[calc(100vw-2rem)] max-w-sm"
            data-testid={`${testidPrefix}-dropdown-content`}
          >
            {recentItems.length ? (
              <>
                <DropdownMenuLabel
                  className="text-[10px] font-bold uppercase tracking-wider"
                  style={{ color: colors.muted }}
                  data-testid={`${testidPrefix}-recent-header`}
                >
                  Recent
                </DropdownMenuLabel>
                {recentItems.map((t) => {
                  const Icon = t.icon;
                  const isActive = t.k === active;
                  return (
                    <DropdownMenuItem
                      key={`recent-${t.k}`}
                      onSelect={() => handleSelect(t.k)}
                      data-testid={_safeTestid(
                        `${testidPrefix}-recent`, t.k)}
                      data-active={isActive ? "true" : undefined}
                      style={{
                        color: isActive ? colors.brand : colors.onSurface,
                        fontWeight: isActive ? 600 : 500,
                      }}
                    >
                      {Icon ? <Icon size={14} className="mr-2" /> : null}
                      {t.label}
                    </DropdownMenuItem>
                  );
                })}
                <DropdownMenuSeparator
                  data-testid={`${testidPrefix}-recent-divider`}
                />
              </>
            ) : null}
            {items.map((t) => {
              const Icon = t.icon;
              const isActive = t.k === active;
              return (
                <DropdownMenuItem
                  key={t.k}
                  onSelect={() => handleSelect(t.k)}
                  data-testid={_safeTestid(testidPrefix, t.k)}
                  data-active={isActive ? "true" : undefined}
                  style={{
                    color: isActive ? colors.brand : colors.onSurface,
                    fontWeight: isActive ? 600 : 500,
                  }}
                >
                  {Icon ? <Icon size={14} className="mr-2" /> : null}
                  {t.label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* ── Horizontal strip (≥ md unless forceDropdown) ────── */}
      <nav
        className={stripClass}
        style={{ borderBottom: `1px solid ${colors.border}` }}
        aria-label={ariaLabel}
      >
        {items.map((t) => {
          const Icon = t.icon;
          const isActive = t.k === active;
          return (
            <button
              key={t.k}
              type="button"
              onClick={() => handleSelect(t.k)}
              className="flex items-center gap-2 px-4 py-3 text-sm font-semibold whitespace-nowrap transition"
              style={{
                color: isActive ? colors.brand : colors.muted,
                borderBottom: `2px solid ${isActive ? colors.brand : "transparent"}`,
              }}
              data-testid={_safeTestid(testidPrefix, t.k)}
            >
              {Icon ? <Icon size={14} /> : null}
              {t.label}
            </button>
          );
        })}
      </nav>
    </>
  );
}

export default ResponsiveTabs;
