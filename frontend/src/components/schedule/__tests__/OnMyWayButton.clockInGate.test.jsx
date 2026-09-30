/**
 * Feb-2026 · Clock-in gate — ``<OnMyWayButton />`` disabled state.
 *
 * Landscape techs who aren't clocked in must see the SMS button
 * rendered but disabled with the exact tooltip
 * ``"Clock in to start working."`` so the affordance stays
 * discoverable (spec: "Keep the buttons rendered — don't hide them
 * — so the tooltip is discoverable").  All other roles (admin,
 * manager, pool tech, super_admin) render enabled unchanged.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import React from "react";


const _h = vi.hoisted(() => ({
  currentUser: null,
  apiGet: vi.fn(),
  toast: {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn(),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _h.currentUser }),
}));

vi.mock("@/api", () => ({
  api: {
    get:  (...args) => _h.apiGet(...args),
    post: vi.fn(),
  },
}));

vi.mock("sonner", () => ({ toast: _h.toast }));


// Import after mocks.
// eslint-disable-next-line import/first
import OnMyWayButton from "@/components/schedule/OnMyWayButton";
// eslint-disable-next-line import/first
import { __resetClockInStatusCacheForTests } from "@/hooks/useClockInGate";


beforeEach(() => {
  _h.currentUser = null;
  _h.apiGet.mockReset();
  __resetClockInStatusCacheForTests();
});
afterEach(() => {
  __resetClockInStatusCacheForTests();
});


describe("<OnMyWayButton /> · clock-in gate — disabled + tooltip", () => {
  it("landscape tech + NOT clocked in → disabled + spec-verbatim title", async () => {
    _h.currentUser = {
      id: "u-luis", role: "technician", department: "landscape_tech",
    };
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    const { getByTestId } = render(<OnMyWayButton jobId="job-1" />);
    // Effect flushes async — wait for the button to reflect the
    // resolved status.
    const btn = await waitFor(() => getByTestId("on-my-way-btn-job-1"));
    await waitFor(() => expect(btn.disabled).toBe(true));
    // Exact tooltip copy from the task spec.
    expect(btn.getAttribute("title")).toBe("Clock in to start working.");
  });

  it("landscape tech + clocked in → enabled, no gate tooltip", async () => {
    _h.currentUser = {
      id: "u-luis", role: "technician", department: "landscape_tech",
    };
    _h.apiGet.mockResolvedValueOnce({ clocked_in: true });
    const { getByTestId } = render(<OnMyWayButton jobId="job-2" />);
    const btn = await waitFor(() => getByTestId("on-my-way-btn-job-2"));
    await waitFor(() => expect(btn.disabled).toBe(false));
    // Falls back to the pre-existing SMS-hint tooltip.
    expect(btn.getAttribute("title")).toBe("Send 'on my way' SMS");
  });

  it("admin → button always enabled, no status probe made", async () => {
    _h.currentUser = {
      id: "u-a", role: "admin", department: "both",
    };
    const { getByTestId } = render(<OnMyWayButton jobId="job-3" />);
    const btn = getByTestId("on-my-way-btn-job-3");
    expect(btn.disabled).toBe(false);
    // Admins bypass the gate entirely — no mine-status hit.
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("pool-only technician → button enabled, gate skipped", async () => {
    _h.currentUser = {
      id: "u-alex", role: "technician", department: "pool",
    };
    const { getByTestId } = render(<OnMyWayButton jobId="job-4" />);
    const btn = getByTestId("on-my-way-btn-job-4");
    expect(btn.disabled).toBe(false);
    expect(_h.apiGet).not.toHaveBeenCalled();
  });

  it("primary variant (top-level ``next-job`` CTA) inherits the same gate", async () => {
    _h.currentUser = {
      id: "u-luis", role: "technician", department: "landscape_tech",
    };
    _h.apiGet.mockResolvedValueOnce({ clocked_in: false });
    const { getByTestId } = render(
      <OnMyWayButton jobId="next-1" variant="primary" />,
    );
    const btn = await waitFor(() => getByTestId("on-my-way-btn-next-1"));
    await waitFor(() => expect(btn.disabled).toBe(true));
    expect(btn.getAttribute("title")).toBe("Clock in to start working.");
  });
});
