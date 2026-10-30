/**
 * Feb-2026 · Quiet Hours Phase-2 UX — QuietHoursQueueSection vitests.
 *
 * Pins the 5 cases locked in the operator dispatch for Commit C:
 *   1. Queue section renders count + next-release-time summary
 *   2. Empty state when count = 0
 *   3. Row Cancel button fires DELETE and refetches
 *   4. "Release all now" button opens confirm → POST + refetch
 *   5. Error state when the queue GET fails
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";


const mockGet = vi.fn();
const mockDel = vi.fn();
const mockPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    delete: (...a) => mockDel(...a),
    post: (...a) => mockPost(...a),
    // ``patch`` is referenced by the sibling settings component
    // but never fires in these tests.
    patch: vi.fn(),
  },
}));

import { QuietHoursQueueSection } from "@/pages/settings/QuietHoursPage";


function _mkRow(i, over = {}) {
  return {
    id: `qh-${i}`,
    channel: i % 2 === 0 ? "email" : "sms",
    recipient: i % 2 === 0 ? `t${i}@example.com` : `+1555000${i}`,
    scheduled_release_at: "2026-03-15T15:00:00+00:00",
    deferred_at: "2026-02-15T08:00:00+00:00",
    subject: i % 2 === 0 ? `Subject ${i}` : null,
    ...over,
  };
}


function _mkQueue(n, over = {}) {
  return {
    count: n,
    next_release_at: n ? "2026-03-15T15:00:00+00:00" : null,
    items: Array.from({ length: n }).map((_, i) => _mkRow(i + 1)),
    ...over,
  };
}


beforeEach(() => {
  mockGet.mockReset();
  mockDel.mockReset();
  mockPost.mockReset();
});


describe("QuietHoursQueueSection", () => {
  it("1. renders count + next-release-time summary", async () => {
    mockGet.mockResolvedValueOnce(_mkQueue(3));
    render(<QuietHoursQueueSection />);
    await waitFor(() => {
      expect(
        screen.getByTestId("quiet-hours-queue-summary"),
      ).toBeTruthy();
    });
    const txt = screen.getByTestId(
      "quiet-hours-queue-summary",
    ).textContent;
    expect(txt).toContain("3 pending");
    expect(txt).toContain("next release");
    expect(screen.getByTestId("quiet-hours-queue-row-qh-1")).toBeTruthy();
    expect(screen.getByTestId("quiet-hours-queue-row-qh-2")).toBeTruthy();
    expect(screen.getByTestId("quiet-hours-queue-row-qh-3")).toBeTruthy();
  });

  it("2. renders empty state when count = 0", async () => {
    mockGet.mockResolvedValueOnce(_mkQueue(0));
    render(<QuietHoursQueueSection />);
    await waitFor(() => {
      expect(screen.getByTestId("quiet-hours-queue-empty")).toBeTruthy();
    });
    expect(
      screen.queryByTestId("quiet-hours-queue-summary"),
    ).toBeNull();
    // Release-now button hides when queue is empty.
    expect(
      screen.queryByTestId("quiet-hours-release-now-btn"),
    ).toBeNull();
  });

  it("3. row Cancel fires DELETE and refetches", async () => {
    mockGet
      .mockResolvedValueOnce(_mkQueue(2))
      .mockResolvedValueOnce(_mkQueue(1, {
        items: [_mkRow(1)],
      }));
    mockDel.mockResolvedValueOnce({ deleted: true, row_id: "qh-2" });

    render(<QuietHoursQueueSection />);
    await waitFor(() => {
      expect(
        screen.getByTestId("quiet-hours-queue-row-qh-2"),
      ).toBeTruthy();
    });
    fireEvent.click(
      screen.getByTestId("quiet-hours-queue-cancel-qh-2"),
    );
    await waitFor(() => {
      expect(mockDel).toHaveBeenCalledWith("/quiet-hours/queue/qh-2");
    });
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(2);
    });
    expect(mockGet.mock.calls[1][0]).toBe("/quiet-hours/queue");
  });

  it("4. Release-all-now opens confirm → POST + refetch", async () => {
    mockGet
      .mockResolvedValueOnce(_mkQueue(2))
      .mockResolvedValueOnce(_mkQueue(0));
    mockPost.mockResolvedValueOnce({ released_count: 2, errors: [] });

    render(<QuietHoursQueueSection />);
    await waitFor(() => {
      expect(
        screen.getByTestId("quiet-hours-release-now-btn"),
      ).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("quiet-hours-release-now-btn"));
    expect(
      screen.getByTestId("quiet-hours-release-now-confirm"),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByTestId("quiet-hours-release-now-confirm-btn"),
    );
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/quiet-hours/queue/release-now",
        {},
      );
    });
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(2);
    });
    // Confirm panel closes after a successful flush.
    expect(
      screen.queryByTestId("quiet-hours-release-now-confirm"),
    ).toBeNull();
  });

  it("5. error state when the queue GET fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("boom"));
    render(<QuietHoursQueueSection />);
    await waitFor(() => {
      expect(
        screen.getByTestId("quiet-hours-queue-error"),
      ).toBeTruthy();
    });
    expect(
      screen.getByTestId("quiet-hours-queue-error").textContent,
    ).toContain("boom");
  });
});
