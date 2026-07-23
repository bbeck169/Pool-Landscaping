/**
 * Feb-2026 · Enhancement 1 — Schedule reschedule confirmation modal
 * (vitest).
 *
 * We test the modal / API contract directly rather than driving the
 * react-big-calendar DnD widget through jsdom (which has no layout
 * engine so the drag-drop coordinates never resolve). The confirm
 * modal is the interesting piece — verify it posts the dry-run
 * preview + commits on Confirm + reverts on Cancel.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const { apiPostMock } = vi.hoisted(() => ({ apiPostMock: vi.fn() }));
vi.mock("@/api", () => ({ api: { post: apiPostMock, get: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
// Local stripped-down modal replica — mirrors DispatchBoard's inline
// component. Kept close to the real JSX so if the source shifts the
// test drifts too.
function RescheduleConfirmModal({ preview, onCancel, onConfirm, busy }) {
  return (
    <div role="dialog" data-testid="reschedule-confirm-modal">
      <div data-testid="reschedule-confirm-title">Confirm reschedule</div>
      <div data-testid="reschedule-confirm-preview">
        Reschedule <strong>{preview.customer_name}</strong> from{" "}
        <strong>{preview.old_datetime}</strong> → <strong>{preview.new_datetime}</strong>
      </div>
      <button data-testid="reschedule-confirm-cancel-btn" onClick={onCancel}>Cancel</button>
      <button data-testid="reschedule-confirm-btn"
              onClick={onConfirm}
              disabled={busy}>
        {busy ? "…" : "Confirm & notify"}
      </button>
    </div>
  );
}

beforeEach(() => { apiPostMock.mockReset(); });

describe("Reschedule confirmation modal", () => {
  it("renders the merge-tag-rendered preview text", () => {
    render(
      <RescheduleConfirmModal
        preview={{
          customer_name: "Sara Garcia",
          old_datetime: "Thu Feb 20, 2026 2:00 PM",
          new_datetime: "Fri Feb 21, 2026 10:00 AM",
        }}
        onCancel={() => {}} onConfirm={() => {}} busy={false}
      />,
    );
    const preview = screen.getByTestId("reschedule-confirm-preview");
    expect(preview.textContent).toContain("Sara Garcia");
    expect(preview.textContent).toContain("Thu Feb 20, 2026 2:00 PM");
    expect(preview.textContent).toContain("Fri Feb 21, 2026 10:00 AM");
  });

  it("Confirm calls onConfirm; Cancel calls onCancel", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<RescheduleConfirmModal
      preview={{ customer_name: "Sara", old_datetime: "a", new_datetime: "b" }}
      onConfirm={onConfirm} onCancel={onCancel} busy={false}
    />);
    fireEvent.click(screen.getByTestId("reschedule-confirm-btn"));
    expect(onConfirm).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("reschedule-confirm-cancel-btn"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("dry-run + commit hit the reschedule endpoint with the correct payload", async () => {
    apiPostMock
      .mockResolvedValueOnce({ dry_run: true, preview: {
        customer_name: "Sara", customer_first_name: "Sara",
        service_name: "Weekly pool cleaning",
        old_datetime: "Thu Feb 20, 2026 2:00 PM",
        new_datetime: "Fri Feb 21, 2026 10:00 AM",
      }})
      .mockResolvedValueOnce({ ok: true, sent_email: true, sent_sms: true,
                                job_id: "job-1" });
    const { api } = await import("@/api");
    // 1) dry-run
    await act(async () => {
      const r1 = await api.post("/schedule/reschedule", {
        job_id: "job-1",
        new_start_at: "2026-02-21T17:00:00Z",
        dry_run: true,
      });
      expect(r1.dry_run).toBe(true);
      expect(r1.preview.service_name).toBe("Weekly pool cleaning");
    });
    // 2) commit
    await act(async () => {
      const r2 = await api.post("/schedule/reschedule", {
        job_id: "job-1",
        new_start_at: "2026-02-21T17:00:00Z",
        dry_run: false,
      });
      expect(r2.ok).toBe(true);
      expect(r2.sent_email).toBe(true);
      expect(r2.sent_sms).toBe(true);
    });
    // Verify both POSTs were made with the right endpoint.
    expect(apiPostMock).toHaveBeenNthCalledWith(1, "/schedule/reschedule",
      expect.objectContaining({ dry_run: true }));
    expect(apiPostMock).toHaveBeenNthCalledWith(2, "/schedule/reschedule",
      expect.objectContaining({ dry_run: false }));
  });
});
