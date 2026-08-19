/**
 * Feb-2026 · JobCountPill — Services / Repairs countdown pill.
 *
 * Rounded rectangle badge. Large centered "remaining/total" numeric,
 * uppercase category label underneath. Used on:
 *   * Admin Workstream page (web).
 *   * Tech Schedule screen (mobile — separate ``JobCountPill.tsx``
 *     in ``mobile/components/``; both files share the classifier
 *     from ``lib/jobCategory.js``).
 *
 * Colours (locked to existing Tailwind palette used elsewhere in
 * the app — no new hex values introduced):
 *   * ``services`` → ``bg-sky-500`` (matches the reference blue).
 *   * ``repairs``  → ``bg-slate-800`` (matches the reference navy).
 * Both variants render white numerals with a subtle drop shadow.
 */
import React from "react";

const _PALETTE = {
  services: {
    // ``sky-500`` is the closest existing Tailwind class to the
    // reference blue (~#0EA5E9 vs. the mock's #3BA7FF); Tailwind's
    // built-in class avoids adding a new custom hex.
    bg: "bg-sky-500",
    label: "SERVICES",
  },
  repairs: {
    // ``slate-800`` (#1E293B) is the closest built-in Tailwind
    // class to the reference navy (~#0F1F4A); keeps parity with
    // the palette already used across StatusPill / Chip.
    bg: "bg-slate-800",
    label: "REPAIRS",
  },
};

export default function JobCountPill({
  category,
  total,
  remaining,
  testid,
}) {
  const p = _PALETTE[category];
  if (!p) return null;
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeRemaining = Math.max(0, Math.min(safeTotal, Number(remaining) || 0));
  const finalTestId = testid || `job-count-pill-${category}`;
  return (
    <div
      className={`${p.bg} inline-flex flex-col items-center justify-center rounded-2xl px-6 py-3 min-w-[7rem] shadow-md`}
      data-testid={finalTestId}
    >
      <div
        className="text-white text-3xl font-bold leading-none tracking-tight"
        style={{ textShadow: "0 1px 2px rgba(0,0,0,0.20)" }}
        data-testid={`${finalTestId}-count`}
      >
        <span data-testid={`${finalTestId}-remaining`}>{safeRemaining}</span>
        <span className="opacity-70">/</span>
        <span data-testid={`${finalTestId}-total`}>{safeTotal}</span>
      </div>
      <div
        className="text-white text-[10px] font-semibold tracking-widest mt-1 opacity-95"
        data-testid={`${finalTestId}-label`}
      >
        {p.label}
      </div>
    </div>
  );
}
