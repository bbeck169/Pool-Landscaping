/**
 * Feb-2026 · Zombie-session hotfix — Vitest for AuthProvider self-heal.
 *
 * Contract (per Fix B):
 *   • When AuthProvider bootstraps with a cached token+user and the
 *     background ``/auth/me`` returns a 401 auth-token failure, the
 *     provider MUST call ``logout()`` (which clears both localStorage
 *     keys AND flips ``user`` back to null).
 *   • Any other error from ``/auth/me`` (network, 5xx) still gets
 *     silently swallowed to preserve the offline-cached path.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args), post: vi.fn(), put: vi.fn() },
  TOKEN_KEY: "token",
}));

import { AuthProvider, useAuth } from "@/auth";

function Probe() {
  const { user } = useAuth();
  return <span data-testid="probe-email">{user?.email || "NO_USER"}</span>;
}

describe("AuthProvider · self-heal on 401 · Fix B", () => {
  beforeEach(() => {
    window.localStorage.clear();
    getMock.mockReset();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("clears the cached user + token when /auth/me returns 401 'Token expired'", async () => {
    window.localStorage.setItem("token", "stale-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "brian@plofv.com", role: "admin" }),
    );
    const err = new Error("Token expired");
    err.status = 401;
    getMock.mockRejectedValueOnce(err);

    await act(async () => {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      );
    });

    // Cached user is visible on first paint (sync bootstrap).
    // After the /auth/me rejection microtask settles, logout() has
    // been called → cache cleared + user null.
    await waitFor(() => {
      expect(screen.getByTestId("probe-email").textContent).toBe("NO_USER");
    });
    expect(window.localStorage.getItem("token")).toBeNull();
    expect(window.localStorage.getItem("user")).toBeNull();
  });

  it("clears on 401 'Invalid token'", async () => {
    window.localStorage.setItem("token", "stale");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u", email: "a@b.co", role: "admin" }),
    );
    const err = new Error("Invalid token");
    err.status = 401;
    getMock.mockRejectedValueOnce(err);

    await act(async () => {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("probe-email").textContent).toBe("NO_USER");
    });
    expect(window.localStorage.getItem("token")).toBeNull();
  });

  it("does NOT log out on a network error (offline resilience)", async () => {
    window.localStorage.setItem("token", "still-valid-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "keep@me.com", role: "admin" }),
    );
    getMock.mockRejectedValueOnce(
      new Error("Network error — check your connection and try again."),
    );

    await act(async () => {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      );
    });

    // Give the microtask queue a beat to flush any accidental logout.
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTestId("probe-email").textContent).toBe("keep@me.com");
    expect(window.localStorage.getItem("token")).toBe("still-valid-jwt");
  });

  it("does NOT log out on a 500 from /auth/me", async () => {
    window.localStorage.setItem("token", "still-valid-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "keep@me.com", role: "admin" }),
    );
    const err = new Error("internal error");
    err.status = 500;
    getMock.mockRejectedValueOnce(err);

    await act(async () => {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      );
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTestId("probe-email").textContent).toBe("keep@me.com");
    expect(window.localStorage.getItem("token")).toBe("still-valid-jwt");
  });

  it("refreshes the user object on a successful /auth/me (no regression)", async () => {
    window.localStorage.setItem("token", "good-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u1", email: "old@stale.com", role: "admin" }),
    );
    getMock.mockResolvedValueOnce({
      id: "u1",
      email: "fresh@server.com",
      role: "admin",
    });

    await act(async () => {
      render(
        <AuthProvider>
          <Probe />
        </AuthProvider>,
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("probe-email").textContent).toBe(
        "fresh@server.com",
      );
    });
  });
});
