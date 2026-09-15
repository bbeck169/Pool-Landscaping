/**
 * Phase C1 · Feb-2026 — ChecklistModal safe-close guard tests.
 *
 * Pins the four implicit-close triggers (backdrop tap, header "×",
 * Escape key) + the explicit Discard / Keep-editing buttons on the
 * confirm dialog:
 *
 *   1. CLEAN form → all three implicit triggers close silently.
 *   2. DIRTY form → all three implicit triggers open the Discard
 *      confirm and do NOT call ``onClose``.
 *   3. "Keep editing" dismisses the confirm; ``onClose`` NEVER
 *      fires until "Discard" is clicked.
 *
 * Dirty state is produced by clicking the modal's own "Save draft"
 * button (which sets ``dirtyRef.current = true`` before awaiting
 * ``flushSave``).  We reject the patch so ``dirtyRef.current``
 * stays true after the button click (successful flushSave would
 * flip it back to false — see ChecklistModal.jsx:200).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

const _mockGet = vi.fn();
const _mockPatch = vi.fn();
const _mockPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:   (...a) => _mockGet(...a),
    patch: (...a) => _mockPatch(...a),
    post:  (...a) => _mockPost(...a),
    put:   vi.fn(),
    del:   vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", name: "Boss", email: "b@t" } }),
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    warning: vi.fn(), info: vi.fn(),
  }),
}));
// Heavy children — stub to null so the shell paints quickly.
vi.mock("@/components/checklist/PoolChecklistForm", () => ({
  default: () => <div data-testid="pool-form-stub" />,
}));
vi.mock("@/components/checklist/LandscapeChecklistForm", () => ({
  default: () => <div data-testid="landscape-form-stub" />,
}));
vi.mock("@/components/checklist/PoolChecklistWizard", () => ({
  default: () => <div data-testid="pool-wizard-stub" />,
}));
vi.mock("@/components/customers/CustomerRecapDialog", () => ({
  default: () => null,
}));

// eslint-disable-next-line import/first
import ChecklistModal from "@/components/checklist/ChecklistModal";


function _wireGet() {
  _mockGet.mockImplementation((path) => {
    if (path.startsWith("/jobs/") && !path.endsWith("/service-report")) {
      // Use landscape service type — the pool wizard suppresses the
      // legacy modal footer (no "Save draft" button), while the
      // landscape template renders the classic footer with the
      // ``checklist-save-draft`` button we use to trigger dirtiness.
      return Promise.resolve({
        id: "job-c1", customer_id: "cust-c1",
        customer_name: "C1 Cust", service_type: "Landscape maintenance",
        title: "C1 test", status: "in-progress",
      });
    }
    if (path.endsWith("/service-report")) {
      return Promise.resolve({
        id: "sr-c1", job_id: "job-c1", template: "landscape",
        chemical_readings: [], chemicals_added: [], photos: [],
        notes: "", checklist_items: [], water_bodies: [],
      });
    }
    return Promise.resolve({});
  });
}


async function _drain(ms = 40) {
  await act(async () => {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await new Promise((r) => setTimeout(r, ms));
  });
}


async function _makeDirty() {
  // Save-draft flips ``dirtyRef=true`` then awaits ``flushSave``.
  // We queue a rejecting patch so flushSave errors and dirtyRef
  // stays true (successful flushSave would flip it back to false —
  // see ChecklistModal.jsx:200).
  _mockPatch.mockRejectedValueOnce(new Error("simulated"));
  await act(async () => {
    fireEvent.click(screen.getByTestId("checklist-save-draft"));
    await Promise.resolve();
  });
  await _drain(60);
}


beforeEach(() => {
  _mockGet.mockReset(); _mockPatch.mockReset(); _mockPost.mockReset();
  _wireGet();
});


describe("Phase C1 · ChecklistModal — CLEAN path", () => {
  it("backdrop tap closes immediately", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    expect(screen.getByTestId("checklist-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("checklist-modal-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("checklist-discard-confirm")).toBeNull();
  });

  it("Esc closes immediately", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("checklist-discard-confirm")).toBeNull();
  });

  it("× button closes immediately", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    fireEvent.click(screen.getByTestId("checklist-modal-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("checklist-discard-confirm")).toBeNull();
  });
});


describe("Phase C1 · ChecklistModal — DIRTY path", () => {
  it("backdrop tap on a dirty form OPENS the Discard confirm and does NOT call onClose", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    await _makeDirty();

    fireEvent.click(screen.getByTestId("checklist-modal-backdrop"));
    expect(await screen.findByTestId("checklist-discard-confirm")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Esc on a dirty form OPENS the Discard confirm", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    await _makeDirty();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(await screen.findByTestId("checklist-discard-confirm")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("× button on a dirty form OPENS the Discard confirm", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    await _makeDirty();

    fireEvent.click(screen.getByTestId("checklist-modal-close"));
    expect(await screen.findByTestId("checklist-discard-confirm")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Keep editing dismisses the confirm but does NOT close the modal", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    await _makeDirty();

    fireEvent.click(screen.getByTestId("checklist-modal-backdrop"));
    await screen.findByTestId("checklist-discard-confirm");
    fireEvent.click(screen.getByTestId("checklist-discard-keep-editing"));

    await waitFor(() =>
      expect(screen.queryByTestId("checklist-discard-confirm")).toBeNull(),
    );
    expect(onClose).not.toHaveBeenCalled();
    // Modal is still there.
    expect(screen.getByTestId("checklist-modal")).toBeInTheDocument();
  });

  it("Discard button dismisses the confirm AND calls onClose", async () => {
    const onClose = vi.fn();
    render(<ChecklistModal jobId="job-c1" open onClose={onClose} />);
    await _drain();
    await _makeDirty();

    fireEvent.click(screen.getByTestId("checklist-modal-backdrop"));
    await screen.findByTestId("checklist-discard-confirm");
    fireEvent.click(screen.getByTestId("checklist-discard-confirm-btn"));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
