/**
 * Feb-2026 · Feature P1 — Customers list Tag filter dropdown.
 *
 * Replaces the previous 147-chip filter bar with a single button
 * + searchable multi-select popover.
 *
 * UI contract (from user brief):
 *   • Button label
 *       — "Filter by tag" when no tags selected
 *       — "N tags selected" when populated + clear-all "×"
 *   • Popover
 *       — Auto-focused search input at top
 *       — System tags section pinned first (Active / Inactive) with
 *         lock icon + SYSTEM badge + usage count
 *       — Divider
 *       — Remaining tags alphabetical with color swatch + count
 *       — Each row is a keyboard-friendly button with a checkbox +
 *         swatch + name + count
 *       — Footer: "Clear all" link + "Done" button
 *   • Selected-state pill row under the button:
 *       — Shows up to 3 tag names + "+N more" collapse
 *       — Individual X removes one; global "Clear all" wipes
 *   • Semantics: multi-select AND (unchanged), URL sync unchanged.
 *
 * TestIDs (locked in Vitest):
 *   customers-tag-filter-dropdown           — the whole wrapper
 *   customers-tag-filter-button             — the trigger
 *   customers-tag-filter-clear-all          — clear-all icon on the trigger
 *   customers-tag-filter-popover            — the popover panel
 *   customers-tag-filter-search             — search input
 *   customers-tag-filter-option-<name>      — one clickable option
 *   customers-tag-filter-footer-clear-all   — footer "Clear all"
 *   customers-tag-filter-footer-done        — footer "Done"
 *   customers-tag-selected-pill-<name>      — selected-state pill
 *   customers-tag-selected-more             — "+N more" collapse
 */
import React, { useMemo, useState } from "react";
import { Lock, Search, X as XIcon, Check, ChevronDown } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { colors } from "@/theme";

const MAX_SELECTED_PILL = 3;

