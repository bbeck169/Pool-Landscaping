/**
 * Feb-2026 · Live-Tech-Map · Phase 2 — 12-chip palette picker.
 *
 * Shared React component used by BOTH the /team tab (per-user
 * display color) and the /crews tab (per-crew color). Fetches the
 * palette via ``useTechColorsPalette`` so the two pickers stay
 * in lockstep and neither hard-codes the 12 hex values.
 *
 * UX contract:
 *  - Renders 12 chips in a wrap-flex row.
 *  - Active chip gets a bold ring (accessible, not colour-only —
 *    ring shape reads against every background).
 *  - Click a chip → ``onPick(hex)`` fires immediately (no
 *    intermediate Save button — the palette IS the whitelist, so
 *    an accidental tap is one click to correct).
 *  - Disabled state (during save) blocks pointer + fades chips.
 *
 * Props:
 *  - ``value``      : currently-selected hex (case-insensitive).
 *  - ``onPick``     : ``(hex: string) => Promise<void>`` — parent
 *                     PATCHes and returns/throws.
 *  - ``disabled``   : gate clicks during a save.
 *  - ``testidPrefix``: string prefix so multiple pickers on the same
 *                     page get unique testids.
 */
import React from "react";
import { useTechColorsPalette } from "@/hooks/useTechColorsPalette";
import { colors } from "@/theme";

export default function PaletteChipPicker({
  value,
  onPick,
  disabled = false,
  testidPrefix = "palette-chip",
}) {
  const { palette, loading } = useTechColorsPalette();
  const normalized = (value || "").toUpperCase();

  if (loading) {
    return (
      <div
        className="flex flex-wrap gap-2"
        data-testid={`${testidPrefix}-loading`}
      >
        {Array.from({ length: 12 }).map((_, i) => (
          <span
            key={i}
            className="w-6 h-6 rounded-full opacity-30"
            style={{ backgroundColor: colors.surfaceSecondary }}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap gap-2"
      role="listbox"
      aria-label="Approved team color palette"
      data-testid={`${testidPrefix}-list`}
    >
      {palette.map((p) => {
        const active = normalized === p.hex.toUpperCase();
        return (
          <button
            key={p.hex}
            type="button"
            role="option"
            aria-selected={active}
            aria-label={`Set color to ${p.name}`}
            title={`${p.name} — ${p.hex}`}
            disabled={disabled}
            onClick={() => onPick(p.hex)}
            className="w-6 h-6 rounded-full transition-transform"
            style={{
              backgroundColor: p.hex,
              outline: active ? `2px solid ${colors.onSurface}` : "none",
              outlineOffset: "2px",
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.5 : 1,
              transform: active ? "scale(1.1)" : "scale(1)",
            }}
            data-testid={`${testidPrefix}-${p.name}`}
            data-hex={p.hex}
            data-active={active ? "true" : "false"}
          />
        );
      })}
    </div>
  );
}
