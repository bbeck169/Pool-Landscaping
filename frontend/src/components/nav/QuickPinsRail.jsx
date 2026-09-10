/**
 * Phase K75 · Step B · Feb-2026 — user-editable Quick Access rail.
 *
 * Renders the 88 px navy vertical rail with the caller's persisted
 * pin list (or the seeded defaults for first-run). Wires:
 *   • K64 active + hover styling (both = ``colors.nav.bgActiveNavy``)
 *   • Drag-reorder via ``@dnd-kit/sortable``. Grip handle owns the
 *     drag listeners so the NavLink stays click-navigable.
 *   • Unpin button (top-right of each row) → RemovePinConfirm.
 *   • "+ Add pin" trigger at the bottom → AddPinModal.
 *   • 15-pin cap surfaced via ``atCap`` state (add trigger
 *     visually disables at cap).
 *
 * Preserves the pre-K75 ``data-testid="quick-nav-rail"`` +
 * ``data-testid="rail-nav-${key}"`` naming so the existing
 * ``rail-nav.test.jsx`` / ``rail-nav-leads.test.jsx`` /
 * ``phase20-quick-nav-rail-managerial-links.test.jsx`` suites keep
 * locking the shape byte-for-byte.
 */
import React, { useState } from "react";
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
import { Plus, X, GripVertical } from "lucide-react";
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
// already on file. Purely UI — the persisted value stays untouched
// so a future migration can rewrite it in place if desired.
function _displayLabel(raw) {
  if (!raw || typeof raw !== "string") return raw || "";
  const m = raw.match(/^.+ · (.+)$/);
  return m ? m[1] : raw;
}


function SortableRailPin({ pin, onRequestRemove }) {
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

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="relative group mx-2"
      data-testid={`rail-pin-${key}`}
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
      {/* Unpin button — top-right, visible on hover. */}
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); onRequestRemove(pin); }}
        className="absolute -right-0 top-1 z-10 opacity-0 group-hover:opacity-100 focus:opacity-100 rounded-full p-0.5"
        style={{ backgroundColor: "rgba(255,255,255,0.14)", color: colors.nav.fg }}
        aria-label={`Remove ${_displayLabel(pin.label)} pin`}
        data-testid={`rail-pin-remove-${key}`}
        title="Remove pin"
      >
        <X size={11} />
      </button>
      <NavLink
        to={pin.to}
        end={pin.end}
        className={({ isActive }) =>
          [
            "rounded-xl flex flex-col items-center justify-center gap-1 py-2.5",
            "text-[10px] font-semibold",
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
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background =
            e.currentTarget.getAttribute("aria-current") === "page"
              ? colors.nav.bgActiveNavy
              : "transparent";
        }}
        data-testid={`rail-nav-${key}`}
        aria-label={_displayLabel(pin.label)}
        title={_displayLabel(pin.label)}
      >
        <Icon size={20} className="transition-colors duration-200" />
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

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

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

  return (
    <nav
      className="flex-1 flex flex-col items-stretch py-3 gap-1 overflow-y-auto"
      data-testid="quick-nav-rail"
      aria-label="Quick Access"
    >
      <div
        className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-center"
        style={{ color: colors.nav.fgMuted }}
        data-testid="quick-nav-rail-header"
      >
        Quick Access
      </div>

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
              onRequestRemove={setPendingRemove}
            />
          ))}
        </SortableContext>
      </DndContext>

      {/* + Add pin trigger — bottom of the rail. */}
      <button
        type="button"
        onClick={() => setAddOpen(true)}
        disabled={atCap}
        className="mx-2 mt-1 rounded-xl flex flex-col items-center justify-center gap-1 py-2.5 text-[10px] font-semibold border border-dashed transition-all duration-200 hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
        style={{
          color: colors.nav.fg,
          borderColor: colors.nav.border,
          background: "transparent",
        }}
        data-testid="rail-pin-add-btn"
        aria-label={atCap ? `Pin cap of ${cap} reached — remove a pin to add another` : "Add a Quick Access pin"}
        title={atCap ? `At cap (${cap})` : "Add pin"}
      >
        <Plus size={18} />
        <span className="leading-none text-center">{atCap ? `${cap}/${cap}` : "Add pin"}</span>
      </button>

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
