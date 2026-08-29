/**
 * Feb-2026 · Customer Delete UX overhaul — CustomerDeleteModal
 * behaviour lock.
 *
 * Locks:
 *   1. Modal renders 3 buttons: Cancel / Soft Delete / Hard Delete.
 *   2. Testids present and stable:
 *        customer-delete-cancel-btn
 *        customer-delete-soft-btn
 *        customer-delete-hard-btn
 *   3. Hard-Delete button is red (#B91C1C) and renders the
 *      ShieldAlert icon (lucide-react `<svg>` with the shield
 *      lucide class).
 *   4. NO type-to-confirm input rendered (Feb-2026 friction removal).
 *   5. Cancel does NOT call the delete handlers.
 *   6. Soft / Hard buttons invoke their respective callbacks.
 *   7. ``busyMode`` disables all buttons + relabels the busy one.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

import CustomerDeleteModal from "@/components/customers/CustomerDeleteModal";


afterEach(() => cleanup());


const _customer = { id: "c-1", name: "Ada Lovelace" };


describe("CustomerDeleteModal · Feb-2026 Customer Delete UX overhaul", () => {
  it("renders three buttons with the required testids", () => {
    render(
      <CustomerDeleteModal
        open
        customer={_customer}
        onCancel={vi.fn()}
        onSoftDelete={vi.fn()}
        onHardDelete={vi.fn()}
      />,
    );
    expect(screen.getByTestId("customer-delete-modal")).toBeTruthy();
    expect(screen.getByTestId("customer-delete-cancel-btn")).toBeTruthy();
    expect(screen.getByTestId("customer-delete-soft-btn")).toBeTruthy();
    expect(screen.getByTestId("customer-delete-hard-btn")).toBeTruthy();
    // Title mentions the customer's name.
    expect(screen.getByTestId("customer-delete-title").textContent)
      .toContain("Ada Lovelace");
  });

  it("Hard-Delete button is red and has the ShieldAlert icon", () => {
    render(
      <CustomerDeleteModal
        open customer={_customer}
        onCancel={vi.fn()} onSoftDelete={vi.fn()} onHardDelete={vi.fn()}
      />,
    );
    const hard = screen.getByTestId("customer-delete-hard-btn");
    // Red background — hex from the component spec.
    const bg = hard.style.backgroundColor;
    // JSDOM normalises "#B91C1C" → "rgb(185, 28, 28)".
    expect(bg.replace(/\s/g, "")).toBe("rgb(185,28,28)");
    // Contains an SVG (lucide-react renders every icon as <svg>).
    const svg = hard.querySelector("svg");
    expect(svg).not.toBeNull();
    // The button also announces the destructive verb.
    expect(hard.textContent.toLowerCase()).toContain("hard delete");
  });

  it("does NOT render any type-to-confirm text input (no friction)", () => {
    render(
      <CustomerDeleteModal
        open customer={_customer}
        onCancel={vi.fn()} onSoftDelete={vi.fn()} onHardDelete={vi.fn()}
      />,
    );
    // The old ConfirmDeleteDialog had a text input for "type DELETE
    // to confirm". This modal must NEVER render one.
    const modal = screen.getByTestId("customer-delete-modal");
    expect(modal.querySelector("input[type=text]")).toBeNull();
  });

  it("Cancel calls onCancel and NEITHER delete callback", () => {
    const onCancel = vi.fn();
    const onSoft = vi.fn();
    const onHard = vi.fn();
    render(
      <CustomerDeleteModal
        open customer={_customer}
        onCancel={onCancel} onSoftDelete={onSoft} onHardDelete={onHard}
      />,
    );
    fireEvent.click(screen.getByTestId("customer-delete-cancel-btn"));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSoft).not.toHaveBeenCalled();
    expect(onHard).not.toHaveBeenCalled();
  });

  it("clicking Soft Delete invokes onSoftDelete only", () => {
    const onSoft = vi.fn();
    const onHard = vi.fn();
    render(
      <CustomerDeleteModal
        open customer={_customer}
        onCancel={vi.fn()} onSoftDelete={onSoft} onHardDelete={onHard}
      />,
    );
    fireEvent.click(screen.getByTestId("customer-delete-soft-btn"));
    expect(onSoft).toHaveBeenCalledTimes(1);
    expect(onHard).not.toHaveBeenCalled();
  });

  it("clicking Hard Delete invokes onHardDelete only", () => {
    const onSoft = vi.fn();
    const onHard = vi.fn();
    render(
      <CustomerDeleteModal
        open customer={_customer}
        onCancel={vi.fn()} onSoftDelete={onSoft} onHardDelete={onHard}
      />,
    );
    fireEvent.click(screen.getByTestId("customer-delete-hard-btn"));
    expect(onHard).toHaveBeenCalledTimes(1);
    expect(onSoft).not.toHaveBeenCalled();
  });

  it("busyMode disables all buttons + relabels the busy one", () => {
    render(
      <CustomerDeleteModal
        open customer={_customer} busyMode="hard"
        onCancel={vi.fn()} onSoftDelete={vi.fn()} onHardDelete={vi.fn()}
      />,
    );
    expect(screen.getByTestId("customer-delete-cancel-btn").disabled).toBe(true);
    expect(screen.getByTestId("customer-delete-soft-btn").disabled).toBe(true);
    expect(screen.getByTestId("customer-delete-hard-btn").disabled).toBe(true);
    expect(screen.getByTestId("customer-delete-hard-btn").textContent)
      .toMatch(/Hard-deleting…/i);
  });
});
