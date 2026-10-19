/**
 * TD-88 · Feb-2026 — PhotoUploader canonical URL consume.
 *
 * Pre-TD-88, ``PhotoUploader.jsx:145-147`` composed the thumbnail
 * ``<img src>`` by hand:
 *
 *   const thumbSrc = jobId
 *     ? `/api/public/job-photo/${jobId}/${p.id}/thumb`
 *     : (p.data || p.url);
 *
 * This worked on fresh uploads (ids originated from
 * ``jobs.photos``) but was fragile under the SR GET-vs-PATCH
 * id-space drift (see TD-89 bookmark in ``memory/TECH_DEBT.md``).
 *
 * TD-88 drops the raw composition in favor of the canonical fields
 * emitted by the BE via ``inject_photo_url_on_doc`` on every SR
 * response path (GET / PATCH / submit).  Fallback ladder:
 *   1. ``p.thumb_url``   — BE-emitted thumbnail route.
 *   2. ``p.url``         — legacy canonical alias / full route.
 *   3. ``p.data``        — base64 inline (upload-response fresh).
 *   4. ``p.data_url``    — alt field name for base64 inline.
 *
 * These specs assert the ladder end-to-end so a future refactor
 * that regresses the resolver blows up here BEFORE it ships to
 * the checklist render surface.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Stub out the api layer + image-compression so the component
// mounts cleanly in isolation.  No network, no canvas.
vi.mock("@/api", () => ({ api: { post: vi.fn(), del: vi.fn() } }));
vi.mock("../../lib/imageCompress", () => ({
  compressImageIfNeeded: async (f) => f,
}));

import PhotoUploader from "@/components/checklist/PhotoUploader";


describe("<PhotoUploader /> · TD-88 canonical URL consume", () => {
  it("renders ``thumb_url`` first when present on the photo subdoc", () => {
    const photos = [{
      id: "p1",
      thumb_url: "/api/public/job-photo/job-1/p1/thumb",
      full_url:  "/api/public/job-photo/job-1/p1",
      url:       "/api/public/job-photo/job-1/p1",
    }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p1");
    expect(img.getAttribute("src"))
      .toBe("/api/public/job-photo/job-1/p1/thumb");
  });

  it("falls back to legacy ``url`` when ``thumb_url`` is absent", () => {
    const photos = [{
      id: "p2",
      url: "/api/public/job-photo/job-1/p2",
    }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p2");
    expect(img.getAttribute("src"))
      .toBe("/api/public/job-photo/job-1/p2");
  });

  it("falls back to base64 ``data`` when canonical fields are absent", () => {
    const dataUri = "data:image/jpeg;base64,AAAA";
    const photos = [{ id: "p3", data: dataUri }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p3");
    expect(img.getAttribute("src")).toBe(dataUri);
  });

  it("falls back to base64 ``data_url`` as the last ladder rung", () => {
    const dataUri = "data:image/png;base64,BBBB";
    const photos = [{ id: "p4", data_url: dataUri }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p4");
    expect(img.getAttribute("src")).toBe(dataUri);
  });

  it("prefers ``thumb_url`` even when every lower rung is also populated", () => {
    const photos = [{
      id: "p5",
      thumb_url: "/thumb/preferred",
      url:       "/url/legacy",
      data:      "data:image/jpeg;base64,CCCC",
      data_url:  "data:image/jpeg;base64,DDDD",
    }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p5");
    expect(img.getAttribute("src")).toBe("/thumb/preferred");
  });

  it("does NOT compose raw ``/api/public/job-photo/`` paths against ``p.id``", () => {
    // Pre-TD-88 regression guard: when the canonical fields are
    // missing AND no base64 fallback is present, the resolver
    // returns ``undefined`` rather than hand-composing a URL
    // against ``p.id``.  This is intentional — a photo with no
    // byte source should not be papered over with a potentially
    // dead URL (same OMIT posture as TD-76 Ph2).
    const photos = [{ id: "p6" }];
    render(<PhotoUploader
      jobId="job-1" photos={photos} onPhotosChange={() => {}} />);
    const img = screen.getByTestId("checklist-photo-img-p6");
    // The <img> renders without a resolvable src — the browser
    // will show the broken-image glyph but we never emit a dead
    // path composition.
    const src = img.getAttribute("src");
    expect(src === null || src === "" || src === "undefined").toBe(true);
    // Hard guard: the pre-TD-88 raw composition must NOT appear.
    expect(src).not.toBe("/api/public/job-photo/job-1/p6/thumb");
  });
});
