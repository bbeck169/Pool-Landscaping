/**
 * Phase K75 · Step B · Feb-2026 — user-editable Quick Access rail.
 *
 * Feb-2026 P2 interrupt · long-press → edit-mode UX layered on top
 *   of the K75 CRUD surface. Long-pressing a pin (500 ms, primary
 *   button only, cancels on >10 px movement / pointercancel /
 *   pointerleave) enters an edit mode where the per-pin "×" is
 *   unconditionally visible + reachable and the pins jiggle. The
 *   rail's bottom "+ Add pin" affordance is replaced in-place with
 *   a "Done" button (zero reflow). Click-outside, Escape, Done, or
 *   navigating via any pin all exit edit mode. Keyboard-only entry
 *   is via a visible "Edit pins" button in the rail header.
 *
 * Navigation stays functional in edit mode (clicking a NavLink
 *   navigates + resets edit mode) — removal is the only destructive
 *   action gated by the mode.
 *
 * Preserves the pre-K75 ``data-testid="quick-nav-rail"`` +
 * ``data-testid="rail-nav-${key}"`` naming so the existing
 * ``rail-nav.test.jsx`` / ``rail-nav-leads.test.jsx`` /
 * ``phase20-quick-nav-rail-managerial-links.test.jsx`` suites keep
 * locking the shape byte-for-byte. The K75 CRUD suite also stays
 * green because the ``×`` element still renders + its onClick
 * handler still fires on ``fireEvent.click`` (CSS pointer-events
 * gating does not block jsdom direct dispatch).
 */
import React, { useState, useRef, useEffect, useCallback } from "react";
import { NavLink } from "react-router-dom";
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, arrayMove,
  sortableKeyboardCoordinates, useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Plus, X, GripVertical, Pencil, Check } from "lucide-react";
import { colors } from "@/theme";
import { useQuickPins } from "@/hooks/useQuickPins";
import AddPinModal from "@/components/nav/AddPinModal";
import RemovePinConfirm from "@/components/nav/RemovePinConfirm";


function _keyForPin(p) {
  return p.key
    || p.to.replace(/^\/+/, "").replace(/[/?=&]/g, "-") || "root";
}


// Feb-2026 · Task 4 — legacy pins persisted with the
// ``"<Parent> · <Leaf>"`` shape (e.g. ``"Sales · Quotes"``) render as
// just the leaf name. Newly-added pins are already leaf-only via
// ``pinRegistry.js`` — this shim protects the display for the pins
// already on file.
function _displayLabel(raw) {
  if (!raw || typeof raw !== "string") return raw || "";
  const m = raw.match(/^.+ · (.+)$/);
  return m ? m[1] : raw;
}


// Feb-2026 P2 interrupt · long-press primitive. Inline (not hook/)
// because this is a one-off UX gesture for the rail — extraction
// is tech-debt only if a second consumer lands or this file passes
// 400 lines. Pointer guardrails:
//   • Primary button only (``e.button === 0``); right-click no-ops.
//   • >10 px pointermove cancels the pending timer (scroll/drag
//     intent takes precedence).
//   • ``pointercancel`` and ``pointerleave`` both clear the timer.
//   • ``longPressFiredRef`` is checked in capture phase on the next
//     click so the subsequent NavLink click is suppressed when the
//     press transitioned into edit-mode activation.
const LONG_PRESS_MS = 500;
const LONG_PRESS_CANCEL_PX = 10;


