/**
 * Feb-2026 · Magic-link staff-header shadowing fix — Vitest for the
 * ``authHeaders(outboundPath)`` gate in ``api.js``.
 *
 * Contract:
 *   • A ``/portal/*`` outbound call is a MAGIC-LINK call when the URL
 *     carries its own credential (either ``?token=`` in the query
 *     string or ``/via-token/…`` in the path segment). On those
 *     calls NO client-side session header may attach — no
 *     ``Authorization`` and no ``X-Tenant-Slug``. The URL-borne
 *     credential is authoritative.
 *   • Authenticated customer-portal ``/portal/*`` calls (no magic-link
 *     marker in the URL) preserve the pre-fix behaviour: attach the
 *     ``localStorage.token`` (or the K13 impersonation
 *     ``sessionStorage.portal_token`` when on a ``/portal`` page) and
 *     the ``X-Tenant-Slug`` when present.
 *   • Non-``/portal/*`` calls are unchanged.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

let realLocation;

function mockLocation(pathname = "/") {
  const fakeLoc = {
    pathname,
    search: "",
    assign: vi.fn(),
    origin: "http://localhost:3000",
    href: `http://localhost:3000${pathname}`,
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

function mockJsonOnce(body = {}, status = 200) {
  global.fetch = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

async function importFreshApi() {
  vi.resetModules();
  return await import("@/api");
}

function outboundHeaders() {
  // ``global.fetch`` is invoked as ``fetch(url, { headers, ... })``.
  // The wrapper spreads ``authHeaders(...)`` into the ``headers`` object
  // (a plain object, not a Headers instance), so we can inspect it
  // directly.
  const call = global.fetch.mock.calls[0];
  return (call && call[1] && call[1].headers) || {};
}

describe("api.js · authHeaders(outboundPath) portal-gate · magic-link fix", () => {
  beforeEach(() => {
    realLocation = window.location;
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  afterEach(() => {
    restoreLocation();
    window.localStorage.clear();
    window.sessionStorage.clear();
    delete global.fetch;
  });

  it("Case 1 · /portal/quotes/via-token?token=… with staff JWT in localStorage → NO Authorization, NO X-Tenant-Slug", async () => {
    mockLocation("/e/estimate");
    window.localStorage.setItem("token", "staff-jwt-value");
    window.localStorage.setItem("tenant_slug", "acme");
    mockJsonOnce({ ok: true }, 200);
    const { api } = await importFreshApi();

    await api.get("/portal/quotes/via-token?token=abc");

    const headers = outboundHeaders();
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Tenant-Slug"]).toBeUndefined();
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("Case 2 · /portal/tenant/branding?token=… with staff JWT in localStorage → NO Authorization, NO X-Tenant-Slug", async () => {
    mockLocation("/e/estimate");
    window.localStorage.setItem("token", "staff-jwt-value");
    window.localStorage.setItem("tenant_slug", "acme");
    mockJsonOnce({ branding: {} }, 200);
    const { api } = await importFreshApi();

    await api.get("/portal/tenant/branding?token=abc");

    const headers = outboundHeaders();
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Tenant-Slug"]).toBeUndefined();
  });

  it("Case 3 · /quotes/xyz (staff endpoint) with staff JWT in localStorage → Authorization + X-Tenant-Slug attached", async () => {
    mockLocation("/quotes");
    window.localStorage.setItem("token", "staff-jwt-value");
    window.localStorage.setItem("tenant_slug", "acme");
    mockJsonOnce({ id: "xyz" }, 200);
    const { api } = await importFreshApi();

    await api.get("/quotes/xyz");

    const headers = outboundHeaders();
    expect(headers.Authorization).toBe("Bearer staff-jwt-value");
    expect(headers["X-Tenant-Slug"]).toBe("acme");
  });

  it("Case 4 · authenticated customer portal (page /portal/dashboard, sessionStorage.portal_token set, staff JWT also in localStorage) → portal_token wins, staff JWT does NOT shadow it", async () => {
    // This case exercises the K13 impersonation preference AND the
    // magic-link fix at the same time: on /portal/customers/me (no
    // magic-link marker in the URL) the wrapper falls through to the
    // pre-existing behaviour, which prefers sessionStorage.portal_token
    // over localStorage.token on /portal pages. The critical assertion
    // is that the STAFF JWT in localStorage never wins.
    mockLocation("/portal/dashboard");
    window.localStorage.setItem("token", "staff-jwt-value");
    window.localStorage.setItem("tenant_slug", "acme");
    window.sessionStorage.setItem("portal_token", "portal-jwt-value");
    mockJsonOnce({ me: {} }, 200);
    const { api } = await importFreshApi();

    await api.get("/portal/customers/me");

    const headers = outboundHeaders();
    expect(headers.Authorization).toBe("Bearer portal-jwt-value");
    // K13 contract: X-Tenant-Slug still attaches on non-magic-link
    // portal calls when present in localStorage.
    expect(headers["X-Tenant-Slug"]).toBe("acme");
  });

  it("Case 5 · POST /portal/quotes/via-token/{tok}/approve with staff JWT in localStorage → NO Authorization header", async () => {
    mockLocation("/e/estimate");
    window.localStorage.setItem("token", "staff-jwt-value");
    window.localStorage.setItem("tenant_slug", "acme");
    mockJsonOnce({ ok: true }, 200);
    const { api } = await importFreshApi();

    await api.post(
      "/portal/quotes/via-token/some.magic.token/approve",
      {},
    );

    const headers = outboundHeaders();
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Tenant-Slug"]).toBeUndefined();
    // Body still went through the wrapper normally.
    expect(global.fetch.mock.calls[0][1].method).toBe("POST");
  });
});
