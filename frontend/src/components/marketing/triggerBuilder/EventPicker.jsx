/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · EventPicker.
 *
 * Searchable, entity-grouped dropdown fed by the
 * ``GET /marketing/sequences/event-catalog`` endpoint from Phase 1.
 * Renders as a compact button that opens a scrollable menu on click;
 * matches the "single line + popover" pattern the rest of the
 * sequence editor uses (see StepCard channel picker).
 */
import React, { useMemo, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { colors } from "@/theme";
import { ENTITY_LABELS, ENTITY_ORDER } from "./helpers";


export function EventPicker({ value, catalog = [], onChange, disabled = false, testIdPrefix = "trigger-event" }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const selected = useMemo(
    () => catalog.find((e) => e.id === value) || null,
    [catalog, value],
  );

  // Group by entity for a clean picker; within each group sort by
  // label alphabetically to match the API's ordering.
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byEntity = new Map();
    ENTITY_ORDER.forEach((k) => byEntity.set(k, []));
    catalog.forEach((e) => {
      if (q && !(`${e.label} ${e.id}`).toLowerCase().includes(q)) return;
      if (!byEntity.has(e.entity)) byEntity.set(e.entity, []);
      byEntity.get(e.entity).push(e);
    });
    // Drop empty groups + sort within each.
    const out = [];
    for (const key of byEntity.keys()) {
      const rows = byEntity.get(key) || [];
      if (rows.length === 0) continue;
      rows.sort((a, b) => a.label.localeCompare(b.label));
      out.push({ entity: key, rows });
    }
    return out;
  }, [catalog, query]);

  return (
    <div className="relative" data-testid={`${testIdPrefix}-wrap`}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm outline-none"
        style={{
          backgroundColor: colors.surface,
          color: selected ? colors.onSurface : colors.muted,
          border: `1px solid ${colors.border}`,
          opacity: disabled ? 0.6 : 1,
        }}
        data-testid={`${testIdPrefix}-button`}
      >
        <span className="truncate text-left">
          {selected ? selected.label : "Pick an event…"}
        </span>
        <ChevronDown size={14} style={{ color: colors.muted }} />
      </button>

      {open ? (
        <>
          {/* Click-outside overlay */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            data-testid={`${testIdPrefix}-overlay`}
          />
          <div
            className="absolute left-0 right-0 z-20 mt-1 max-h-80 overflow-y-auto rounded-lg shadow-xl"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.borderStrong}`,
            }}
            data-testid={`${testIdPrefix}-menu`}
          >
            <div
              className="sticky top-0 flex items-center gap-2 px-3 py-2"
              style={{
                backgroundColor: colors.surface,
                borderBottom: `1px solid ${colors.divider}`,
              }}
            >
              <Search size={14} style={{ color: colors.muted }} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search events…"
                className="flex-1 text-sm outline-none"
                style={{ backgroundColor: colors.surface, color: colors.onSurface }}
                autoFocus
                data-testid={`${testIdPrefix}-search`}
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  style={{ color: colors.muted }}
                  data-testid={`${testIdPrefix}-search-clear`}
                >
                  <X size={12} />
                </button>
              ) : null}
            </div>

            {grouped.length === 0 ? (
              <div
                className="px-3 py-4 text-sm text-center"
                style={{ color: colors.muted }}
                data-testid={`${testIdPrefix}-empty`}
              >
                No events match "{query}".
              </div>
            ) : (
              grouped.map((g) => (
                <div key={g.entity} data-testid={`${testIdPrefix}-group-${g.entity}`}>
                  <div
                    className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider"
                    style={{
                      color: colors.muted,
                      backgroundColor: colors.surfaceSecondary,
                    }}
                  >
                    {ENTITY_LABELS[g.entity] || g.entity}
                  </div>
                  {g.rows.map((r) => {
                    const isSelected = r.id === value;
                    return (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => {
                          onChange?.(r);
                          setOpen(false);
                          setQuery("");
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between"
                        style={{
                          color: colors.onSurface,
                          backgroundColor: isSelected
                            ? colors.brandTertiary
                            : "transparent",
                        }}
                        data-testid={`${testIdPrefix}-option-${r.id}`}
                      >
                        <span>{r.label}</span>
                        {r.scheduled ? (
                          <span
                            className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: colors.accent.sky[100],
                              color: colors.accent.sky[700],
                            }}
                          >
                            scheduled
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