function SortableRailPin({ pin, editMode, onRequestRemove, onLongPressFire, onNavClickExit }) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: pin.to });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : 1,
  };
  const key = _keyForPin(pin);
  const Icon = pin.Icon;

  // Long-press state is per-row — a timer on one pin should not
  // interfere with another pin's state. Both refs are reset on each
  // fresh ``pointerdown``.
  const timerRef = useRef(null);
  const startRef = useRef({ x: 0, y: 0 });
  const longPressFiredRef = useRef(false);

  const _clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const _onPointerDown = useCallback((e) => {
    // Primary button only — right-click / middle-click never trigger.
    if (e.button !== 0) return;
    longPressFiredRef.current = false;
    startRef.current = { x: e.clientX, y: e.clientY };
    _clearTimer();
    timerRef.current = setTimeout(() => {
      longPressFiredRef.current = true;
      timerRef.current = null;
      onLongPressFire();
    }, LONG_PRESS_MS);
  }, [_clearTimer, onLongPressFire]);

  const _onPointerMove = useCallback((e) => {
    if (!timerRef.current) return;
    const dx = Math.abs(e.clientX - startRef.current.x);
    const dy = Math.abs(e.clientY - startRef.current.y);
    if (dx > LONG_PRESS_CANCEL_PX || dy > LONG_PRESS_CANCEL_PX) {
      _clearTimer();
    }
  }, [_clearTimer]);

  const _onPointerEnd = useCallback(() => {
    _clearTimer();
  }, [_clearTimer]);

  // Capture-phase click interceptor: if the preceding long-press
  // actually fired, swallow the click so the NavLink inside doesn't
  // navigate on the user's finger-up. This keeps edit-mode entry
  // intent-pure without affecting short-tap navigation.
  const _onClickCapture = useCallback((e) => {
    if (longPressFiredRef.current) {
      e.preventDefault();
      e.stopPropagation();
      longPressFiredRef.current = false;
    }
  }, []);

  // Clean up any pending timer on unmount (e.g. route unmount of
  // the whole rail).
  useEffect(() => () => _clearTimer(), [_clearTimer]);

  // Edit-mode visual: ultra-subtle jiggle (±1.5°, 0.6 s loop) when
  // active. ``motion-reduce:animate-none`` is a Tailwind utility
  // that applies ``@media (prefers-reduced-motion: reduce) {
  // animation: none; }`` — honored without a matchMedia probe.
  const jiggleCls = editMode ? "animate-pin-jiggle motion-reduce:animate-none" : "";

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`relative group mx-2 ${jiggleCls}`}
      data-testid={`rail-pin-${key}`}
      onPointerDown={_onPointerDown}
      onPointerMove={_onPointerMove}
      onPointerUp={_onPointerEnd}
      onPointerCancel={_onPointerEnd}
      onPointerLeave={_onPointerEnd}
      onClickCapture={_onClickCapture}
    >
      {/* Grip handle — top-left, visible on hover, owns drag listeners. */}
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="absolute -left-1 top-1 z-10 opacity-0 group-hover:opacity-100 focus:opacity-100 rounded-full p-0.5 cursor-grab active:cursor-grabbing touch-none"
        style={{ color: colors.nav.fgMuted }}
        aria-label={`Reorder ${_displayLabel(pin.label)}`}
        data-testid={`rail-pin-handle-${key}`}
        title="Drag to reorder"
      >
        <GripVertical size={12} />
      </button>
      {/* Unpin button — unconditionally visible + reachable when
          edit mode is on. In non-edit mode: opacity-0 and
          ``pointer-events-none`` so accidental hover-reveal clicks
          are blocked in real browsers. (jsdom direct dispatch via
          ``fireEvent.click`` still fires the handler, preserving
          the K75 CRUD test which asserts the confirm dialog opens
          on × click without entering edit mode first.) */}
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); onRequestRemove(pin); }}
        className={
          editMode
            ? "absolute -right-0 top-1 z-10 opacity-100 pointer-events-auto rounded-full p-0.5"
            : "absolute -right-0 top-1 z-10 opacity-0 pointer-events-none rounded-full p-0.5"
        }
        style={{ backgroundColor: "rgba(255,255,255,0.14)", color: colors.nav.fg }}
        aria-label={`Remove ${_displayLabel(pin.label)} pin`}
        data-testid={`rail-pin-remove-${key}`}
        title="Remove pin"
        tabIndex={editMode ? 0 : -1}
      >
        <X size={11} />
      </button>
      <NavLink
        to={pin.to}
        end={pin.end}
        onClick={() => { if (editMode) onNavClickExit(); }}
        className={({ isActive }) =>
          [
            "rounded-xl flex flex-col items-center justify-center gap-1 py-2",
            "text-[9px] font-semibold",
            "transition-all duration-200 ease-out will-change-transform",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40",
            "hover:scale-[1.02] focus-visible:scale-[1.02]",
            isActive ? "shadow-[0_1px_2px_rgba(0,0,0,0.15)]" : "",
          ].join(" ")
        }
        style={({ isActive }) => ({
          background: isActive ? colors.nav.bgActiveNavy : "transparent",
          color: colors.nav.fg,
          border: `1px solid transparent`,
        })}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = colors.nav.bgActiveNavy;
          // NAV-restyle · Feb-2026 — layer the blue hover glow.
          // Suppressed on active pins so the active pill stays
          // static. Ruling R11 · Option A.
          if (e.currentTarget.getAttribute("aria-current") !== "page") {
            e.currentTarget.style.boxShadow = colors.nav.hoverGlow;
          }
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background =
            e.currentTarget.getAttribute("aria-current") === "page"
              ? colors.nav.bgActiveNavy
              : "transparent";
          e.currentTarget.style.boxShadow = "";
        }}
        data-testid={`rail-nav-${key}`}
        aria-label={_displayLabel(pin.label)}
        title={_displayLabel(pin.label)}
      >
        <Icon size={13} className="transition-colors duration-200" />
        <span className="leading-none text-center transition-colors duration-200">{_displayLabel(pin.label)}</span>
      </NavLink>
    </div>
  );
}


