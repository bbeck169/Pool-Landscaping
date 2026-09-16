/**
 * Phase W1 · Feb-2026 — PoolChecklistWizard dirty-close guard.
 *
 * Mirrors the C1 / C1.1 exit-flow guard that already lives on the
 * host `<ChecklistModal>`. Locks the three-intent contract:
 *
 *   • Next on any step         → NEVER opens the confirm.
 *   • Back on step 1+          → walks the step index down, no confirm.
 *   • Back on step 0 + dirty   → opens the confirm.
 *   • Close-job on clean form  → fires ``onCloseJob`` immediately.
 *   • Close-job on dirty form  → opens the confirm.
 *   • Save & close (happy)     → ``flushSave`` fires ONCE, then intent fires.
 *   • Save & close (failure)   → error toast, wizard stays open, dirty preserved.
 *   • Discard changes          → intent fires immediately, no save.
 *   • Keep editing             → dismisses the confirm, no intent fires.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";

// Toast surface — the wizard's Save & close failure path fires
// ``toast.error(...)``; capture the spy so we can assert on it.
// ``vi.hoisted`` runs BEFORE the top-level ``vi.mock`` factory
// (which itself is hoisted above imports), so ``_toastError`` is
// safe to reference from the factory closure.
const { _toastError } = vi.hoisted(() => ({ _toastError: vi.fn() }));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    error:   _toastError,
    success: vi.fn(), warning: vi.fn(), info: vi.fn(),
  }),
}));

// Heavy children — the wizard mounts <PoolChecklistForm> and
// <PhotoUploader>; stub them to isolate the footer state machine.
vi.mock("@/components/checklist/PoolChecklistForm", () => ({
  default: () => <div data-testid="pool-form-stub" />,
}));
vi.mock("@/components/checklist/PhotoUploader", () => ({
  default: () => <div data-testid="photo-uploader-stub" />,
}));

// eslint-disable-next-line import/first
import PoolChecklistWizard from "@/components/checklist/PoolChecklistWizard";


// ─── Test harness ──────────────────────────────────────────────────
function _report(overrides = {}) {
  return {
    id: "sr-w1", job_id: "job-w1", template: "pool",
    chemical_readings: [],
    chemicals_added: [],
    checklist_items: [],
    photos: [],
    notes: "", internal_notes: "", customer_notes: "",
    water_bodies: [],
    wizard_step: 1,
    ...overrides,
  };
}


function _mount(props = {}) {
  const dirtyRef = { current: false };
  const flushSave = vi.fn().mockImplementation(async () => {
    // Default happy-path flusher — clears dirty like the parent does.
    dirtyRef.current = false;
  });
  const onSaveExit = vi.fn();
  const onCloseJob = vi.fn();
  const onChange = vi.fn();

  const utils = render(
    <PoolChecklistWizard
      jobId="job-w1"
      customerId="cust-w1"
      locked={false}
      report={_report(props.report)}
      onChange={onChange}
      onSaveExit={onSaveExit}
      onCloseJob={onCloseJob}
      submitting={false}
      isDirty={() => dirtyRef.current}
      flushSave={flushSave}
      {...props.overrides}
    />,
  );

  return {
    ...utils,
    dirtyRef,
    flushSave,
    onSaveExit,
    onCloseJob,
    onChange,
    // Sugar for "the tech typed something".
    markDirty: () => { dirtyRef.current = true; },
  };
}


beforeEach(() => {
  _toastError.mockReset();
  cleanup();
});


// ─── (1) Next NEVER opens the confirm ──────────────────────────────
describe("Phase W1 · wizard-next never gates on dirty", () => {
  it("Next on step 1 with a dirty form advances the step, no confirm", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-next"));
    expect(h.onChange).toHaveBeenCalledWith({ wizard_step: 2 });
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });

  it("Next on step 5 (dirty) advances to step 6, no confirm", async () => {
    const h = _mount({ report: { wizard_step: 5 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-next"));
    expect(h.onChange).toHaveBeenCalledWith({ wizard_step: 6 });
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });
});


// ─── (2) Back on step > 1 walks step down, no confirm ─────────────
describe("Phase W1 · Back on step > 1", () => {
  it("dirty form on step 3 → step 2, no confirm", async () => {
    const h = _mount({ report: { wizard_step: 3 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-back"));
    expect(h.onChange).toHaveBeenCalledWith({ wizard_step: 2 });
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
    expect(h.onSaveExit).not.toHaveBeenCalled();
  });

  it("clean form on step 2 → step 1, no confirm", async () => {
    const h = _mount({ report: { wizard_step: 2 } });
    fireEvent.click(screen.getByTestId("wizard-back"));
    expect(h.onChange).toHaveBeenCalledWith({ wizard_step: 1 });
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });
});


// ─── (3) Back on step 1 · exit-flow ───────────────────────────────
describe("Phase W1 · Back on step 1 (exit-flow)", () => {
  it("clean form → fires onSaveExit immediately, no confirm", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    fireEvent.click(screen.getByTestId("wizard-back"));
    expect(h.onSaveExit).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });

  it("dirty form → opens confirm dialog with all three buttons, no onSaveExit yet", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-back"));
    expect(await screen.findByTestId("wizard-discard-confirm")).toBeInTheDocument();
    // All three buttons rendered with the wizard-scoped testids.
    expect(screen.getByTestId("wizard-discard-keep-editing")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-discard-confirm-btn")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-save-and-close")).toBeInTheDocument();
    expect(h.onSaveExit).not.toHaveBeenCalled();
  });
});


// ─── (4) Close-job on clean vs dirty ──────────────────────────────
describe("Phase W1 · Close-job", () => {
  it("clean form → fires onCloseJob immediately, no confirm", async () => {
    const h = _mount({
      report: {
        wizard_step: 6,
        // closeJobValid → readings all answered / empty is OK.
        chemical_readings: [],
      },
    });
    fireEvent.click(screen.getByTestId("wizard-close-job"));
    expect(h.onCloseJob).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });

  it("dirty form → opens confirm, does NOT fire onCloseJob yet", async () => {
    const h = _mount({ report: { wizard_step: 6 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-close-job"));
    expect(await screen.findByTestId("wizard-discard-confirm")).toBeInTheDocument();
    expect(h.onCloseJob).not.toHaveBeenCalled();
  });
});


// ─── (5) Confirm buttons · happy + failure ────────────────────────
describe("Phase W1 · confirm-dialog buttons", () => {
  it("Save & close (happy) → flushSave fires exactly once, then onSaveExit", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-back"));
    await screen.findByTestId("wizard-discard-confirm");

    await act(async () => {
      fireEvent.click(screen.getByTestId("wizard-save-and-close"));
    });

    expect(h.flushSave).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(h.onSaveExit).toHaveBeenCalledTimes(1));
    expect(_toastError).not.toHaveBeenCalled();
    // Dialog dismissed.
    await waitFor(() =>
      expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull(),
    );
  });

  it("Save & close (failure) → error toast, dialog stays open, no onSaveExit", async () => {
    const failingFlush = vi.fn().mockImplementation(async () => {
      // Simulate the parent's flushSave that swallows the error and
      // leaves ``dirtyRef.current`` truthy.
    });
    const h = _mount({
      report: { wizard_step: 1 },
      overrides: {
        // Parent-owned dirty getter — stays true because failing
        // flush does NOT clear it.
        isDirty: () => true,
        flushSave: failingFlush,
      },
    });
    fireEvent.click(screen.getByTestId("wizard-back"));
    await screen.findByTestId("wizard-discard-confirm");

    await act(async () => {
      fireEvent.click(screen.getByTestId("wizard-save-and-close"));
    });

    expect(failingFlush).toHaveBeenCalledTimes(1);
    expect(_toastError).toHaveBeenCalledTimes(1);
    expect(_toastError).toHaveBeenCalledWith(
      expect.stringMatching(/Couldn't save your changes/i),
    );
    // Dialog still there.
    expect(screen.getByTestId("wizard-discard-confirm")).toBeInTheDocument();
    expect(h.onSaveExit).not.toHaveBeenCalled();
  });

  it("Discard changes → intent fires immediately, no flushSave", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-back"));
    await screen.findByTestId("wizard-discard-confirm");

    fireEvent.click(screen.getByTestId("wizard-discard-confirm-btn"));

    expect(h.onSaveExit).toHaveBeenCalledTimes(1);
    expect(h.flushSave).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull(),
    );
  });

  it("Discard clears the parent-owned dirty flag BEFORE firing the intent", async () => {
    const clearDirty = vi.fn();
    const dirtyRef = { current: true };
    const onSaveExit = vi.fn(() => {
      // Assert the parent-owned dirty getter reads clean AT the
      // moment the exit intent fires — guards against the double-
      // confirm bug where the parent's C1 backdrop guard would
      // pop its own confirm on the same click.
      expect(dirtyRef.current).toBe(false);
    });
    render(
      <PoolChecklistWizard
        jobId="job-w1" customerId="cust-w1" locked={false}
        report={_report({ wizard_step: 1 })}
        onChange={vi.fn()}
        onSaveExit={onSaveExit}
        onCloseJob={vi.fn()}
        submitting={false}
        isDirty={() => dirtyRef.current}
        flushSave={vi.fn()}
        clearDirty={() => { clearDirty(); dirtyRef.current = false; }}
      />,
    );
    fireEvent.click(screen.getByTestId("wizard-back"));
    await screen.findByTestId("wizard-discard-confirm");

    fireEvent.click(screen.getByTestId("wizard-discard-confirm-btn"));

    expect(clearDirty).toHaveBeenCalledTimes(1);
    expect(onSaveExit).toHaveBeenCalledTimes(1);
  });

  it("Discard on Close-job intent → onCloseJob fires (not onSaveExit)", async () => {
    const h = _mount({ report: { wizard_step: 6 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-close-job"));
    await screen.findByTestId("wizard-discard-confirm");

    fireEvent.click(screen.getByTestId("wizard-discard-confirm-btn"));
    expect(h.onCloseJob).toHaveBeenCalledTimes(1);
    expect(h.onSaveExit).not.toHaveBeenCalled();
    expect(h.flushSave).not.toHaveBeenCalled();
  });

  it("Keep editing → dismisses dialog, no intent fires", async () => {
    const h = _mount({ report: { wizard_step: 1 } });
    h.markDirty();
    fireEvent.click(screen.getByTestId("wizard-back"));
    await screen.findByTestId("wizard-discard-confirm");

    fireEvent.click(screen.getByTestId("wizard-discard-keep-editing"));
    await waitFor(() =>
      expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull(),
    );
    expect(h.onSaveExit).not.toHaveBeenCalled();
    expect(h.onCloseJob).not.toHaveBeenCalled();
    expect(h.flushSave).not.toHaveBeenCalled();
  });
});


// ─── (6) Pre-W1 compatibility (missing isDirty/flushSave) ─────────
describe("Phase W1 · backward compat when parent doesn't wire dirty props", () => {
  it("Back on step 1 without isDirty → falls back to onSaveExit (never opens confirm)", async () => {
    const onSaveExit = vi.fn();
    render(
      <PoolChecklistWizard
        jobId="job-w1" customerId="cust-w1" locked={false}
        report={_report({ wizard_step: 1 })}
        onChange={vi.fn()}
        onSaveExit={onSaveExit}
        onCloseJob={vi.fn()}
        submitting={false}
      />,
    );
    fireEvent.click(screen.getByTestId("wizard-back"));
    expect(onSaveExit).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });

  it("Close-job without isDirty → falls back to onCloseJob (never opens confirm)", async () => {
    const onCloseJob = vi.fn();
    render(
      <PoolChecklistWizard
        jobId="job-w1" customerId="cust-w1" locked={false}
        report={_report({ wizard_step: 6 })}
        onChange={vi.fn()}
        onSaveExit={vi.fn()}
        onCloseJob={onCloseJob}
        submitting={false}
      />,
    );
    fireEvent.click(screen.getByTestId("wizard-close-job"));
    expect(onCloseJob).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("wizard-discard-confirm")).toBeNull();
  });
});
