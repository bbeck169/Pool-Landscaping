/**
 * Task 6b · Feb 2026 — Login page must render a friendly banner
 * when the portal auto-login redemption 302s here with
 * ``?reason=link_revoked`` (admin-revoked service-records link).
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({ api: { post: vi.fn(), get: vi.fn(() => Promise.resolve({})) } }));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: null, login: vi.fn() }),
}));

import Login from "@/pages/Login";

describe("Login · link_revoked banner", () => {
  afterEach(() => cleanup());

  it("renders the revoke-specific copy for reason=link_revoked", () => {
    render(
      <MemoryRouter initialEntries={["/login?reason=link_revoked"]}>
        <Login />
      </MemoryRouter>,
    );
    const banner = screen.getByTestId("login-session-expired-banner");
    expect(banner.textContent).toMatch(/link has been revoked/i);
    expect(banner.textContent).toMatch(/contact your service provider/i);
  });

  it("renders the expired copy for reason=link_expired (unchanged)", () => {
    render(
      <MemoryRouter initialEntries={["/login?reason=link_expired"]}>
        <Login />
      </MemoryRouter>,
    );
    const banner = screen.getByTestId("login-session-expired-banner");
    expect(banner.textContent).toMatch(/one-click link has expired/i);
  });

  it("renders the generic expired copy for reason=expired", () => {
    render(
      <MemoryRouter initialEntries={["/login?reason=expired"]}>
        <Login />
      </MemoryRouter>,
    );
    const banner = screen.getByTestId("login-session-expired-banner");
    expect(banner.textContent).toMatch(/session has expired/i);
  });
});
