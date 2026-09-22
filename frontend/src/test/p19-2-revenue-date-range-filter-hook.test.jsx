/**
 * Phase P19.2 · Feb-2026 · Vitest.
 *
 * Regression cover for the Rules-of-Hooks refactor of
 * ``RevenueDateRangeFilter``. Before this phase ``useAuth()`` was
 * wrapped in a try/catch inside the component body — a hooks
 * violation. The refactor lifts the hook to the top of the
 * component and lets optional chaining handle the "no auth
 * context" case.
 *
 * Assertions:
 *   1. Mounting the component under ``AuthProvider`` with no user
 *      (localStorage empty → bootstraps ``user = null``) does NOT
 *      throw and does NOT log a Rules-of-Hooks React warning.
 *   2. The effective timezone falls back to ``America/Phoenix``
 *      when neither an explicit ``tenantTimezone`` prop nor an
 *      authenticated tenant tz is available. Read via the
 *      ``revenue-tz-badge`` testid — text-only assertions on a
 *      user-facing label are fragile against copy tweaks, so the
 *      badge is the stable seam.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// The AuthProvider imports ``@/api`` at module load. We stub it out
// so the effect's ``api.get("/auth/me")`` is a no-op even if a stray
// token ever slipped into localStorage (defence-in-depth — the
// beforeEach clears storage anyway).
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve(null)),
    post: vi.fn(),
    patch: vi.fn(),
  },
  TOKEN_KEY: "token",
}));

import { AuthProvider } from "@/auth";
import RevenueDateRangeFilter from "@/components/dashboard/RevenueDateRangeFilter";

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});
afterEach(() => cleanup());

describe("RevenueDateRangeFilter · P19.2 hook refactor", () => {
  it("mounts under AuthProvider with user=null without throwing", () => {
    expect(() =>
      render(
        <AuthProvider>
          <RevenueDateRangeFilter onChange={() => {}} />
        </AuthProvider>,
      ),
    ).not.toThrow();
  });

  it("falls back to America/Phoenix when auth has no user", () => {
    render(
      <AuthProvider>
        <RevenueDateRangeFilter onChange={() => {}} />
      </AuthProvider>,
    );
    const badge = screen.getByTestId("revenue-tz-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toBe("America/Phoenix");
  });

  it("does not log a Rules-of-Hooks warning during mount", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <AuthProvider>
        <RevenueDateRangeFilter onChange={() => {}} />
      </AuthProvider>,
    );
    const hookViolation = errSpy.mock.calls.some((call) =>
      String(call[0] || "").toLowerCase().includes("rules of hooks"),
    );
    expect(hookViolation).toBe(false);
    errSpy.mockRestore();
  });
});
