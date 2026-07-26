/**
 * Feb-2026 · LoginPage · SHOW_DEMO_LOGINS gate — vitest.
 *
 * The Login screen reads ``GET /api/config/public`` on mount and
 * flips the visibility of the "Demo accounts" quick-login block +
 * the credential-hint text based on ``show_demo_logins``. Preview /
 * dev keep the affordance on for QA; production sets the env var to
 * ``false`` and the block must be hidden entirely.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: apiGetMock },
  api_base: () => "http://test.example/api",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    login: vi.fn(),
    me: vi.fn().mockResolvedValue({ role: "admin" }),
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));


beforeEach(() => { apiGetMock.mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });


async function mountLogin() {
  const { default: Login } = await import("@/pages/Login");
  return render(<MemoryRouter><Login /></MemoryRouter>);
}


describe("LoginPage · show_demo_logins gate", () => {
  it("shows the demo section when the flag is true", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/config/public")
        return Promise.resolve({ show_demo_logins: true });
      return Promise.resolve({});
    });
    await mountLogin();

    const section = await screen.findByTestId("login-demo-section");
    expect(section).toBeInTheDocument();
    // The section is rendered (not display:none).
    expect(section.style.display).not.toBe("none");
    // Individual quick-login buttons resolve.
    expect(screen.getByTestId("login-demo-admin")).toBeInTheDocument();
    expect(screen.getByTestId("login-demo-technician")).toBeInTheDocument();
    expect(screen.getByTestId("login-demo-customer")).toBeInTheDocument();
  });

  it("hides the demo section when the flag is false", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/config/public")
        return Promise.resolve({ show_demo_logins: false });
      return Promise.resolve({});
    });
    await mountLogin();

    // Section still mounts (so the effect can toggle it) — but its
    // ``display`` inline style flips to ``none``. Assert on the
    // computed inline style.
    const section = await screen.findByTestId("login-demo-section");
    await waitFor(() => expect(section.style.display).toBe("none"));
    // The email/password form remains fully functional.
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
  });

  it("defaults to showing the demo section when the config call fails", async () => {
    apiGetMock.mockRejectedValue(new Error("network down"));
    await mountLogin();

    // Fallback path — the ``useState(true)`` initial value stands
    // and the section renders as-is.
    const section = await screen.findByTestId("login-demo-section");
    expect(section.style.display).not.toBe("none");
    expect(screen.getByTestId("login-demo-admin")).toBeInTheDocument();
  });

  it("defaults to showing the section when show_demo_logins is missing from the response", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/config/public")
        return Promise.resolve({ /* no show_demo_logins field */ });
      return Promise.resolve({});
    });
    await mountLogin();
    const section = await screen.findByTestId("login-demo-section");
    expect(section.style.display).not.toBe("none");
  });
});
