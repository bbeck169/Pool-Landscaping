/**
 * Feb-2026 · Item 1 — ConfirmDeleteDialog vitest.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";

describe("ConfirmDeleteDialog", () => {
  it("renders title + body and disabled state respects requireTypeConfirm", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDeleteDialog open
      title="Delete customer?"
      body="Sara Garcia will be soft-deleted."
      requireTypeConfirm
      typeConfirmString="DELETE"
      onConfirm={onConfirm}
      onCancel={() => {}}
    />);
    expect(screen.getByTestId("confirm-delete-title").textContent).toContain("Delete customer");
    expect(screen.getByTestId("confirm-delete-body").textContent).toContain("Sara Garcia");
    // Confirm disabled until "DELETE" typed.
    expect(screen.getByTestId("confirm-delete-confirm-btn")).toBeDisabled();
    fireEvent.change(screen.getByTestId("confirm-delete-type-input"),
                      { target: { value: "delete" } });
    expect(screen.getByTestId("confirm-delete-confirm-btn")).toBeDisabled();
    fireEvent.change(screen.getByTestId("confirm-delete-type-input"),
                      { target: { value: "DELETE" } });
    expect(screen.getByTestId("confirm-delete-confirm-btn")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("confirm-delete-confirm-btn"));
    expect(onConfirm).toHaveBeenCalled();
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
    // Escape key.
    onCancel.mockClear();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("standard (non-typed) confirm is enabled from the start + fires onConfirm", () => {
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

  it("does not render when open=false", () => {
    render(<ConfirmDeleteDialog open={false}
      title="x" body="y" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.queryByTestId("confirm-delete-dialog")).toBeNull();
  });
});
