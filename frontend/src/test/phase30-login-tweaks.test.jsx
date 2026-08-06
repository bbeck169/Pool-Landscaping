/**
 * Phase 30 · Feb 2026 — Login page tweaks.
 *
 * Verifies:
 *   1. The DEMO ACCOUNTS block is NEVER rendered (removed
 *      unconditionally; the ``SHOW_DEMO_LOGINS`` flag is no longer
 *      consulted by the frontend).
 *   2. The brand header renders as two lines with the correct text.
 *   3. Line 2's font size is exactly half of Line 1's — enforced via
 *      the inline ``fontSize`` on the two ``<span>``s so the check is
 *      hermetic (doesn't depend on jsdom computed styles).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";

// Mock auth so Login renders without a live token / api client.
vi.mock("@/auth", () => ({
  useAuth: () => ({ login: vi.fn(), me: async () => null }),
}));
vi.mock("@/theme", () => ({
  brandGradientCss: "linear-gradient(#000,#111)",
  colors: {
    brand: "#0f6ed1", muted: "#666", onSurface: "#111",
    surface: "#fff", surfaceSecondary: "#f5f5f5", border: "#ccc",
  },
  font: { mono: "monospace" },
}));
vi.mock("@/api", () => ({ api: { get: async () => ({}) } }));

import Login from "@/pages/Login";

function renderPage() {
  return render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  );
}

function _px(v) {
  return parseFloat(v);
}

describe("Login page · Phase 30", () => {
  it("does not render the demo-accounts block", () => {
    renderPage();
    expect(screen.queryByTestId("login-demo-section")).toBeNull();
    expect(screen.queryByTestId("login-demo-accounts")).toBeNull();
    expect(screen.queryByTestId("login-demo-admin")).toBeNull();
    expect(screen.queryByTestId("login-demo-technician")).toBeNull();
    expect(screen.queryByTestId("login-demo-customer")).toBeNull();
    expect(screen.queryByText(/DEMO ACCOUNTS/i)).toBeNull();
  });

  it("renders the two-line brand header with the correct text", () => {
    renderPage();
    const l1 = screen.getByTestId("login-welcome-line1");
    const l2 = screen.getByTestId("login-welcome-line2");
    expect(l1.textContent).toBe("Welcome to");
    expect(l2.textContent).toContain("Pool");
    expect(l2.textContent).toContain("Vistancia");
    expect(l2.textContent).toContain("LLC");
  });

  it("Line 2 font size is exactly half of Line 1", () => {
    renderPage();
    const l1 = screen.getByTestId("login-welcome-line1");
    const l2 = screen.getByTestId("login-welcome-line2");
    const l1px = _px(l1.style.fontSize);
    const l2px = _px(l2.style.fontSize);
    expect(l1px).toBeGreaterThan(0);
    expect(l2px).toBeGreaterThan(0);
    expect(l2px).toBeCloseTo(l1px / 2, 5);
  });

  it("fetches /config/public on mount to gate the demo-tiles block at runtime (Feb 2026 P0 hotfix)", async () => {
    // The runtime app_env gate is the correct behavior — we call
    // /api/config/public on mount and gate the tiles on the
    // returned ``app_env``. This test locks that contract so a
    // future refactor can't silently regress back to the
    // build-time ``process.env.REACT_APP_PUBLIC_ENV`` gate that
    // leaked the tiles to production.
    const api = (await import("@/api")).api;
    const spy = vi.spyOn(api, "get");
    renderPage();
    await Promise.resolve();
    expect(spy).toHaveBeenCalledWith("/config/public");
  });

  it("renders elements in the correct DOM order: [logo] → [Line 1] → [Line 2] → [form]", () => {
    renderPage();
    const logo = screen.getByTestId("login-logo-full");
    const l1 = screen.getByTestId("login-welcome-line1");
    const l2 = screen.getByTestId("login-welcome-line2");
    const form = screen.getByTestId("login-form");
    // DOCUMENT_POSITION_FOLLOWING === 4 — verifies later-in-DOM order.
    expect(logo.compareDocumentPosition(l1) & 4).toBe(4);
    expect(l1.compareDocumentPosition(l2) & 4).toBe(4);
    expect(l2.compareDocumentPosition(form) & 4).toBe(4);
  });

  it("still renders the manual email + password inputs (backdoor login works)", () => {
    renderPage();
    // The manual form must remain — user can still type
    // admin@aquaterra.com / password123 and submit.
    expect(screen.getByTestId("login-form")).toBeTruthy();
  });
});
