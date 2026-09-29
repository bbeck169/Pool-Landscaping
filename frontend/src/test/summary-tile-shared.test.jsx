/**
 * QUOTES-SUMMARY · Feb-2026 — shared SummaryTile component.
 *
 * Locks the extraction contract for ``components/SummaryTile.jsx``:
 *
 *   1. Renders the InvoicesList prop shape byte-for-byte.
 *   2. Renders standalone from the shared path (no InvoicesList
 *      required).
 *   3. When ``children`` is passed, replaces the ``value`` slot.
 *   4. Optional ``testid`` stamps ``data-testid`` on the outer
 *      card.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Clock } from "lucide-react";

import SummaryTile from "@/components/SummaryTile";


describe("SummaryTile · extracted shared component", () => {
  it("renders the InvoicesList prop shape (icon + tone + label + value + sub)", () => {
    render(
      <SummaryTile
        icon={Clock}
        tone="#A16207"
        label="Outstanding"
        value="$1,200.00"
        sub="3 inv"
        testid="test-summary-tile-outstanding"
      />,
    );
    const tile = screen.getByTestId("test-summary-tile-outstanding");
    expect(tile.textContent).toContain("Outstanding");
    expect(tile.textContent).toContain("$1,200.00");
    expect(tile.textContent).toContain("3 inv");
  });

  it("omits the sub row when ``sub`` is not provided", () => {
    render(
      <SummaryTile
        icon={Clock}
        tone="#A16207"
        label="Overdue count"
        value="7"
        testid="test-summary-tile-overdue"
      />,
    );
    const tile = screen.getByTestId("test-summary-tile-overdue");
    expect(tile.textContent).toContain("7");
    expect(tile.textContent).not.toContain("null");
    expect(tile.textContent).not.toContain("undefined");
  });

  it("renders ``children`` in place of ``value`` when provided", () => {
    render(
      <SummaryTile
        icon={Clock}
        tone="#0891B2"
        label="Stage Breakdown"
        value="THIS_VALUE_SHOULD_NOT_APPEAR"
        testid="test-summary-tile-children"
      >
        <div data-testid="test-summary-tile-child-inner">custom slot</div>
      </SummaryTile>,
    );
    const tile = screen.getByTestId("test-summary-tile-children");
    expect(tile.textContent).toContain("custom slot");
    expect(tile.textContent).not.toContain("THIS_VALUE_SHOULD_NOT_APPEAR");
    // The inner child is present so a caller can style / test its
    // subtree directly.
    expect(
      screen.getByTestId("test-summary-tile-child-inner"),
    ).toBeTruthy();
  });

  it("does NOT stamp a testid attribute when the ``testid`` prop is omitted", () => {
    // InvoicesList's original callers never pass ``testid`` — the
    // DOM must NOT gain a spurious ``data-testid=""`` attribute
    // that could collide with existing testids in the tree.
    render(
      <SummaryTile
        icon={Clock}
        tone="#A16207"
        label="No testid"
        value="0"
      />,
    );
    // Grab by the visible label and verify no testid attribute.
    const label = screen.getByText("No testid");
    // Outer wrapper is the ``rounded-2xl p-4`` div — walk up.
    const outer = label.closest("div.rounded-2xl");
    expect(outer).not.toBeNull();
    expect(outer.getAttribute("data-testid")).toBeNull();
  });
});
