/**
 * Feb-2026 · Task 4 · Option A — Login chooser UI regression tests.
 *
 * Covers:
 *  1. Normal single-record login (no chooser rendered).
 *  2. ``multi_account_choice_required`` response renders the chooser
 *     with the correct heading, subhead, one card per choice.
 *  3. Picking a card posts to ``/api/auth/login/select-account`` with
 *     the choice_token + account_id and persists like a normal login.
 *  4. Cancel restores the login form and clears the chooser state.
 *  5. Error surface: select-account failure shows the message inline
 *     without wiping the choices.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Hoisted API mock so both auth.jsx and Login.jsx see the same fake.
const { postSpy, getSpy } = vi.hoisted(() => ({
  postSpy: vi.fn(),
  getSpy: vi.fn(),
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

import { AuthProvider } from "@/auth";
import Login from "@/pages/Login";

const _render = (props = {}) => render(
  <MemoryRouter>
    <AuthProvider>
      <Login {...props} />
    </AuthProvider>
  </MemoryRouter>,
);

beforeEach(() => {
  postSpy.mockReset(); getSpy.mockReset();
  localStorage.clear();
  // /auth/me is called on mount by AuthProvider; return null (logged out).
  getSpy.mockImplementation((path) => {
    if (path === "/auth/me") return Promise.resolve(null);
    if (path === "/tenants/memberships/mine") return Promise.resolve([]);
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());


describe("Login · Option A account chooser", () => {
  it("does NOT render the chooser on a normal single-record login", async () => {
    postSpy.mockResolvedValueOnce({
      access_token: "tok-x",
      user: { id: "u-1", role: "admin", email: "jane@example.com" },
    });
    _render();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "jane@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledWith(
      "/auth/login", { email: "jane@example.com", password: "pwd" },
    ));
    expect(screen.queryByTestId("account-chooser")).toBeNull();
  });

  it("renders the chooser when the backend returns multi_account_choice_required", async () => {
    postSpy.mockResolvedValueOnce({
      status: "multi_account_choice_required",
      email: "brian@example.com",
      choice_token: "choice-tok-abc",
      choices: [
        { account_id: "u-cust", role: "customer",
          display: "Customer account · Brian" },
        { account_id: "u-admin", role: "admin",
          display: "Staff · Aquaterra (admin)" },
      ],
    });
    _render();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "brian@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));

    const chooser = await screen.findByTestId("account-chooser");
    expect(chooser).toBeTruthy();
    expect(screen.getByTestId("account-chooser-heading").textContent)
      .toBe("Which account?");
    expect(screen.getByTestId("account-chooser-subhead").textContent)
      .toMatch(/two accounts.*brian@example\.com.*Pick one/);
    expect(screen.getByTestId("account-chooser-option-customer").textContent)
      .toMatch(/Customer account · Brian/);
    expect(screen.getByTestId("account-chooser-option-admin").textContent)
      .toMatch(/Staff · Aquaterra \(admin\)/);
  });

  it("posts to /auth/login/select-account when a card is picked", async () => {
    postSpy.mockResolvedValueOnce({
      status: "multi_account_choice_required",
      email: "brian@example.com",
      choice_token: "choice-tok-abc",
      choices: [
        { account_id: "u-cust", role: "customer", display: "Customer" },
        { account_id: "u-admin", role: "admin", display: "Staff" },
      ],
    }).mockResolvedValueOnce({
      access_token: "final-tok",
      user: { id: "u-cust", role: "customer", email: "brian@example.com" },
    });
    _render();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "brian@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));
    fireEvent.click(await screen.findByTestId("account-chooser-option-customer"));

    await waitFor(() => expect(postSpy).toHaveBeenCalledWith(
      "/auth/login/select-account",
      { choice_token: "choice-tok-abc", account_id: "u-cust" },
    ));
    // Token was persisted like a normal login.
    await waitFor(() => expect(localStorage.getItem("access_token"))
      .toBe("final-tok"));
  });

  it("shows the failure message when select-account rejects", async () => {
    postSpy
      .mockResolvedValueOnce({
        status: "multi_account_choice_required",
        email: "brian@example.com", choice_token: "tok",
        choices: [
          { account_id: "u-cust", role: "customer", display: "Cust" },
          { account_id: "u-admin", role: "admin", display: "Admin" },
        ],
      })
      .mockRejectedValueOnce(new Error("Choice token expired. Please sign in again."));
    _render();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "brian@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));
    fireEvent.click(await screen.findByTestId("account-chooser-option-admin"));
    const err = await screen.findByTestId("account-chooser-error");
    expect(err.textContent).toMatch(/expired/i);
    // The chooser is STILL visible after failure so the user can try again.
    expect(screen.getByTestId("account-chooser")).toBeTruthy();
  });

  it("Cancel returns to the login form and clears the password", async () => {
    postSpy.mockResolvedValueOnce({
      status: "multi_account_choice_required",
      email: "brian@example.com", choice_token: "tok",
      choices: [
        { account_id: "u-cust", role: "customer", display: "C" },
        { account_id: "u-admin", role: "admin", display: "A" },
      ],
    });
    _render();
    fireEvent.change(await screen.findByTestId("login-email-input"),
                       { target: { value: "brian@example.com" } });
    fireEvent.change(screen.getByTestId("login-password-input"),
                       { target: { value: "pwd" } });
    fireEvent.click(screen.getByTestId("login-submit-button"));
    fireEvent.click(await screen.findByTestId("account-chooser-cancel"));
    await waitFor(() => expect(screen.queryByTestId("account-chooser")).toBeNull());
    // Password field is cleared so the user re-enters it.
    expect(screen.getByTestId("login-password-input").value).toBe("");
  });
});
