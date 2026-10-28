/**
 * Task L+P · Commit 4 · Feb-2026 — MediaStrip URL swap.
 *
 * Pins:
 *   • Grid <img> thumbnails render the ``/thumb`` derivative
 *     URL (append-only append on the ``/api/public/job-photo/``
 *     shape). SR photos returned with a stored ``url`` (which
 *     doesn't hit the ``/api/public/job-photo/`` path) are
 *     passed through verbatim — matches Commit 4 backend
 *     semantics (SR entries emit their SR streaming URL).
 *   • Lightbox <img> + <video> still open the FULL-SIZE URL —
 *     do NOT swap; click-to-enlarge stays byte-identical to
 *     pre-Task-L+P.
 *   • All existing testids preserved verbatim.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/workstream/WorkstreamPage.jsx"),
  "utf-8",
);

describe("Task L+P · Commit 4 — MediaStrip URL swap contract", () => {
  it("defines a _thumbSrc helper that appends /thumb to /api/public/job-photo URLs only", () => {
    // Helper exists and is scoped inside MediaStrip.
    expect(SRC).toMatch(/const\s+_thumbSrc\s*=\s*\(u\)\s*=>\s*\{/);
    // Only mutates /api/public/job-photo/* URLs.
    expect(SRC).toMatch(/u\.includes\("\/api\/public\/job-photo\/"\)/);
    // Appends /thumb (idempotent — bails out when already
    // suffixed).
    expect(SRC).toMatch(/u\.endsWith\("\/thumb"\)\s*\?\s*u\s*:/);
    expect(SRC).toMatch(/`\$\{u\}\/thumb`/);
  });

  it("grid <img> src funnels through _thumbSrc(t.url)", () => {
    // The photo branch of the grid thumb loop consumes
    // _thumbSrc — this is the URL swap itself.
    //
    // ZZ-A Wave 3-E · Feb-2026 — WorkstreamPage.jsx:140 now
    // reads ``_thumbSrc(t.thumb_url || t.url)`` so SR entries
    // (which may carry an explicit ``thumb_url`` short-circuit)
    // prefer the stored thumb when present. The pre-Wave-3
    // bare-``t.url`` regex no longer matches. Loosened to accept
    // the optional ``t.thumb_url ||`` fallback prefix. Also
    // widened the between-``<img``-and-``src=`` window
    // (120 → 500 chars) to span the 7-line TD-76-ph2c rationale
    // comment block that landed between the tag and the attr.
    expect(SRC).toMatch(
      /<img[\s\S]{0,500}src=\{`\$\{BACKEND\}\$\{_thumbSrc\(t\.(?:thumb_url\s*\|\|\s*t\.)?url\)\}`\}/
    );
  });

  it("lightbox <img> src still uses the full-size preview.url (NOT thumb'd)", () => {
    // Lightbox image element renders inside the `preview.kind ===
    // "photo"` branch of the preview modal — must resolve to the
    // full-size URL so click-to-enlarge stays high-res.
    //
    // ZZ-A Wave 3-E · Feb-2026 — WorkstreamPage.jsx:193 now
    // reads ``${preview.full_url || preview.url}`` so SR
    // photos (which may carry a distinct ``full_url``) resolve
    // to the explicit full-size path when present. Loosened the
    // src regex to accept the optional ``preview.full_url ||``
    // fallback prefix; widened the between-``<img``-and-``src=``
    // window (120 → 300 chars) to span the TD-76-ph2c comment
    // line that landed between the tag and the attr. The
    // belt-and-braces anti-``_thumbSrc`` guard below is unchanged.
    expect(SRC).toMatch(
      /preview\.kind === "photo"[\s\S]{0,300}<img[\s\S]{0,300}src=\{`\$\{BACKEND\}\$\{preview\.(?:full_url\s*\|\|\s*preview\.)?url\}`\}/
    );
    // Belt-and-braces: the lightbox img must NOT wrap
    // preview.url in _thumbSrc.
    expect(SRC).not.toMatch(
      /preview\.kind === "photo"[\s\S]{0,300}<img[\s\S]{0,120}_thumbSrc\(preview\.url\)/
    );
  });

  it("lightbox <video> src still uses full-size preview.url (NOT thumb'd)", () => {
    // ZZ-A Wave 3-E · Feb-2026 — WorkstreamPage.jsx:204 now
    // wraps the video src in ``withAuthToken(..., token)`` so
    // the signed-stream token rides on the request. The
    // underlying URL template is unchanged
    // (``${BACKEND}${preview.url}...``). Allowed the optional
    // ``withAuthToken(`` wrapper in the src regex; the full-size
    // thesis (preview.url, no thumb) is preserved.
    expect(SRC).toMatch(
      /<video[\s\S]{0,400}src=\{(?:withAuthToken\()?`\$\{BACKEND\}\$\{preview\.url\}/
    );
  });

  it("preserves every existing MediaStrip testid verbatim", () => {
    // Grid container.
    expect(SRC).toMatch(/data-testid=\{`ws-job-media-\$\{jid\}`\}/);
    // Per-thumb button.
    expect(SRC).toMatch(/data-testid=\{`ws-thumb-\$\{jid\}-\$\{i\}`\}/);
    // Overflow badge.
    expect(SRC).toMatch(/data-testid=\{`ws-thumb-extra-\$\{jid\}`\}/);
    // Lightbox.
    expect(SRC).toMatch(/data-testid="ws-lightbox"/);
  });

  it("preserves upstream Work Stream testids from Task E (regression guard)", () => {
    // A representative sample of the Task E testid set — if any
    // of these drift this test file will still catch the leak.
    expect(SRC).toMatch(/data-testid="workstream-filter-bar"/);
    expect(SRC).toMatch(/data-testid="ws-filter-since"/);
    expect(SRC).toMatch(/data-testid="ws-filter-until"/);
    expect(SRC).toMatch(/data-testid="ws-filter-tech"/);
    expect(SRC).toMatch(/testid="ws-filter-customer"/);
    expect(SRC).toMatch(/data-testid="ws-sort"/);
    // Job card + assignee.
    expect(SRC).toMatch(/data-testid=\{`ws-job-\$\{job\.id\}`\}/);
    expect(SRC).toMatch(/data-testid=\{`ws-job-assignee-\$\{job\.id\}`\}/);
    // Bulk toolbar.
    expect(SRC).toMatch(/data-testid="ws-selection-toolbar"/);
    expect(SRC).toMatch(/data-testid="ws-selection-delete"/);
  });
});
