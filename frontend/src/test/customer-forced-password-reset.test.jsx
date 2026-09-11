/**
 * Feb-2026 · P0 · Customer forced-password-reset loop fix — FE tests.
 *
 * Covers:
 *   1) Login response ``password_reset_required`` with ``role="customer"``
 *      → navigates to ``/reset-password?...&flow=temp_password``.
 *   2) Login response ``password_reset_required`` with a non-customer
 *      role → does NOT navigate to the reset page; surfaces an
 *      inline error instead (defense-in-depth guard).
 *   3) ResetPassword happy path — when the backend returns an
 *      ``auto_login`` envelope, the FE persists the JWT and
 *      navigates to the customer portal home (``/portal/home``)
 *      rather than the login screen.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { postSpy, getSpy, navigateSpy } = vi.hoisted(() => ({
  postSpy: vi.fn(),
  getSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    post: (...a) => postSpy(...a),
    get: (...a) => getSpy(...a),
  },
  TOKEN_KEY: "access_token",
}));
vi.mock("@/utils/env", () => ({ isPreviewOrDev: () => false }));
vi.mock("@/components/auth/PreviewDemoLogins", () => ({
  PreviewDemoLogins: () => null,
}));
vi.mock("@/components/portal/PortalWaterBackground", () => ({
  default: () => null,
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useSearchParams: () => [
      { get: (k) => (k === "token" ? "tok-abc" : "temp_password") },
    ],
  };
});

import { AuthProvider } from "@/auth";
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";

const _renderLogin = (props = {}) => render(
  <MemoryRouter>
    <AuthProvider>
      <Login {...props} />
    </AuthProvider>
  </MemoryRouter>,
);

const _renderReset = () => render(
  <MemoryRouter>
    <AuthProvider>
      <ResetPassword />
    </AuthProvider>
  </MemoryRouter>,
);

beforeEach(() => {
  postSpy.mockReset(); getSpy.mockReset(); navigateSpy.mockReset();
  localStorage.clear();
  getSpy.mockImplementation((path) => {
    if (path === "/auth/me") return Promise.resolve(null);
    if (path === "/tenants/memberships/mine") return Promise.resolve([]);
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());


describe("Customer forced-password-reset loop fix · Login", () => {
  it("customer + reset_required → navigates to /reset-password?flow=temp_password", async () => {
    postSpy.mockResolvedValueOnce({
      status: "password_reset_required",
      reset_token: "reset-tok-abc",
      user_id: "u-cust",
      token_ttl_minutes: 15,
      role: "customer",
    });
    _renderLogin();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "brian@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "tmp-pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));
    await waitFor(() => expect(navigateSpy).toHaveBeenCalled());
    const calledWith = navigateSpy.mock.calls[0][0];
    expect(calledWith).toMatch(/^\/reset-password\?token=reset-tok-abc/);
    expect(calledWith).toMatch(/flow=temp_password/);
    // No token persisted — the reset must complete first.
    expect(localStorage.getItem("access_token")).toBeNull();
  });

  it.each(["admin", "technician", "super_admin"])(
    "%s role + reset_required → does NOT redirect; shows inline error (defense-in-depth)",
    async (role) => {
      postSpy.mockResolvedValueOnce({
        status: "password_reset_required",
        reset_token: "should-not-be-honored",
        user_id: "u-staff",
        token_ttl_minutes: 15,
        role,
      });
      _renderLogin();
      fireEvent.change(await screen.findByTestId("login-email-input"),
                         { target: { value: "staff@example.com" } });
      fireEvent.change(screen.getByTestId("login-password-input"),
                         { target: { value: "pwd" } });
      fireEvent.click(screen.getByTestId("login-submit-button"));
      // Inline error banner rather than a redirect.
      const err = await screen.findByTestId("login-error");
      expect(err.textContent).toMatch(/unexpected/i);
      // No navigation to the reset page happened.
      const navPaths = navigateSpy.mock.calls
        .map((c) => c[0])
        .filter((p) => typeof p === "string");
      expect(navPaths.every((p) => !p.startsWith("/reset-password"))).toBe(true);
    },
  );
});


describe("Customer forced-password-reset loop fix · ResetPassword", () => {
  it("auto_login envelope → persists JWT + navigates to /portal/home", async () => {
    postSpy.mockResolvedValueOnce({
      ok: true,
      auto_login: true,
      access_token: "fresh-tok-xyz",
      token_type: "bearer",
      user: {
        id: "u-cust", role: "customer", email: "brian@example.com",
        name: "Brian",
      },
    });
    _renderReset();
    // Fill in matching password meeting the client-side policy.
    const pw = await screen.findByTestId("reset-password-new");
    fireEvent.change(pw, { target: { value: "Brand-New-2026" } });
    fireEvent.change(screen.getByTestId("reset-password-confirm"),
                       { target: { value: "Brand-New-2026" } });
    fireEvent.click(screen.getByTestId("reset-password-submit"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledWith(
      "/auth/reset-password",
      { token: "tok-abc", new_password: "Brand-New-2026" },
    ));
    // Token was persisted via applyResetAutoLogin.
    await waitFor(() => expect(localStorage.getItem("access_token"))
      .toBe("fresh-tok-xyz"));
    // Navigated to the customer portal home, NOT back to login.
    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith(
      "/portal/home", { replace: true },
    ));
  });
});
