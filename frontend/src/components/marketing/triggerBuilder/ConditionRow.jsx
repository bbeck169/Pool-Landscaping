/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · ConditionRow.
 *
 * One row = one condition = one event pick + one delay + zero-or-more
 * filters. Rendered inside TriggerBuilder's condition list, with a
 * sky-500 left border to signal "this is a trigger condition".
 *
 * Phase 3 polish · Feb 2026 — HTML5 native drag-reorder handle.  No
 * new dependency; :func:`onReorder` is passed down from
 * :file:`TriggerBuilder.jsx` and receives ``(fromIndex, toIndex)``.
 * The drag data payload is the row's own index (as a string).
 */
import React, { useState } from "react";
import { Trash2, ChevronDown, ChevronRight, GripVertical } from "lucide-react";
import { colors } from "@/theme";

import { EventPicker } from "./EventPicker";
import { DelayComposer } from "./DelayComposer";
import { FilterBuilder } from "./FilterBuilder";


export function ConditionRow({
  index,
  condition,
  catalog = [],
  technicians = [],
  crews = [],
  onChange,
  onRemove,
  onReorder,
  autoSwitchedInfo = null,
  testIdPrefix,
}) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const eventMeta = catalog.find((e) => e.id === condition.event) || null;
  const activeFilters = Object.keys(condition.filters || {}).length;

  // ─── HTML5 drag handlers ─────────────────────────────────────
  const canReorder = typeof onReorder === "function";
  const handleDragStart = (e) => {
    if (!canReorder) return;
    e.dataTransfer.setData("text/plain", String(index));
    e.dataTransfer.effectAllowed = "move";
  };
  const handleDragOver = (e) => {
    if (!canReorder) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (!dragOver) setDragOver(true);
  };
  const handleDragLeave = () => { if (dragOver) setDragOver(false); };
  const handleDrop = (e) => {
    if (!canReorder) return;
    e.preventDefault();
    setDragOver(false);
    const raw = e.dataTransfer.getData("text/plain");
    const from = Number(raw);
    if (Number.isInteger(from) && from !== index) onReorder(from, index);
  };

  return (
    <div
      className="rounded-xl p-3"
      style={{
        backgroundColor: colors.surface,
        borderTopWidth: 1,
        borderRightWidth: 1,
        borderBottomWidth: 1,
        borderTopStyle: "solid",
        borderRightStyle: "solid",
        borderBottomStyle: "solid",
        borderTopColor: dragOver ? colors.brand : colors.divider,
        borderRightColor: dragOver ? colors.brand : colors.divider,
        borderBottomColor: dragOver ? colors.brand : colors.divider,
        borderLeft: `3px solid ${colors.accent.sky[500]}`,
        transition: "border-color 120ms ease",
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      data-testid={`${testIdPrefix}-row-${index}`}
      data-drag-over={dragOver ? "true" : "false"}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5">
          {canReorder ? (
            <button
              type="button"
              draggable
              onDragStart={handleDragStart}
              className="p-1 rounded cursor-grab active:cursor-grabbing"
              style={{ color: colors.muted }}
              aria-label={`Drag to reorder condition ${index + 1}`}
              data-testid={`${testIdPrefix}-row-${index}-drag-handle`}
            >
              <GripVertical size={12} />
            </button>
          ) : null}
          <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Condition {index + 1}
          </div>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="p-1 rounded"
          style={{ color: colors.error }}
          data-testid={`${testIdPrefix}-row-${index}-remove`}
          aria-label={`Remove condition ${index + 1}`}
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Event picker */}
      <div className="mb-2">
        <div className="text-[10px] font-semibold mb-1" style={{ color: colors.muted }}>WHEN</div>
        <EventPicker
          value={condition.event}
          catalog={catalog}
          onChange={(ev) => onChange({ ...condition, event: ev.id })}
          testIdPrefix={`${testIdPrefix}-row-${index}-event`}
        />
      </div>

      {/* Delay composer */}
      <div className="mb-2">
        <div className="text-[10px] font-semibold mb-1" style={{ color: colors.muted }}>DELAY</div>
        <DelayComposer
          value={condition.delay}
          event={eventMeta}
          onChange={(d) => onChange({ ...condition, delay: d })}
          testIdPrefix={`${testIdPrefix}-row-${index}-delay`}
        />
        {autoSwitchedInfo ? (
          <div
            className="mt-2 text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded-md"
            style={{ backgroundColor: colors.accent.amber[50], color: colors.accent.amber[700] }}
            data-testid={`${testIdPrefix}-row-${index}-auto-switch`}
          >
            {autoSwitchedInfo}
          </div>
        ) : null}
      </div>

      {/* Filters — collapsible */}
      <div>
        <button
          type="button"
          onClick={() => setFiltersOpen((v) => !v)}
          className="flex items-center gap-1 text-xs font-semibold"
          style={{ color: colors.brand }}
          data-testid={`${testIdPrefix}-row-${index}-filters-toggle`}
        >
          {filtersOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Filters {activeFilters > 0 ? (
            <span
              className="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
              style={{
                backgroundColor: colors.accent.emerald[100],
                color: colors.accent.emerald[700],
              }}
              data-testid={`${testIdPrefix}-row-${index}-filters-count`}
            >
              {activeFilters}
            </span>
          ) : null}
        </button>
        {filtersOpen ? (
          <div className="mt-2">
            <FilterBuilder
              filters={condition.filters || {}}
              onChange={(f) => onChange({ ...condition, filters: f })}
              technicians={technicians}
              crews={crews}
              testIdPrefix={`${testIdPrefix}-row-${index}-filter`}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
