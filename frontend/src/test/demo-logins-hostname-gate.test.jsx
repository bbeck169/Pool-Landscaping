/**
 * Feb 2026 · Demo-login P0 Hotfix #3 — hostname-based strict gate.
 *
 * The prior gate read only the backend's ``/api/config/public.app_env``
 * value. A prod backend deployed with ``APP_ENV=preview`` +
 * ``SHOW_DEMO_LOGINS=true`` in ``.env`` leaked the demo tiles to a
 * live customer domain (``app.plofv.com``).
 *
 * New behavior: even when the server reports the tiles are allowed,
 * the client refuses to render them unless the current hostname is a
 * preview / dev host. Belt AND suspenders — a wrong-env server can
 * no longer override the hostname check.
 *
 * These three cases exercise the outer hostname gate specifically:
 *   1. ``*.preview.emergentagent.com`` + server=allowed → render.
 *   2. ``app.plofv.com`` + server=allowed → hidden (this is the P0).
 *   3. Some random ``.com`` + server=allowed → hidden.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks (mirror the sibling ``portal-login-hides-demo-tiles`` test) ─
vi.mock("@/auth", () => ({
  useAuth: () => ({ login: vi.fn(), me: async () => null }),
}));
vi.mock("@/theme", () => ({
  gradients: { navyToGreen: { css: "linear-gradient(#000,#111)" } },
  colors: {
    brand: "#0f6ed1", muted: "#666", onSurface: "#111",
    surface: "#fff", surfaceSecondary: "#f5f5f5", border: "#ccc",
    onSurfaceSecondary: "#444", error: "#a10", input: "#fff",
  },
  font: { family: "system-ui", mono: "monospace" },
}));
// Server ALWAYS says demo tiles are allowed — the whole point of the
// three tests is to prove the client-side hostname gate refuses on
// production hosts anyway.
const mockApiGet = vi.fn(async (path) => {
  if (path === "/config/features") return { demo_logins_enabled: true };
  if (path === "/config/public") return { app_env: "preview" };
  return {};
});
vi.mock("@/api", () => ({ api: { get: (...args) => mockApiGet(...args) } }));

// eslint-disable-next-line import/first
import Login from "@/pages/Login";

function _setHostname(host) {
  // jsdom won't let us reassign ``window.location`` outright; replace
  // it with a plain object exposing the fields we care about.
  const _origin = `https://${host}`;
  const stub = {
    hostname: host,
    origin: _origin,
    href: `${_origin}/login`,
    pathname: "/login",
    search: "",
    hash: "",
    assign: vi.fn(),
    replace: vi.fn(),
  };
  Object.defineProperty(window, "location", {
    configurable: true, writable: true, value: stub,
  });
}

function renderStaffLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Login />
    </MemoryRouter>,
  );
}

beforeEach(() => { mockApiGet.mockClear(); });
afterEach(() => { mockApiGet.mockClear(); });

describe("Login · demo-tiles hostname strict gate", () => {
  it("renders tiles on *.preview.emergentagent.com even when server flag flips", async () => {
    _setHostname("poolscape-audit.preview.emergentagent.com");
    renderStaffLogin();
    await waitFor(
      () => expect(screen.queryByTestId("preview-demo-logins")).not.toBeNull(),
      { timeout: 500 },
    );
  });

  it("does NOT render tiles on app.plofv.com even though server says enabled", async () => {
    _setHostname("app.plofv.com");
    renderStaffLogin();
    // Give the effect time to resolve.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
    expect(screen.queryByText(/DEMO LOGINS/i)).toBeNull();
    expect(screen.queryByTestId("demo-login-super")).toBeNull();
  });

  it("does NOT render tiles on any random production host", async () => {
    _setHostname("some-random-domain.com");
    renderStaffLogin();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("preview-demo-logins")).toBeNull();
    expect(screen.queryByTestId("demo-login-super")).toBeNull();
  });
});
