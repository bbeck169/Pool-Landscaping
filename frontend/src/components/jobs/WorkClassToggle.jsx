/**
 * Feb 2026 · Color-coded Job TYPE toggle (Service / Repair).
 *
 * Segmented control that flips ``work_class`` between:
 *   • ``"service"`` — cyan / pool family (matches "pool-service" semantics used across the app)
 *   • ``"repair"``  — amber / warning family (matches maintenance/repair urgency)
 *
 * Active state: solid color-family primary background + white text.
 * Inactive:     white surface + colored text; hover tints with the family's 50-shade.
 *
 * Contrast — the family's 500-shade is too light for white text
 * against WCAG AA large-text (3.0:1):
 *   * ``colors.pool[500]``          #06B6D4 → 2.43:1 (fails)
 *   * ``colors.pool[600]``          #0891B2 → 3.68:1 (passes)
 *   * ``colors.accent.amber[500]``  #F59E0B → 2.15:1 (fails)
 *   * ``colors.accent.amber[600]``  #D97706 → 3.19:1 (passes)
 * Active states use the 600-shade so both pass AA large-text. The
 * dark-hover / focus ring uses 700 for extra emphasis.
 *
 * Shared by ``pages/jobs/JobNew.jsx`` + ``pages/schedule/ScheduleJobEditModal.jsx``.
 */
import React, { useState } from "react";
import { colors } from "@/theme";


const OPTIONS = [
  {
    value: "service",
    label: "Service",
    activeBg: colors.pool[600],
    inactiveFg: colors.pool[700],
    hoverBg: colors.pool[50],
  },
  {
    value: "repair",
    label: "Repair",
    activeBg: colors.accent.amber[600],
    inactiveFg: colors.accent.amber[700],
    hoverBg: colors.accent.amber[50],
  },
];


export default function WorkClassToggle({
  value,
  onChange,
  disabled = false,
  testIdPrefix = "work-class",
  ariaLabel = "Job type",
}) {
  return (
    <div
      className="inline-flex rounded-lg overflow-hidden"
      role="radiogroup"
      aria-label={ariaLabel}
      data-testid={testIdPrefix}
      style={{ border: `1px solid ${colors.border}` }}
    >
      {OPTIONS.map((opt) => (
        <WorkClassOption
          key={opt.value}
          opt={opt}
          selected={value === opt.value}
          onSelect={() => onChange(opt.value)}
          disabled={disabled}
          testId={`${testIdPrefix}-${opt.value}`}
        />
      ))}
    </div>
  );
}


function WorkClassOption({ opt, selected, onSelect, disabled, testId }) {
  const [hover, setHover] = useState(false);
  const bg = selected
    ? opt.activeBg
    : hover
      ? opt.hoverBg
      : colors.surface;
  const fg = selected ? "#FFFFFF" : opt.inactiveFg;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      disabled={disabled}
      className="px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 transition-colors disabled:opacity-60"
      style={{
        backgroundColor: bg,
        color: fg,
        // Expose the active color on the DOM so tests can assert on
        // the token without needing computed-style shenanigans.
        "--work-class-color": opt.activeBg,
      }}
      data-testid={testId}
      data-selected={selected ? "1" : "0"}
      data-tone={opt.value === "service" ? "pool" : "amber"}
    >
      {opt.label}
    </button>
  );
}
