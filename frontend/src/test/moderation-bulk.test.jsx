import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _rows = [
  { id: "b1", tenant_id: "T", state: "pending_review",
    service_name: "A", photos: [], submitted_at: "2026-02-14T09:00:00Z",
    raw_address: { street: "1 Way", city: "Peoria", state: "AZ" } },
  { id: "b2", tenant_id: "T", state: "pending_review",
    service_name: "B", photos: [], submitted_at: "2026-02-14T09:01:00Z",
    raw_address: { street: "2 Oak", city: "Peoria", state: "AZ" } },
  { id: "b3", tenant_id: "T", state: "pending_review",
    service_name: "C", photos: [], submitted_at: "2026-02-14T09:02:00Z",
    raw_address: { street: "3 Elm", city: "Peoria", state: "AZ" } },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/admin/moderation/public-checkins?")) {
        return { items: _rows, total: _rows.length, limit: 200, offset: 0 };
      }
      if (path.startsWith("/admin/moderation/public-checkins/")) {
        return _rows[0];
      }
      return {};
    }),
    post: vi.fn(async () => ({ approved: 3, skipped: 0, results: [] })),
    patch: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import ModerationCheckinsPage from "@/pages/admin/ModerationCheckinsPage";
import { api } from "@/api";

describe("ModerationCheckinsPage · bulk", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("select-all toggles every row checkbox", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-b1");
    const cb1 = screen.getByTestId("moderation-select-b1");
    const cb2 = screen.getByTestId("moderation-select-b2");
    expect(cb1.checked).toBe(false);
    fireEvent.click(screen.getByTestId("moderation-select-all"));
    expect(cb1.checked).toBe(true);
    expect(cb2.checked).toBe(true);
    fireEvent.click(screen.getByTestId("moderation-select-all"));
    expect(cb1.checked).toBe(false);
  });

  it("bulk approve modal fires POST bulk-approve with selected ids", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-b1");
    fireEvent.click(screen.getByTestId("moderation-select-b1"));
    fireEvent.click(screen.getByTestId("moderation-select-b3"));
    fireEvent.click(screen.getByTestId("moderation-bulk-approve"));
    await waitFor(() => screen.getByTestId("moderation-bulk-modal"));
    fireEvent.click(screen.getByTestId("moderation-bulk-submit"));
    await waitFor(() => { expect(api.post).toHaveBeenCalled(); });
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/admin/moderation/public-checkins/bulk-approve");
    expect(body.ids).toEqual(["b1", "b3"]);
  });

  it("bulk reject modal disables submit until notes are typed", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-b2");
    fireEvent.click(screen.getByTestId("moderation-select-b2"));
    fireEvent.click(screen.getByTestId("moderation-bulk-reject"));
    await waitFor(() => screen.getByTestId("moderation-bulk-modal"));
    // Click without notes → no POST fires.
    fireEvent.click(screen.getByTestId("moderation-bulk-submit"));
    expect(api.post).not.toHaveBeenCalled();
    // Type notes and click again.
    fireEvent.change(screen.getByTestId("moderation-bulk-notes"),
                       { target: { value: "duplicate row" } });
    fireEvent.click(screen.getByTestId("moderation-bulk-submit"));
    await waitFor(() => { expect(api.post).toHaveBeenCalled(); });
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/admin/moderation/public-checkins/bulk-reject");
    expect(body.ids).toEqual(["b2"]);
    expect(body.reviewer_notes).toBe("duplicate row");
  });
});
