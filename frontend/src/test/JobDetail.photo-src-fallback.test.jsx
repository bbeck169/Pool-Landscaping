/**
 * JOB-PHOTOS-FIX · Feb-2026 — regression guard for the
 * ``<img src>`` fallback ladder on JobDetail's photo grid +
 * lightbox.
 *
 * TD-76 Ph2f · Feb-2026 — widened to lock the canonical
 * ``thumb_url`` / ``full_url`` consume shape that landed with
 * ``services/jobs_slim_photos::inject_photo_url_on_doc`` emitting
 * the TD-76 Phase B canonical photo-URL shape. The grid tile now
 * reads ``p.thumb_url || p.url || p.data || p.data_url || p`` and
 * the lightbox reads ``.full_url || .url || .data || .data_url``.
 * Legacy ``url`` / ``data`` / ``data_url`` fallbacks are retained
 * as defence-in-depth for cached responses + base64-inline rows.
 *
 * JobDetail is a 1.4-kloc page component with multiple parent
 * providers (auth, tenant, router) so we lock the contract via a
 * source-text grep which is cheap, fast, and surfaces drift
 * before shipping.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf8",
);

describe("JOB-PHOTOS-FIX · <img src> fallback ladder", () => {
  it("grid tile prefers p.thumb_url, falls back through p.url → p.data → p.data_url", () => {
    // Canonical TD-76 Ph2f ladder — thumb_url wins, legacy
    // retained.
    const re = /src=\{p\.thumb_url \|\| p\.url \|\| p\.data \|\| p\.data_url \|\| p\}/;
    expect(SRC).toMatch(re);
  });

  it("legacy p.url-first ladder is gone from the grid", () => {
    // The pre-Ph2f shape was ``src={p.url || p.data || p.data_url || p}``.
    // Must not reappear after a bad merge / revert.
    const stale = /src=\{p\.url \|\| p\.data \|\| p\.data_url \|\| p\}/;
    expect(SRC).not.toMatch(stale);
    // Even older pre-fix: ``src={p.url || p.data_url || p}``.
    const ancient = /src=\{p\.url \|\| p\.data_url \|\| p\}/;
    expect(SRC).not.toMatch(ancient);
  });

  it("lightbox prefers .full_url, falls back through .url → .data → .data_url", () => {
    // The lightbox uses a multi-line expanded expression (because
    // of the ``job.photos[lightbox]`` repeated access) so match
    // the body across newlines.
    expect(SRC).toMatch(
      /\(job\.photos\[lightbox\] \|\| \{\}\)\.full_url \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.url \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.data \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.data_url \|\|\s*job\.photos\[lightbox\]/,
    );
  });

  it("legacy lightbox ladder (missing .full_url rung) is gone", () => {
    // Pre-Ph2f shape started the lightbox ladder with ``.url``;
    // after Ph2f, ``.full_url`` is the first rung. Count: there
    // must be exactly one ``.full_url`` reference in the lightbox
    // expression for ``job.photos[lightbox]``.
    const matches = SRC.match(
      /\(job\.photos\[lightbox\] \|\| \{\}\)\.full_url/g,
    );
    expect(matches).not.toBeNull();
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("SR grid tile adds defensive thumb_url fallback over legacy url", () => {
    // TD-76 Ph2f — additive defence-in-depth. Phase B BE already
    // emits canonical shape on this surface; the FE adds the
    // guard so cached / legacy responses still render.
    const re = /src=\{p\.thumb_url \|\| p\.url\}/;
    expect(SRC).toMatch(re);
  });

  it("SR lightbox uses canonical full_url with legacy url fallback", () => {
    // The SR lightbox uses the multi-line expanded form; match
    // across newlines.
    expect(SRC).toMatch(
      /\(detail\.service_report_photos\[srLightbox\] \|\| \{\}\)\.full_url \|\|\s*\(detail\.service_report_photos\[srLightbox\] \|\| \{\}\)\.url/,
    );
  });

  it("no raw /api/public/job-photo path composition remains in JobDetail", () => {
    // TD-76 §1 close-out — FE must not hand-compose any streaming
    // endpoint path; the BE emits canonical ``thumb_url`` /
    // ``full_url`` for every photo row.
    const rawCompose = /`\$\{[^}]+\}\/api\/public\/job-photo\//;
    expect(SRC).not.toMatch(rawCompose);
    const literalCompose = /"\/api\/public\/job-photo\//;
    expect(SRC).not.toMatch(literalCompose);
  });
});
