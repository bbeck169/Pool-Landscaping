/**
 * Feb-2026 · Phase 21 · Addition B — Team-row color swatch + picker.
 *
 * Updated by Live-Tech-Map Phase 2 (Feb-2026): the ``TechColorSwatch``
 * picker replaced its ``<input type="color">`` + Save button with a
 * shared 12-chip ``<PaletteChipPicker />`` fed by
 * ``GET /api/tech-colors/palette``. Save-on-click semantics — the
 * ``team-color-picker-save-*`` and ``team-color-picker-input-*``
 * testids no longer exist. This test rewrites the interaction
 * assertions accordingly while preserving the swatch/popover/
 * clear/close testids that other suites depend on.
 *
 * The ``TechColorSwatch`` component is exported from ``OpsHub.jsx``
 * specifically so this test can render it in isolation without
 * booting the whole team-page tree.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// The palette-picker previously fetched from ``/tech-colors/palette``;
// Feb-2026 the shared ``<ColorPicker />`` imports the palette constant
// directly + fetches ``/users/me/recent-colors`` for the recents row.
// Both stubbed here so the popover mounts without network.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockImplementation((path) => {
      if (path === "/users/me/recent-colors") {
        return Promise.resolve({ recent_colors: [] });
      }
      return Promise.resolve({
        palette: [
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
        ],
      });
    }),
    post: vi.fn().mockResolvedValue({ recent_colors: [] }),
    patch: vi.fn(),
  },
}));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

import { TechColorSwatch } from "@/pages/ops/OpsHub";


describe("TechColorSwatch", () => {
  it("renders swatch with data-color reflecting current state", () => {
    const { rerender } = render(
      <TechColorSwatch
        user={{ id: "u1", display_color_hex: "#3B82F6" }}
        editable={true}
        onChange={vi.fn()}
      />,
    );
    const swatch = screen.getByTestId("team-row-color-swatch-u1");
    expect(swatch.getAttribute("data-color")).toBe("#3B82F6");
    // Unset state.
    rerender(
      <TechColorSwatch
        user={{ id: "u1", display_color_hex: null }}
        editable={true}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("team-row-color-swatch-u1").getAttribute("data-color"))
      .toBe("unset");
  });

  it("opens the popover on click when editable", () => {
    render(
      <TechColorSwatch
        user={{ id: "u2", display_color_hex: "#3B82F6" }}
        editable={true}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("team-color-picker-popover-u2")).toBeNull();
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u2"));
    expect(screen.getByTestId("team-color-picker-popover-u2")).toBeInTheDocument();
  });

  it("does not open the popover when not editable", () => {
    render(
      <TechColorSwatch
        user={{ id: "u3", display_color_hex: "#3B82F6" }}
        editable={false}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u3"));
    expect(screen.queryByTestId("team-color-picker-popover-u3")).toBeNull();
  });

  it("clicking a preset chip calls onChange with that palette hex", async () => {
    // Feb-2026 · Post-``ColorPicker`` swap: preset testid shape
    // is now ``team-color-picker-<user>-preset-#RRGGBB`` and the
    // WCAG 3.0 contrast guard disables low-contrast entries
    // (emerald ``#10B981`` is one of those). Uses pink ``#EC4899``
    // which passes the guard.
    const onChange = vi.fn().mockResolvedValue(undefined);
    render(
      <TechColorSwatch
        user={{ id: "u4", display_color_hex: "#3B82F6" }}
        editable={true}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u4"));
    const chip = await screen.findByTestId(
      "team-color-picker-u4-preset-#EC4899",
    );
    fireEvent.click(chip);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("#EC4899"));
  });

  it("Clear calls onChange with null and is disabled when unset", async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    // Unset — Clear is disabled.
    const { rerender } = render(
      <TechColorSwatch
        user={{ id: "u5", display_color_hex: null }}
        editable={true}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u5"));
    expect(screen.getByTestId("team-color-picker-clear-u5")).toBeDisabled();
    // Now with color — Clear should fire onChange(null).
    rerender(
      <TechColorSwatch
        user={{ id: "u5", display_color_hex: "#3B82F6" }}
        editable={true}
        onChange={onChange}
      />,
    );
    // Popover already open from prior click.
    fireEvent.click(screen.getByTestId("team-color-picker-clear-u5"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null));
  });

  it("Close dismisses without firing onChange", () => {
    const onChange = vi.fn();
    render(
      <TechColorSwatch
        user={{ id: "u6", display_color_hex: "#3B82F6" }}
        editable={true}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u6"));
    fireEvent.click(screen.getByTestId("team-color-picker-cancel-u6"));
    expect(screen.queryByTestId("team-color-picker-popover-u6")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});
