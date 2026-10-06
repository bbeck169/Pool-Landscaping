/**
 * JOB-PHOTOS-FIX · Feb-2026 — regression guard for the
 * ``<img src>`` fallback ladder on JobDetail's photo grid +
 * lightbox.
 *
 * Context: historically the grid rendered
 * ``src={p.url || p.data_url || p}`` which fell through to the
 * raw photo object (``p``) when neither ``.url`` nor ``.data_url``
 * existed on the backend doc.  Backend persists photos as
 * ``{id, data, label, created_at}`` so React coerced the dict to
 * ``[object Object]`` and the browser showed a broken image /
 * filename-shaped alt text.
 *
 * This fix extends the ladder to ``p.url || p.data || p.data_url
 * || p`` so even in the (impossible-after-the-serializer-fix) case
 * where ``url`` is missing, the raw base64 ``data`` DataURL still
 * renders.  Backend serializer injection stays canonical; the FE
 * fallback is defence-in-depth for legacy / cached responses.
 *
 * JobDetail is a 1.4-kloc page component with multiple parent
 * providers (auth, tenant, router) so we lock the contract via a
 * source-text grep (same style as the BULK-RESCHEDULE-FIX
 * selection-unification guard) which is cheap, fast, and surfaces
 * drift before shipping.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf8",
);

describe("JOB-PHOTOS-FIX · <img src> fallback ladder", () => {
  it("grid tile prefers p.url, falls back to p.data, then p.data_url", () => {
    // Grid tile uses the compact per-element form:
    //   src={p.url || p.data || p.data_url || p}
    const re = /src=\{p\.url \|\| p\.data \|\| p\.data_url \|\| p\}/;
    expect(SRC).toMatch(re);
  });

  it("legacy p.data_url-only ladder is gone from the grid", () => {
    // The pre-fix shape was ``src={p.url || p.data_url || p}``.
    // Must not reappear after a bad merge / revert.
    const stale = /src=\{p\.url \|\| p\.data_url \|\| p\}/;
    expect(SRC).not.toMatch(stale);
  });

  it("lightbox prefers .url, falls back to .data, then .data_url", () => {
    // The lightbox uses a multi-line expanded expression (because
    // of the ``job.photos[lightbox]`` repeated access) so match
    // the body across newlines.
    expect(SRC).toMatch(
      /\(job\.photos\[lightbox\] \|\| \{\}\)\.url \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.data \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.data_url \|\|\s*job\.photos\[lightbox\]/,
    );
  });

  it("legacy lightbox ladder (missing .data branch) is gone", () => {
    // Pre-fix shape — 2-rung ladder.  Must not reappear.
    const stale =
      /\(job\.photos\[lightbox\] \|\| \{\}\)\.url \|\|\s*\(job\.photos\[lightbox\] \|\| \{\}\)\.data_url \|\|\s*job\.photos\[lightbox\]\n/;
    expect(SRC).not.toMatch(stale);
  });
});
