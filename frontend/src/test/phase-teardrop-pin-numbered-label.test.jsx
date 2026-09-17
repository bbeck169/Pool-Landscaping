/**
 * Feb-2026 · Ticket A · TeardropPin numbered label.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import TeardropPin, {
  formatPinLabel,
  pickLabelTextColor,
} from "../components/maps/TeardropPin";


describe("formatPinLabel", () => {
  it("zero-pads single digits", () => {
    expect(formatPinLabel(1)).toBe("01");
    expect(formatPinLabel(9)).toBe("09");
  });
  it("preserves 2-digit + 3-digit numbers", () => {
    expect(formatPinLabel(10)).toBe("10");
    expect(formatPinLabel(99)).toBe("99");
    expect(formatPinLabel(100)).toBe("100");
    expect(formatPinLabel(999)).toBe("999");
  });
  it("returns null for null / undefined / empty", () => {
    expect(formatPinLabel(null)).toBeNull();
    expect(formatPinLabel(undefined)).toBeNull();
    expect(formatPinLabel("")).toBeNull();
  });
  it("zero-pads numeric strings", () => {
    expect(formatPinLabel("3")).toBe("03");
    expect(formatPinLabel("12")).toBe("12");
  });
});


describe("pickLabelTextColor", () => {
  it("returns white on dark backgrounds", () => {
    expect(pickLabelTextColor("#000000")).toBe("#FFFFFF");
    expect(pickLabelTextColor("#1E3A8A")).toBe("#FFFFFF"); // midnight_blue
    expect(pickLabelTextColor("#B45309")).toBe("#FFFFFF"); // slate_amber
  });
  it("returns dark on light backgrounds", () => {
    expect(pickLabelTextColor("#FDE68A")).toBe("#0F172A");
    expect(pickLabelTextColor("#FFFFFF")).toBe("#0F172A");
    expect(pickLabelTextColor("#EAB308")).toBe("#0F172A"); // yellow-500
  });
});


describe("<TeardropPin label>", () => {
  it("renders zero-padded number and drops hollow inner circle", () => {
    const { container, getByTestId } = render(
      <TeardropPin color="#1E3A8A" label={1} />,
    );
    const svg = getByTestId("teardrop-pin");
    expect(svg.getAttribute("data-label")).toBe("01");
    const text = getByTestId("teardrop-pin-label");
    expect(text.textContent).toBe("01");
    // The body path SHOULD be the solid variant (no inner cutout).
    const body = getByTestId("teardrop-pin-body");
    const d = body.getAttribute("d");
    // Solid path has 1 subpath (no ``M 12 5.5`` second Move-To).
    expect(d).not.toContain("M 12 5.5");
    // White text on dark navy background.
    expect(text.getAttribute("fill")).toBe("#FFFFFF");
    expect(container).toBeTruthy();
  });

  it("renders 100 without truncation", () => {
    const { getByTestId } = render(
      <TeardropPin color="#1E3A8A" label={100} />,
    );
    expect(getByTestId("teardrop-pin-label").textContent).toBe("100");
  });

  it("preserves the hollow-circle path when label is undefined", () => {
    const { getByTestId, queryByTestId } = render(
      <TeardropPin color="#1E3A8A" />,
    );
    const body = getByTestId("teardrop-pin-body");
    expect(body.getAttribute("d")).toContain("M 12 5.5");
    expect(queryByTestId("teardrop-pin-label")).toBeNull();
  });

  it("flips text color on light backgrounds", () => {
    const { getByTestId } = render(
      <TeardropPin color="#FDE68A" label={5} />,
    );
    expect(getByTestId("teardrop-pin-label").getAttribute("fill"))
      .toBe("#0F172A");
  });
});
