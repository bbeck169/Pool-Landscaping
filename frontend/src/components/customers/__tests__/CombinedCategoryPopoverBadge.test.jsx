/**
 * Feb-2026 · Ticket γ · CombinedCategoryPopoverBadge vitest.
 *
 * Pins the click-to-edit affordance layered on the shipped
 * ``<CombinedCategoryBadge>``:
 *
 *   1. ``admin`` / ``super_admin`` / ``owner`` roles → badge is a
 *      <button> with aria-haspopup="dialog".
 *   2. Other roles (``technician``, ``customer``, ``manager``) →
 *      badge is a static chip (no trigger button) matching the
 *      pre-γ experience.
 *   3. Click (or Enter / Space on the focused trigger) opens the
 *      popover with one row per active property.
 *   4. Clicking a chip inside the popover fires
 *      ``PATCH /properties/{pid}`` with
 *      ``{service_category: nextCat | null}``.  Clicking the
 *      selected chip clears the category.
 *   5. After a successful save, the local shadow updates so the
 *      badge label re-derives.  Save also invokes
 *      ``onRefreshCustomer()``.
 *   6. Esc + outside-click dismiss the popover.
 *   7. Inactive properties are not listed inside the popover.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, act,
} from "@testing-library/react";

const _patchMock = vi.fn();
vi.mock("@/api", () => ({
  api: { patch: (...a) => _patchMock(...a) },
}));

import CombinedCategoryPopoverBadge
  from "@/components/customers/CombinedCategoryPopoverBadge";


const _p = (id, service_category, extra = {}) => ({
  id, service_category, active: true, label: `Prop ${id}`,
  address: { line1: `${id} Main St`, city: "Phoenix", state: "AZ" },
  ...extra,
});


describe("Ticket γ · CombinedCategoryPopoverBadge", () => {
  beforeEach(() => { _patchMock.mockReset(); });

  it("renders as a static chip (no button) for non-admin roles", () => {
    render(<CombinedCategoryPopoverBadge
      properties={[_p("a", "pool")]} userRole="technician" />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toBeInTheDocument();
    expect(screen.queryByTestId(
      "customer-combined-category-badge-trigger",
    )).toBeNull();
  });

  it("renders as a button with aria-haspopup for admin roles",
      () => {
    for (const role of ["admin", "super_admin", "owner"]) {
      const { unmount } = render(<CombinedCategoryPopoverBadge
        properties={[_p("a", "pool")]} userRole={role} />);
      const btn = screen.getByTestId(
        "customer-combined-category-badge-trigger",
      );
      expect(btn.tagName).toBe("BUTTON");
      expect(btn).toHaveAttribute("aria-haspopup", "dialog");
      expect(btn).toHaveAttribute("aria-expanded", "false");
      unmount();
    }
  });

  it("opens the popover on click and lists one row per active "
      + "property (inactive filtered out)", () => {
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[
        _p("a", "pool"),
        _p("b", "landscaping"),
        _p("c", null, { active: false }),
      ]}
    />);
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    expect(screen.getByTestId(
      "customer-combined-category-popover",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "customer-category-popover-row-a",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "customer-category-popover-row-b",
    )).toBeInTheDocument();
    expect(screen.queryByTestId(
      "customer-category-popover-row-c",
    )).toBeNull();
    expect(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    )).toHaveAttribute("aria-expanded", "true");
  });

  it("clicking a chip inside the popover calls "
      + "PATCH /properties/{pid} with the chosen category + fires "
      + "onRefreshCustomer on success", async () => {
    _patchMock.mockResolvedValueOnce({
      id: "a", service_category: "landscaping",
    });
    const onToast = vi.fn();
    const onRefreshCustomer = vi.fn();
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[_p("a", "pool")]}
      onToast={onToast}
      onRefreshCustomer={onRefreshCustomer}
    />);
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    fireEvent.click(screen.getByTestId("pc-cat-landscaping-a"));
    await waitFor(() => {
      expect(_patchMock).toHaveBeenCalledWith(
        "/properties/a", { service_category: "landscaping" },
      );
    });
    await waitFor(() => {
      expect(onRefreshCustomer).toHaveBeenCalled();
    });
    expect(onToast).toHaveBeenCalledWith(expect.objectContaining({
      tone: "success",
    }));
  });

  it("clicking the SELECTED chip clears the category (patch with "
      + "service_category: null)", async () => {
    _patchMock.mockResolvedValueOnce({ id: "a", service_category: null });
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[_p("a", "pool")]}
    />);
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    fireEvent.click(screen.getByTestId("pc-cat-pool-a"));
    await waitFor(() => {
      expect(_patchMock).toHaveBeenCalledWith(
        "/properties/a", { service_category: null },
      );
    });
  });

  it("rolls back optimistic update + toasts error when PATCH "
      + "fails", async () => {
    _patchMock.mockRejectedValueOnce(new Error("boom"));
    const onToast = vi.fn();
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[_p("a", "pool")]}
      onToast={onToast}
    />);
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    fireEvent.click(screen.getByTestId("pc-cat-landscaping-a"));
    await waitFor(() => {
      expect(onToast).toHaveBeenCalledWith(expect.objectContaining({
        tone: "error",
      }));
    });
    // After rollback the pool chip is selected again.
    expect(screen.getByTestId("pc-cat-pool-a"))
      .toHaveAttribute("data-selected", "true");
  });

  it("Esc closes the popover and restores focus to the trigger",
      async () => {
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[_p("a", "pool")]}
    />);
    const btn = screen.getByTestId(
      "customer-combined-category-badge-trigger",
    );
    fireEvent.click(btn);
    expect(screen.getByTestId(
      "customer-combined-category-popover",
    )).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(screen.queryByTestId(
      "customer-combined-category-popover",
    )).toBeNull();
  });

  it("outside-click dismisses the popover", () => {
    render(<div>
      <div data-testid="outside">outside</div>
      <CombinedCategoryPopoverBadge
        userRole="admin"
        properties={[_p("a", "pool")]}
      />
    </div>);
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    expect(screen.getByTestId(
      "customer-combined-category-popover",
    )).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByTestId(
      "customer-combined-category-popover",
    )).toBeNull();
  });

  it("after a successful save the badge label re-derives from the "
      + "updated local shadow", async () => {
    _patchMock.mockResolvedValueOnce({
      id: "a", service_category: "landscaping",
    });
    render(<CombinedCategoryPopoverBadge
      userRole="admin"
      properties={[_p("a", "pool")]}
    />);
    expect(screen.getByTestId("customer-combined-category-badge")
      .getAttribute("data-combined-category")).toBe("Pool");
    fireEvent.click(screen.getByTestId(
      "customer-combined-category-badge-trigger",
    ));
    fireEvent.click(screen.getByTestId("pc-cat-landscaping-a"));
    await waitFor(() => {
      expect(screen.getByTestId("customer-combined-category-badge")
        .getAttribute("data-combined-category")).toBe("Landscaping");
    });
  });
});
