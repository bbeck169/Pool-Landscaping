/**
 * Feb-2026 · Phase 1 — Tech "On my way" SMS button (web).
 *
 * Covers the four acceptance criteria in the spec:
 *   1. Visible only for tech / manager / admin / super_admin roles.
 *   2. Click posts to the correct endpoint — with coords when
 *      ``navigator.geolocation`` resolves; without when it errors
 *      or times out.
 *   3. Guard-hit response renders a yellow toast with a humanized
 *      reason (uses the shared ``sonner`` toast API).
 *   4. 10-second local re-click disable backstops the server-side
 *      once-per-job-per-day guard.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";


// --- Mocks (hoisted so vi.mock can reference them) ------------------
const _h = vi.hoisted(() => ({
  role: { current: "technician" },
  apiPost: vi.fn(),
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u-1", role: _h.role.current } }),
}));
vi.mock("@/api", () => ({
  api: { post: (...a) => _h.apiPost(...a) },
}));
vi.mock("sonner", () => ({ toast: _h.toast }));


import OnMyWayButton from "@/components/schedule/OnMyWayButton";


beforeEach(() => {
  vi.useFakeTimers();
  _h.role.current = "technician";
  _h.apiPost.mockReset();
  _h.toast.success.mockReset();
  _h.toast.warning.mockReset();
  _h.toast.error.mockReset();
  window.navigator.geolocation = {
    getCurrentPosition: (ok) => ok({
      coords: { latitude: 33.71, longitude: -112.24 },
    }),
  };
});
afterEach(() => {
  vi.useRealTimers();
  delete window.navigator.geolocation;
});


async function _flushRafs() {
  // The button awaits geolocation → api.post → setState; drain
  // pending microtasks so the assertions see the settled UI.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
}


describe("<OnMyWayButton />", () => {
  it("hides itself for non-authorized roles (customer)", () => {
    _h.role.current = "customer";
    const { container } = render(<OnMyWayButton jobId="j-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders for technician / manager / admin / super_admin", () => {
    for (const r of ["technician", "manager", "admin", "super_admin"]) {
      _h.role.current = r;
      const { container, unmount } = render(<OnMyWayButton jobId="j-1" />);
      expect(container.firstChild).not.toBeNull();
      unmount();
    }
  });

  it("click POSTs to /jobs/{id}/on-my-way with coords when geolocation resolves", async () => {
    _h.apiPost.mockResolvedValueOnce({ sent: true, eta_minutes: 12,
                                       communication_id: "c-1" });
    render(<OnMyWayButton jobId="job-42" customerFirstName="Jane" />);
    fireEvent.click(screen.getByTestId("on-my-way-btn-job-42"));
    await _flushRafs();
    expect(_h.apiPost).toHaveBeenCalledWith("/jobs/job-42/on-my-way", {
      origin_lat: 33.71, origin_lng: -112.24,
    });
    expect(_h.toast.success).toHaveBeenCalled();
    expect(_h.toast.success.mock.calls[0][0]).toMatch(/Jane/);
    expect(_h.toast.success.mock.calls[0][0]).toMatch(/12 min/);
  });

  it("posts without coords when geolocation errors (or is unavailable)", async () => {
    window.navigator.geolocation = {
      getCurrentPosition: (_ok, err) => err({ code: 1, message: "denied" }),
    };
    _h.apiPost.mockResolvedValueOnce({ sent: true, eta_minutes: null });
    render(<OnMyWayButton jobId="job-99" />);
    fireEvent.click(screen.getByTestId("on-my-way-btn-job-99"));
    await _flushRafs();
    expect(_h.apiPost).toHaveBeenCalledWith("/jobs/job-99/on-my-way", {});
  });

  it("times out geolocation after 4s and posts without coords", async () => {
    window.navigator.geolocation = { getCurrentPosition: () => {} };
    _h.apiPost.mockResolvedValueOnce({ sent: true, eta_minutes: null });
    render(<OnMyWayButton jobId="job-77" />);
    fireEvent.click(screen.getByTestId("on-my-way-btn-job-77"));
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });
    expect(_h.apiPost).toHaveBeenCalledWith("/jobs/job-77/on-my-way", {});
  });

  it("guard-hit response renders a warning toast with humanized reason", async () => {
    _h.apiPost.mockResolvedValueOnce({ sent: false, reason: "already_sent_today" });
    render(<OnMyWayButton jobId="job-9" />);
    fireEvent.click(screen.getByTestId("on-my-way-btn-job-9"));
    await _flushRafs();
    expect(_h.toast.warning).toHaveBeenCalledWith(
      "Already notified this customer today.",
    );
    expect(_h.toast.success).not.toHaveBeenCalled();
  });

  it("humanizes every guard reason", async () => {
    const cases = [
      ["sms_opt_in_false",   /opted out/i],
      ["customer_blocked",   /blocked|demo/i],
      ["no_phone",           /No phone/i],
      ["outbound_disabled",  /disabled/i],
      ["send_failed",        /rejected|try again/i],
    ];
    for (const [reason, pattern] of cases) {
      _h.apiPost.mockResolvedValueOnce({ sent: false, reason });
      _h.toast.warning.mockReset();
      const { unmount } = render(<OnMyWayButton jobId={`job-${reason}`} />);
      fireEvent.click(screen.getByTestId(`on-my-way-btn-job-${reason}`));
      await _flushRafs();
      const msg = _h.toast.warning.mock.calls[0]?.[0];
      expect(msg).toMatch(pattern);
      unmount();
    }
  });

  it("10-second local disable after a completed request", async () => {
    _h.apiPost.mockResolvedValueOnce({ sent: true, eta_minutes: null });
    render(<OnMyWayButton jobId="job-cool" />);
    const btn = screen.getByTestId("on-my-way-btn-job-cool");
    fireEvent.click(btn);
    await _flushRafs();
    // Immediately after resolve: button is in cooldown.
    expect(btn.hasAttribute("disabled")).toBe(true);
    // Second click while cooldown active — no new post.
    fireEvent.click(btn);
    await _flushRafs();
    expect(_h.apiPost).toHaveBeenCalledTimes(1);
    // Advance past the 10s cooldown → re-enabled.
    await act(async () => { await vi.advanceTimersByTimeAsync(10_100); });
    expect(btn.hasAttribute("disabled")).toBe(false);
  });

  it("primary variant renders the top-level next-job label", () => {
    render(
      <OnMyWayButton
        jobId="job-next"
        customerFirstName="Alex"
        variant="primary"
        testId="on-my-way-next-btn"
      />,
    );
    const btn = screen.getByTestId("on-my-way-next-btn");
    expect(btn.textContent).toMatch(/On my way — next job/);
  });
});
