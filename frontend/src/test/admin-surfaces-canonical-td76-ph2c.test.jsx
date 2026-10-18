/**
 * TD-76 Phase B (ph2c) · Feb-2026 — admin FE surfaces consume
 * canonical ``thumb_url`` / ``full_url`` fields emitted by the
 * TD-76-ph2b BE emission layer.
 *
 * Coverage locks:
 *   1. ``WorkstreamPage.jsx`` MediaStrip reads ``t.thumb_url || t.url``
 *      (canonical first, legacy ``url`` as defensive fallback).
 *   2. ``WorkstreamPage.jsx`` lightbox reads ``preview.full_url ||
 *      preview.url``.
 *   3. ``ServiceLogPage.jsx`` carousel + lightbox read ``cur.full_url``
 *      / ``cur.thumb_url`` with legacy ``cur.url`` as the final
 *      fallback.
 *   4. Negative lock — no raw ``t.url`` or ``cur.url`` consumption
 *      remains WITHOUT the canonical-first chain on these two files.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";


const WS_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/workstream/WorkstreamPage.jsx"),
  "utf-8",
);
const SL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/workstream/ServiceLogPage.jsx"),
  "utf-8",
);


describe("TD-76-ph2c · WorkstreamPage canonical consumption", () => {
  it("MediaStrip thumb <img> reads t.thumb_url first", () => {
    expect(WS_SRC).toMatch(/_thumbSrc\(t\.thumb_url\s*\|\|\s*t\.url\)/);
  });

  it("Lightbox photo <img> reads preview.full_url first", () => {
    expect(WS_SRC).toMatch(/preview\.full_url\s*\|\|\s*preview\.url/);
  });

  it("no bare `${BACKEND}${t.url}` composition remains in the MediaStrip", () => {
    // Pre-TD-76-ph2c the MediaStrip thumb src was
    // ``${BACKEND}${_thumbSrc(t.url)}`` with ``t.url`` alone.
    // Negative regression lock.
    expect(WS_SRC).not.toMatch(/_thumbSrc\(t\.url\)/);
  });

  it("photo-branch Lightbox no longer uses bare `preview.url` as the primary — video branch is out of scope", () => {
    // Scope narrowing: TD-76 Phase B covers photo URL emission
    // only. Video URLs stream through ``/api/media/videos/<path>``
    // which is public and does NOT carry canonical fields. The
    // ``<video>`` src keeps its ``preview.url`` reference until
    // a dedicated video-canonical cycle.  This test asserts the
    // PHOTO branch's `<img>` src uses the canonical-first chain,
    // nothing else.
    expect(WS_SRC).toMatch(
      /<img\s+[\s\S]{0,200}src=\{`\$\{BACKEND\}\$\{preview\.full_url\s*\|\|\s*preview\.url\}`\}/,
    );
  });
});


describe("TD-76-ph2c · ServiceLogPage canonical consumption", () => {
  it("carousel resolves cur.full_url first, cur.url as fallback", () => {
    expect(SL_SRC).toMatch(
      /_resolved\s*=\s*cur\?\.full_url\s*\|\|\s*cur\?\.url\s*\|\|\s*""/,
    );
  });

  it("thumb variant resolves cur.thumb_url first, cur.url as fallback", () => {
    expect(SL_SRC).toMatch(
      /_resolvedThumb\s*=\s*cur\?\.thumb_url\s*\|\|\s*cur\?\.url\s*\|\|\s*""/,
    );
  });

  it("<img> src for the carousel uses the thumb-resolved URL", () => {
    expect(SL_SRC).toMatch(/withAuthToken\(thumbUrl,\s*token\)/);
  });

  it("no bare `cur?.url` as the primary URL source remains", () => {
    // Pre-TD-76-ph2c the carousel assigned
    // ``cur?.url ? (cur.url.startsWith(...))``. The canonical
    // migration moves ``cur?.url`` to the FALLBACK position.
    expect(SL_SRC).not.toMatch(
      /const url\s*=\s*cur\?\.url\s*\?\s*\(cur\.url\.startsWith/,
    );
  });
});
