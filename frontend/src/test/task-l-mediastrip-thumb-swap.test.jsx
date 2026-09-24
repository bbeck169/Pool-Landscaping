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
    expect(SRC).toMatch(
      /<img[\s\S]{0,120}src=\{`\$\{BACKEND\}\$\{_thumbSrc\(t\.url\)\}`\}/
    );
  });

  it("lightbox <img> src still uses the full-size preview.url (NOT thumb'd)", () => {
    // Lightbox image element renders inside the `preview.kind ===
    // "photo"` branch of the preview modal — must resolve to the
    // full-size URL so click-to-enlarge stays high-res.
    expect(SRC).toMatch(
      /preview\.kind === "photo"[\s\S]{0,300}<img[\s\S]{0,120}src=\{`\$\{BACKEND\}\$\{preview\.url\}`\}/
    );
    // Belt-and-braces: the lightbox img must NOT wrap
    // preview.url in _thumbSrc.
    expect(SRC).not.toMatch(
      /preview\.kind === "photo"[\s\S]{0,300}<img[\s\S]{0,120}_thumbSrc\(preview\.url\)/
    );
  });

  it("lightbox <video> src still uses full-size preview.url (NOT thumb'd)", () => {
    expect(SRC).toMatch(
      /<video[\s\S]{0,400}src=\{`\$\{BACKEND\}\$\{preview\.url\}\$\{token/
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
