/**
 * Phase S2 · Feb-2026 — Reddit toggle hard-block.
 *
 * Reddit autopilot is disabled at the UI layer (defence-in-depth
 * alongside the backend 409 guard). This test locks in:
 *
 *   1. Reddit's toggle is rendered but ``disabled``.
 *   2. Reddit's row surfaces the "Manual Only" badge.
 *   3. Clicking Reddit's toggle does NOT fire a PATCH.
 *   4. Reddit's toggle has an explanatory tooltip (``title``).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { api } from "@/api";
import AutopilotSchedulesTab
  from "@/pages/soshie/AutopilotSchedulesTab";

const CONFIGS = [
  { platform: "reddit", enabled: false,
     posts_per_day: null, posts_per_week: 0,
     manual_only: true, timezone: "America/Phoenix" },
  { platform: "wordpress", enabled: false,
     posts_per_week: 3,
     manual_only: false, timezone: "America/Phoenix" },
];
const PLATFORMS = { platforms: [
  { platform: "reddit", ok: false, detail: "Manual only" },
  { platform: "wordpress", ok: true, detail: "" },
]};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((path) => {
    if (path.includes("/autopilot/global")) return Promise.resolve({ enabled: true });
    if (path.includes("/autopilot/config")) return Promise.resolve({ items: CONFIGS });
    if (path.includes("/soshie/platforms")) return Promise.resolve(PLATFORMS);
    if (path.includes("/autopilot/recent-actions")) return Promise.resolve({ items: [] });
    return Promise.resolve({});
  });
});

describe("S2 · reddit hard-block", () => {
  it("renders Reddit toggle disabled + Manual Only badge", async () => {
    render(<AutopilotSchedulesTab />);
    const redditToggle = await screen.findByTestId("platform-toggle-reddit");
    expect(redditToggle.hasAttribute("disabled")).toBe(true);
    // Explanatory tooltip.
    expect(redditToggle.getAttribute("title") || "")
      .toMatch(/manual only/i);
    // Manual Only badge visible on Reddit's row (StatusBadge
    // renders it based on the reddit flag).
    expect(await screen.findByTestId("platform-badge-manual"))
      .toBeInTheDocument();
  });

  it("clicking a disabled Reddit toggle never fires PATCH", async () => {
    render(<AutopilotSchedulesTab />);
    const redditToggle = await screen.findByTestId("platform-toggle-reddit");
    fireEvent.click(redditToggle);
    // Give React a tick to process any queued PATCH.
    await new Promise((r) => setTimeout(r, 10));
    // Reddit's PATCH URL is never called.
    for (const call of api.patch.mock.calls) {
      expect(call[0]).not.toMatch(/reddit/);
    }
  });
});
