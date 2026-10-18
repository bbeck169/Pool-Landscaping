/**
 * TD-76d/e · Feb-2026 — Phase A FE canonical-field consumption +
 * Portal Photos grouped-layout contract.
 *
 * Coverage:
 *   1. ``PortalPhotos.jsx`` + ``PortalServiceReports.jsx`` read
 *      ``thumb_url`` / ``full_url`` directly — no FE path
 *      composition remains on these two surfaces.
 *   2. ``withAuthToken`` is no longer imported / called in the
 *      jobPhotos render path of ``PortalServiceReports.jsx`` (TD-67
 *      token stamping is replaced by BE-resolved URLs).
 *   3. ``groupPhotosByDateAndVisit`` produces the operator-spec
 *      grouped tree: date groups DESC, visits within a day sorted
 *      by ``submitted_at`` ASC with ``job_id`` as the deterministic
 *      tiebreak.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

import {
  groupPhotosByDateAndVisit,
} from "../pages/portal/PortalPhotos.jsx";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const PHOTOS_SRC = R("../pages/portal/PortalPhotos.jsx");
const SR_SRC = R("../pages/portal/PortalServiceReports.jsx");


// ────────────────────────────────────────────────────────────────
// 1. FE purge locks — canonical fields consumed directly.
// ────────────────────────────────────────────────────────────────
describe("TD-76d · PortalPhotos consumes canonical thumb_url/full_url", () => {
  it("<img> src reads p.thumb_url first", () => {
    expect(PHOTOS_SRC).toMatch(/<img\s+src=\{p\.thumb_url\s*\|\|/);
  });

  it("lightbox items read p.full_url first", () => {
    expect(PHOTOS_SRC).toMatch(/photo\.full_url\s*\|\|/);
  });

  it("no FE path composition — no `/api/public/service/` string literal in PortalPhotos.jsx", () => {
    expect(PHOTOS_SRC).not.toMatch(/`\/api\/public\/service\//);
  });

  it("no `withAuthToken` import in PortalPhotos.jsx", () => {
    expect(PHOTOS_SRC).not.toMatch(/withAuthToken/);
  });
});

describe("TD-76d · PortalServiceReports consumes canonical thumb_url/full_url", () => {
  it("jobPhotos grid src reads p.thumb_url first (no path composition)", () => {
    // The jobPhotos grid _raw assignment now starts with
    // ``p.thumb_url ||`` instead of the pre-TD-76d
    // ``p.thumb || p.url``.
    expect(SR_SRC).toMatch(/const _raw = p\.thumb_url \|\| p\.thumb \|\| p\.full_url \|\| p\.url \|\| ""/);
  });

  it("no `withAuthToken(_raw, _tok)` wrapping on the jobPhotos path", () => {
    // Pre-TD-76d: ``withAuthToken(_raw, _tok)``. Post-TD-76d: BE
    // emits the fully-resolved URL so FE assigns `_raw` directly.
    expect(SR_SRC).not.toMatch(/withAuthToken\(_raw,\s*_tok\)/);
  });
});


// ────────────────────────────────────────────────────────────────
// 2. groupPhotosByDateAndVisit — deterministic tiebreak contract.
// ────────────────────────────────────────────────────────────────
describe("TD-76e · groupPhotosByDateAndVisit tree + tiebreak", () => {
  it("groups by date (YYYY-MM-DD prefix of submitted_at), newest first", () => {
    const g = groupPhotosByDateAndVisit([
      { id: "a", job_id: "j1", job_title: "Weekly Pool",
        submitted_at: "2026-10-14T09:00:00Z" },
      { id: "b", job_id: "j1", job_title: "Weekly Pool",
        submitted_at: "2026-10-06T09:00:00Z" },
    ]);
    expect(g.map((x) => x.day)).toEqual(["2026-10-14", "2026-10-06"]);
  });

  it("groups photos from the same visit under one service sub-header", () => {
    const g = groupPhotosByDateAndVisit([
      { id: "a", job_id: "j1", job_title: "Weekly Pool",
        submitted_at: "2026-10-14T09:00:00Z" },
      { id: "b", job_id: "j1", job_title: "Weekly Pool",
        submitted_at: "2026-10-14T09:05:00Z" },
      { id: "c", job_id: "j1", job_title: "Weekly Pool",
        submitted_at: "2026-10-14T09:10:00Z" },
    ]);
    expect(g).toHaveLength(1);
    expect(g[0].visits).toHaveLength(1);
    expect(g[0].visits[0].photos.map((p) => p.id)).toEqual(["a", "b", "c"]);
  });

  it("multiple visits same day → multiple sub-headers, sorted by first submitted_at ASC", () => {
    const g = groupPhotosByDateAndVisit([
      // Visit j2 is EARLIER in the day than visit j1.
      { id: "a", job_id: "j1", job_title: "Afternoon pool",
        submitted_at: "2026-10-14T14:00:00Z" },
      { id: "b", job_id: "j2", job_title: "Morning landscape",
        submitted_at: "2026-10-14T09:00:00Z" },
    ]);
    expect(g).toHaveLength(1);
    expect(g[0].visits.map((v) => v.visitKey)).toEqual(["j2", "j1"]);
  });

  it("same submitted_at tiebreak falls back to visitKey (job_id) lex ASC", () => {
    const g = groupPhotosByDateAndVisit([
      { id: "a", job_id: "zebra", job_title: "Z",
        submitted_at: "2026-10-14T09:00:00Z" },
      { id: "b", job_id: "apple", job_title: "A",
        submitted_at: "2026-10-14T09:00:00Z" },
    ]);
    expect(g[0].visits.map((v) => v.visitKey)).toEqual(["apple", "zebra"]);
  });

  it("empty / missing submitted_at buckets to 'Unknown date' at the end", () => {
    const g = groupPhotosByDateAndVisit([
      { id: "a", job_id: "j1", submitted_at: "" },
      { id: "b", job_id: "j1", submitted_at: "2026-10-14T09:00:00Z" },
    ]);
    expect(g.map((x) => x.day)).toEqual(["Unknown date", "2026-10-14"]);
  });
});
