/**
 * Feb-2026 · Phase 21 · Addition B — Team-row color swatch + picker.
 *
 * The ``TechColorSwatch`` component is exported from ``OpsHub.jsx``
 * specifically so this test can render it in isolation without
 * booting the whole team-page tree.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

import { TechColorSwatch } from "@/pages/ops/OpsHub";


describe("TechColorSwatch", () => {
  it("renders swatch with data-color reflecting current state", () => {
    const { rerender } = render(
      <TechColorSwatch
        user={{ id: "u1", display_color_hex: "#22C55E" }}
        editable={true}
        onChange={vi.fn()}
      />,
    );
    const swatch = screen.getByTestId("team-row-color-swatch-u1");
    expect(swatch.getAttribute("data-color")).toBe("#22C55E");
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
        user={{ id: "u2", display_color_hex: "#0EA5E9" }}
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
        user={{ id: "u3", display_color_hex: "#0EA5E9" }}
        editable={false}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u3"));
    expect(screen.queryByTestId("team-color-picker-popover-u3")).toBeNull();
  });

  it("Save calls onChange with the chosen hex", async () => {
    const onChange = vi.fn().mockResolvedValue(undefined);
    render(
      <TechColorSwatch
        user={{ id: "u4", display_color_hex: "#0EA5E9" }}
        editable={true}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("team-row-color-swatch-u4"));
    const input = screen.getByTestId("team-color-picker-input-u4");
    fireEvent.change(input, { target: { value: "#22c55e" } });
    fireEvent.click(screen.getByTestId("team-color-picker-save-u4"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("#22C55E"));
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
        user={{ id: "u5", display_color_hex: "#22C55E" }}
        editable={true}
        onChange={onChange}
      />,
    );
    // Popover already open from prior click.
    fireEvent.click(screen.getByTestId("team-color-picker-clear-u5"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null));
  });

  it("Cancel dismisses without firing onChange", () => {
    const onChange = vi.fn();
    render(
      <TechColorSwatch
        user={{ id: "u6", display_color_hex: "#0EA5E9" }}
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
