/**
 * Phase F3 · Feb-2026 — Soshie moderation queue frontend tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...a) => toastSuccess(...a),
           error:   (...a) => toastError(...a) },
}));

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock("../api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: vi.fn(), del: vi.fn(),
  },
}));

import SoshieModerationQueuePage from "@/pages/admin/SoshieModerationQueue";

const P1 = {
  id: "p1", platform: "facebook", status: "awaiting_review",
  scheduled_at: "2026-02-06T09:00:00Z",
  preview: "Beautiful pool ready for family fun",
  moderation_decision: "flag",
  moderation_reasons: ["aggressive_tone", "unusual_claim"],
  moderation_risk_level: "medium",
};
const P2 = {
  id: "p2", platform: "instagram", status: "awaiting_review",
  scheduled_at: "2026-02-06T10:00:00Z",
  preview: "Second flagged post",
  moderation_decision: "flag",
  moderation_reasons: ["low_confidence"],
};

beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset();
  toastSuccess.mockReset(); toastError.mockReset();
  mockGet.mockResolvedValue({ status: "awaiting_review", count: 2,
                                posts: [P1, P2] });
  mockPost.mockResolvedValue({ ok: true });
});

const renderPage = () =>
  render(<MemoryRouter><SoshieModerationQueuePage /></MemoryRouter>);

describe("SoshieModerationQueuePage", () => {
  it("renders the awaiting_review list from GET /soshie/moderation/queue",
     async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`soshie-moderation-row-${P1.id}`)).toBeTruthy(),
    );
    expect(screen.getByTestId(`soshie-moderation-row-${P2.id}`)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith(
      "/soshie/moderation/queue?status=awaiting_review",
    );
    // Reasons pills rendered.
    expect(screen.getAllByText("aggressive_tone")).toBeTruthy();
  });

  it("Approve calls POST + re-fetches", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`soshie-moderation-row-${P1.id}`)).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId(`soshie-moderation-approve-${P1.id}`));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        `/soshie/moderation/${P1.id}/approve`,
      ),
    );
    // list reloaded.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("Reject uses ArmToDelete and POSTs with a reason", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`soshie-moderation-row-${P1.id}`)).toBeTruthy(),
    );
    // ArmToDelete's testIdPrefix + "-btn" is the single-click button
    // when count < catastrophicThreshold.
    fireEvent.click(
      screen.getByTestId(`soshie-moderation-reject-${P1.id}-btn`),
    );
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        `/soshie/moderation/${P1.id}/reject`,
        expect.objectContaining({ reason: "admin_reject" }),
      ),
    );
  });

  it("switching tabs re-fetches with the new status", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`soshie-moderation-row-${P1.id}`)).toBeTruthy(),
    );
    mockGet.mockResolvedValueOnce({ status: "blocked", count: 0, posts: [] });
    fireEvent.click(screen.getByTestId("soshie-moderation-tab-blocked"));
    await waitFor(() =>
      expect(mockGet).toHaveBeenLastCalledWith(
        "/soshie/moderation/queue?status=blocked",
      ),
    );
  });
});
