/**
 * Feb-2026 · Fix 2 · AuthProvider bootstrap race — Vitest.
 *
 * Regression guard on the sync-init change. When a token + user are
 * present in localStorage BEFORE React renders, the very first paint
 * must see ``user != null`` so auth-guarded routes don't flash to
 * /login. Previously ``user`` was initialised to null and only
 * populated inside a ``useEffect`` (deferred until AFTER paint),
 * which produced the Playwright bootstrap race.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock the api module so no network I/O in tests.
vi.mock("@/api", () => ({
  api: { get: vi.fn(async () => null), post: vi.fn(), put: vi.fn() },
  TOKEN_KEY: "token",
}));

import { AuthProvider, useAuth } from "@/auth";

function ProbeUser() {
  const { user, loading } = useAuth();
  return (
    <div>
      <span data-testid="user-email">{user?.email || "NO_USER"}</span>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
    </div>
  );
}

describe("AuthProvider · sync bootstrap · Fix 2", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("populates `user` on the FIRST render when token+user are pre-seeded", () => {
    // Simulate Playwright's `page.evaluate(localStorage.setItem(...))`
    // BEFORE React mounts.
    window.localStorage.setItem("token", "test-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "brian@plofv.com", role: "admin" }),
    );

    render(
      <AuthProvider>
        <ProbeUser />
      </AuthProvider>,
    );

    // The initial paint must already show the user (was 'NO_USER'
    // before the fix — hence the /login redirect flash).
    expect(screen.getByTestId("user-email").textContent).toBe("brian@plofv.com");
  });

  it("shows NO_USER when localStorage is empty (no bootstrap crash)", () => {
    render(
      <AuthProvider>
        <ProbeUser />
      </AuthProvider>,
    );
    expect(screen.getByTestId("user-email").textContent).toBe("NO_USER");
  });

  it("survives a corrupt user JSON blob without crashing", () => {
    window.localStorage.setItem("token", "test-jwt");
    window.localStorage.setItem("user", "not-valid-json{{{");
    render(
      <AuthProvider>
        <ProbeUser />
      </AuthProvider>,
    );
    expect(screen.getByTestId("user-email").textContent).toBe("NO_USER");
  });

  it("does not flip `loading` on for a re-render when cache is present", () => {
    window.localStorage.setItem("token", "test-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "x@y.z", role: "admin" }),
    );
    render(
      <AuthProvider>
        <ProbeUser />
      </AuthProvider>,
    );
    // The refactor removed the transient loading=true state — the
    // auth boot is now instantaneous when cache is present.
    expect(screen.getByTestId("loading").textContent).toBe("ready");
  });
});
