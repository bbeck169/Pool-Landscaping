/**
 * Feb-2026 · Notifications page — grouped multi-select filter popover.
 *
 * Replaces the ~40-chip wall on ``/notifications`` with one dropdown
 * button + a Popover containing checkbox rows grouped by section.
 *
 * Behavior:
 *   * Trigger button label shows an at-a-glance summary:
 *       - 0 selected → "Filter: All"
 *       - 1 selected → "Filter: {label}"
 *       - N selected → "Filter: {first-label} +N"
 *   * "All" button at the top of the popover clears the selection
 *     (equivalent to no filter). "Clear" mirror-linked at the top
 *     right for accessibility parity with the "All" pattern.
 *   * Multi-select via ``role="listbox"`` + ``role="option"`` + a
 *     visible checkbox per row. Keyboard: Tab moves between rows,
 *     Space / Enter toggles, Escape closes the popover.
 *   * Section headers are visually distinct but non-interactive
 *     (``aria-hidden``). Options inside carry the interactive
 *     semantics.
 *   * Responsive: on narrow viewports the popover expands to a
 *     max-height scroll region; parent Popover primitive handles
 *     side positioning automatically.
 *
 * Filter state is a ``string[]`` of ``kind`` keys. The parent
 * component owns state + persistence.
 */
import React, { useMemo, useState } from "react";
import { Popover, PopoverContent, PopoverTrigger }
  from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Filter as FilterIcon, ChevronDown } from "lucide-react";
import { colors } from "@/theme";
import { groupKinds } from "@/lib/notificationGroups";


/**
 * @param {object} props
 * @param {Array<{key:string,label:string}>} props.kinds - full catalog
 * @param {string[]}                          props.selected - kind keys
 * @param {(next:string[]) => void}           props.onChange
 * @param {string}                           [props.testId] - test root id
 */
export default function NotificationsFilterDropdown({
  kinds, selected, onChange, testId = "notif-filter-dropdown",
}) {
  const [open, setOpen] = useState(false);

  const sections = useMemo(() => groupKinds(kinds || []), [kinds]);
  const byKey = useMemo(() => {
    const m = {};
    for (const k of kinds || []) m[k.key] = k.label;
    return m;
  }, [kinds]);

  const summary = useMemo(() => {
    if (!selected || selected.length === 0) return "Filter: All";
    if (selected.length === 1) {
      return `Filter: ${byKey[selected[0]] || selected[0]}`;
    }
    const first = byKey[selected[0]] || selected[0];
    return `Filter: ${first} +${selected.length - 1}`;
  }, [selected, byKey]);

  const toggle = (key) => {
    const has = selected.includes(key);
    const next = has
      ? selected.filter((k) => k !== key)
      : [...selected, key];
    onChange(next);
  };

  const selectAll = () => onChange([]); // empty = "All"
  const clear = () => onChange([]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Filter notifications by type"
          data-testid={testId}
          className="justify-between gap-2 text-xs font-semibold h-8"
          style={{ borderColor: colors.border,
                    color: colors.onSurface,
                    background: colors.surface }}
        >
          <span className="inline-flex items-center gap-1.5">
            <FilterIcon size={12} />
            <span data-testid={`${testId}-summary`}>{summary}</span>
          </span>
          <ChevronDown size={14} aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[320px] max-w-[92vw] p-0"
        data-testid={`${testId}-panel`}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b"
             style={{ borderColor: colors.border }}>
          <button
            type="button"
            onClick={selectAll}
            className="text-xs font-semibold px-2 py-1 rounded"
            style={{
              background: selected.length === 0
                ? colors.brand : "transparent",
              color: selected.length === 0 ? "#fff" : colors.onSurface,
            }}
            data-testid={`${testId}-all`}
          >
            All
          </button>
          <button
            type="button"
            onClick={clear}
            disabled={selected.length === 0}
            className="text-xs font-semibold underline disabled:opacity-40"
            style={{ color: colors.brand }}
            data-testid={`${testId}-clear`}
          >
            Clear
          </button>
        </div>
        <ul
          role="listbox"
          aria-multiselectable="true"
          aria-label="Notification types"
          className="max-h-[60vh] overflow-y-auto py-1"
        >
          {sections.map(({ section, items }) => (
            <li key={section} className="mt-1 first:mt-0">
              <div
                aria-hidden="true"
                className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}
                data-testid={`${testId}-section-${section
                  .toLowerCase().replace(/\s+/g, "-").replace(/&/g, "and")}`}
              >
                {section}
              </div>
              {items.map((k) => {
                const checked = selected.includes(k.key);
                return (
                  <label
                    key={k.key}
                    role="option"
                    aria-selected={checked}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-black/5 focus-within:bg-black/5"
                    style={{ color: colors.onSurface }}
                    data-testid={`${testId}-option-${k.key}`}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggle(k.key)}
                      aria-label={k.label}
                    />
                    <span className="flex-1">{k.label}</span>
                  </label>
                );
              })}
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
