/**
 * Feb-2026 · Item 1 — REWRITTEN for the app-wide type-to-confirm removal.
 *
 * History: Originally asserted the "type DELETE" heavy-blast input
 * gated the Confirm button in ``ConfirmDeleteDialog``. The typed
 * input has been removed per the sitewide brief; the props
 * (``requireTypeConfirm``, ``typeConfirmString``) stay on the API
 * for backwards-compat but are intentionally ignored.
 *
 * New assertions:
 *   • Standard modal: Confirm enabled from mount, click fires.
 *   • Heavy-blast (``requireTypeConfirm`` passed): NO text input
 *     rendered; Confirm still enabled from mount; click fires.
 *   • Cancel button + Escape key both call ``onCancel``.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";

describe("ConfirmDeleteDialog · Feb-2026 · type-to-confirm removed", () => {
  it("renders title + body and Confirm is enabled from mount (no gate)", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDeleteDialog open
      title="Delete customer?"
      body="Sara Garcia will be soft-deleted."
      onConfirm={onConfirm}
      onCancel={() => {}}
    />);
    expect(screen.getByTestId("confirm-delete-title").textContent)
      .toContain("Delete customer");
    expect(screen.getByTestId("confirm-delete-body").textContent)
      .toContain("Sara Garcia");
    // No typed-confirm input anywhere in the dialog.
    expect(screen.queryByTestId("confirm-delete-type-input")).toBeNull();
    // Confirm enabled immediately + fires on single click.
    const btn = screen.getByTestId("confirm-delete-confirm-btn");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("``requireTypeConfirm`` prop is accepted for backwards-compat "
      + "but does NOT render a text input or disable Confirm", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDeleteDialog open
      title="Delete pricebook item?"
      body="Item will be soft-deleted."
      requireTypeConfirm
      typeConfirmString="DELETE"
      onConfirm={onConfirm}
      onCancel={() => {}}
    />);
    expect(screen.queryByTestId("confirm-delete-type-input")).toBeNull();
    // No raw text input inside the dialog either.
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelector("input[type=\"text\"]")).toBeNull();
    // Confirm still enabled from mount.
    const btn = screen.getByTestId("confirm-delete-confirm-btn");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancel button + escape key both call onCancel", () => {
    const onCancel = vi.fn();
    render(<ConfirmDeleteDialog open
      title="Delete pricebook item?"
      body="Item will be soft-deleted."
      onConfirm={() => {}} onCancel={onCancel}
    />);
    fireEvent.click(screen.getByTestId("confirm-delete-cancel-btn"));
    expect(onCancel).toHaveBeenCalled();
    onCancel.mockClear();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("standard (non-typed) confirm — enabled from the start + fires onConfirm", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDeleteDialog open
      title="Cancel shift?"
      body="This will restore the source tech's route."
      confirmLabel="Cancel shift"
      onConfirm={onConfirm} onCancel={() => {}}
    />);
    expect(screen.getByTestId("confirm-delete-confirm-btn")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("confirm-delete-confirm-btn"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("busy state disables Confirm and swaps the label to '…'", () => {
    render(<ConfirmDeleteDialog open
      title="Delete item?"
      body="…"
      confirmLabel="Delete"
      busy
      onConfirm={() => {}} onCancel={() => {}}
    />);
    const btn = screen.getByTestId("confirm-delete-confirm-btn");
    expect(btn).toBeDisabled();
    expect(btn.textContent).toContain("…");
  });
});
