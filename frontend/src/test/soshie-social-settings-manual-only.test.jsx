/**
 * Phase H5.5 · Feb-2026 — Social settings Manual-Only mode.
 *
 * Verifies that the AutopilotSchedulesTab surfaces the "Manual
 * Only" pill for the 6 flipped platforms (Facebook, Instagram,
 * LinkedIn, YouTube, TikTok, GBP) AND leaves their toggles /
 * cadence inputs enabled so operators can drive the manual flow.
 * Reddit stays hard-blocked (S2 contract).
 */
import React from "react";
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


const MANUAL_ONLY_PLATFORMS = [
  "facebook", "instagram", "linkedin",
  "youtube", "tiktok", "gbp",
];


const CONFIGS = [
  ...MANUAL_ONLY_PLATFORMS.map((p) => ({
    platform: p, enabled: false,
    posts_per_day: p === "gbp" ? 1 : null,
    posts_per_week: p === "gbp" ? null : 2,
    manual_only: true, timezone: "America/Phoenix",
  })),
  { platform: "wordpress", enabled: false,
     posts_per_week: 3, manual_only: false,
     timezone: "America/Phoenix" },
  { platform: "reddit", enabled: false,
     posts_per_week: 0, manual_only: true,
     timezone: "America/Phoenix" },
];
const PLATFORMS = { platforms: [
  { platform: "facebook", ok: false, detail: "Pending operator setup: FB" },
  { platform: "wordpress", ok: true, detail: "" },
  { platform: "reddit", ok: false, detail: "Manual only" },
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


describe("H5.5 · Social settings — Manual Only for 6 platforms", () => {
  it("renders 'Manual Only' pill for FB / IG / LinkedIn / YT / TikTok / GBP",
     async () => {
    render(<AutopilotSchedulesTab />);
    // All 6 rows exist and each carries the Manual Only badge (via
    // StatusBadge — the same testid Reddit uses today).
    for (const p of MANUAL_ONLY_PLATFORMS) {
      await waitFor(() =>
        expect(screen.getByTestId(`platform-row-${p}`)).toBeInTheDocument(),
      );
      const row = screen.getByTestId(`platform-row-${p}`);
      // Manual Only badge is inside this row (multiple rows carry
      // the same testid so we scope by getAllByTestId + presence).
      const manualPill = row.querySelector(
        '[data-testid="platform-badge-manual"]',
      );
      expect(manualPill).not.toBeNull();
      // Never rendering the "Coming Soon" pill for these rows —
      // that would signal we haven't done the H5.5 flip.
      expect(row.querySelector(
        '[data-testid="platform-badge-coming-soon"]',
      )).toBeNull();
    }
  });

  it("leaves the 6 flipped platforms' toggles ENABLED (only Reddit disabled)",
     async () => {
    render(<AutopilotSchedulesTab />);
    for (const p of MANUAL_ONLY_PLATFORMS) {
      const toggle = await screen.findByTestId(`platform-toggle-${p}`);
      expect(toggle.hasAttribute("disabled")).toBe(false);
      // Explanatory tooltip on non-Reddit manual-only platforms.
      expect(toggle.getAttribute("title") || "").toMatch(/manual only/i);
    }
    // Reddit still hardblocked.
    const redditToggle = await screen.findByTestId("platform-toggle-reddit");
    expect(redditToggle.hasAttribute("disabled")).toBe(true);
  });

  it("leaves cadence inputs editable for the 6 flipped platforms",
     async () => {
    render(<AutopilotSchedulesTab />);
    for (const p of MANUAL_ONLY_PLATFORMS) {
      const cadence = await screen.findByTestId(`platform-cadence-${p}`);
      expect(cadence.hasAttribute("disabled")).toBe(false);
    }
  });

  it("clicking a flipped-platform toggle fires the PATCH endpoint",
     async () => {
    api.patch.mockResolvedValue({
      platform: "facebook", enabled: true,
      posts_per_week: 2, manual_only: true,
    });
    render(<AutopilotSchedulesTab />);
    const fbToggle = await screen.findByTestId("platform-toggle-facebook");
    fireEvent.click(fbToggle);
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const call = api.patch.mock.calls[0];
    expect(call[0]).toBe("/soshie/autopilot/config/facebook");
    expect(call[1]).toEqual({ enabled: true });
  });

  it("preserves WordPress 'Connected' status (H5.5 non-goal)", async () => {
    render(<AutopilotSchedulesTab />);
    const wpRow = await screen.findByTestId("platform-row-wordpress");
    // "Connected" pill for WordPress — did NOT flip to Manual Only.
    expect(wpRow.querySelector(
      '[data-testid="platform-badge-connected"]',
    )).not.toBeNull();
    expect(wpRow.querySelector(
      '[data-testid="platform-badge-manual"]',
    )).toBeNull();
  });
});
