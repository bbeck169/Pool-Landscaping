/**
 * TD-67 · Feb-2026 — Portal media field-contract regression lock.
 *
 * Pre-TD-67 three field-shape mismatches silently blanked the
 * portal media surfaces for every seeded customer:
 *
 *   1. `/portal/photos` — FE read `res.items`; BE emits `res.photos`.
 *   2. `/portal/videos` — FE read `res.items`; BE emits `res.videos`.
 *   3. SR detail `jobPhotos` — FE fell back to `p.preview` which the
 *      BE serializer has NEVER emitted; the correct fallback is
 *      `p.url` (the customer-session streaming route).
 *
 * This file pins the three contracts at the source level so a
 * future refactor can't silently restore the symptoms. Source-grep
 * assertions mirror the convention used by the P49 restyle test.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");

const PHOTOS_SRC = R("../pages/portal/PortalPhotosPage.jsx");
const VIDEOS_SRC = R("../pages/portal/PortalVideosPage.jsx");
const SR_SRC     = R("../pages/portal/PortalServiceReports.jsx");


describe("TD-67 · Portal media field-contract regression lock", () => {
  it("PortalPhotosPage reads `.photos` from the BE response", () => {
    // Primary accessor matches the BE shape; `.items` kept as a
    // defensive secondary only. The pre-TD-67 code had `res.items`
    // as the ONLY accessor — that's the symptom we're locking out.
    expect(PHOTOS_SRC).toMatch(/res\.photos\s*\|\|\s*res\.items/);
    // Negative assertion — no bare ``res.items`` as the sole
    // right-hand side of the collector assignment.
    expect(PHOTOS_SRC).not.toMatch(/const\s+nextRows\s*=\s*res\.items\s*\|\|\s*\[\]\s*;/);
  });

  it("PortalVideosPage reads `.videos` from the BE response", () => {
    expect(VIDEOS_SRC).toMatch(/res\.videos\s*\|\|\s*res\.items/);
    expect(VIDEOS_SRC).not.toMatch(/const\s+nextRows\s*=\s*res\.items\s*\|\|\s*\[\]\s*;/);
  });

  it("PortalServiceReportDetail jobPhotos fallback reads `p.url`, not `p.preview`", () => {
    // Both the grid-render loop AND the lightbox items loop use
    // the ``p.thumb || p.url`` chain — ``p.preview`` was the bug.
    const chain = /p\.thumb\s*\|\|\s*p\.url\s*\|\|\s*""/g;
    const matches = SR_SRC.match(chain) || [];
    // Two sites — grid tile + lightbox items.
    expect(matches.length).toBeGreaterThanOrEqual(2);
    // Negative — ``p.preview`` no longer appears in the jobPhotos
    // fallback chain. (Visitor-photos `photos[]` loop still uses
    // ``p.data_url`` / ``p.thumb_url`` which is fine — those come
    // from a different serializer branch.)
    expect(SR_SRC).not.toMatch(/p\.thumb\s*\|\|\s*p\.preview/);
  });

  it("PortalServiceReportDetail routes jobPhotos through withAuthToken for <img src>", () => {
    // Pre-TD-67 the ``<img src>`` tag was the raw URL — the BE
    // handler required a Bearer header which browsers can't attach
    // to image requests. The ``withAuthToken`` helper appends
    // ``?auth=<token>`` and the BE now accepts the query-param
    // fallback (see routers/service_reports.py
    // stream_customer_job_photo).
    expect(SR_SRC).toMatch(/import\s+\{\s*withAuthToken\s*\}\s+from\s+["']@\/lib\/urlToken["']/);
    expect(SR_SRC).toMatch(/withAuthToken\(_raw,\s*_tok\)/);
  });

  it("PortalPhotosPage uses index-based React keys (BE emits no file_id)", () => {
    // Composite key fallback — matches on {source}|{report_id|job_id}|{i}.
    expect(PHOTOS_SRC).toMatch(/\$\{p\.source\s*\|\|\s*"src"\}\|\$\{p\.report_id\s*\|\|\s*p\.job_id\s*\|\|\s*"x"\}\|\$\{i\}/);
    // Testid uses the loop index — never ``portal-photo-undefined``.
    expect(PHOTOS_SRC).toMatch(/data-testid=\{`portal-photo-\$\{i\}`\}/);
  });

  it("PortalVideosPage uses index-based React keys (BE emits no file_id)", () => {
    expect(VIDEOS_SRC).toMatch(/\$\{v\.source\s*\|\|\s*"src"\}\|\$\{v\.video_id\s*\|\|\s*v\.entity_id\s*\|\|\s*"x"\}\|\$\{i\}/);
    expect(VIDEOS_SRC).toMatch(/data-testid=\{`portal-video-\$\{i\}`\}/);
  });
});
