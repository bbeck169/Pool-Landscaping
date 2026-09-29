/**
 * Feb-2026 · TeardropPin — numbered label prop coverage.
 *
 * The primary ScheduleMap coverage lives in
 * ``pages/schedule/__tests__/ScheduleMap.pinsColoring.test.jsx``.
 * This suite exercises the pin component in isolation so any
 * future refactor that regresses label rendering blows up here
 * BEFORE it hits the schedule integration tests.
 *
 * NB — the actual component ships at
 * ``frontend/src/components/maps/TeardropPin.jsx`` (not under
 * ``components/schedule/`` as the spec brief suggested). Test
 * placement mirrors the source path so path-based glob searches
 * find both files together.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import TeardropPin from "@/components/maps/TeardropPin";


describe("<TeardropPin /> — numbered label prop", () => {
  it("renders the label text when provided (numeric)", () => {
    render(<TeardropPin color="#FF0000" label={7} testid="p" />);
    expect(screen.getByTestId("p-label").textContent).toBe("07");
    // The white inner disc appears alongside the label so the
    // number sits on a readable background.
    expect(screen.getByTestId("p-disc")).toBeTruthy();
  });

  it("renders 3-digit labels without zero-padding", () => {
    render(<TeardropPin color="#FF0000" label={123} testid="p" />);
    expect(screen.getByTestId("p-label").textContent).toBe("123");
  });

  it("omits the label + inner disc when no label prop is passed", () => {
    render(<TeardropPin color="#FF0000" testid="p" />);
    expect(screen.queryByTestId("p-label")).toBeNull();
    expect(screen.queryByTestId("p-disc")).toBeNull();
  });

  it("omits the label when the prop is null or an empty string", () => {
    const { rerender } = render(
      <TeardropPin color="#FF0000" label={null} testid="p" />,
    );
    expect(screen.queryByTestId("p-label")).toBeNull();
    rerender(<TeardropPin color="#FF0000" label="" testid="p" />);
    expect(screen.queryByTestId("p-label")).toBeNull();
  });

  it("does not crash when the label prop is missing entirely", () => {
    // Baseline sanity check: rendering must succeed without a label.
    // If this ever throws, every unlabeled schedule pin would blow up.
    expect(() => render(
      <TeardropPin color="#FF0000" testid="p" />,
    )).not.toThrow();
    expect(screen.getByTestId("p")).toBeTruthy();
  });

  it("passes through explicit stroke + strokeWidth + fillOpacity overrides", () => {
    render(
      <TeardropPin
        color="#FF0000"
        stroke="#123456"
        strokeWidth={3}
        fillOpacity={0.5}
        label={1}
        testid="p"
      />,
    );
    const body = screen.getByTestId("p-body");
    expect(body.getAttribute("data-color")).toBe("#FF0000");
    expect(body.getAttribute("data-stroke")).toBe("#123456");
    expect(body.getAttribute("data-stroke-width")).toBe("3");
    expect(body.getAttribute("data-fill-opacity")).toBe("0.5");
  });
});
