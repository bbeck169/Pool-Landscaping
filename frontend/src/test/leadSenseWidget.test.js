/**
 * LS-B · Feb-2026 — MARCO Lead-Sense tracker widget tests.
 *
 * Locks the five acceptance cases for the vanilla-JS widget at
 * ``frontend/public/widget/lead-sense.js``:
 *
 *   (a) Reads ``data-ls-id`` from its own <script> tag.
 *   (b) Generates + persists a stable session_id in localStorage.
 *   (c) POSTs to ``<script origin>/api/lead-sense/track`` with
 *       the expected payload shape.
 *   (d) Prefers ``navigator.sendBeacon`` when available; falls
 *       back to ``fetch({keepalive: true, credentials: "omit"})``.
 *   (e) Never throws on missing DOM APIs (SSR-safe — the top-level
 *       IIFE early-returns when window/document are undefined).
 *
 * Test seam: the widget IIFE runs once at module import. We
 * re-execute it manually against a JSDOM ``<script>`` fixture
 * for each test by resetting ``window.__MARCO_LS_LOADED__`` and
 * re-evaluating the source via ``new Function()``.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WIDGET_PATH = path.resolve(
  __dirname, "..", "..", "public", "widget", "lead-sense.js",
);
const WIDGET_SRC = fs.readFileSync(WIDGET_PATH, "utf-8");


function _mountWidget({ lsId, backendOrigin, ready = true } = {}) {
  // Reset the load-once sentinel so the IIFE re-executes.
  delete window.__MARCO_LS_LOADED__;
  delete window.MARCO_LS;
  // Simulate the <script data-ls-id="...">.
  const scriptEl = document.createElement("script");
  scriptEl.setAttribute("data-ls-id", lsId || "ABCDEFGHIJKL");
  scriptEl.src = (backendOrigin || "https://app.example.com") + "/widget/lead-sense.js";
  document.head.appendChild(scriptEl);
  // Point document.currentScript at our stub for the IIFE's read.
  Object.defineProperty(document, "currentScript", {
    value: scriptEl,
    configurable: true,
  });
  // Force document.readyState so the immediate-init path fires.
  Object.defineProperty(document, "readyState", {
    value: ready ? "complete" : "loading",
    configurable: true,
  });
  // Execute the widget source.
  // eslint-disable-next-line no-new-func
  new Function(WIDGET_SRC)();
  return scriptEl;
}


describe("MARCO Lead-Sense widget", () => {
  beforeEach(() => {
    // Clean DOM + globals between tests.
    document.head.innerHTML = "";
    document.body.innerHTML = "";
    try { window.localStorage.clear(); } catch { /* ignore */ }
    delete window.__MARCO_LS_LOADED__;
    delete window.MARCO_LS;
  });

  // ── (a) reads data-ls-id ──────────────────────────────────
  it("(a) reads the data-ls-id attribute from its own <script> tag "
     + "and exposes window.MARCO_LS.track for SPA use", () => {
    // Stub navigator.sendBeacon so the IIFE doesn't error out.
    const beacon = vi.fn().mockReturnValue(true);
    Object.defineProperty(navigator, "sendBeacon", {
      value: beacon, configurable: true, writable: true,
    });
    _mountWidget({ lsId: "MyTenantID42" });
    // The IIFE deferred the first fire via setTimeout(fn, 0).
    // Flush it.
    return new Promise((resolve) => setTimeout(() => {
      expect(beacon).toHaveBeenCalledTimes(1);
      const [url, body] = beacon.mock.calls[0];
      expect(url).toBe(
        "https://app.example.com/api/lead-sense/track",
      );
      // Body is a Blob (text/plain). Content assertions covered
      // by test (c) via the fetch fallback path — here we just
      // confirm the beacon was called with a truthy body.
      expect(body).toBeTruthy();
      // Global exposure.
      expect(typeof window.MARCO_LS.track).toBe("function");
      expect(window.MARCO_LS.__version).toMatch(/ls-b/);
      resolve();
    }, 10));
  });

  // ── (b) session_id persisted in localStorage ──────────────
  it("(b) generates and persists a session_id in localStorage under "
     + "the marco_ls_session key; a second call reuses the same id", () => {
    Object.defineProperty(navigator, "sendBeacon", {
      value: vi.fn().mockReturnValue(true),
      configurable: true, writable: true,
    });
    _mountWidget();
    return new Promise((resolve) => setTimeout(() => {
      const stored = window.localStorage.getItem("marco_ls_session");
      expect(stored).toBeTruthy();
      expect(stored.length).toBeGreaterThanOrEqual(8);
      expect(/^[A-Za-z0-9\-_]{8,64}$/.test(stored)).toBe(true);
      // Second track() call reuses the same id.
      window.MARCO_LS.track();
      const after = window.localStorage.getItem("marco_ls_session");
      expect(after).toBe(stored);
      resolve();
    }, 10));
  });

  // ── (c) POST payload shape ────────────────────────────────
  it("(c) POSTs the full payload shape to the expected endpoint via "
     + "the fetch fallback when sendBeacon is unavailable", () => {
    // Remove sendBeacon so fetch fallback fires.
    Object.defineProperty(navigator, "sendBeacon", {
      value: undefined, configurable: true, writable: true,
    });
    // Stub fetch.
    const fetchMock = vi.fn().mockResolvedValue({ status: 204 });
    window.fetch = fetchMock;
    _mountWidget({
      lsId: "LSID-shape-test",
      backendOrigin: "https://api.marco.test",
    });
    return new Promise((resolve) => setTimeout(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(url).toBe(
        "https://api.marco.test/api/lead-sense/track",
      );
      expect(init.method).toBe("POST");
      expect(init.keepalive).toBe(true);
      expect(init.credentials).toBe("omit");
      expect(init.mode).toBe("cors");
      expect(init.headers["Content-Type"]).toBe("text/plain");
      const payload = JSON.parse(init.body);
      expect(payload.ls_id).toBe("LSID-shape-test");
      expect(typeof payload.session_id).toBe("string");
      expect(payload.session_id.length).toBeGreaterThanOrEqual(8);
      expect(typeof payload.current_url).toBe("string");
      expect(payload.viewport).toEqual(
        expect.objectContaining({ w: expect.any(Number),
                                    h: expect.any(Number) }),
      );
      resolve();
    }, 10));
  });

  // ── (d) sendBeacon preferred ─────────────────────────────
  it("(d) prefers navigator.sendBeacon when available; fetch is NOT "
     + "called on the initial fire", () => {
    const beacon = vi.fn().mockReturnValue(true);
    Object.defineProperty(navigator, "sendBeacon", {
      value: beacon, configurable: true, writable: true,
    });
    const fetchMock = vi.fn().mockResolvedValue({ status: 204 });
    window.fetch = fetchMock;
    _mountWidget();
    return new Promise((resolve) => setTimeout(() => {
      expect(beacon).toHaveBeenCalledTimes(1);
      expect(fetchMock).not.toHaveBeenCalled();
      resolve();
    }, 10));
  });

  it("(d2) falls back to fetch when sendBeacon returns false "
     + "(beacon queue full)", () => {
    const beacon = vi.fn().mockReturnValue(false);
    Object.defineProperty(navigator, "sendBeacon", {
      value: beacon, configurable: true, writable: true,
    });
    const fetchMock = vi.fn().mockResolvedValue({ status: 204 });
    window.fetch = fetchMock;
    _mountWidget();
    return new Promise((resolve) => setTimeout(() => {
      expect(beacon).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      resolve();
    }, 10));
  });

  // ── (e) SSR-safe early return ─────────────────────────────
  it("(e) never throws when eval'd — module load path is defensive", () => {
    // Just ensure the source itself doesn't throw when parsed +
    // executed. The IIFE will run against jsdom's window; that's
    // fine, we're locking that the top-level try/catch envelope
    // holds even with a benign DOM.
    expect(() => {
      // eslint-disable-next-line no-new-func
      new Function(WIDGET_SRC)();
    }).not.toThrow();
  });
});
