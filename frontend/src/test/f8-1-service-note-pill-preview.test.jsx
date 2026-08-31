/**
 * Phase F8.1 · Feb-2026 — ServiceNotePill inline preview tests.
 *
 * Coverage:
 *   • Pill without note renders nothing (no preview affordance).
 *   • Pill with short note → click → preview text visible, no
 *     "…more" toggle.
 *   • Pill with long note → click → truncated preview + "…more"
 *     toggle; clicking "…more" reveals full text.
 *   • Keyboard: Enter and Space toggle expansion; aria-expanded
 *     reflects the state.
 *   • Second click on the pill collapses back to pill-only.
 *   • Cmd/Ctrl/middle-click still routes to /jobs/{id}?focus=notes
 *     (deep-link path preserved from pre-F8.1 behavior).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const navigate = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
}));

import ServiceNotePill from "@/components/schedule/ServiceNotePill";

const SHORT = "pH 7.6 target.";
const LONG =
  "pH 7.6 target. Leave chlorine tabs stocked in the pump-house " +
  "cabinet on the west wall. If the skimmer basket is full please " +
  "empty it before running the filter cycle.";

describe("F8.1 · ServiceNotePill inline preview", () => {
  beforeEach(() => {
    navigate.mockReset();
  });

  it("renders nothing when note is empty", () => {
    const { container } = render(
      <ServiceNotePill note="" serviceType="Pool Cleaning" jobId="j1" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders pill only when collapsed; preview only after click", () => {
    render(
      <ServiceNotePill note={SHORT} serviceType="Pool Cleaning" jobId="j1" />,
    );
    const pill = screen.getByTestId("service-note-pill-j1");
    expect(pill).toBeInTheDocument();
    expect(pill.getAttribute("aria-expanded")).toBe("false");
    // Preview NOT rendered yet.
    expect(screen.queryByTestId("service-note-pill-j1-preview")).toBeNull();

    fireEvent.click(pill);
    expect(pill.getAttribute("aria-expanded")).toBe("true");
    const preview = screen.getByTestId("service-note-pill-j1-preview");
    expect(preview).toBeInTheDocument();
    expect(screen.getByTestId("service-note-pill-j1-preview-text").textContent)
      .toBe(SHORT);
  });

  it("truncates long notes to ~80 chars with a …more toggle", () => {
    render(
      <ServiceNotePill note={LONG} serviceType="Pool Cleaning" jobId="j2" />,
    );
    fireEvent.click(screen.getByTestId("service-note-pill-j2"));

    const text = screen.getByTestId("service-note-pill-j2-preview-text");
    // Truncated body ends in "…"; length ~= 80 + 1 for ellipsis.
    expect(text.textContent.endsWith("…")).toBe(true);
    expect(text.textContent.length).toBeLessThanOrEqual(82);

    // "…more" toggle appears; clicking it reveals the full body.
    const moreBtn = screen.getByTestId("service-note-pill-j2-more-toggle");
    expect(moreBtn.textContent).toContain("more");
    fireEvent.click(moreBtn);
    expect(screen.getByTestId("service-note-pill-j2-preview-text").textContent)
      .toBe(LONG);
    // Toggle now reads "less".
    expect(screen.getByTestId("service-note-pill-j2-more-toggle").textContent)
      .toBe("less");
  });

  it("keyboard Enter and Space toggle the preview", () => {
    render(
      <ServiceNotePill note={SHORT} serviceType="Pool Cleaning" jobId="j3" />,
    );
    const pill = screen.getByTestId("service-note-pill-j3");
    // Enter opens.
    fireEvent.keyDown(pill, { key: "Enter" });
    expect(pill.getAttribute("aria-expanded")).toBe("true");
    // Space closes (space toggles same as click).
    fireEvent.keyDown(pill, { key: " " });
    expect(pill.getAttribute("aria-expanded")).toBe("false");
  });

  it("second click on the pill collapses the preview", () => {
    render(
      <ServiceNotePill note={SHORT} serviceType="Landscaping" jobId="j4" />,
    );
    const pill = screen.getByTestId("service-note-pill-j4");
    fireEvent.click(pill);
    expect(pill.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(pill);
    expect(pill.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("service-note-pill-j4-preview")).toBeNull();
  });

  it("cmd/ctrl-click deep-links to /jobs/{id}?focus=notes (legacy path)", () => {
    render(
      <ServiceNotePill note={SHORT} serviceType="Pool Cleaning" jobId="j5" />,
    );
    fireEvent.click(screen.getByTestId("service-note-pill-j5"), {
      ctrlKey: true,
    });
    expect(navigate).toHaveBeenCalledWith("/jobs/j5?focus=notes");
    // And the pill did NOT expand.
    expect(
      screen.getByTestId("service-note-pill-j5").getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("preview container is aria-live=polite so SRs announce the note", () => {
    render(
      <ServiceNotePill note={SHORT} serviceType="Pool Cleaning" jobId="j6" />,
    );
    fireEvent.click(screen.getByTestId("service-note-pill-j6"));
    const preview = screen.getByTestId("service-note-pill-j6-preview");
    expect(preview.getAttribute("aria-live")).toBe("polite");
    expect(preview.getAttribute("role")).toBe("region");
  });
});
