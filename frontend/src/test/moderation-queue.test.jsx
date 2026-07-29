import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _rows = [
  { id: "p1", tenant_id: "T", state: "pending_review",
    service_name: "Weekly Pool", photos: [{ id: "ph1", url: "https://x/p.jpg" }],
    submitted_at: "2026-02-14T09:00:00Z",
    raw_address: { street: "1234 Main St", city: "Peoria", state: "AZ" } },
  { id: "p2", tenant_id: "T", state: "pending_review",
    service_name: "Chem Check", photos: [],
    submitted_at: "2026-02-14T08:00:00Z",
    raw_address: { street: "5 Oak Ave", city: "Peoria", state: "AZ" } },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/admin/moderation/public-checkins?")) {
        const url = new URL("http://x" + path);
        const state = url.searchParams.get("state");
        const items = state === "approved" ? [] :
                        state === "all" ? _rows : _rows;
        return { items, total: items.length, limit: 200, offset: 0 };
      }
      if (path.startsWith("/admin/moderation/public-checkins/")) {
        const id = path.split("/").pop();
        return _rows.find((r) => r.id === id) || null;
      }
      return {};
    }),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import ModerationCheckinsPage from "@/pages/admin/ModerationCheckinsPage";

describe("ModerationCheckinsPage · list + state filter", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renders the page shell", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    expect(screen.getByTestId("moderation-checkins-page")).toBeTruthy();
    expect(screen.getByTestId("moderation-checkins-title")).toBeTruthy();
  });

  it("loads pending_review by default and shows both rows", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    expect(await screen.findByTestId("moderation-item-p1")).toBeTruthy();
    expect(screen.getByTestId("moderation-item-p2")).toBeTruthy();
  });

  it("switches to approved and shows empty state", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    await screen.findByTestId("moderation-item-p1");
    fireEvent.change(screen.getByTestId("moderation-state-filter"),
                       { target: { value: "approved" } });
    expect(await screen.findByTestId("moderation-empty")).toBeTruthy();
  });

  it("selects a row on click and loads the detail panel", async () => {
    render(<MemoryRouter><ModerationCheckinsPage /></MemoryRouter>);
    const item = await screen.findByTestId("moderation-item-p2");
    fireEvent.click(item);
    await waitFor(() => {
      expect(screen.getByTestId("moderation-detail-p2")).toBeTruthy();
    });
    // Address preview shows raw + masked (masked is a live preview for pending).
    const masked = screen.getByTestId("moderation-masked-address").textContent;
    expect(masked).toContain("Oak Ave"); // "5 Oak Ave" → "Oak Ave"
  });
});
