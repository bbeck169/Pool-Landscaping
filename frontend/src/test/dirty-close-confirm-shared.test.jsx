/**
 * Phase W1 · Feb-2026 — DirtyCloseConfirm shared component contract.
 *
 * Locks the three-button layout + disabled semantics that both
 * ChecklistModal (C1/C1.1) and PoolChecklistWizard (W1) depend on:
 *
 *   • Three buttons rendered, left → right:
 *       Keep editing | Discard changes | Save & close
 *   • Keep editing ALWAYS enabled (tech escape hatch — even while
 *     ``isSaving`` a save is in flight, they can bail).
 *   • Discard changes disabled when ``isSaving``.
 *   • Save & close disabled when ``isSaving`` and swaps its label
 *     to "Saving…" with a spinner.
 *   • Backdrop click fires ``onKeepEditing`` UNLESS ``isSaving``
 *     (double-guard against dismissing a mid-flight save).
 *   • Custom testids: default to C1 legacy contract, overridable
 *     via the ``*TestId`` props (used by the wizard mount).
 *   • ``open={false}`` → renders nothing.
 */
import React from "react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import DirtyCloseConfirm from "@/components/checklist/DirtyCloseConfirm";


afterEach(() => cleanup());


describe("DirtyCloseConfirm · rendering + testids", () => {
  it("open={false} renders nothing", () => {
    const { container } = render(<DirtyCloseConfirm open={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("open={true} renders all three buttons with the C1 default testids", () => {
    render(<DirtyCloseConfirm open />);
    expect(screen.getByTestId("checklist-discard-confirm-backdrop")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-discard-confirm")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-discard-keep-editing")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-discard-confirm-btn")).toBeInTheDocument();
    expect(screen.getByTestId("checklist-save-and-close")).toBeInTheDocument();
  });

  it("testid props override the default prefix (wizard mount)", () => {
    render(
      <DirtyCloseConfirm
        open
        backdropTestId="wizard-discard-confirm-backdrop"
        bodyTestId="wizard-discard-confirm"
        keepEditingTestId="wizard-discard-keep-editing"
        discardTestId="wizard-discard-confirm-btn"
        saveTestId="wizard-save-and-close"
        hintId="wizard-discard-hint"
      />,
    );
    expect(screen.getByTestId("wizard-discard-confirm")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-save-and-close")).toBeInTheDocument();
    // C1-default testids MUST NOT co-exist alongside the wizard ones.
    expect(screen.queryByTestId("checklist-discard-confirm")).toBeNull();
  });
});


describe("DirtyCloseConfirm · disabled semantics", () => {
  it("isSaving=false → all three buttons enabled", () => {
    render(<DirtyCloseConfirm open isSaving={false} />);
    expect(screen.getByTestId("checklist-discard-keep-editing")).not.toBeDisabled();
    expect(screen.getByTestId("checklist-discard-confirm-btn")).not.toBeDisabled();
    expect(screen.getByTestId("checklist-save-and-close")).not.toBeDisabled();
  });

  it("isSaving=true → Discard + Save disabled; Keep editing still enabled", () => {
    render(<DirtyCloseConfirm open isSaving />);
    expect(screen.getByTestId("checklist-discard-keep-editing")).not.toBeDisabled();
    expect(screen.getByTestId("checklist-discard-confirm-btn")).toBeDisabled();
    expect(screen.getByTestId("checklist-save-and-close")).toBeDisabled();
  });

  it("isSaving=true → Save & close label swaps to Saving…", () => {
    render(<DirtyCloseConfirm open isSaving />);
    expect(screen.getByTestId("checklist-save-and-close").textContent).toMatch(/Saving…/);
  });
});


describe("DirtyCloseConfirm · click wiring", () => {
  it("Keep editing fires onKeepEditing (once)", () => {
    const onKeepEditing = vi.fn();
    render(<DirtyCloseConfirm open onKeepEditing={onKeepEditing} />);
    fireEvent.click(screen.getByTestId("checklist-discard-keep-editing"));
    expect(onKeepEditing).toHaveBeenCalledTimes(1);
  });

  it("Discard fires onDiscard when not saving", () => {
    const onDiscard = vi.fn();
    render(<DirtyCloseConfirm open onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("checklist-discard-confirm-btn"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });

  it("Discard does NOT fire onDiscard while isSaving", () => {
    const onDiscard = vi.fn();
    render(<DirtyCloseConfirm open isSaving onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("checklist-discard-confirm-btn"));
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("Save & close fires onSaveAndClose when not saving", () => {
    const onSaveAndClose = vi.fn();
    render(<DirtyCloseConfirm open onSaveAndClose={onSaveAndClose} />);
    fireEvent.click(screen.getByTestId("checklist-save-and-close"));
    expect(onSaveAndClose).toHaveBeenCalledTimes(1);
  });

  it("Save & close does NOT fire while isSaving (double-guard)", () => {
    const onSaveAndClose = vi.fn();
    render(<DirtyCloseConfirm open isSaving onSaveAndClose={onSaveAndClose} />);
    fireEvent.click(screen.getByTestId("checklist-save-and-close"));
    expect(onSaveAndClose).not.toHaveBeenCalled();
  });

  it("Backdrop click fires onKeepEditing when not saving", () => {
    const onKeepEditing = vi.fn();
    render(<DirtyCloseConfirm open onKeepEditing={onKeepEditing} />);
    fireEvent.click(screen.getByTestId("checklist-discard-confirm-backdrop"));
    expect(onKeepEditing).toHaveBeenCalledTimes(1);
  });

  it("Backdrop click is a no-op while isSaving", () => {
    const onKeepEditing = vi.fn();
    render(<DirtyCloseConfirm open isSaving onKeepEditing={onKeepEditing} />);
    fireEvent.click(screen.getByTestId("checklist-discard-confirm-backdrop"));
    expect(onKeepEditing).not.toHaveBeenCalled();
  });
});
