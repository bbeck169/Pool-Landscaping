/**
 * Phase K13 · Feb-2026 — impersonation flow client-side contracts.
 *
 * 1. Portal shell reads ``?impersonation_token=<jwt>`` from URL,
 *    pins to sessionStorage, strips the query param.
 * 2. api.js prefers ``sessionStorage["portal_token"]`` over
 *    ``localStorage["token"]`` on ``/portal/*`` routes.
 * 3. Normal admin routes fall back to localStorage.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("Phase K13 · portal impersonation token wiring", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });
  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.resetModules();
  });

  it("api.js authHeaders prefers sessionStorage['portal_token'] on /portal/* routes", async () => {
    sessionStorage.setItem("portal_token", "IMP-JWT-XYZ");
    localStorage.setItem("token", "ADMIN-JWT-ABC");
    Object.defineProperty(window, "location", {
      value: new URL("http://localhost/portal/home"),
      writable: true,
    });
    // Spy on fetch to capture the header.
    let capturedAuth = null;
    global.fetch = vi.fn(async (_url, init) => {
      capturedAuth = init?.headers?.Authorization;
      return { ok: true, status: 200, headers: new Map(),
                text: async () => "{}",
                json: async () => ({}) };
    });
    const { api } = await import("@/api");
    await api.get("/portal/me");
    expect(capturedAuth).toBe("Bearer IMP-JWT-XYZ");
  });

  it("api.js authHeaders falls back to localStorage['token'] on admin routes", async () => {
    sessionStorage.setItem("portal_token", "IMP-JWT-XYZ");
    localStorage.setItem("token", "ADMIN-JWT-ABC");
    Object.defineProperty(window, "location", {
      value: new URL("http://localhost/customers/some-id"),
      writable: true,
    });
    let capturedAuth = null;
    global.fetch = vi.fn(async (_url, init) => {
      capturedAuth = init?.headers?.Authorization;
      return { ok: true, status: 200, headers: new Map(),
                text: async () => "{}",
                json: async () => ({}) };
    });
    const { api } = await import("@/api");
    await api.get("/customers");
    expect(capturedAuth).toBe("Bearer ADMIN-JWT-ABC");
  });

  it("api.js authHeaders on /portal/* with no sessionStorage still uses localStorage", async () => {
    localStorage.setItem("token", "REAL-CUSTOMER-JWT");
    Object.defineProperty(window, "location", {
      value: new URL("http://localhost/portal/home"),
      writable: true,
    });
    let capturedAuth = null;
    global.fetch = vi.fn(async (_url, init) => {
      capturedAuth = init?.headers?.Authorization;
      return { ok: true, status: 200, headers: new Map(),
                text: async () => "{}",
                json: async () => ({}) };
    });
    const { api } = await import("@/api");
    await api.get("/portal/me");
    expect(capturedAuth).toBe("Bearer REAL-CUSTOMER-JWT");
  });
});
