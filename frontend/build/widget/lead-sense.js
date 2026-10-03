/*!
 * LS-B · Feb-2026 — MARCO Lead-Sense Tracker Widget
 *
 * Self-contained vanilla JS. No React, no framework, no cookies,
 * no external dependencies. Total minified budget: <5KB.
 *
 * Embed on tenant marketing sites via:
 *
 *   <script async defer
 *     src="https://app.plofv.com/widget/lead-sense.js"
 *     data-ls-id="XXXXXXXXXXXX"></script>
 *
 * Behavior
 * ────────
 *   1. Read ``data-ls-id`` from its own <script> tag.
 *   2. Capture page-load telemetry (URL, referrer, UA, title,
 *      viewport) and a stable, browser-scoped ``session_id`` in
 *      localStorage.
 *   3. POST once to /api/lead-sense/track. Prefers
 *      ``navigator.sendBeacon`` (survives page unload); falls
 *      back to ``fetch({ keepalive: true, credentials: "omit" })``.
 *   4. Expose ``window.MARCO_LS.track()`` so SPA route changes
 *      can fire additional intents on demand (host site opts in).
 *
 * Security posture
 * ────────────────
 * Never throws — every DOM/localStorage/fetch access is wrapped
 * in try/catch so a broken host page can't blow up the tracker
 * (and vice-versa). No PII collection beyond user-agent + IP
 * (which the server picks up from the request itself).
 *
 * Testing note: the top-level IIFE swallows an SSR path if
 * ``window`` or ``document`` is undefined so the widget file can
 * be require()'d in vitest without a JSDOM shim.
 */
(function () {
  "use strict";

  // SSR guard — vitest / node smoke tests can require() this file
  // without a DOM. Nothing to do outside a browser.
  if (typeof window === "undefined" ||
      typeof document === "undefined") {
    return;
  }
  if (window.__MARCO_LS_LOADED__) return;
  window.__MARCO_LS_LOADED__ = true;

  // ── Locate the tag that included us ─────────────────────────
  var CUR_SCRIPT = document.currentScript ||
    (function () {
      var scripts = document.getElementsByTagName("script");
      return scripts[scripts.length - 1] || null;
    })();
  if (!CUR_SCRIPT) return;

  var LS_ID = CUR_SCRIPT.getAttribute("data-ls-id") || "";
  var API_BASE = (function () {
    try {
      return new URL(CUR_SCRIPT.src).origin;
    } catch (e) { return ""; }
  })();
  if (!LS_ID || !API_BASE) return;

  var ENDPOINT = API_BASE + "/api/lead-sense/track";
  var STORAGE_KEY = "marco_ls_session";

  // ── Session id helpers ──────────────────────────────────────
  function _uuid() {
    // Prefer the standardised generator when available. Fall back
    // to a simple RFC 4122 v4 shim for older browsers.
    try {
      if (typeof window.crypto !== "undefined" &&
          typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
      }
    } catch (e) { /* fall through */ }
    // Fallback — Math.random-based UUIDv4. Not cryptographically
    // strong but adequate for a session id (server treats it as
    // an opaque token).
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(
      /[xy]/g,
      function (c) {
        var r = (Math.random() * 16) | 0;
        var v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      },
    );
  }

  function _getSessionId() {
    try {
      var existing = window.localStorage.getItem(STORAGE_KEY);
      if (existing && /^[A-Za-z0-9\-_]{8,64}$/.test(existing)) {
        return existing;
      }
    } catch (e) { /* localStorage blocked — fall through */ }
    var fresh = _uuid();
    try {
      window.localStorage.setItem(STORAGE_KEY, fresh);
    } catch (e) { /* ignore quota / disabled storage */ }
    return fresh;
  }

  // ── Payload builder ─────────────────────────────────────────
  function _viewport() {
    try {
      return {
        w: Math.max(0, window.innerWidth || 0) | 0,
        h: Math.max(0, window.innerHeight || 0) | 0,
      };
    } catch (e) { return null; }
  }

  function _payload() {
    return {
      ls_id: LS_ID,
      session_id: _getSessionId(),
      current_url: (function () {
        try { return window.location.href || ""; }
        catch (e) { return ""; }
      })(),
      referrer: (function () {
        try { return document.referrer || null; }
        catch (e) { return null; }
      })(),
      user_agent: (function () {
        try { return (navigator && navigator.userAgent) || null; }
        catch (e) { return null; }
      })(),
      page_title: (function () {
        try { return document.title || null; }
        catch (e) { return null; }
      })(),
      viewport: _viewport(),
    };
  }

  // ── Transport ───────────────────────────────────────────────
  function _send(payload) {
    var body = null;
    try { body = JSON.stringify(payload); }
    catch (e) { return; }
    // Prefer sendBeacon — survives page unload.
    try {
      if (navigator && typeof navigator.sendBeacon === "function") {
        // Use text/plain so browsers don't force a CORS preflight
        // on the beacon (Content-Type text/plain is a "CORS-safe"
        // request header). Server accepts either; body is parsed
        // as JSON via request.json() regardless.
        var blob = null;
        try {
          blob = new Blob([body], { type: "text/plain" });
        } catch (be) { blob = body; }
        var ok = navigator.sendBeacon(ENDPOINT, blob);
        if (ok) return;
      }
    } catch (e) { /* fall through to fetch */ }
    // fetch fallback — keepalive so the request survives
    // navigation, credentials omitted so we never send cookies
    // to a foreign origin. Content-Type text/plain to keep it a
    // simple (preflight-free) request.
    try {
      window.fetch(ENDPOINT, {
        method: "POST",
        keepalive: true,
        credentials: "omit",
        mode: "cors",
        headers: { "Content-Type": "text/plain" },
        body: body,
      });
    } catch (e) { /* silently swallow — tracker is best-effort */ }
  }

  function track() {
    try { _send(_payload()); }
    catch (e) { /* swallow */ }
  }

  // Expose so SPA route changes can fire an additional hit.
  window.MARCO_LS = window.MARCO_LS || {};
  window.MARCO_LS.track = track;
  window.MARCO_LS.__version = "ls-b/1.0";

  // ── Initial fire ────────────────────────────────────────────
  function _init() {
    // Defer with a microtask so any test hooking window.fetch AFTER
    // the script tag runs synchronously still sees the call.
    try { setTimeout(track, 0); }
    catch (e) { track(); }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init, { once: true });
  } else {
    _init();
  }
})();
