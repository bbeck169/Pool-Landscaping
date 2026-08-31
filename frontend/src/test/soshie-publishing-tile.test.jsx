/**
 * Phase F3 · Feb-2026 — Soshie Publishing dashboard tile tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
vi.mock("../api", () => ({
  api: { get: (...a) => mockGet(...a), post: vi.fn(),
          put: vi.fn(), del: vi.fn() },
}));

import SoshiePublishingTile from "@/components/admin/SoshiePublishingTile";

beforeEach(() => {
  mockGet.mockReset();
});

const renderTile = () =>
  render(<MemoryRouter><SoshiePublishingTile /></MemoryRouter>);

describe("SoshiePublishingTile", () => {
  it("renders the 5 counts + next-up list from today-summary", async () => {
    mockGet.mockResolvedValue({
      tenant_id: "t", date: "2026-02-06",
      scheduled: 3, published: 1, flagged: 2, blocked: 1, failed: 0,
      next_up: [
        { post_id: "n1", platform: "facebook",
          scheduled_at: "2026-02-06T18:00:00Z", preview: "Post A preview" },
        { post_id: "n2", platform: "instagram",
          scheduled_at: "2026-02-06T19:00:00Z", preview: "Post B preview" },
      ],
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-publishing-tile-scheduled").textContent)
        .toMatch(/3/),
    );
    expect(screen.getByTestId("soshie-publishing-tile-published").textContent)
      .toMatch(/1/);
    expect(screen.getByTestId("soshie-publishing-tile-flagged").textContent)
      .toMatch(/2/);
    expect(screen.getByTestId("soshie-publishing-tile-blocked").textContent)
      .toMatch(/1/);
    expect(screen.getByTestId("soshie-publishing-tile-failed").textContent)
      .toMatch(/0/);
    // Attention pill because flagged+blocked > 0.
    expect(screen.getByTestId("soshie-publishing-tile-attention")).toBeTruthy();
    // next_up rows.
    expect(screen.getByTestId("soshie-publishing-tile-next-n1")).toBeTruthy();
    expect(screen.getByTestId("soshie-publishing-tile-next-n2")).toBeTruthy();
  });

  it("renders zero counts + no attention pill when nothing is queued",
     async () => {
    mockGet.mockResolvedValue({
      tenant_id: "t", date: "2026-02-06",
      scheduled: 0, published: 0, flagged: 0, blocked: 0, failed: 0,
      next_up: [],
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-publishing-tile-scheduled").textContent)
        .toMatch(/0/),
    );
    expect(screen.queryByTestId("soshie-publishing-tile-attention")).toBeNull();
    expect(screen.queryByTestId("soshie-publishing-tile-next")).toBeNull();
  });

  it("click-through link goes to /admin/soshie/moderation", async () => {
    mockGet.mockResolvedValue({
      scheduled: 0, published: 0, flagged: 0, blocked: 0, failed: 0,
      next_up: [],
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-publishing-tile-link")).toBeTruthy(),
    );
    const link = screen.getByTestId("soshie-publishing-tile-link");
    expect(link.getAttribute("href")).toBe("/admin/soshie/moderation");
  });

  it("shows an error banner when the summary API rejects", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-publishing-tile-error")).toBeTruthy(),
    );
  });

  it("refresh button re-invokes the summary API", async () => {
    mockGet.mockResolvedValue({
      scheduled: 1, published: 0, flagged: 0, blocked: 0, failed: 0,
      next_up: [],
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-publishing-tile-scheduled").textContent)
        .toMatch(/1/),
    );
    const before = mockGet.mock.calls.length;
    fireEvent.click(screen.getByTestId("soshie-publishing-tile-refresh"));
    await waitFor(() =>
      expect(mockGet.mock.calls.length).toBeGreaterThan(before),
    );
  });
});
