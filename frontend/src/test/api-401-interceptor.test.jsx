/**
 * Feb-2026 · Zombie-session hotfix — Vitest for the api.js 401 interceptor.
 *
 * Contract (per Fix A):
 *   • When ``fetch`` returns 401 with detail in the AUTH_401_DETAILS set
 *     AND we're on a normal in-app path, clear session localStorage keys
 *     and call ``window.location.assign("/login?reason=expired&from=…")``.
 *   • When ``fetch`` returns 401 on a session-safe path (/login, /portal,
 *     /public, /signup, /forgot-password, /reset-password), do NOT touch
 *     the session or redirect — just throw the error as before.
 *   • When ``fetch`` returns 401 with a NON-auth detail (e.g. rate-limit
 *     sentinel), do NOT touch the session or redirect.
 *   • The thrown Error carries ``.status`` for callers that want to key
 *     off the numeric code without regexing the message.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Preserve real ``window.location`` so we can restore it after each test.
let realLocation;
let assignMock;

function mockLocation(pathname = "/", search = "") {
  assignMock = vi.fn();
  const fakeLoc = {
    pathname,
    search,
    assign: assignMock,
    // preserve the origin for URL constructor sanity (unused by the fix)
    origin: "http://localhost:3000",
    href: `http://localhost:3000${pathname}${search}`,
  };
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: fakeLoc,
  });
}

function restoreLocation() {
  if (realLocation) {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: realLocation,
    });
  }
}

function mockFetchOnce({ status, detail }) {
  global.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ detail }), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

async function importFreshApi() {
  // Fresh module registry so the module-level ``AUTH_401_DETAILS`` set +
  // helpers re-evaluate against the current mocked ``window.location``.
  // vi.resetModules is a nop for un-touched deps; only api.js re-loads.
  vi.resetModules();
  const mod = await import("@/api");
  return mod;
}

describe("api.js · 401 interceptor · Fix A", () => {
  beforeEach(() => {
    realLocation = window.location;
    window.localStorage.clear();
    window.localStorage.setItem("token", "stale-jwt");
    window.localStorage.setItem("user", JSON.stringify({ id: "u1" }));
    window.localStorage.setItem("tenant_slug", "acme");
    window.localStorage.setItem("tenant_name", "Acme");
  });

  afterEach(() => {
    restoreLocation();
    window.localStorage.clear();
    delete global.fetch;
  });

  it("401 'Token expired' on a normal path → clears session + redirects to /login?reason=expired", async () => {
    mockLocation("/dashboard", "");
    mockFetchOnce({ status: 401, detail: "Token expired" });
    const { api } = await importFreshApi();

    await expect(api.get("/admin/dashboard/revenue-by-category")).rejects.toThrow(
      "Token expired",
    );

    expect(window.localStorage.getItem("token")).toBeNull();
    expect(window.localStorage.getItem("user")).toBeNull();
    expect(window.localStorage.getItem("tenant_slug")).toBeNull();
    expect(window.localStorage.getItem("tenant_name")).toBeNull();
    expect(assignMock).toHaveBeenCalledTimes(1);
    expect(assignMock.mock.calls[0][0]).toContain("/login?reason=expired");
    expect(assignMock.mock.calls[0][0]).toContain("from=");
  });

  it("401 'Invalid token' on a normal path → same redirect + clear", async () => {
    mockLocation("/customers", "");
    mockFetchOnce({ status: 401, detail: "Invalid token" });
    const { api } = await importFreshApi();

    await expect(api.get("/customers")).rejects.toThrow("Invalid token");
    expect(window.localStorage.getItem("token")).toBeNull();
    expect(assignMock).toHaveBeenCalledTimes(1);
  });

  it("401 'Account is deactivated' → clears + redirects", async () => {
    mockLocation("/schedule", "");
    mockFetchOnce({ status: 401, detail: "Account is deactivated" });
    const { api } = await importFreshApi();

    await expect(api.get("/jobs")).rejects.toThrow("Account is deactivated");
    expect(window.localStorage.getItem("token")).toBeNull();
    expect(assignMock).toHaveBeenCalledTimes(1);
  });

  it("401 'account_deleted' → clears + redirects", async () => {
    mockLocation("/team", "");
    mockFetchOnce({ status: 401, detail: "account_deleted" });
    const { api } = await importFreshApi();

    await expect(api.get("/team")).rejects.toThrow("account_deleted");
    expect(window.localStorage.getItem("token")).toBeNull();
    expect(assignMock).toHaveBeenCalledTimes(1);
  });

  it("401 already on /login → does NOT clear or redirect (loop guard)", async () => {
    mockLocation("/login", "?reason=expired");
    mockFetchOnce({ status: 401, detail: "Token expired" });
    const { api } = await importFreshApi();

    await expect(api.get("/config/public")).rejects.toThrow("Token expired");
    // Session preserved so the login page banner logic can read it.
    expect(window.localStorage.getItem("token")).toBe("stale-jwt");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("401 on /portal/* magic-link path → does NOT clear staff session", async () => {
    mockLocation("/portal/preferences", "?token=magic-abc");
    mockFetchOnce({ status: 401, detail: "Token expired" });
    const { api } = await importFreshApi();

    await expect(
      api.get("/portal/preferences/context?token=magic-abc"),
    ).rejects.toThrow("Token expired");
    expect(window.localStorage.getItem("token")).toBe("stale-jwt");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("401 on /public/* → does NOT clear or redirect", async () => {
    mockLocation("/public/invoice/inv_123", "?token=magic");
    mockFetchOnce({ status: 401, detail: "Token expired" });
    const { api } = await importFreshApi();

    await expect(api.get("/invoices/inv_123/full-magic?token=magic")).rejects.toThrow(
      "Token expired",
    );
    expect(window.localStorage.getItem("token")).toBe("stale-jwt");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("401 with a NON-auth detail (e.g. 'rate_limited') → does NOT clear or redirect", async () => {
    mockLocation("/dashboard", "");
    mockFetchOnce({ status: 401, detail: "rate_limited" });
    const { api } = await importFreshApi();

    await expect(api.get("/some/endpoint")).rejects.toThrow("rate_limited");
    // Session must be untouched — this is a non-auth 401 sentinel.
    expect(window.localStorage.getItem("token")).toBe("stale-jwt");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("thrown Error carries .status = 401 for callers that key off it", async () => {
    mockLocation("/dashboard", "");
    mockFetchOnce({ status: 401, detail: "Token expired" });
    const { api } = await importFreshApi();

    let caught;
    try {
      await api.get("/x");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeDefined();
    expect(caught.status).toBe(401);
  });

  it("500 error path is unaffected — no clear, no redirect", async () => {
    mockLocation("/dashboard", "");
    mockFetchOnce({ status: 500, detail: "internal error" });
    const { api } = await importFreshApi();

    await expect(api.get("/x")).rejects.toThrow("internal error");
    expect(window.localStorage.getItem("token")).toBe("stale-jwt");
    expect(assignMock).not.toHaveBeenCalled();
  });
});
