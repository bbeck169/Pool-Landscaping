/**
 * Feb-2026 · Live-Tech-Map · Phase 2 — PaletteChipPicker RTL suite.
 *
 * Verifies the shared 12-chip color picker used by BOTH the /team
 * tab (per-tech ``display_color_hex``) and the /crews tab (per-crew
 * ``color``). The picker fetches the palette from
 * ``GET /api/tech-colors/palette`` (Phase 1) and hard-clicks to
 * save — no intermediate "Save" button.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const _PALETTE_MOCK = [
  { name: "blue",    hex: "#3B82F6" },
  { name: "red",     hex: "#EF4444" },
  { name: "emerald", hex: "#10B981" },
  { name: "amber",   hex: "#F59E0B" },
  { name: "violet",  hex: "#8B5CF6" },
  { name: "pink",    hex: "#EC4899" },
  { name: "teal",    hex: "#14B8A6" },
  { name: "orange",  hex: "#F97316" },
  { name: "indigo",  hex: "#6366F1" },
  { name: "lime",    hex: "#84CC16" },
  { name: "cyan",    hex: "#06B6D4" },
  { name: "fuchsia", hex: "#D946EF" },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ palette: _PALETTE_MOCK }),
  },
}));

// Reset the module-scoped palette cache between tests so each spec
// gets a fresh fetch. Without this the ``vi.fn()`` call-count
// assertions leak across tests.
beforeEach(async () => {
  vi.resetModules();
  const { api } = await import("@/api");
  api.get.mockClear();
  api.get.mockResolvedValue({ palette: _PALETTE_MOCK });
});

describe("PaletteChipPicker (Phase 2)", () => {
  it("renders 12 chips from the palette endpoint", async () => {
    const { default: PaletteChipPicker } = await import(
      "@/components/team/PaletteChipPicker"
    );
    render(
      <PaletteChipPicker value={null} onPick={vi.fn()} testidPrefix="tst" />,
    );
    // Loading state renders first.
    expect(screen.queryByTestId("tst-loading")).toBeInTheDocument();
    // Then palette resolves.
    const list = await screen.findByTestId("tst-list");
    expect(list).toBeInTheDocument();
    for (const p of _PALETTE_MOCK) {
      expect(screen.getByTestId(`tst-${p.name}`)).toBeInTheDocument();
    }
  });

  it("marks the currently-selected chip active by data-active", async () => {
    const { default: PaletteChipPicker } = await import(
      "@/components/team/PaletteChipPicker"
    );
    render(
      <PaletteChipPicker
        value="#F97316" onPick={vi.fn()} testidPrefix="tst2"
      />,
    );
    const activeChip = await screen.findByTestId("tst2-orange");
    expect(activeChip.getAttribute("data-active")).toBe("true");
    // Any other chip should be inactive.
    const otherChip = screen.getByTestId("tst2-blue");
    expect(otherChip.getAttribute("data-active")).toBe("false");
  });

  it("clicking a chip fires onPick with that chip's hex", async () => {
    const onPick = vi.fn();
    const { default: PaletteChipPicker } = await import(
      "@/components/team/PaletteChipPicker"
    );
    render(
      <PaletteChipPicker value={null} onPick={onPick} testidPrefix="tst3" />,
    );
    const chip = await screen.findByTestId("tst3-cyan");
    fireEvent.click(chip);
    await waitFor(() =>
      expect(onPick).toHaveBeenCalledWith("#06B6D4"),
    );
  });

  it("disabled=true blocks clicks and grays the chips", async () => {
    const onPick = vi.fn();
    const { default: PaletteChipPicker } = await import(
      "@/components/team/PaletteChipPicker"
    );
    render(
      <PaletteChipPicker
        value={null} onPick={onPick} disabled={true} testidPrefix="tst4"
      />,
    );
    const chip = await screen.findByTestId("tst4-blue");
    expect(chip).toBeDisabled();
    fireEvent.click(chip);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("falls back to the local mirror palette when the endpoint errors", async () => {
    const { api } = await import("@/api");
    api.get.mockRejectedValueOnce(new Error("network down"));
    const { default: PaletteChipPicker } = await import(
      "@/components/team/PaletteChipPicker"
    );
    render(
      <PaletteChipPicker value={null} onPick={vi.fn()} testidPrefix="tst5" />,
    );
    // Fallback still renders 12 chips (module mirror).
    await screen.findByTestId("tst5-list");
    // The local mirror uses the same palette, so blue is present.
    expect(screen.getByTestId("tst5-blue")).toBeInTheDocument();
    expect(screen.getByTestId("tst5-fuchsia")).toBeInTheDocument();
  });
});
