/**
 * Feb-2026 · Diag-Timeout Task 2 — Vitest for the client-side timeout
 * telemetry POST fired from api.js when the 30 s fetch AbortController
 * trips.
 *
 * Contract:
 *   • On AbortError from fetch, api.js MUST call
 *     ``fetch("/api/admin/client-telemetry/timeout", ...)`` with a JSON
 *     body containing request_url, request_method, duration_ms,
 *     route_path, user_agent, request_id.
 *   • The telemetry POST is fire-and-forget: a rejection from the
 *     telemetry fetch (server 500 / network error) MUST NOT swallow
 *     or alter the surfaced "Request timed out — check your connection
 *     and try again." Error thrown to the caller.
 *   • No telemetry POST when the user has no JWT in localStorage
 *     (anonymous session) — spec §2.3.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

function mockLocation(pathname = "/customers") {
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: {
      pathname,
      search: "",
      assign: vi.fn(),
      origin: "http://localhost:3000",
      href: `http://localhost:3000${pathname}`,
    },
  });
}

async function importFreshApi() {
  vi.resetModules();
  return await import("../api.js");
}

describe("api.js timeout telemetry", () => {
  beforeEach(() => {
    localStorage.clear();
    mockLocation("/customers");
  });
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("POSTs telemetry to /admin/client-telemetry/timeout on AbortError when a JWT is present", async () => {
    localStorage.setItem("token", "test-jwt");
    localStorage.setItem("tenant_slug", "aquaterra");

    // First call = the target request that aborts. Second call = the
    // telemetry POST. Vitest lets us script both via mockImplementation.
    const fetchMock = vi.fn()
      .mockImplementationOnce(async () => {
        const err = new Error("The user aborted a request.");
        err.name = "AbortError";
        throw err;
      })
      .mockImplementationOnce(async () =>
        new Response(JSON.stringify({ ok: true }), { status: 201 }),
      );
    global.fetch = fetchMock;

    const { api } = await importFreshApi();
    await expect(api.get("/customers?search=lynn")).rejects.toThrow(
      /Request timed out/i,
    );

    // Wait a microtask so the fire-and-forget telemetry fetch enqueues.
    await new Promise((r) => setTimeout(r, 5));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const telemetryUrl = fetchMock.mock.calls[1][0];
    const telemetryOpts = fetchMock.mock.calls[1][1] || {};
    expect(telemetryUrl).toMatch(/\/api\/admin\/client-telemetry\/timeout$/);
    expect(telemetryOpts.method).toBe("POST");
    expect(telemetryOpts.headers.Authorization).toBe("Bearer test-jwt");
    expect(telemetryOpts.headers["X-Tenant-Slug"]).toBe("aquaterra");
    const body = JSON.parse(telemetryOpts.body);
    expect(body.request_method).toBe("GET");
    expect(body.request_url).toMatch(/\/api\/customers\?search=lynn$/);
    expect(body.route_path).toBe("/customers");
    expect(typeof body.duration_ms).toBe("number");
  });

  it("skips telemetry POST when no JWT is present (anonymous session)", async () => {
    // No token in localStorage.
    const fetchMock = vi.fn()
      .mockImplementationOnce(async () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      });
    global.fetch = fetchMock;

    const { api } = await importFreshApi();
    await expect(api.get("/customers")).rejects.toThrow(/Request timed out/i);

    // Only ONE fetch call (the aborted target). No telemetry follow-up.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still surfaces the timeout Error even when the telemetry POST rejects", async () => {
    localStorage.setItem("token", "test-jwt");

    const fetchMock = vi.fn()
      .mockImplementationOnce(async () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      })
      .mockImplementationOnce(async () => {
        throw new Error("telemetry network failure");
      });
    global.fetch = fetchMock;

    const { api } = await importFreshApi();
    await expect(api.get("/customers")).rejects.toThrow(/Request timed out/i);

    // Both fetches were attempted; the second failure MUST NOT surface.
    await new Promise((r) => setTimeout(r, 5));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
