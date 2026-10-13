/**
 * Feb-2026 · MergeHistoryPanel vitest.
 * 5 cases per dispatch spec: panel render, rollback button
 * visibility rules, rollback flow (confirm → POST →
 * success toast + refetch).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";

// Mock the shared api facade so each test controls the HTTP
// surface explicitly.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "@/api";
import { MergeHistoryPanel }
  from "@/components/customers/MergeHistoryPanel";


const _entryWinner = {
  audit_id: "a1", role: "winner",
  counterpart_customer_id: "c-loser",
  counterpart_customer_name: "Jane Loser",
  merged_at: "2026-02-05T10:00:00Z",
  expires_at: "2026-05-06T10:00:00Z",
  rolled_back_at: null,
  rolled_back_by: null,
  actor_id: "admin1",
  remaining_rollback_days: 85,
  child_record_counts: { jobs: 2 },
  credit_merged_cents: 500,
};
const _entryRolledBack = {
  ..._entryWinner,
  audit_id: "a2",
  rolled_back_at: "2026-02-06T12:00:00Z",
  rolled_back_by: "admin1",
  remaining_rollback_days: 0,
};
const _entryExpired = {
  ..._entryWinner,
  audit_id: "a3",
  rolled_back_at: null,
  remaining_rollback_days: 0,
};


beforeEach(() => {
  vi.clearAllMocks();
});


describe("Feb-2026 · MergeHistoryPanel", () => {
  it("1 · toggle open fetches + lists merge entries", async () => {
    api.get.mockResolvedValueOnce({
      entries: [_entryWinner],
      summary: { count: 1 },
    });
    render(<MergeHistoryPanel customerId="c1" canRollback />);
    // Collapsed by default.
    expect(screen.queryByTestId("merge-history-table")).toBeNull();
    fireEvent.click(screen.getByTestId("merge-history-panel-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-table")).toBeTruthy(),
    );
    expect(api.get).toHaveBeenCalledWith(
      "/customers/c1/merge-history",
    );
    expect(screen.getByTestId("merge-history-row-a1")).toBeTruthy();
  });

  it("2 · rollback button hidden when canRollback=false", async () => {
    api.get.mockResolvedValueOnce({ entries: [_entryWinner] });
    render(<MergeHistoryPanel customerId="c1" canRollback={false} />);
    fireEvent.click(screen.getByTestId("merge-history-panel-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-row-a1")).toBeTruthy(),
    );
    expect(screen.queryByTestId("merge-history-rollback-btn-a1"))
      .toBeNull();
  });

  it("3 · rollback button hidden for expired / rolled-back rows "
      + "even for admins", async () => {
    api.get.mockResolvedValueOnce({
      entries: [_entryRolledBack, _entryExpired],
    });
    render(<MergeHistoryPanel customerId="c1" canRollback />);
    fireEvent.click(screen.getByTestId("merge-history-panel-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-row-a2")).toBeTruthy(),
    );
    // Rolled-back row shows the rolled-back pill, no rollback btn.
    expect(screen.getByTestId("merge-history-rolled-back-a2")).toBeTruthy();
    expect(screen.queryByTestId("merge-history-rollback-btn-a2"))
      .toBeNull();
    // Expired row shows Expired badge, no rollback btn.
    expect(screen.getByTestId("merge-history-expired-a3")).toBeTruthy();
    expect(screen.queryByTestId("merge-history-rollback-btn-a3"))
      .toBeNull();
  });

  it("4 · rollback happy path POSTs + toast + refetches", async () => {
    api.get
      .mockResolvedValueOnce({ entries: [_entryWinner] })  // open
      .mockResolvedValueOnce({ entries: [                   // refetch
        { ..._entryWinner,
          rolled_back_at: "2026-02-06T12:00:00Z",
          rolled_back_by: "admin1",
          remaining_rollback_days: 0 },
      ]});
    api.post.mockResolvedValueOnce({
      audit_id: "a1", winner_id: "w", loser_id: "l",
      rolled_back_at: "2026-02-06T12:00:00Z",
    });
    render(<MergeHistoryPanel customerId="c1" canRollback />);
    fireEvent.click(screen.getByTestId("merge-history-panel-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-rollback-btn-a1"))
        .toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("merge-history-rollback-btn-a1"));
    // Confirm modal mounted.
    expect(screen.getByTestId("merge-history-rollback-modal")).toBeTruthy();
    fireEvent.click(
      screen.getByTestId("merge-history-rollback-confirm-btn"),
    );
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/customer-merges/a1/rollback", { confirm: true },
      ),
    );
    // Toast + refetched row flips to rolled-back visual.
    await waitFor(() =>
      expect(screen.queryByTestId("merge-history-rolled-back-a1"))
        .toBeTruthy(),
    );
    expect(screen.getByTestId("merge-history-toast").textContent)
      .toContain("Jane Loser");
  });

  it("5 · rollback error surfaces inline in confirm modal", async () => {
    api.get.mockResolvedValueOnce({ entries: [_entryWinner] });
    api.post.mockRejectedValueOnce({
      status: 409,
      data: { detail: {
        error_code: "merge_rollback_already_done",
        message: "This merge has already been rolled back.",
      }},
    });
    render(<MergeHistoryPanel customerId="c1" canRollback />);
    fireEvent.click(screen.getByTestId("merge-history-panel-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-rollback-btn-a1"))
        .toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("merge-history-rollback-btn-a1"));
    fireEvent.click(
      screen.getByTestId("merge-history-rollback-confirm-btn"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("merge-history-rollback-error"))
        .toBeTruthy(),
    );
    expect(screen.getByTestId("merge-history-rollback-error")
      .textContent).toContain("already been rolled back");
    // Modal stays open so operator can see the error + cancel.
    expect(screen.getByTestId("merge-history-rollback-modal"))
      .toBeTruthy();
  });
});
