/**
 * Phase K62 · Feb-2026 — CustomersPager First/Last + size selector
 * unit tests (component in isolation, no CustomersList mount).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import CustomersPager from "@/components/customers/CustomersPager";

function _mount(overrides = {}) {
  const onPageChange = vi.fn();
  const onPageSizeChange = vi.fn();
  render(
    <CustomersPager
      page={3}
      total_pages={10}
      total={250}
      page_size={25}
      onPageChange={onPageChange}
      pageSizeOptions={[25, 50, 100]}
      onPageSizeChange={onPageSizeChange}
      testidPrefix="pgr"
      {...overrides}
    />,
  );
  return { onPageChange, onPageSizeChange };
}

describe("CustomersPager · K62", () => {
  it("renders First / Prev / strip / Next / Last controls on a multi-page result", () => {
    _mount();
    const pgr = screen.getByTestId("pgr");
    expect(within(pgr).getByTestId("pgr-first")).toBeTruthy();
    expect(within(pgr).getByTestId("pgr-prev")).toBeTruthy();
    expect(within(pgr).getByTestId("pgr-next")).toBeTruthy();
    expect(within(pgr).getByTestId("pgr-last")).toBeTruthy();
    expect(within(pgr).getByTestId("pgr-page-3")
      .getAttribute("aria-current")).toBe("page");
  });

  it("First is disabled at page 1", () => {
    _mount({ page: 1 });
    expect(screen.getByTestId("pgr-first").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("pgr-prev").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("pgr-next").hasAttribute("disabled")).toBe(false);
    expect(screen.getByTestId("pgr-last").hasAttribute("disabled")).toBe(false);
  });

  it("Last is disabled at total_pages", () => {
    _mount({ page: 10 });
    expect(screen.getByTestId("pgr-first").hasAttribute("disabled")).toBe(false);
    expect(screen.getByTestId("pgr-prev").hasAttribute("disabled")).toBe(false);
    expect(screen.getByTestId("pgr-next").hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("pgr-last").hasAttribute("disabled")).toBe(true);
  });

  it("clicking First emits page 1, Last emits total_pages", () => {
    const { onPageChange } = _mount({ page: 5 });
    fireEvent.click(screen.getByTestId("pgr-first"));
    expect(onPageChange).toHaveBeenCalledWith(1);
    onPageChange.mockClear();
    fireEvent.click(screen.getByTestId("pgr-last"));
    expect(onPageChange).toHaveBeenCalledWith(10);
  });

  it("size selector emits the new size", () => {
    const { onPageSizeChange } = _mount();
    fireEvent.change(screen.getByTestId("pgr-size-selector"), {
      target: { value: "50" },
    });
    expect(onPageSizeChange).toHaveBeenCalledWith(50);
  });

  it("renders only the size selector when total_pages < 2 AND selector is enabled", () => {
    _mount({ total_pages: 1, total: 10, page: 1 });
    expect(screen.getByTestId("pgr")).toBeTruthy();
    expect(screen.queryByTestId("pgr-next")).toBeNull();
    expect(screen.queryByTestId("pgr-first")).toBeNull();
    expect(screen.getByTestId("pgr-size-selector")).toBeTruthy();
  });

  it("returns null when total_pages < 2 AND no size selector is provided (legacy)", () => {
    const { container } = render(
      <CustomersPager
        page={1}
        total_pages={1}
        total={10}
        page_size={100}
        onPageChange={() => {}}
        testidPrefix="legacy"
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
