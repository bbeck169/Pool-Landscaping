/**
 * SO-A · Feb-2026 — Apply-Optimization wiring tests.
 *
 * Locks:
 *   1. Click "Apply Optimization" → POST /schedule/apply-recommendation
 *      with { job_id, technician_id, insertion_index, source_recommendation }.
 *   2. On status="applied" → success toast + onApplied invoked +
 *      panel signal usable to reload the schedule.
 *   3. On rejection → error toast fires + drawer stays mounted
 *      (no unmount).
 *   4. Queued path (apply_mode=queued_for_approval) POSTs the same
 *      endpoint but surfaces an INFO toast rather than success.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(), success: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { post: vi.fn(), put: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import { MarcoSuggestionsPanel } from
  "@/components/schedule/MarcoSuggestionsPanel";

const REC = {
  job_id: "job-x", target_date: "2026-02-16",
  apply_mode: "one_click",
  plain_english_source: "llm",
  provider_used: "google",
  rate_limit: { limit: 10, window_seconds: 60, remaining: 9 },
  suggestions: [
    { technician_id: "tech_top", technician_name: "David",
      insertion_index: 1, detour_minutes: 2.3, detour_miles: 0.8,
      rank: 1, provider_used: "google", route_len: 3,
      plain_english: "David…" },
  ],
  unavailable_technicians: [],
};

describe("SO-A · CalendarSchedule apply optimization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValueOnce(REC);
  });

  it("Apply Optimization POSTs /schedule/apply-recommendation", async () => {
    _apiMock.post
      .mockResolvedValueOnce({
        status: "applied", job_id: "job-x",
        technician_id: "tech_top", route_index: 1,
      });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("marco-suggestion-apply-1"));
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenLastCalledWith(
        "/schedule/apply-recommendation",
        expect.objectContaining({
          job_id: "job-x",
          technician_id: "tech_top",
          insertion_index: 1,
          source_recommendation: expect.objectContaining({
            detour_minutes: 2.3,
            rank: 1,
          }),
        }),
      ),
    );
  });

  it("Success → toast success + onApplied invoked", async () => {
    _apiMock.post.mockResolvedValueOnce({
      status: "applied", job_id: "job-x",
      technician_id: "tech_top", route_index: 1,
    });
    const onApplied = vi.fn();
    render(
      <MarcoSuggestionsPanel
        jobId="job-x" targetDate="2026-02-16"
        onApplied={onApplied}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("marco-suggestion-apply-1"));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringMatching(/Assigned to David\. Route updated/i),
      ),
    );
    expect(onApplied).toHaveBeenCalledWith(
      expect.objectContaining({ status: "applied" }),
    );
    // Drawer still mounted.
    expect(
      screen.getByTestId("marco-suggestions-panel"),
    ).toBeInTheDocument();
  });

  it("Failure → toast error + drawer stays mounted", async () => {
    _apiMock.post.mockRejectedValueOnce({
      status: 500,
      data: { detail: { message: "server exploded" } },
    });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("marco-suggestion-apply-1"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/Apply failed.*server exploded/i),
      ),
    );
    expect(
      screen.getByTestId("marco-suggestions-panel"),
    ).toBeInTheDocument();
  });

  it("Queued path surfaces info toast", async () => {
    // Overwrite the pre-set mock — we want the FIRST call (fetch)
    // to return a queued-mode recommendation.
    _apiMock.post.mockReset();
    _apiMock.post
      .mockResolvedValueOnce({
        ...REC, apply_mode: "queued_for_approval",
      })
      .mockResolvedValueOnce({
        status: "queued_for_approval",
        job_id: "job-x", technician_id: "tech_top",
        route_index: null, action_id: "act-1",
      });
    render(
      <MarcoSuggestionsPanel jobId="job-x" targetDate="2026-02-16" />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("marco-suggestion-apply-1"),
      ).toBeInTheDocument(),
    );
    // Button copy changes.
    expect(
      screen.getByTestId("marco-suggestion-apply-1").textContent,
    ).toMatch(/Suggest Reassignment/i);
    fireEvent.click(screen.getByTestId("marco-suggestion-apply-1"));
    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        expect.stringMatching(/queued for admin approval/i),
      ),
    );
  });
});
