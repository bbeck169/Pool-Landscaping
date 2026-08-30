/**
 * Phase S2 · Feb-2026 — Autopilot schedule row toggling.
 *
 * Locks in the optimistic-UI contract for the per-platform enable
 * toggle:
 *
 *   1. Click flips the toggle immediately (optimistic UI).
 *   2. On PATCH success, state is committed (aria-checked stays true).
 *   3. On PATCH failure, the toggle REVERTS to the previous value
 *      and a toast is fired.
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
import { toast } from "sonner";
import AutopilotSchedulesTab
  from "@/pages/soshie/AutopilotSchedulesTab";

const CONFIGS = [
  { platform: "wordpress", enabled: false,
     posts_per_day: null, posts_per_week: 3,
     manual_only: false, timezone: "America/Phoenix" },
];
const PLATFORMS = { platforms: [
  { platform: "wordpress", ok: true, detail: "" },
]};

beforeEach(() => {
  vi.clearAllMocks();
  // GlobalKillSwitch fetches /soshie/autopilot/global, then
  // AutopilotSchedulesTab loads /soshie/autopilot/config,
  // /soshie/platforms, /soshie/autopilot/recent-actions.
  api.get.mockImplementation((path) => {
    if (path.includes("/autopilot/global")) return Promise.resolve({ enabled: true });
    if (path.includes("/autopilot/config")) return Promise.resolve({ items: CONFIGS });
    if (path.includes("/soshie/platforms")) return Promise.resolve(PLATFORMS);
    if (path.includes("/autopilot/recent-actions")) return Promise.resolve({ items: [] });
    return Promise.resolve({});
  });
});

describe("S2 · autopilot row toggle", () => {
  it("optimistically flips the toggle and commits on success", async () => {
    api.patch.mockResolvedValueOnce({
      ...CONFIGS[0], enabled: true,
    });
    render(<AutopilotSchedulesTab />);
    const toggle = await screen.findByTestId("platform-toggle-wordpress");
    expect(toggle.getAttribute("aria-checked")).toBe("false");

    fireEvent.click(toggle);
    // Optimistic — commit is synchronous.
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      "/soshie/autopilot/config/wordpress",
      { enabled: true }));
    // Still on after resolve.
    await waitFor(() =>
      expect(toggle.getAttribute("aria-checked")).toBe("true"));
  });

  it("reverts + toasts error when the PATCH fails", async () => {
    api.patch.mockRejectedValueOnce(new Error("boom"));
    render(<AutopilotSchedulesTab />);
    const toggle = await screen.findByTestId("platform-toggle-wordpress");
    fireEvent.click(toggle);
    // Optimistic flip.
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await waitFor(() =>
      expect(toggle.getAttribute("aria-checked")).toBe("false"));
    expect(toast.error).toHaveBeenCalled();
  });
});