export default function CustomersTagFilterDropdown({
  allTags,        // Array<{ id, name, color, is_system, usage_count }>
  selectedTags,   // Set<string>
  setSelectedTags,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const sorted = useMemo(() => {
    // System tags pinned first, others alphabetical.
    const sys = (allTags || []).filter((t) => t.is_system);
    const rest = (allTags || [])
      .filter((t) => !t.is_system)
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    return { sys, rest };
  }, [allTags]);

  const filterMatch = (t) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (t.name || "").toLowerCase().includes(q);
  };

  const sysFiltered = sorted.sys.filter(filterMatch);
  const restFiltered = sorted.rest.filter(filterMatch);
  const nothingMatches = query && sysFiltered.length === 0 && restFiltered.length === 0;

  const toggle = (name) => {
    const next = new Set(selectedTags);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setSelectedTags(next);
  };
  const clearAll = () => setSelectedTags(new Set());

  const selectedList = Array.from(selectedTags);
  const visiblePills = selectedList.slice(0, MAX_SELECTED_PILL);
  const overflowCount = Math.max(0, selectedList.length - MAX_SELECTED_PILL);

  const label = selectedTags.size === 0
    ? "Filter by tag"
    : `${selectedTags.size} tag${selectedTags.size === 1 ? "" : "s"} selected`;

  return (
    <div
      className="mb-3"
      data-testid="customers-tag-filter-dropdown"
    >
      <Popover open={open} onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="inline-flex items-center gap-2 text-xs font-semibold px-3 py-2 rounded-lg"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="customers-tag-filter-button"
          >
            <span>{label}</span>
            {selectedTags.size > 0 ? (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); clearAll(); }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.stopPropagation(); clearAll();
                  }
                }}
                className="inline-flex items-center justify-center rounded-full w-4 h-4"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
                data-testid="customers-tag-filter-clear-all"
                aria-label="Clear all selected tags"
              >
                <XIcon size={10} />
              </span>
            ) : (
              <ChevronDown size={12} style={{ color: colors.muted }} />
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="p-0 w-80"
          data-testid="customers-tag-filter-popover"
        >
          <div className="px-3 pt-3 pb-2 relative">
            <Search
              size={12}
              className="absolute left-5 top-1/2 -translate-y-1/2"
              style={{ color: colors.searchIcon, transform: "translateY(-50%)" }}
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${allTags.length} tags…`}
              autoFocus
              className="w-full pl-7 pr-2 py-1.5 text-xs rounded-lg outline-none focus:ring-2"
              style={{
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
                backgroundColor: colors.surface,
              }}
              data-testid="customers-tag-filter-search"
            />
          </div>

          <div className="max-h-72 overflow-y-auto pb-1">
            {sysFiltered.length > 0 ? (
              <>
                <SectionHeader label="System" />
                {sysFiltered.map((t) => (
                  <OptionRow
                    key={t.id}
                    tag={t}
                    checked={selectedTags.has(t.name)}
                    onToggle={() => toggle(t.name)}
                  />
                ))}
                {restFiltered.length > 0 ? (
                  <div
                    className="my-1"
                    style={{ height: 1, backgroundColor: colors.divider }}
                    aria-hidden="true"
                  />
                ) : null}
              </>
            ) : null}
            {restFiltered.map((t) => (
              <OptionRow
                key={t.id}
                tag={t}
                checked={selectedTags.has(t.name)}
                onToggle={() => toggle(t.name)}
              />
            ))}
            {nothingMatches ? (
              <div className="px-3 py-4 text-xs italic text-center"
                     style={{ color: colors.muted }}
                     data-testid="customers-tag-filter-no-match">
                No tags match "{query}"
              </div>
            ) : null}
          </div>

          <div
            className="flex items-center justify-between px-3 py-2"
            style={{ borderTop: `1px solid ${colors.divider}` }}
          >
            <button
              type="button"
              onClick={clearAll}
              disabled={selectedTags.size === 0}
              className="text-xs font-semibold underline disabled:opacity-40"
              style={{ color: colors.onSurfaceSecondary }}
              data-testid="customers-tag-filter-footer-clear-all"
            >
              Clear all
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-xs font-bold px-3 py-1.5 rounded-lg text-white"
              style={{ backgroundColor: colors.brandPrimary }}
              data-testid="customers-tag-filter-footer-done"
            >
              Done
            </button>
          </div>
        </PopoverContent>
      </Popover>

      {selectedTags.size > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {visiblePills.map((name) => {
            const tag = allTags.find((t) => t.name === name);
            return (
              <span
                key={name}
                className="inline-flex items-center gap-1 text-xs font-semibold rounded-full px-2 py-0.5"
                style={{
                  backgroundColor: tag?.color || colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`customers-tag-selected-pill-${name}`}
              >
                {tag?.is_system ? <Lock size={9} /> : null}
                {name}
                <button
                  type="button"
                  onClick={() => toggle(name)}
                  aria-label={`Remove ${name} filter`}
                  className="opacity-70 hover:opacity-100"
                  data-testid={`customers-tag-selected-pill-remove-${name}`}
                >
                  <XIcon size={10} />
                </button>
              </span>
            );
          })}
          {overflowCount > 0 ? (
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: colors.surfaceTertiary,
                color: colors.onSurfaceSecondary,
              }}
              data-testid="customers-tag-selected-more"
            >
              +{overflowCount} more
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SectionHeader({ label }) {
  return (
    <div
      className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ color: colors.muted }}
    >
      {label}
    </div>
  );
}

function OptionRow({ tag, checked, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-left"
      style={{
        backgroundColor: checked ? colors.surfaceSecondary : "transparent",
      }}
      data-testid={`customers-tag-filter-option-${tag.name}`}
      aria-pressed={checked}
    >
      <span
        className="inline-flex items-center justify-center w-4 h-4 rounded"
        style={{
          border: `1px solid ${checked ? colors.brandPrimary : colors.border}`,
          backgroundColor: checked ? colors.brandPrimary : "transparent",
        }}
      >
        {checked ? <Check size={10} color="#fff" /> : null}
      </span>
      <span
        className="inline-block w-3 h-3 rounded-full shrink-0"
        style={{
          backgroundColor: tag.color || "#94A3B8",
          border: `1px solid ${colors.border}`,
        }}
      />
      {tag.is_system ? <Lock size={10} style={{ color: colors.muted }} /> : null}
      <span
        className="text-xs font-semibold flex-1"
        style={{ color: colors.onSurface }}
      >
        {tag.name}
      </span>
      {tag.is_system ? (
        <span
          className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: colors.surfaceTertiary,
            color: colors.onSurfaceSecondary,
          }}
        >
          System
        </span>
      ) : null}
      <span
        className="text-[10px] font-semibold"
        style={{ color: colors.muted }}
      >
        ({tag.usage_count ?? 0})
      </span>
    </button>
  );
}
