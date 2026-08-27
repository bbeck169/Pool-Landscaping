/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · ConditionRow.
 *
 * One row = one condition = one event pick + one delay + zero-or-more
 * filters. Rendered inside TriggerBuilder's condition list, with a
 * sky-500 left border to signal "this is a trigger condition".
 */
import React, { useState } from "react";
import { Trash2, ChevronDown, ChevronRight } from "lucide-react";
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
  autoSwitchedInfo = null,
  testIdPrefix,
}) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const eventMeta = catalog.find((e) => e.id === condition.event) || null;
  const activeFilters = Object.keys(condition.filters || {}).length;

  return (
    <div
      className="rounded-xl p-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.divider}`,
        borderLeft: `3px solid ${colors.accent.sky[500]}`,
      }}
      data-testid={`${testIdPrefix}-row-${index}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
          Condition {index + 1}
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
