// Phase 7B · Feb-2026 — Field list (drag-to-reorder) for the form
// template editor.
//
// Reuses the already-installed ``@dnd-kit/*`` stack (same deps as
// ``pages/pricebook/CategoriesAdmin.jsx`` — see Phase L1).  Each
// field row surfaces:
//   * Drag handle          (disabled if ``locked_reorder`` true)
//   * Label + field_type   (click surface to select the field)
//   * Width/padding chips  (quick summary of ``style``)
//   * Lock icon            (visible when ``locked_reorder`` true)
//
// The ``onReorder`` callback receives the fully-reordered array —
// the hook stamps the ``order`` field.  No side-effects live in this
// component.
import React, { useMemo } from "react";
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy, useSortable,
  arrayMove, sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Lock } from "lucide-react";
import { colors } from "@/theme";


// Pure reorder helper — exported so the vitest harness can drive
// drag-end logic without simulating pointer events (which jsdom
// doesn't fire reliably for dnd-kit's PointerSensor).
export function applyDragEndReorder(fields, event) {
  const activeId = event?.active?.id;
  const overId   = event?.over?.id;
  if (!activeId || !overId || activeId === overId) return fields;
  const from = fields.findIndex((f) => f.field_id === activeId);
  const to   = fields.findIndex((f) => f.field_id === overId);
  if (from === -1 || to === -1) return fields;
  const activeField = fields[from];
  const overField   = fields[to];
  // Phase 7B — ``locked_reorder: true`` is an immovable anchor.
  // Neither the dragged field nor the drop target may be locked.
  if (activeField?.locked_reorder) return fields;
  if (overField?.locked_reorder)   return fields;
  return arrayMove(fields, from, to);
}


function _summary(style = {}) {
  const w = style.width_cols ?? 12;
  const p = style.padding_y  ?? 2;
  return `${w}/12 · pad ${p}`;
}


function FieldRow({ field, selected, onSelect }) {
  const locked = Boolean(field.locked_reorder);
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: field.field_id, disabled: locked });

  const rowStyle = {
    transform:  CSS.Transform.toString(transform),
    transition,
    background: isDragging
      ? colors.surfaceSecondary
      : (selected ? "#EFF6FF" : "#FFFFFF"),
    borderLeft: selected ? "3px solid #0284C7" : "3px solid transparent",
  };

  return (
    <li
      ref={setNodeRef}
      style={rowStyle}
      className="flex items-center gap-3 px-3 py-2 border-b"
      data-testid={`form-field-row-${field.field_id}`}
    >
      <button
        type="button"
        {...(locked ? {} : attributes)}
        {...(locked ? {} : listeners)}
        disabled={locked}
        aria-label={locked
          ? "Field is locked and cannot be reordered"
          : "Drag to reorder"}
        className={locked
          ? "p-1 opacity-30 cursor-not-allowed"
          : "p-1 cursor-grab active:cursor-grabbing"}
        style={{ color: colors.muted || "#71717A" }}
        data-testid={`form-field-drag-${field.field_id}`}
      >
        {locked
          ? <Lock size={14} data-testid={`form-field-lock-${field.field_id}`} />
          : <GripVertical size={14} />}
      </button>
      <button
        type="button"
        onClick={() => onSelect(field.field_id)}
        className="flex-1 text-left"
        data-testid={`form-field-select-${field.field_id}`}
      >
        <div className="font-semibold text-sm"
             style={{ color: colors.onSurface }}>
          {field.label}
        </div>
        <div className="text-xs flex items-center gap-2"
             style={{ color: colors.onSurfaceSecondary || "#52525B" }}>
          <span
            className="inline-block px-1.5 py-0.5 rounded"
            style={{ background: "#F4F4F5", color: "#52525B" }}
          >{field.field_type}</span>
          <span>{_summary(field.style)}</span>
        </div>
      </button>
      <div className="flex items-center gap-1">
        <span
          className="inline-block w-4 h-4 rounded border"
          title="bg_color"
          style={{
            background:  field.style?.bg_color   || "#FFFFFF",
            borderColor: field.style?.border_color || "#E5E7EB",
            opacity:     field.style?.bg_alpha ?? 1,
          }}
          data-testid={`form-field-swatch-${field.field_id}`}
        />
      </div>
    </li>
  );
}


export default function FieldList({
  fields, selectedFieldId, onSelectField, onReorder,
}) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const ids = useMemo(() => fields.map((f) => f.field_id), [fields]);

  const onDragEnd = (event) => {
    const next = applyDragEndReorder(fields, event);
    if (next !== fields) onReorder(next);
  };

  return (
    <div data-testid="form-field-list"
         className="rounded-lg border bg-white overflow-hidden">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext
          items={ids}
          strategy={verticalListSortingStrategy}
        >
          <ul className="divide-y">
            {fields.map((f) => (
              <FieldRow
                key={f.field_id}
                field={f}
                selected={selectedFieldId === f.field_id}
                onSelect={onSelectField}
              />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
    </div>
  );
}
