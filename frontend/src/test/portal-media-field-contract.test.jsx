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

  it("PortalServiceReportDetail jobPhotos fallback reads canonical fields (TD-76d) with `p.url` fallback — never `p.preview`", () => {
    // TD-76d · Feb-2026 — chain is now
    // ``p.thumb_url || p.thumb || p.full_url || p.url``.
    // Both the grid-render loop AND the lightbox items loop use
    // the identical chain. Negative lock on the pre-TD-67 bug
    // (``p.thumb || p.preview``) preserved.
    const chain = /p\.thumb_url\s*\|\|\s*p\.thumb\s*\|\|\s*p\.full_url\s*\|\|\s*p\.url\s*\|\|\s*""/g;
    const matches = SR_SRC.match(chain) || [];
    // Two sites — grid tile + lightbox items.
    expect(matches.length).toBeGreaterThanOrEqual(2);
    // Negative — ``p.preview`` no longer appears in the jobPhotos
    // fallback chain. (Visitor-photos `photos[]` loop still uses
    // ``p.data_url`` / ``p.thumb_url`` which is fine — those come
    // from a different serializer branch.)
    expect(SR_SRC).not.toMatch(/p\.thumb\s*\|\|\s*p\.preview/);
  });

  it("PortalServiceReportDetail consumes BE-resolved canonical URLs (TD-76d)", () => {
    // TD-67 originally wrapped the <img src> with withAuthToken so
    // ``?auth=<token>`` landed. TD-76d supersedes that: the BE
    // emission layer (``_build_customer_job_photos`` in
    // ``routers/service_reports.py``) now resolves the canonical
    // ``thumb_url`` + ``full_url`` server-side, so the FE consumes
    // them directly — no path composition, no token stamping on
    // this surface.
    expect(SR_SRC).toMatch(/const _raw = p\.thumb_url \|\| p\.thumb \|\| p\.full_url \|\| p\.url \|\| ""/);
    expect(SR_SRC).not.toMatch(/withAuthToken\(_raw,\s*_tok\)/);
  });

  // TD-76e grouped-tree React key shape is covered by the
  // dedicated ``portal-photos-td76-canonical.test.jsx`` suite —
  // the pre-TD-67 index-based-key assertion was retired when the
  // flat grid was replaced by the date/visit tree.

  it("PortalVideosPage uses index-based React keys (BE emits no file_id)", () => {
    expect(VIDEOS_SRC).toMatch(/\$\{v\.source\s*\|\|\s*"src"\}\|\$\{v\.video_id\s*\|\|\s*v\.entity_id\s*\|\|\s*"x"\}\|\$\{i\}/);
    expect(VIDEOS_SRC).toMatch(/data-testid=\{`portal-video-\$\{i\}`\}/);
  });
});
