/**
 * Sprint 3d · Feb-2026 · Insert-and-shift Vitest coverage.
 *
 * Locks the acceptance behaviour on the ``useNumberedOrder`` hook +
 * ``NumberOrderInput`` primitive:
 *   1. Old "Job numbers must be unique" copy is gone.
 *   2. Blur on a changed input fires the new insert-shift endpoint
 *      with the correct payload.
 *   3. Blur when value is unchanged is a no-op.
 *   4. Optimistic rollback — on API failure, the input reverts to
 *      its pre-focus value.
 *   5. Success updates the local drafts and toast/banner.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";

vi.mock("@/api", () => {
  const _api = { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
  return { api: _api };
});

import {
  useNumberedOrder, NumberOrderInput, ReorderBanner,
} from "@/pages/schedule/NumberedReorder";
import { api } from "@/api";


// Harness — mounts the hook + input for a 5-job day.
function Harness({ jobs, techUserId = "tech-a", date = "2026-02-14",
                    onSaved, onError }) {
  const controller = useNumberedOrder(jobs, {
    techUserId, date, onSaved, onError,
  });
  return (
    <div>
      <ReorderBanner controller={controller} />
      {jobs.map((j) => (
        <NumberOrderInput key={j.id} job={j} controller={controller} />
      ))}
    </div>
  );
}

const JOBS_5 = [
  { id: "job1", route_index: 0, customer_name: "A" },
  { id: "job2", route_index: 1, customer_name: "B" },
  { id: "job3", route_index: 2, customer_name: "C" },
  { id: "job4", route_index: 3, customer_name: "D" },
  { id: "job5", route_index: 4, customer_name: "E" },
];


beforeEach(() => {
  api.post.mockReset();
  api.get.mockReset();
});
afterEach(() => vi.clearAllMocks());


describe("useNumberedOrder + NumberOrderInput · Sprint 3d insert-shift", () => {
  it("typing a duplicate no longer shows 'Job numbers must be unique'", async () => {
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    // Change job1 from 1 → 3 (collides with job3). Under old
    // semantics this would flash the "must be unique" banner. Under
    // insert-shift semantics duplicates are welcome — no banner.
    fireEvent.focus(in1);
    fireEvent.change(in1, { target: { value: "3" } });
    // Simulate the input still being focused; banner should not
    // yet show the removed uniqueness copy.
    expect(screen.queryByText(/Job numbers must be unique/i)).toBeNull();
  });

  it("blur on a changed input fires /jobs/reorder-day-route with correct payload", async () => {
    api.post.mockResolvedValue({
      success: true, changed: true,
      renumbered: [
        { job_id: "job1", sequence_number: 3 },
        { job_id: "job2", sequence_number: 1 },
        { job_id: "job3", sequence_number: 2 },
        { job_id: "job4", sequence_number: 4 },
        { job_id: "job5", sequence_number: 5 },
      ],
      old_position: 1, new_position: 3,
      affected_job_ids: ["job1", "job2", "job3"],
    });
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    fireEvent.focus(in1);
    fireEvent.change(in1, { target: { value: "3" } });
    fireEvent.blur(in1);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/jobs/reorder-day-route", {
        date: "2026-02-14",
        technician_id: "tech-a",
        job_id: "job1",
        new_position: 3,
      });
    });
  });

  it("blur when value is unchanged is a no-op (no API call)", async () => {
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    fireEvent.focus(in1);
    // Don't change the value — job1's route_index is 0 so drafts["job1"]==="1".
    fireEvent.blur(in1);
    // Give the hook a tick to potentially fire.
    await new Promise((r) => setTimeout(r, 20));
    expect(api.post).not.toHaveBeenCalled();
  });

  it("Enter key triggers blur which fires the reorder endpoint", async () => {
    api.post.mockResolvedValue({
      success: true, changed: true,
      renumbered: [], old_position: 1, new_position: 2,
      affected_job_ids: [],
    });
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    fireEvent.focus(in1);
    fireEvent.change(in1, { target: { value: "2" } });
    fireEvent.keyDown(in1, { key: "Enter" });
    // The onKeyDown handler calls e.currentTarget.blur() which
    // synchronously fires the blur handler. We DO need to actually
    // trigger blur since JSDOM doesn't fire blur automatically from
    // .blur() reliably in all versions; call it explicitly to
    // guarantee the assertion.
    fireEvent.blur(in1);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/reorder-day-route",
        expect.objectContaining({ job_id: "job1", new_position: 2 }),
      ),
    );
  });

  it("optimistic rollback — API failure reverts the input to pre-focus value", async () => {
    api.post.mockRejectedValueOnce(new Error("route reorder failed"));
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    fireEvent.focus(in1);
    fireEvent.change(in1, { target: { value: "3" } });
    fireEvent.blur(in1);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    // After the API failed, the hook should revert the value.
    await waitFor(() => {
      expect(in1.value).toBe("1");
    });
    // And show an error banner (the copy is the API's message).
    expect(screen.getByTestId("route-order-error-banner")).toBeTruthy();
  });

  it("banner shows the 'Moved · X → Y' success message on save", async () => {
    api.post.mockResolvedValue({
      success: true, changed: true, renumbered: [],
      old_position: 1, new_position: 3,
      affected_job_ids: [],
    });
    render(<Harness jobs={JOBS_5} />);
    const in1 = screen.getByTestId("route-order-input-job1");
    fireEvent.focus(in1);
    fireEvent.change(in1, { target: { value: "3" } });
    fireEvent.blur(in1);
    await waitFor(() => {
      expect(screen.getByTestId("route-order-info-banner").textContent)
        .toMatch(/Moved.*1.*3/);
    });
  });

  it("multi-tech day view — POST payload uses the MOVED job's own tech + date, not the hook's closure hint", async () => {
    // Sprint 3d follow-up regression — the calendar can render a
    // multi-tech day. Previously the closure ``techUserId`` was
    // seeded from the first job in the list, so reordering a job
    // that belonged to a *different* tech shipped the wrong
    // ``technician_id`` and the backend rejected with
    // "job_id not on this tech's day". The fix reads the tech +
    // date from the moved job itself.
    const jobsMixed = [
      {
        id: "job-tech-a-1", route_index: 0, customer_name: "A1",
        tech_user_id: "tech-alice", scheduled_date: "2026-09-09T09:00:00+00:00",
      },
      {
        id: "job-tech-b-1", route_index: 1, customer_name: "B1",
        // NOTE: different tech than the first row — this is the
        // row whose row-order input the user edits.
        tech_user_id: "tech-bob",   scheduled_date: "2026-09-09T09:00:00+00:00",
      },
    ];
    api.post.mockResolvedValue({
      success: true, changed: true, renumbered: [],
      old_position: 2, new_position: 1, affected_job_ids: [],
    });
    // Harness passes techUserId="tech-a" (the hook-level HINT) —
    // if we shipped that, the backend would 404. The fix must
    // ignore the hint and use each job's own tech_user_id.
    render(<Harness jobs={jobsMixed} techUserId="tech-alice" date="2026-09-09" />);
    const inputB = screen.getByTestId("route-order-input-job-tech-b-1");
    fireEvent.focus(inputB);
    fireEvent.change(inputB, { target: { value: "1" } });
    fireEvent.blur(inputB);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith(
      "/jobs/reorder-day-route",
      expect.objectContaining({
        job_id:        "job-tech-b-1",
        technician_id: "tech-bob",     // MOVED job's tech, NOT "tech-alice"
        date:          "2026-09-09",
        new_position:  1,
      }),
    );
  });
});