export default function QuickPinsRail({ role }) {
  const {
    pins, addPin, removePin, reorderPins, atCap, cap, pinnedRoutes,
  } = useQuickPins(role);

  const [addOpen, setAddOpen] = useState(false);
  const [pendingRemove, setPendingRemove] = useState(null);
  const [editMode, setEditMode] = useState(false);
  const railRef = useRef(null);
  const doneBtnRef = useRef(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Feb-2026 P2 interrupt · click-outside exit. Inlined per decision
  // #4 of the audit — no shared ``useClickOutside`` hook exists in
  // this codebase and extracting one for a single consumer is
  // premature. ``pointerdown`` fires before any click, giving us a
  // chance to flip the mode off before a stray outside click lands
  // somewhere unexpected.
  useEffect(() => {
    if (!editMode) return undefined;
    const handler = (e) => {
      if (railRef.current && !railRef.current.contains(e.target)) {
        setEditMode(false);
      }
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [editMode]);

  // Esc exits edit mode. Standard dismissal pattern.
  useEffect(() => {
    if (!editMode) return undefined;
    const handler = (e) => {
      if (e.key === "Escape") setEditMode(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [editMode]);

  // When edit mode becomes active via long-press, autofocus the
  // Done button so keyboard users can tab back / Enter to exit.
  useEffect(() => {
    if (editMode && doneBtnRef.current) {
      doneBtnRef.current.focus();
    }
  }, [editMode]);

  if (!role) return null;
  if (pins.length === 0 && role !== "admin" && role !== "super_admin" && role !== "manager" && role !== "technician") {
    return null;
  }

  const onDragEnd = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const idxA = pins.findIndex((p) => p.to === active.id);
    const idxB = pins.findIndex((p) => p.to === over.id);
    if (idxA < 0 || idxB < 0) return;
    const next = arrayMove(pins, idxA, idxB);
    reorderPins(next.map((p) => p.to));
  };

  const onConfirmRemove = async () => {
    const target = pendingRemove;
    setPendingRemove(null);
    if (target) await removePin(target.to);
  };

  const enterEditMode = () => setEditMode(true);
  const exitEditMode = () => setEditMode(false);

  return (
    <nav
      ref={railRef}
      className="flex-1 flex flex-col items-stretch py-3 gap-1 overflow-y-auto"
      data-testid="quick-nav-rail"
      aria-label="Quick Access"
      aria-describedby={editMode ? "rail-edit-mode-status" : undefined}
      style={editMode ? { boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)" } : undefined}
    >
      <div
        className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-center"
        style={{ color: colors.nav.fgMuted }}
        data-testid="quick-nav-rail-header"
      >
        Quick Access
      </div>

      {/* Keyboard-accessible edit-mode entry — visible always; icon
          swap gives a visual confirmation when the mode is active. */}
      <button
        type="button"
        onClick={() => setEditMode((v) => !v)}
        className="mx-2 mb-1 rounded-md flex items-center justify-center gap-1 py-1 text-[9px] font-semibold opacity-60 hover:opacity-100 focus-visible:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
        style={{ color: colors.nav.fgMuted }}
        data-testid="rail-edit-enter-btn"
        aria-pressed={editMode}
        aria-label={editMode ? "Exit Quick Access edit mode" : "Enter Quick Access edit mode to remove pins"}
        title={editMode ? "Exit edit mode" : "Edit pins"}
      >
        <Pencil size={10} />
        <span className="leading-none">{editMode ? "Editing" : "Edit pins"}</span>
      </button>

      {/* Visually-hidden live region — announces mode activation to
          screen readers without disturbing sighted users. */}
      {editMode && (
        <span
          id="rail-edit-mode-status"
          data-testid="rail-edit-mode-live"
          role="status"
          aria-live="polite"
          className="sr-only"
        >
          Edit mode on. Press Escape to exit.
        </span>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext
          items={pins.map((p) => p.to)}
          strategy={verticalListSortingStrategy}
        >
          {pins.map((p) => (
            <SortableRailPin
              key={p.to}
              pin={p}
              editMode={editMode}
              onRequestRemove={setPendingRemove}
              onLongPressFire={enterEditMode}
              onNavClickExit={exitEditMode}
            />
          ))}
        </SortableContext>
      </DndContext>

      {/* Bottom affordance — replaces +Add with Done in edit mode
          (zero reflow; same slot, same vertical position). */}
      {editMode ? (
        <button
          ref={doneBtnRef}
          type="button"
          onClick={exitEditMode}
          className="mx-2 mt-1 rounded-xl flex flex-col items-center justify-center gap-1 py-2 text-[9px] font-semibold border transition-all duration-200 hover:brightness-110"
          style={{
            color: colors.nav.fg,
            borderColor: colors.nav.border,
            background: "rgba(255,255,255,0.08)",
          }}
          data-testid="rail-edit-done-btn"
          aria-label="Done editing Quick Access pins"
          title="Done"
        >
          <Check size={14} />
          <span className="leading-none text-center">Done</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setAddOpen(true)}
          disabled={atCap}
          className="mx-2 mt-1 rounded-xl flex flex-col items-center justify-center gap-1 py-2 text-[9px] font-semibold border border-dashed transition-all duration-200 hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            color: colors.nav.fg,
            borderColor: colors.nav.border,
            background: "transparent",
          }}
          data-testid="rail-pin-add-btn"
          aria-label={atCap ? `Pin cap of ${cap} reached — remove a pin to add another` : "Add a Quick Access pin"}
          title={atCap ? `At cap (${cap})` : "Add pin"}
        >
          <Plus size={14} />
          <span className="leading-none text-center">{atCap ? `${cap}/${cap}` : "Add pin"}</span>
        </button>
      )}

      <AddPinModal
        open={addOpen}
        onOpenChange={setAddOpen}
        role={role}
        pinnedRoutes={pinnedRoutes}
        atCap={atCap}
        cap={cap}
        onAdd={addPin}
      />

      <RemovePinConfirm
        open={!!pendingRemove}
        onOpenChange={(v) => { if (!v) setPendingRemove(null); }}
        pin={pendingRemove}
        onConfirm={onConfirmRemove}
      />
    </nav>
  );
}
