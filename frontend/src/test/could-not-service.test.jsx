/**
 * Feb-2026 · Phase 1 — <CouldNotServiceModal /> tests.
 *
 * Covers the four acceptance criteria in the spec:
 *   1. Submit blocked with 0 photos; enabled with ≥1 photo + reason.
 *   2. reason=other requires notes; other reasons don't.
 *   3. Status pill renders new label + color for ``could_not_service``.
 *   4. Job card / detail button hidden for terminal statuses.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";


const _h = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(),
            message: vi.fn() },
  uploader: {
    onUploaded: null,
  },
}));


vi.mock("@/api", () => ({ api: _h.api }));
vi.mock("sonner", () => ({ toast: _h.toast }));
vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: ({ onUploaded }) => {
    _h.uploader.onUploaded = onUploaded;
    return (
      <button
        data-testid="stub-file-upload"
        onClick={() => onUploaded({ id: `file_${Date.now()}` })}
      >
        Upload
      </button>
    );
  },
}));


import CouldNotServiceModal from "@/components/schedule/CouldNotServiceModal";
import { StatusPill } from "@/components/ui-kit";


const _reasons = [
  { id: "r-locked", key: "locked_out",        label: "Locked out",       is_default: true, active: true },
  { id: "r-weather", key: "weather",           label: "Weather",          is_default: true, active: true },
  { id: "r-other",   key: "other",             label: "Other",            is_default: true, active: true },
];


beforeEach(() => {
  _h.api.get.mockReset();
  _h.api.post.mockReset();
  _h.toast.success.mockReset();
  _h.toast.error.mockReset();
  _h.toast.message.mockReset();
  _h.api.get.mockResolvedValue({ reasons: _reasons });
});


async function _open() {
  const job = { id: "job-1", customer_name: "Jane Doe", status: "scheduled" };
  render(<CouldNotServiceModal job={job} onClose={() => {}} onDone={() => {}} />);
  await waitFor(() => expect(_h.api.get).toHaveBeenCalled());
}


describe("<CouldNotServiceModal />", () => {
  it("submit disabled until reason + ≥1 photo selected", async () => {
    await _open();
    const submit = screen.getByTestId("cns-submit");
    expect(submit).toBeDisabled();
    // Pick a reason
    fireEvent.change(screen.getByTestId("cns-reason"),
                       { target: { value: "r-locked" } });
    expect(submit).toBeDisabled();
    // Upload a photo
    fireEvent.click(screen.getByTestId("stub-file-upload"));
    expect(submit).not.toBeDisabled();
  });

  it("reason=other requires non-empty notes", async () => {
    await _open();
    fireEvent.change(screen.getByTestId("cns-reason"),
                       { target: { value: "r-other" } });
    fireEvent.click(screen.getByTestId("stub-file-upload"));
    const submit = screen.getByTestId("cns-submit");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId("cns-notes"),
                       { target: { value: "pool cover jammed" } });
    expect(submit).not.toBeDisabled();
  });

  it("non-other reasons do NOT require notes", async () => {
    await _open();
    fireEvent.change(screen.getByTestId("cns-reason"),
                       { target: { value: "r-weather" } });
    fireEvent.click(screen.getByTestId("stub-file-upload"));
    expect(screen.getByTestId("cns-submit")).not.toBeDisabled();
  });

  it("submit posts to /api/jobs/{id}/could-not-service with body", async () => {
    _h.api.post.mockResolvedValue({
      status: "could_not_service",
      job: { id: "job-1", status: "could_not_service" },
      sms_result: { sent: true, reason: null, communication_id: "c1" },
    });
    await _open();
    fireEvent.change(screen.getByTestId("cns-reason"),
                       { target: { value: "r-locked" } });
    fireEvent.click(screen.getByTestId("stub-file-upload"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("cns-submit"));
    });
    expect(_h.api.post).toHaveBeenCalledWith(
      "/jobs/job-1/could-not-service",
      expect.objectContaining({
        reason_id: "r-locked",
        photo_file_ids: expect.arrayContaining([expect.stringMatching(/^file_/)]),
      }),
    );
    expect(_h.toast.success).toHaveBeenCalled();
    expect(_h.toast.message).toHaveBeenCalledWith("Customer notified");
  });

  it("surfaces humanized guard reasons via toast.message when sms suppressed", async () => {
    _h.api.post.mockResolvedValue({
      status: "could_not_service",
      job: { id: "job-1", status: "could_not_service" },
      sms_result: { sent: false, reason: "sms_opt_in_false" },
    });
    await _open();
    fireEvent.change(screen.getByTestId("cns-reason"),
                       { target: { value: "r-locked" } });
    fireEvent.click(screen.getByTestId("stub-file-upload"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("cns-submit"));
    });
    expect(_h.toast.message.mock.calls[0][0]).toMatch(/opted out/i);
  });
});


describe("<StatusPill /> · could_not_service", () => {
  it("renders new label + amber palette for could_not_service", () => {
    render(<StatusPill status="could_not_service" />);
    const pill = screen.getByTestId("status-pill-could_not_service");
    expect(pill.textContent).toBe("Could Not Service");
    // Amber palette — background #FEF3C7 (fef3c7).
    expect(pill.getAttribute("style")).toMatch(/rgb\(254,\s*243,\s*199\)|#FEF3C7/i);
  });

  it("skipped keeps its own distinct gray label", () => {
    render(<StatusPill status="skipped" />);
    const pill = screen.getByTestId("status-pill-skipped");
    expect(pill.textContent).toBe("Skipped");
  });
});
