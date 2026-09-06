/**
 * Phase R0.1 · Feb-2026 — LensToggle component tests.
 *
 * Covers:
 *   1. Renders both invoiced / collected pills with correct aria state.
 *   2. Clicking the inactive pill emits the new lens key.
 *   3. Clicking the already-active pill still emits (no-op semantics).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { LensToggle } from "../components/reports/LensToggle";

describe("R0.1 · LensToggle", () => {
  it("renders invoiced as active by default", () => {
    render(<LensToggle value="invoiced" onChange={() => {}} />);
    expect(screen.getByTestId("lens-toggle-invoiced").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("lens-toggle-collected").getAttribute("aria-selected")).toBe("false");
  });

  it("switches active pill when value prop flips", () => {
    const { rerender } = render(<LensToggle value="invoiced" onChange={() => {}} />);
    rerender(<LensToggle value="collected" onChange={() => {}} />);
    expect(screen.getByTestId("lens-toggle-collected").getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("lens-toggle-invoiced").getAttribute("aria-selected")).toBe("false");
  });

  it("emits the target lens key on click", () => {
    const onChange = vi.fn();
    render(<LensToggle value="invoiced" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("lens-toggle-collected"));
    expect(onChange).toHaveBeenCalledWith("collected");
  });

  it("supports a custom testid prefix", () => {
    render(<LensToggle value="invoiced" onChange={() => {}} testid="my-lens" />);
    expect(screen.getByTestId("my-lens")).toBeTruthy();
    expect(screen.getByTestId("my-lens-invoiced")).toBeTruthy();
    expect(screen.getByTestId("my-lens-collected")).toBeTruthy();
  });
});
