/**
 * Feb-2026 · P7 hotfix — pins the ``api.delete`` verb.
 *
 * Prod-surfaced bug (verbatim from user):
 *
 *   Disconnect failed: Xt.api.delete is not a function
 *
 * ``Xt`` is the minified module handle for ``src/api.js``. The client
 * exposed ``.del()`` but not ``.delete()``; every call site that
 * wrote ``api.delete(...)`` (10+ places, incl. the Homeworks
 * IntegrationCard Disconnect handler) blew up in production.
 *
 * Pins:
 *   1. ``api.delete`` is a function (API-verb parity with get/post).
 *   2. Calling ``api.delete("/foo")`` fires the underlying request
 *      wrapper with ``method: DELETE`` and the ``/api`` prefix intact.
 *   3. ``api.del`` STILL exists (legacy call sites use it).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("api.delete verb (P7 hotfix)", () => {
  const _fetch = global.fetch;

  beforeEach(() => {
    // Wire process.env.REACT_APP_BACKEND_URL for the api.js constant.
    process.env.REACT_APP_BACKEND_URL = "https://test.example";
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true }),
    }));
    // localStorage lands the (empty) auth token — no bearer header.
    localStorage.clear();
  });

  afterEach(() => {
    global.fetch = _fetch;
    vi.resetModules();
  });

  it("exposes api.delete as a function", async () => {
    const { api } = await import("@/api");
    expect(typeof api.delete).toBe("function");
  });

  it("keeps api.del as legacy alias", async () => {
    const { api } = await import("@/api");
    expect(typeof api.del).toBe("function");
  });

  it("api.delete(path) hits the correct URL with method DELETE", async () => {
    const { api } = await import("@/api");
    // Feb-2026 · K55.a — old assertion used the Homeworks disconnect
    // URL as a canonical DELETE example; the endpoint was retired
    // in the sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md).  Any
    // path exercises the DELETE verb wrapper equivalently.
    await api.delete("/customers/example-id");
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("https://test.example/api/customers/example-id");
    expect(opts.method).toBe("DELETE");
  });

  it("api.delete + api.del route through the same DELETE wrapper", async () => {
    const { api } = await import("@/api");
    await api.delete("/x");
    await api.del("/x");
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(global.fetch.mock.calls[0][1].method).toBe("DELETE");
    expect(global.fetch.mock.calls[1][1].method).toBe("DELETE");
  });
});
