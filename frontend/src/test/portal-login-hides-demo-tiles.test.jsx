/**
 * Feb 2026 · P0 Hotfix #2 (Option C) — Customer-facing login surface.
 *
 * A NEW route ``/portal/login`` renders the same ``Login`` page with
 * ``variant="customer"``. That variant:
 *   1. Never renders the ``<PreviewDemoLogins>`` block — no gate, no
 *      toggle, no render, in ANY environment.
 *   2. Never fetches ``/api/config/public`` (the app_env gate is not
 *      needed on the customer surface).
 *
 * The default staff-facing ``/login`` route (``variant="staff"``) is
 * unchanged from the previous P0 hotfix — demo tiles still gated on
 * ``app_env !== "production"``.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks ────────────────────────────────────────────────────────────
vi.mock("@/auth", () => ({
  useAuth: () => ({ login: vi.fn(), me: async () => null }),
}));
vi.mock("@/theme", () => ({
  brandGradientCss: "linear-gradient(#000,#111)",
  colors: {
    brand: "#0f6ed1", muted: "#666", onSurface: "#111",
    surface: "#fff", surfaceSecondary: "#f5f5f5", border: "#ccc",
    onSurfaceSecondary: "#444", error: "#a10", input: "#fff",
  },
  font: { family: "system-ui", mono: "monospace" },
}));
// Default mock: /config/public returns app_env=preview so the STAFF
// login WOULD render tiles. Individual tests override as needed.
const mockApiGet = vi.fn(async () => ({ app_env: "preview" }));
vi.mock("@/api", () => ({ api: { get: (...args) => mockApiGet(...args) } }));

import Login from "@/pages/Login";

function renderStaffLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Login />
    </MemoryRouter>,
  );
}

function renderCustomerLogin() {
  return render(
    <MemoryRouter initialEntries={["/portal/login"]}>
      <Login variant="customer" />
    </MemoryRouter>,
  );
}

afterEach(() => {
  mockApiGet.mockClear();
  mockApiGet.mockImplementation(async () => ({ app_env: "preview" }));
});

describe("Portal login (customer variant) · never renders demo tiles", () => {
  it("does not render <PreviewDemoLogins> when app_env=preview", async () => {
    mockApiGet.mockImplementation(async () => ({ app_env: "preview" }));
    renderCustomerLogin();
    // Give any effects a tick.
    await Promise.resolve();
    await Promise.resolve();
    // No demo-tile testids, no headline text, no per-role buttons.
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
    expect(screen.queryByTestId("demo-login-super")).toBeNull();
    expect(screen.queryByTestId("demo-login-admin")).toBeNull();
    expect(screen.queryByTestId("demo-login-customer")).toBeNull();
    expect(screen.queryByTestId("demo-login-tech")).toBeNull();
    expect(screen.queryByText(/DEMO LOGINS/i)).toBeNull();
  });

  it("does not render <PreviewDemoLogins> when app_env=development", async () => {
    mockApiGet.mockImplementation(async () => ({ app_env: "development" }));
    renderCustomerLogin();
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
  });

  it("does not render <PreviewDemoLogins> when app_env=production", async () => {
    mockApiGet.mockImplementation(async () => ({ app_env: "production" }));
    renderCustomerLogin();
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
  });

  it("does not render <PreviewDemoLogins> when /config/public fetch fails", async () => {
    mockApiGet.mockImplementation(async () => { throw new Error("boom"); });
    renderCustomerLogin();
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
  });

  it("does NOT even fetch /config/public on the customer variant", async () => {
    renderCustomerLogin();
    await Promise.resolve();
    await Promise.resolve();
    expect(mockApiGet).not.toHaveBeenCalledWith("/config/public");
  });

  it("still renders the manual email + password form on the customer variant", () => {
    renderCustomerLogin();
    expect(screen.getByTestId("login-form")).toBeTruthy();
    expect(screen.getByTestId("login-email-input")).toBeTruthy();
    expect(screen.getByTestId("login-password-input")).toBeTruthy();
    expect(screen.getByTestId("login-submit-button")).toBeTruthy();
  });

  it("still renders the 'Forgot password?' link on the customer variant", () => {
    renderCustomerLogin();
    expect(screen.getByTestId("login-forgot-password-link")).toBeTruthy();
  });

  it("still renders the 'Create an account' link on the customer variant", () => {
    renderCustomerLogin();
    expect(screen.getByTestId("login-goto-signup")).toBeTruthy();
  });

  it("root element carries the portal-login-page testid + variant marker", () => {
    renderCustomerLogin();
    const root = screen.getByTestId("portal-login-page");
    expect(root).toBeTruthy();
    expect(root.getAttribute("data-login-variant")).toBe("customer");
  });
});

describe("Staff login (default) · still gated by app_env (regression guard)", () => {
  it("renders <PreviewDemoLogins> when app_env=preview (unchanged from previous hotfix)", async () => {
    mockApiGet.mockImplementation(async () => ({ app_env: "preview" }));
    renderStaffLogin();
    // Wait for the /config/public fetch effect to settle and the
    // tiles to mount.
    await waitFor(
      () => expect(screen.queryByTestId("preview-demo-logins")).not.toBeNull(),
      { timeout: 3000 },
    );
  });

  it("does NOT render <PreviewDemoLogins> when app_env=production (unchanged)", async () => {
    mockApiGet.mockImplementation(async () => ({ app_env: "production" }));
    renderStaffLogin();
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/config/public"));
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
  });

  it("root element carries login-page testid + staff variant marker", () => {
    renderStaffLogin();
    const root = screen.getByTestId("login-page");
    expect(root).toBeTruthy();
    expect(root.getAttribute("data-login-variant")).toBe("staff");
  });

  it("fetches /config/public on the staff variant", async () => {
    renderStaffLogin();
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/config/public"));
  });
});

describe("Route wiring lock (source-grep guard)", () => {
  it("App.js wires /portal/login to <Login variant=\"customer\" />", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../App.js"),
      "utf-8",
    );
    expect(src.includes('/portal/login')).toBe(true);
    expect(src.match(/Login\s+variant="customer"/)).toBeTruthy();
  });
});
