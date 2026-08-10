/**
 * Feb-2026 · Zombie-session hotfix — Vitest for the /login?reason=expired banner.
 *
 * Contract:
 *   • When Login is rendered with ``?reason=expired`` in the URL, a
 *     friendly one-liner banner appears above the form. Otherwise no
 *     banner is rendered.
 *   • Banner uses ``role="status"`` for a11y and testid
 *     ``login-session-expired-banner`` for reliable Playwright reach.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(async () => ({ app_env: "production" })), post: vi.fn() },
  TOKEN_KEY: "token",
}));

// Preview demo-logins block does its own fetch dance — stub it out so
// this test focuses purely on the banner behaviour.
vi.mock("@/components/auth/PreviewDemoLogins", () => ({
  PreviewDemoLogins: () => null,
}));

import Login from "@/pages/Login";
import { AuthProvider } from "@/auth";

function renderAt(pathAndSearch) {
  return render(
    <MemoryRouter initialEntries={[pathAndSearch]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Login · session-expired banner · Fix A follow-up", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("shows the banner when navigated with ?reason=expired", () => {
    renderAt("/login?reason=expired");
    const banner = screen.getByTestId("login-session-expired-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/session has expired/i);
  });

  it("does NOT show the banner on a bare /login visit", () => {
    renderAt("/login");
    expect(
      screen.queryByTestId("login-session-expired-banner"),
    ).not.toBeInTheDocument();
  });

  it("does NOT show the banner for an unrelated reason value", () => {
    renderAt("/login?reason=signup-required");
    expect(
      screen.queryByTestId("login-session-expired-banner"),
    ).not.toBeInTheDocument();
  });

  it("survives extra query params alongside reason=expired", () => {
    renderAt("/login?reason=expired&from=%2Fdashboard%3Ftab%3Drevenue");
    expect(
      screen.getByTestId("login-session-expired-banner"),
    ).toBeInTheDocument();
  });
});
