/**
 * Phase P52 · Feb-2026 — i18n detector chain tenant-fallback wire.
 *
 * The detector chain in ``i18n/index.js`` (P52-wired) is:
 *   1. ``lang-localstorage``       — user personal pref.
 *   2. ``lang-tenant-default``     — tenant admin's chosen default
 *                                    (hydrated by auth.jsx from
 *                                    /auth/me.tenant_default_locale
 *                                    into localStorage on prior boot).
 *   3. ``navigator``               — browser language.
 *   4. ``fallbackLng`` ("en").
 *
 * These tests exercise the two P52-added detectors by driving
 * ``localStorage`` directly + calling ``i18n.changeLanguage`` /
 * ``i18n.detector.detect`` to observe the resolution.  We do NOT
 * mount ``<App />`` — the detector is a pure function of
 * localStorage + navigator + supportedLngs.
 */
import { describe, it, expect, beforeAll, afterEach } from "vitest";
import fs from "fs";
import path from "path";

// Eager-import so the singleton is initialised for the worker.
import i18n from "@/i18n";


const _readIndex = () =>
  fs.readFileSync(
    path.resolve(__dirname, "../i18n/index.js"),
    "utf-8",
  );


beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  try {
    window.localStorage.removeItem("lang");
    window.localStorage.removeItem("tenant_default_locale");
  } catch { /* jsdom */ }
});


describe("P52 · i18n detector chain wiring", () => {
  it("registers the lang-tenant-default detector in i18n/index.js " +
     "AND slots it between lang-localstorage and navigator in the " +
     "detection order", () => {
    const src = _readIndex();
    // Detector defined.
    expect(src).toMatch(
      /addDetector\(\{\s*name:\s*"lang-tenant-default"/,
    );
    // Reads localStorage.tenant_default_locale.
    expect(src).toMatch(
      /window\.localStorage\s*\.\s*getItem\(["']tenant_default_locale["']\)/,
    );
    // Guards against out-of-bundle values (only returns en/es/fr).
    expect(src).toMatch(/\["en",\s*"es",\s*"fr"\]\s*\.\s*includes/);
    // Order includes the tenant rung between local + navigator.
    expect(src).toMatch(
      /order:\s*\[\s*"lang-localstorage",\s*"lang-tenant-default",\s*"navigator"\s*\]/,
    );
    // Marker that the P50 TODO comment was removed / superseded —
    // the ``TODO(P52)`` block should NOT still be in the file.
    expect(src.includes("TODO(P52)")).toBe(false);
  });
});


describe("P52 · Detector chain runtime resolution", () => {
  it("USER PREF WINS: when localStorage.lang is set, it takes " +
     "priority over the tenant default and the navigator", () => {
    window.localStorage.setItem("lang", "es");
    window.localStorage.setItem("tenant_default_locale", "fr");
    // Manually drive the detector to observe resolution.
    const detected = i18n.services.languageDetector.detect();
    // ``detect()`` returns the first detector that produced a
    // non-undefined value.  It should be ``es`` (user pref).
    // (i18next may return an array of candidates — normalise.)
    const first = Array.isArray(detected) ? detected[0] : detected;
    expect(first).toBe("es");
  });

  it("TENANT DEFAULT WINS OVER NAVIGATOR: when no user pref is " +
     "set but a tenant_default_locale is cached, the tenant value " +
     "surfaces ahead of the navigator locale", () => {
    // No user pref.
    try { window.localStorage.removeItem("lang"); } catch { /* */ }
    window.localStorage.setItem("tenant_default_locale", "fr");
    const detected = i18n.services.languageDetector.detect();
    const first = Array.isArray(detected) ? detected[0] : detected;
    expect(first).toBe("fr");
  });

  it("COLD BOOT FALLTHROUGH: neither user pref nor tenant default " +
     "cached - the detector falls through to navigator (or the EN " +
     "fallback if navigator returns an unsupported locale)", () => {
    // Both keys absent.
    try {
      window.localStorage.removeItem("lang");
      window.localStorage.removeItem("tenant_default_locale");
    } catch { /* */ }
    const detected = i18n.services.languageDetector.detect();
    const first = Array.isArray(detected) ? detected[0] : detected;
    // Navigator in jsdom is typically ``en-US``.  Either way the
    // result must be one of our supported locales after
    // ``supportedLngs`` filtering.  A missing tenant/user rung
    // must NEVER throw / return undefined here.
    expect(first).toBeTruthy();
    // Guard against a stale test-run leaking a non-en value into
    // this environment.  Whatever the navigator says, once i18next
    // applies ``supportedLngs`` the resolvedLanguage must be one
    // of en/es/fr (or fall back to en).
    expect(["en", "es", "fr"]).toContain(
      String(first).slice(0, 2).toLowerCase(),
    );
  });

  it("STALE TENANT VALUE IGNORED: an out-of-bundle " +
     "tenant_default_locale (e.g. ``de`` from a rolled-back " +
     "future rollout) must fall through to navigator/en, NOT " +
     "poison the detector", () => {
    try { window.localStorage.removeItem("lang"); } catch { /* */ }
    window.localStorage.setItem("tenant_default_locale", "de");
    const detected = i18n.services.languageDetector.detect();
    const first = Array.isArray(detected) ? detected[0] : detected;
    // The tenant detector guards with the en/es/fr allow-list, so
    // it returns undefined for ``de`` and the chain falls to
    // navigator.  Whatever navigator resolves to must be one of
    // our supported locales.
    expect(first).not.toBe("de");
    expect(first).toBeTruthy();
  });
});
