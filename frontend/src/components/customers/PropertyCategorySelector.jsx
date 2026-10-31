/**
 * Feb-2026 · Ticket γ · PropertyCategorySelector (shared primitive).
 *
 * Lifted from the inline component in
 * ``pages/customers/PropertiesTab.jsx`` so the Ticket γ identity-
 * header popover can reuse the exact same chip-group UI + write-
 * path contract (``onPick(value)`` → caller patches
 * ``PATCH /properties/{pid}`` with ``{service_category: value}``).
 *
 * Deliberately presentational: it owns no state, fetches nothing,
 * does not know about auth.  All role gating + optimistic-update
 * logic lives at the caller level so both call sites
 * (PropertiesTab card + CombinedCategoryBadge popover) can keep
 * their own semantics (toast placement, parent refresh, etc.).
 */
import React from "react";


const OPTIONS = [
  { value: "pool",         label: "Pool",         tone: "sky" },
  { value: "landscaping",  label: "Landscaping",  tone: "emerald" },
  { value: "both",         label: "Both",         tone: "violet" },
];
const TONE_BG = {
  sky:     { on: "#DBEAFE", off: "transparent", fg: "#1E3A8A", border: "#93C5FD" },
  emerald: { on: "#D1FAE5", off: "transparent", fg: "#064E3B", border: "#6EE7B7" },
  violet:  { on: "#EDE9FE", off: "transparent", fg: "#4C1D95", border: "#C4B5FD" },
};


export default function PropertyCategorySelector({
  propertyId, current, onPick, disabled,
}) {
  return (
    <div
      className="inline-flex items-center gap-1"
      // Prevent card's onClick (opens drawer) from firing when
      // the operator picks a chip.
      onClick={(e) => e.stopPropagation()}
      data-testid={`pc-category-group-${propertyId}`}
      role="radiogroup"
      aria-label="Property service category"
    >
      {OPTIONS.map((o) => {
        const selected = current === o.value;
        const t = TONE_BG[o.tone];
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onPick?.(o.value)}
            title={selected
              ? `Clear category (currently ${o.label})`
              : `Set category to ${o.label}`}
            className="px-2 py-0.5 rounded-full text-[11px] font-semibold transition hover:brightness-95 disabled:cursor-not-allowed"
            style={{
              backgroundColor: selected ? t.on : t.off,
              color: t.fg,
              border: `1px solid ${t.border}`,
              opacity: disabled ? 0.4 : (selected ? 1 : 0.55),
            }}
            data-testid={`pc-cat-${o.value}-${propertyId}`}
            data-selected={selected ? "true" : "false"}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
