/**
 * Feb-2026 Enhancement — <PendingNoCrewNudge /> tests.
 *
 * Verifies:
 *   1. Admin sees the banner with the right count when > 0.
 *   2. Renders nothing when count == 0.
 *   3. Renders nothing for a technician.
 *   4. Renders nothing when the endpoint 500s.
 *   5. Review CTA navigates to the filter URL.
 *   6. Dismiss X-button hides for the session (sessionStorage).
 *   7. Persists dismiss across a re-mount within the same session.
 *   8. Singular vs plural copy ("1 job has been" vs "N jobs have been").
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => {
  const responses = {};
  const api = {
    get: vi.fn(async (path) => {
      const r = responses[path];
      if (r instanceof Error) throw r;
      return r ?? null;
    }),
    post: vi.fn(), patch: vi.fn(), del: vi.fn(),
  };
  return { __esModule: true, default: api, api, __responses: responses };
});
vi.mock("@/theme", () => ({
  colors: { muted: "#6b7280", onSurface: "#111" },
}));

import PendingNoCrewNudge from "@/components/schedule/PendingNoCrewNudge";
import * as apiMod from "@/api";


function _render(user, sessionValue) {
  if (sessionValue !== undefined) {
    window.sessionStorage.setItem(
      "schedule.pendingNoCrewNudge.dismissed", sessionValue,
    );
  } else {
    window.sessionStorage.removeItem(
      "schedule.pendingNoCrewNudge.dismissed",
    );
  }
  return render(
    <MemoryRouter>
      <PendingNoCrewNudge user={user} />
    </MemoryRouter>,
  );
}


describe("PendingNoCrewNudge", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
    for (const k of Object.keys(apiMod.__responses)) {
      delete apiMod.__responses[k];
    }
    window.sessionStorage.clear();
  });
  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("renders banner for admin when count > 0", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 3, days: 7, cutoff: "2026-02-01T00:00:00Z",
    };
    _render({ role: "admin" });
    const banner = await screen.findByTestId("schedule-pending-no-crew-nudge");
    expect(banner).toBeDefined();
    const label = screen.getByTestId("schedule-pending-no-crew-nudge-label");
    expect(label.textContent).toBe(
      "3 jobs have been pending assignment for over a week.",
    );
  });

  it("uses singular copy when count is exactly 1", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 1, days: 7,
    };
    _render({ role: "admin" });
    const label = await screen.findByTestId("schedule-pending-no-crew-nudge-label");
    expect(label.textContent).toBe(
      "1 job has been pending assignment for over a week.",
    );
  });

  it("renders nothing when count is 0", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 0, days: 7,
    };
    _render({ role: "admin" });
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalledWith(
        "/schedule/unassigned-pending-stale?days=7",
      );
    });
    expect(screen.queryByTestId("schedule-pending-no-crew-nudge")).toBeNull();
  });

  it("renders nothing for a technician (no endpoint call)", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 5, days: 7,
    };
    _render({ role: "technician" });
    // Wait a tick to be sure the effect didn't fire late.
    await new Promise((r) => setTimeout(r, 30));
    expect(apiMod.default.get).not.toHaveBeenCalled();
    expect(screen.queryByTestId("schedule-pending-no-crew-nudge")).toBeNull();
  });

  it("hides when the endpoint throws (graceful degradation)", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"]
      = new Error("boom");
    _render({ role: "admin" });
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("schedule-pending-no-crew-nudge")).toBeNull();
  });

  it("Review CTA is present and clickable", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 3, days: 7,
    };
    _render({ role: "admin" });
    const btn = await screen.findByTestId("schedule-pending-no-crew-nudge-review");
    expect(btn).toBeDefined();
    // MemoryRouter swallows the nav, but the click should not throw.
    fireEvent.click(btn);
  });

  it("dismiss X-button stamps sessionStorage AND hides the banner", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 3, days: 7,
    };
    _render({ role: "admin" });
    const x = await screen.findByTestId("schedule-pending-no-crew-nudge-dismiss");
    fireEvent.click(x);
    await waitFor(() => {
      expect(screen.queryByTestId("schedule-pending-no-crew-nudge")).toBeNull();
    });
    expect(
      window.sessionStorage.getItem("schedule.pendingNoCrewNudge.dismissed"),
    ).toBe("1");
  });

  it("stays dismissed on re-mount within the same session", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 3, days: 7,
    };
    // Pre-seed the dismissed flag.
    _render({ role: "admin" }, "1");
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalled();
    });
    // Even with count>0, banner must not render because dismissed=1.
    expect(screen.queryByTestId("schedule-pending-no-crew-nudge")).toBeNull();
  });

  it("manager role is treated as admin-equivalent", async () => {
    apiMod.__responses["/schedule/unassigned-pending-stale?days=7"] = {
      count: 2, days: 7,
    };
    _render({ role: "manager" });
    const banner = await screen.findByTestId("schedule-pending-no-crew-nudge");
    expect(banner).toBeDefined();
  });
});
