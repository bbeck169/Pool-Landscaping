/**
 * OutstandingInvoicesTile · TD-admin-dashboard-outstanding-invoices-tile
 * Feb-2026
 *
 * Locks the new Revenue-Insights-top tile:
 *   1. Renders ``money(outstanding_total)`` + "N invoices · all time"
 *      sublabel on a happy payload.
 *   2. Pluralization pivots on count (0, 1, many).
 *   3. Empty payload (0 outstanding) renders "$0.00 · 0 invoices · all time".
 *   4. ``null`` summary (loading) renders em-dash + "loading…" sublabel
 *      and the button is disabled.
 *   5. ``undefined`` summary (fetch error) renders em-dash + "unavailable"
 *      sublabel and the button is disabled.
 *   6. Click fires the parent-supplied handler exactly once with no
 *      arguments (parent owns the deep-link target).
 *   7. Dedicated ``tile-outstanding-invoices`` testid + child testids
 *      (value / sublabel) are stable.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

afterEach(() => cleanup());

import OutstandingInvoicesTile from "@/components/dashboard/OutstandingInvoicesTile";


const _sum = (over = {}) => ({
  month_label: "Feb 2026",
  collected_this_month: 1234.56,
  outstanding_total: 4567.89,
  outstanding_count: 3,
  overdue: [],
  range_active: false,
  date_field: "created_at",
  ...over,
});


describe("<OutstandingInvoicesTile />", () => {
  it("renders money + pluralized sublabel on a happy payload", () => {
    render(
      <OutstandingInvoicesTile summary={_sum()} onClick={() => {}} />,
    );
    const tile = screen.getByTestId("tile-outstanding-invoices");
    expect(tile).toBeTruthy();
    expect(tile.getAttribute("data-tone")).toBe("amber");
    expect(tile.getAttribute("data-loading")).toBe("false");
    expect(tile.getAttribute("data-error")).toBe("false");
    expect(
      screen.getByTestId("tile-outstanding-invoices-value").textContent,
    ).toMatch(/\$4,?567\.89/);
    expect(
      screen.getByTestId("tile-outstanding-invoices-sublabel").textContent,
    ).toContain("3 invoices · all time");
  });

  it("uses singular 'invoice' when count is 1", () => {
    render(
      <OutstandingInvoicesTile
        summary={_sum({ outstanding_count: 1, outstanding_total: 10 })}
        onClick={() => {}}
      />,
    );
    expect(
      screen.getByTestId("tile-outstanding-invoices-sublabel").textContent,
    ).toContain("1 invoice · all time");
  });

  it("renders $0.00 · 0 invoices on an empty-AR payload", () => {
    render(
      <OutstandingInvoicesTile
        summary={_sum({ outstanding_total: 0, outstanding_count: 0 })}
        onClick={() => {}}
      />,
    );
    expect(
      screen.getByTestId("tile-outstanding-invoices-value").textContent,
    ).toMatch(/\$0\.00/);
    expect(
      screen.getByTestId("tile-outstanding-invoices-sublabel").textContent,
    ).toContain("0 invoices · all time");
  });

  it("renders a loading placeholder when summary is null", () => {
    render(
      <OutstandingInvoicesTile summary={null} onClick={() => {}} />,
    );
    const tile = screen.getByTestId("tile-outstanding-invoices");
    expect(tile.getAttribute("data-loading")).toBe("true");
    expect(tile.hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByTestId("tile-outstanding-invoices-value").textContent.trim(),
    ).toBe("—");
    expect(
      screen.getByTestId("tile-outstanding-invoices-sublabel").textContent,
    ).toContain("loading");
  });

  it("renders an error placeholder when summary is undefined", () => {
    render(
      <OutstandingInvoicesTile summary={undefined} onClick={() => {}} />,
    );
    const tile = screen.getByTestId("tile-outstanding-invoices");
    expect(tile.getAttribute("data-error")).toBe("true");
    expect(tile.hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByTestId("tile-outstanding-invoices-sublabel").textContent,
    ).toContain("unavailable");
  });

  it("fires onClick exactly once when the tile is clicked", () => {
    const onClick = vi.fn();
    render(
      <OutstandingInvoicesTile summary={_sum()} onClick={onClick} />,
    );
    fireEvent.click(screen.getByTestId("tile-outstanding-invoices"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does NOT fire onClick while loading (button is disabled)", () => {
    const onClick = vi.fn();
    render(
      <OutstandingInvoicesTile summary={null} onClick={onClick} />,
    );
    fireEvent.click(screen.getByTestId("tile-outstanding-invoices"));
    expect(onClick).not.toHaveBeenCalled();
  });
});
