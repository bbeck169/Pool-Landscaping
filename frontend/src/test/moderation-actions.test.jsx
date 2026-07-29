import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _pending = {
  id: "p1", tenant_id: "T", state: "pending_review",
  service_name: "Weekly Pool", photos: [],
  submitted_at: "2026-02-14T09:00:00Z",
  raw_address: { street: "1234 Main St", city: "Peoria", state: "AZ" },
};
const _approved = {
  ..._pending, id: "p3", state: "approved",
  approved_at: "2026-02-14T10:00:00Z",
  masked_address: { street_name: "Main St", city: "Peoria", state: "AZ" },
};

let _mode = "pending";  // "pending" | "approved"

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      const rows = _mode === "approved" ? [_approved] : [_pending];
      if (path.startsWith("/admin/moderation/public-checkins?")) {
        return { items: rows, total: rows.length, limit: 200, offset: 0 };
      }
      if (path.startsWith("/admin/moderation/public-checkins/")) {
        return rows[0];
      }
      return {};
    }),
    post: vi.fn(async () => _approved),
    patch: vi.fn(async () => _pending),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import ModerationCheckinsPage from "@/pages/admin/ModerationCheckinsPage";
import { api } from "@/api";

describe("ModerationCheckinsPage · actions", () => {
  beforeEach(() => {
    _mode = "pending";
    vi.clearAllMocks();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("approve button POSTs to the correct approve endpoint", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-p1");
    fireEvent.click(await screen.findByTestId("moderation-btn-approve"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalled();
    });
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/admin/moderation/public-checkins/p1/approve");
    expect(body).toEqual({ reviewer_notes: null });
  });

  it("reject button is disabled until notes are typed", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-p1");
    const rejectBtn = await screen.findByTestId("moderation-btn-reject");
    // disabled reflects via style opacity (0.6) — hard to inspect directly.
    // Click without notes triggers a toast.error and skips POST.
    fireEvent.click(rejectBtn);
    expect(api.post).not.toHaveBeenCalled();

    // Type notes and click reject.
    fireEvent.change(screen.getByTestId("moderation-reject-notes"),
                       { target: { value: "Not on brand" } });
    fireEvent.click(screen.getByTestId("moderation-btn-reject"));
    await waitFor(() => { expect(api.post).toHaveBeenCalled(); });
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/admin/moderation/public-checkins/p1/reject");
    expect(body).toEqual({ reviewer_notes: "Not on brand" });
  });

  it("unpublish only appears when state=approved", async () => {
    // Pending: no unpublish button.
    const { unmount } = render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-p1");
    await waitFor(() => screen.getByTestId("moderation-detail-p1"));
    expect(screen.queryByTestId("moderation-btn-unpublish")).toBeNull();
    unmount();

    // Approved: unpublish button IS present.
    _mode = "approved";
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-p3");
    fireEvent.change(screen.getByTestId("moderation-state-filter"),
                       { target: { value: "approved" } });
    await waitFor(() => screen.getByTestId("moderation-btn-unpublish"));
  });
});
