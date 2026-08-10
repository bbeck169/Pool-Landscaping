/**
 * Aug-2026 · Fix P2 · api.js error-unwrap fallback extension.
 *
 * Contract:
 *   • ``{detail: {error: "service_category_required", ...}}`` — since
 *     Fix P2 adds ``msg.error`` to the fallback chain in api.js,
 *     the thrown Error.message must be ``"service_category_required"``
 *     — NOT ``"Request failed (400)"``.
 *   • Fully unknown detail shapes (``{detail: {random_key: 1}}``)
 *     still land on the generic ``Request failed (<status>)`` message
 *     — locked so future refactors don't accidentally over-match.
 *   • Fix #1 (401 zombie-session interceptor) is untouched — a 401
 *     with ``{detail: "Token expired"}`` still clears session + throws
 *     ``"Token expired"``.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

let realLocation;
let assignMock;

function mockLocation(pathname = "/dashboard") {
  assignMock = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true, writable: true,
    value: { pathname, search: "", assign: assignMock,
              origin: "http://localhost:3000", href: `http://localhost:3000${pathname}` },
  });
}
function restoreLocation() {
  if (realLocation) {
    Object.defineProperty(window, "location", {
      configurable: true, writable: true, value: realLocation,
    });
  }
}

function mockFetchOnce({ status, body }) {
  global.fetch = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

async function importFreshApi() {
  vi.resetModules();
  const mod = await import("@/api");
  return mod;
}

describe("api.js · Fix P2 · error unwrap fallback to detail.error", () => {
  beforeEach(() => {
    realLocation = window.location;
    window.localStorage.clear();
    window.localStorage.setItem("token", "fresh-jwt");
    mockLocation("/ops/pricebook");
  });
  afterEach(() => {
    restoreLocation();
    window.localStorage.clear();
    delete global.fetch;
  });

  it("400 with detail={error: 'service_category_required'} surfaces the error string", async () => {
    mockFetchOnce({
      status: 400,
      body: {
        detail: {
          error: "service_category_required",
          field: "service_category_id",
          available_categories: ["Pool", "Landscaping"],
        },
      },
    });
    const { api } = await importFreshApi();

    let caught;
    try { await api.post("/items", { name: "x" }); }
    catch (e) { caught = e; }

    expect(caught).toBeDefined();
    // Fix P2 — must NOT fall through to the generic message.
    expect(caught.message).toBe("service_category_required");
    expect(caught.message).not.toBe("Request failed (400)");
    expect(caught.status).toBe(400);
  });

  it("Fix #1 · 401 with detail='Token expired' still clears + redirects (regression guard)", async () => {
    mockFetchOnce({
      status: 401,
      body: { detail: "Token expired" },
    });
    const { api } = await importFreshApi();

    await expect(api.get("/x")).rejects.toThrow("Token expired");
    expect(window.localStorage.getItem("token")).toBeNull();
    expect(assignMock).toHaveBeenCalled();
  });

  it("400 with a totally unknown detail object still falls through to 'Request failed (400)'", async () => {
    mockFetchOnce({
      status: 400,
      body: { detail: { random_key: 1, other_key: "x" } },
    });
    const { api } = await importFreshApi();

    let caught;
    try { await api.post("/x"); }
    catch (e) { caught = e; }
    expect(caught.message).toBe("Request failed (400)");
  });

  it("400 with detail={msg: 'A'} still prefers msg over error (order preserved)", async () => {
    mockFetchOnce({
      status: 400,
      body: { detail: { msg: "A", error: "B" } },
    });
    const { api } = await importFreshApi();

    let caught;
    try { await api.post("/x"); }
    catch (e) { caught = e; }
    expect(caught.message).toBe("A"); // msg wins over error per the chain order.
  });
});
