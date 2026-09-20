import React, { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { Star, ChevronRight, ChevronDown, Search as SearchIcon, HelpCircle, GripVertical, Home as HomeIcon } from "lucide-react";
import { ADMIN_NAV_V2, NAV_FLAT, KEYBOARD_SHORTCUTS, SHORTCUT_TARGETS, filterNavByIndustries } from "@/nav/adminNav";
import { usePermissions } from "@/hooks/usePermissions";
import { useIndustries } from "@/hooks/useIndustries";
import RolePreviewSwitcher from "@/components/RolePreviewSwitcher";
import { colors, gradients } from "@/theme";
// Feb-2026 · Drag-and-drop reordering of pinned nav items.
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, arrayMove,
  sortableKeyboardCoordinates, useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

// Groups that render nested sub-subgroups (from entry.subsection) when present.
// Phase 35 — all five reorganised categories now use subsections for readability.
const SUBGROUPED_GROUPS = new Set([
  "finance",
  "marketing",
  "operations",
  "customers",
]);

const LS_PINNED = "nav_pinned_v1";
const LS_RECENT = "nav_recent_v1";
const LS_GROUPS = "nav_groups_state_v1";
// Feb-2026 · Admin pinned-nav cap raised from 8 → 20 per user request.
const MAX_PINNED = 20;

function loadLS(k, fb) { try { return JSON.parse(localStorage.getItem(k) || "null") ?? fb; } catch { return fb; } }
function saveLS(k, v)  { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }

/* ═══ Admin Sidebar (Phase 15 redesign) ═══════════════════════════════ */
export default function AdminSidebar() {
  const { can, effectiveRole } = usePermissions();
  // Phase Feb-2026 · Multi-industry Phase C — hide industry-specific
  // nav items (Pool Service, Landscape AI, etc.) when the tenant
  // doesn't have that industry active.
  const { industries } = useIndustries();
  const location = useLocation();
  const navigate = useNavigate();

  const [pinned, setPinned] = useState(() => loadLS(LS_PINNED, []));
  const [recent, setRecent] = useState(() => loadLS(LS_RECENT, []));
  const [groupsOpen, setGroupsOpen] = useState(() => loadLS(LS_GROUPS, {
    overview: true, work: true, sales: true, billing: false, ops: false,
    reports: false, marketing: false, seo_gbp: false, ai_tools: false, settings: false,
  }));
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // Persist
  useEffect(() => saveLS(LS_PINNED, pinned), [pinned]);
  useEffect(() => saveLS(LS_GROUPS, groupsOpen), [groupsOpen]);

  // Collapsible Left Nav · Feb 2026 — auto-expand the group that owns the
  // current route on mount (and whenever the route changes). Preserves
  // any other groups the user has manually toggled — only ever OPENS the
  // active group; never closes anything.
  useEffect(() => {
    const activeGroupKey = (() => {
      // Longest-prefix match wins so /admin/finance/stripe-payments beats /admin.
      let best = null;
      let bestLen = -1;
      for (const g of ADMIN_NAV_V2) {
        for (const e of (g.entries || [])) {
          if (!e.to) continue;
          const to = e.to;
          if (location.pathname === to || location.pathname.startsWith(to + "/")) {
            if (to.length > bestLen) {
              best = g.key;
              bestLen = to.length;
            }
          }
        }
      }
      return best;
    })();
    if (activeGroupKey) {
      setGroupsOpen((prev) => (prev[activeGroupKey] ? prev : { ...prev, [activeGroupKey]: true }));
    }
  }, [location.pathname]);

  // Track recent
  useEffect(() => {
    const item = NAV_FLAT.find((e) => e.to === location.pathname);
    if (!item) return;
    setRecent((prev) => {
      const next = [item.to, ...prev.filter((p) => p !== item.to)].slice(0, 5);
      saveLS(LS_RECENT, next);
      return next;
    });
  }, [location.pathname]);

  // Keyboard shortcuts
  useEffect(() => {
    let gArmed = false, gTimer = null;
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault(); setPaletteOpen(true); return;
      }
      if (e.key === "?" && !e.target.matches("input,textarea")) {
        e.preventDefault(); setHelpOpen(true); return;
      }
      if (e.target.matches("input,textarea")) return;
      if (e.key.toLowerCase() === "g") {
        gArmed = true; clearTimeout(gTimer);
        gTimer = setTimeout(() => { gArmed = false; }, 900);
        return;
      }
      if (gArmed) {
        gArmed = false;
        const target = SHORTCUT_TARGETS[e.key.toLowerCase()];
        if (target) { e.preventDefault(); navigate(target); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const togglePin = (to) => setPinned((p) => p.includes(to) ? p.filter((x) => x !== to) : [...p, to].slice(0, MAX_PINNED));
  const toggleGroup = (k) => setGroupsOpen((s) => ({ ...s, [k]: !s[k] }));

  const visible = useMemo(() => ADMIN_NAV_V2.map((g) => ({
    ...g,
    entries: filterNavByIndustries(g.entries, industries).filter((e) => {
      if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
      if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
      // Phase A1 · Feb-2026 — Proactive Intelligence.
      // Mirrors the backend ``insufficient_role_for_alerts`` gate
      // exactly (admin + super_admin, no manager, no technician).
      if (e.hard_rule === "admin_or_super_admin") {
        return ["admin", "super_admin"].includes(effectiveRole);
      }
      // Feb 2026 · Task A hotfix — ``manager_only`` is authoritative.
      // Backend permission matrix (see ``routers/rbac.py::_DEFAULT_MATRIX``)
      // seeds ONLY super_admin, admin, technician, customer, marketer,
      // sales — ``manager`` is deliberately absent. That means
      // ``can("scheduling","read")`` returns false for a real manager
      // account, which was silently hiding every ``manager_only`` nav
      // entry (Recurring Jobs, Driver Activity, SEO Auditor, etc.).
      // Treat the hard_rule as the authorization source of truth:
      // if the role is in the allowed three-role set, grant access
      // without falling through to the feature matrix. Roles OUTSIDE
      // the allowed set stay blocked (unchanged behaviour for
      // marketer / sales / technician / customer).
      if (e.hard_rule === "manager_only") {
        return ["super_admin", "admin", "manager"].includes(effectiveRole);
      }
      return can(e.feature || "dashboard", "read") || effectiveRole === "admin";
    }),
  })).filter((g) => g.entries.length > 0), [can, effectiveRole, industries]);

  const flatVisible = useMemo(() => visible.flatMap((g) => g.entries), [visible]);
  const pinnedItems = pinned.map((to) => flatVisible.find((e) => e.to === to)).filter(Boolean);
  const recentItems = recent.map((to) => flatVisible.find((e) => e.to === to)).filter(Boolean);

  const Entry = ({ e, showStar = true }) => {
    const Icon = e.icon || SearchIcon;
    const isPinned = pinned.includes(e.to);
    return (
      <div className="flex items-center group" data-testid={`nav-entry-${e.to.replaceAll("/", "-")}`}>
        <NavLink
          to={e.to}
          className={({ isActive }) =>
            [
              "flex-1 flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm",
              "transition-all duration-200 ease-out will-change-transform",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:scale-[1.02]",
              "hover:scale-[1.02]",
              isActive
                ? ""
                : "hover:bg-sky-50/70 hover:text-sky-600",
            ].join(" ")
          }
          style={({ isActive }) => ({
            background: isActive ? gradients.navyToGreen.css : undefined,
            color: isActive ? "#fff" : colors.onSurface,
            fontWeight: isActive ? 600 : 400,
          })}
        >
          <Icon size={15} className="transition-colors duration-200 group-hover:text-sky-600" />
          <span className="truncate transition-colors duration-200">{e.label}</span>
        </NavLink>
        {showStar && (
          <button onClick={() => togglePin(e.to)}
                  className={`ml-1 p-1 rounded ${isPinned ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                  style={{ color: isPinned ? "#EAB308" : colors.onSurfaceSecondary }}
                  data-testid={`nav-pin-${e.to.replaceAll("/", "-")}`}
                  title={isPinned ? "Unpin" : "Pin to top"}>
            <Star size={13} fill={isPinned ? "#EAB308" : "none"} />
          </button>
        )}
      </div>
    );
  };

  // Feb-2026 · Drag-and-drop reordering — pinned-only wrapper.
  // Each pinned row gets a grip-handle that owns the drag listeners;
  // the rest of the row (link + star) stays clickable so single-click
  // navigation continues to work.
  const SortablePinnedEntry = ({ e }) => {
    const {
      attributes, listeners, setNodeRef, transform, transition, isDragging,
    } = useSortable({ id: e.to });
    const style = {
      transform: CSS.Transform.toString(transform),
      transition,
      opacity: isDragging ? 0.6 : 1,
    };
    const Icon = e.icon || SearchIcon;
    return (
      <div ref={setNodeRef} style={style}
            className="flex items-center group"
            data-testid={`nav-pinned-entry-${e.to.replaceAll("/", "-")}`}>
        <button
          type="button"
          {...attributes}
          {...listeners}
          className="p-1 rounded cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 touch-none"
          aria-label={`Reorder ${e.label}`}
          data-testid={`nav-pinned-handle-${e.to.replaceAll("/", "-")}`}
          title="Drag to reorder"
        >
          <GripVertical size={13} />
        </button>
        <NavLink to={e.to}
                  className={() => "flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm"}
                  style={({ isActive }) => ({
                    background: isActive ? gradients.navyToGreen.css : "transparent",
                    color: isActive ? "#fff" : colors.onSurface,
                    fontWeight: isActive ? 600 : 400,
                  })}>
          <Icon size={15} />
          <span className="truncate">{e.label}</span>
        </NavLink>
        <button onClick={() => togglePin(e.to)}
                className="ml-1 p-1 rounded opacity-0 group-hover:opacity-100"
                style={{ color: "#EAB308" }}
                data-testid={`nav-unpin-${e.to.replaceAll("/", "-")}`}
                title="Unpin">
          <Star size={13} fill="#EAB308" />
        </button>
      </div>
    );
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handlePinnedDragEnd = (event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setPinned((prev) => {
      const from = prev.indexOf(active.id);
      const to = prev.indexOf(over.id);
      if (from === -1 || to === -1) return prev;
      return arrayMove(prev, from, to);
    });
  };

  return (
    <>
      {/* Command palette trigger (rendered by parent AppLayout top-bar too) */}
      <div className="px-3 mb-2">
        <button
          onClick={() => setPaletteOpen(true)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary, border: `1px solid ${colors.border}` }}
          data-testid="nav-palette-trigger"
        >
          <SearchIcon size={14} />
          <span className="flex-1 text-left">Search or jump to…</span>
          <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ backgroundColor: "#fff", border: `1px solid ${colors.border}` }}>⌘K</span>
        </button>
      </div>

      {/* Queue Item 6 · Feb-2026 — Dashboard shortcut. Rendered
          directly under the palette trigger so the top of every
          admin sidebar snap has a Home affordance. */}
      <div className="px-3 mb-3">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold ${
              isActive ? "" : "hover:brightness-95"
            }`
          }
          style={({ isActive }) => ({
            backgroundColor: isActive ? colors.brandTertiary : colors.surface,
            color: isActive ? colors.onBrandTertiary : colors.onSurface,
            border: `1px solid ${colors.border}`,
          })}
          data-testid="nav-dashboard-link"
        >
          <HomeIcon size={14} />
          <span className="flex-1 text-left">Dashboard</span>
        </NavLink>
      </div>

      {/* Phase 29C · "Test as role" switcher — admin / super-admin only. */}
      <div className="px-3 mb-3">
        <RolePreviewSwitcher />
      </div>

      {/* Pinned */}
      {pinnedItems.length > 0 && (
        <div className="px-2 mb-3" data-testid="nav-pinned">
          <div className="px-2 mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>⭐ Pinned</div>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handlePinnedDragEnd}
          >
            <SortableContext
              items={pinnedItems.map((e) => e.to)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-0.5" data-testid="nav-pinned-sortable">
                {pinnedItems.map((e) => (
                  <SortablePinnedEntry key={e.to} e={e} />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        </div>
      )}

      {/* Feb-2026 · Item 3 — the "🕘 Recent" widget was removed from
          the main menu per user request. The nav_recent_v1 tracker
          still runs so the ⌘K palette can surface recent pages,
          but the sidebar section is no longer rendered. */}

      {/* Main groups */}
      <div className="px-2">
        {visible.map((g) => {
          const GIcon = g.icon;
          const open = groupsOpen[g.key];
          const useSubgroups = SUBGROUPED_GROUPS.has(g.key) && g.entries.some((e) => e.subsection);
          // Preserve first-appearance order of subsections.
          const subsections = useSubgroups
            ? g.entries.reduce((acc, e) => {
                const s = e.subsection || "General";
                if (!acc.find((row) => row.name === s)) acc.push({ name: s, entries: [] });
                acc.find((row) => row.name === s).entries.push(e);
                return acc;
              }, [])
            : null;
          return (
            <div key={g.key} className="mb-1" data-testid={`nav-group-${g.key}`}>
              <button onClick={() => toggleGroup(g.key)}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-bold uppercase tracking-wider"
                      style={{ color: colors.onSurfaceSecondary }}
                      data-testid={`nav-group-toggle-${g.key}`}>
                <GIcon size={13} />
                <span className="flex-1 text-left">{g.label}</span>
                {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              </button>
              {open && (
                <div className="space-y-0.5 pl-1">
                  {useSubgroups
                    ? subsections.map((sub) => (
                        <div key={sub.name} className="mt-1" data-testid={`nav-subsection-${g.key}-${sub.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
                          <div className="px-3 pt-1 pb-0.5 text-[10px] font-semibold tracking-wide" style={{ color: colors.muted }}>
                            {sub.name}
                          </div>
                          <div className="space-y-0.5">
                            {sub.entries.map((e) => <Entry key={e.to} e={e} />)}
                          </div>
                        </div>
                      ))
                    : g.entries.map((e) => <Entry key={e.to} e={e} />)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Floating help */}
      <button onClick={() => setHelpOpen(true)}
              className="fixed bottom-4 right-4 z-40 w-9 h-9 rounded-full text-white flex items-center justify-center shadow-lg"
              style={{ background: gradients.navyToGreen.css }}
              data-testid="nav-help-btn" title="Keyboard shortcuts">
        <HelpCircle size={17} />
      </button>

      {paletteOpen && <Palette flat={flatVisible} recent={recentItems} onClose={() => setPaletteOpen(false)} />}
      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
    </>
  );
}

/* ─── Command Palette (no external lib) ────────────────────────────── */
function Palette({ flat, recent, onClose }) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef(null);
  useEffect(() => inputRef.current?.focus(), []);

  const query = q.trim().toLowerCase();
  const isCmd = query.startsWith(">");
  const term = isCmd ? query.slice(1).trim() : query;

  const pageResults = useMemo(() => {
    if (!term) return flat.slice(0, 10);
    return flat.filter((e) =>
      (e.label || "").toLowerCase().includes(term) ||
      (e.group || "").toLowerCase().includes(term) ||
      (e.to || "").toLowerCase().includes(term)
    ).slice(0, 30);
  }, [term, flat]);

  const commands = [
    { label: "New customer", to: "/customers/new", group: "Command" },
    { label: "New job", to: "/jobs/new", group: "Command" },
    { label: "New quote", to: "/quotes/new", group: "Command" },
    { label: "New lead", to: "/leads/new", group: "Command" },
    { label: "New form", to: "/forms", group: "Command" },
    { label: "Access settings (impersonation preview)", to: "/access-settings", group: "Command" },
  ].filter((c) => !term || (c.label || "").toLowerCase().includes(term));

  const sections = isCmd
    ? [{ heading: "Commands", rows: commands }]
    : [
        { heading: "Pages", rows: pageResults },
        !query && recent.length ? { heading: "Recent", rows: recent } : null,
      ].filter(Boolean);
  const allRows = sections.flatMap((s) => s.rows);

  const go = (row) => { if (row?.to) navigate(row.to); onClose(); };

  useEffect(() => setIdx(0), [q]);

  const onKey = (e) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, allRows.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(allRows[idx]); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 p-4" style={{ backgroundColor: "rgba(0,0,0,0.5)" }} onClick={onClose} data-testid="nav-palette">
      <div className="bg-white rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()} style={{ border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: colors.border }}>
          <SearchIcon size={16} style={{ color: colors.onSurfaceSecondary }} />
          <input
            ref={inputRef}
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Search or type > for commands…"
            className="flex-1 outline-none text-sm"
            data-testid="nav-palette-input"
          />
          <kbd className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ backgroundColor: colors.surfaceSecondary }}>Esc</kbd>
        </div>
        <div className="max-h-96 overflow-y-auto">
          {sections.map((sec) => (
            <div key={sec.heading}>
              <div className="px-4 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>{sec.heading}</div>
              {sec.rows.length === 0 && <div className="px-4 py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>Nothing matches.</div>}
              {sec.rows.map((row, _i) => {
                const globalIdx = allRows.indexOf(row);
                const active = globalIdx === idx;
                return (
                  <button key={`${sec.heading}-${row.to}`} onClick={() => go(row)}
                          onMouseEnter={() => setIdx(globalIdx)}
                          className="w-full flex items-center gap-2 px-4 py-2 text-sm text-left"
                          style={{ backgroundColor: active ? colors.surfaceSecondary : "transparent" }}
                          data-testid={`nav-palette-row-${row.to.replaceAll("/", "-")}`}>
                    <span className="flex-1">{row.label}</span>
                    <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{row.group || row.to}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ─── Shortcut help modal ─────────────────────────────────────────── */
function ShortcutHelp({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(0,0,0,0.5)" }} onClick={onClose} data-testid="nav-shortcut-help">
      <div className="bg-white rounded-2xl max-w-md w-full p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} style={{ border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold">Keyboard shortcuts</h2>
          <button onClick={onClose} className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Close</button>
        </div>
        {KEYBOARD_SHORTCUTS.map((s) => (
          <div key={s.label} className="flex items-center justify-between py-1.5 border-b last:border-0" style={{ borderColor: colors.border }}>
            <span className="text-sm">{s.label}</span>
            <kbd className="text-xs font-mono px-2 py-0.5 rounded" style={{ backgroundColor: colors.surfaceSecondary }}>{s.keys}</kbd>
          </div>
        ))}
      </div>
    </div>
  );
}
