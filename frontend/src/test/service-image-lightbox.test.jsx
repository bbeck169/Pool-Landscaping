/**
 * Feb-2026 · Clickable service log images — Workstream ServiceLog lightbox.
 *
 * Covers:
 *   1. Main carousel image is wrapped in a clickable button with the
 *      required testids.
 *   2. Click opens the lightbox showing the correct src.
 *   3. ESC key closes the lightbox.
 *   4. Backdrop click closes the lightbox.
 *   5. Prev/Next arrows cycle when >1 image.
 *   6. Counter updates when navigating.
 *   7. Single-image case hides prev/next + counter.
 *   8. Videos are skipped by lightbox nav (kind="video" items are
 *      not shown in the lightbox slot count).
 *   9. Testid catalog present.
 *
 * Uses the source-string guard pattern from prior ships for parts
 * that would require mounting the full ServiceLogPage (which fetches
 * on mount and hangs under jsdom). The MediaCarousel component is
 * NOT exported from ServiceLogPage.jsx — so we mount a small proxy
 * harness that reproduces the shape the app renders.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, act,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";


// The token used in URL suffixes; localStorage read at MediaCarousel
// module boundary so we set it once here.
beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: {
      getItem: vi.fn((k) => (k === "token" ? "test-token" : "")),
      setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn(),
    },
    writable: true, configurable: true,
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 1 — source-string guards. These lock the wire-up shape on
// ``ServiceLogPage.jsx`` so future refactors don't drop the click
// handler, the lightbox trigger, or the required testids.
// ══════════════════════════════════════════════════════════════════
describe("ServiceLogPage source · lightbox wire-up (Feb-2026)", () => {
  const src = readFileSync(
    resolve(__dirname, "../pages/workstream/ServiceLogPage.jsx"), "utf8",
  );

  it("main carousel image is wrapped in a clickable button", () => {
    // The <img data-testid="service-log-media-image"> must be inside
    // a <button onClick={() => setLightboxOpen(true)} ...>.
    // Match the exact wire-up shape.
    expect(src).toMatch(
      /onClick=\{\(\)\s*=>\s*setLightboxOpen\(true\)\}[\s\S]{0,300}data-testid=\{`id-service-image-thumb-\$\{idx\}`\}/,
    );
  });

  it("declares an inline ImageLightbox component", () => {
    expect(src).toMatch(/function ImageLightbox\(/);
    expect(src).toMatch(/data-testid="id-service-image-lightbox"/);
  });

  it("has all required testids in the source", () => {
    for (const tid of [
      "id-service-image-lightbox",
      "id-service-image-close",
      "id-service-image-prev",
      "id-service-image-next",
      "id-service-image-download",
      "id-service-image-counter",
    ]) {
      expect(src).toContain(`data-testid="${tid}"`);
    }
  });

  it("ESC + ArrowLeft + ArrowRight keys are wired", () => {
    expect(src).toMatch(/e\.key\s*===\s*["']Escape["']/);
    expect(src).toMatch(/e\.key\s*===\s*["']ArrowRight["']/);
    expect(src).toMatch(/e\.key\s*===\s*["']ArrowLeft["']/);
  });

  it("swipe handlers are wired (onTouchStart + onTouchEnd)", () => {
    expect(src).toMatch(/onTouchStart=\{onTouchStart\}/);
    expect(src).toMatch(/onTouchEnd=\{onTouchEnd\}/);
  });

  it("videos are excluded from lightbox nav (kind === 'video' filter)", () => {
    expect(src).toMatch(/it\.kind\s*===\s*["']video["']/);
    // Guard: the returned lightbox short-circuits on video items.
    expect(src).toMatch(/if\s*\(\s*!cur\s*\|\|\s*cur\.kind\s*===\s*["']video["']/);
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 2 — behavioural render tests via a proxy harness that
// reproduces the lightbox shape from the source. This is the same
// pattern already used by ``typed-confirm-delete-modal.test.jsx``
// and ``schedule-optimize-route.test.jsx`` for pages that hang
// under jsdom when mounted whole.
// ══════════════════════════════════════════════════════════════════
function ProxyLightbox({ items, initialIndex = 0 }) {
  // Small proxy that mirrors the ServiceLogPage internal wiring:
  //   * ``lightboxOpen`` state
  //   * click on the "thumbnail" opens the lightbox
  //   * lightbox owns idx via onIndexChange
  // The lightbox JSX is copy-of-source (mirrors the ImageLightbox
  // component's public behaviour). If ServiceLogPage adds a new
  // testid or key handler, layer 1 catches the drift.
  const [idx, setIdx] = React.useState(initialIndex);
  const [open, setOpen] = React.useState(false);
  const _imageIdx = items
    .map((it, i) => (it.kind === "video" ? -1 : i))
    .filter((i) => i >= 0);
  const _imgTotal = _imageIdx.length;
  const _curSlot = Math.max(0, _imageIdx.indexOf(idx));

  const goto = (d) => {
    if (_imgTotal <= 1) return;
    const next = (_curSlot + d + _imgTotal) % _imgTotal;
    setIdx(_imageIdx[next]);
  };

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
      else if (e.key === "ArrowRight") { e.preventDefault(); goto(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); goto(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const cur = items[idx];
  return (
    <div>
      {items.map((it, i) => (
        <button
          key={it.id || i}
          type="button"
          onClick={() => { setIdx(i); setOpen(true); }}
          data-testid={`id-service-image-thumb-${i}`}
        >
          <img src={it.url} alt="" />
        </button>
      ))}
      {open && cur && cur.kind !== "video" ? (
        <div
          onClick={(e) => { if (e.currentTarget === e.target) setOpen(false); }}
          data-testid="id-service-image-lightbox"
        >
          <img src={cur.url} data-testid="id-service-image-lightbox-img" />
          <button data-testid="id-service-image-close"
                    onClick={() => setOpen(false)}>×</button>
          <a data-testid="id-service-image-download" href={cur.url} download>DL</a>
          {_imgTotal > 1 ? (
            <>
              <button data-testid="id-service-image-prev"
                        onClick={(e) => { e.stopPropagation(); goto(-1); }}>‹</button>
              <button data-testid="id-service-image-next"
                        onClick={(e) => { e.stopPropagation(); goto(1); }}>›</button>
              <div data-testid="id-service-image-counter">
                {_curSlot + 1} / {_imgTotal}
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


const IMAGES = [
  { id: "i1", url: "https://cdn.example.com/a.jpg", kind: "image" },
  { id: "i2", url: "https://cdn.example.com/b.jpg", kind: "image" },
  { id: "i3", url: "https://cdn.example.com/c.jpg", kind: "image" },
];


describe("Service log lightbox · behaviour", () => {
  it("thumbnails are rendered with the required clickable testids", () => {
    render(<ProxyLightbox items={IMAGES} />);
    expect(screen.getByTestId("id-service-image-thumb-0")).toBeTruthy();
    expect(screen.getByTestId("id-service-image-thumb-1")).toBeTruthy();
    expect(screen.getByTestId("id-service-image-thumb-2")).toBeTruthy();
  });

  it("clicking a thumbnail opens the lightbox with the correct src", () => {
    render(<ProxyLightbox items={IMAGES} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-1"));
    const img = screen.getByTestId("id-service-image-lightbox-img");
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/b.jpg");
  });

  it("ESC closes the lightbox", () => {
    render(<ProxyLightbox items={IMAGES} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-0"));
    expect(screen.getByTestId("id-service-image-lightbox")).toBeTruthy();
    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(screen.queryByTestId("id-service-image-lightbox")).toBeNull();
  });

  it("clicking the backdrop closes the lightbox", () => {
    render(<ProxyLightbox items={IMAGES} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-0"));
    fireEvent.click(screen.getByTestId("id-service-image-lightbox"));
    expect(screen.queryByTestId("id-service-image-lightbox")).toBeNull();
  });

  it("Next/Prev cycles through images when >1 present", () => {
    render(<ProxyLightbox items={IMAGES} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-0"));
    // Counter: 1 / 3
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("1 / 3");
    fireEvent.click(screen.getByTestId("id-service-image-next"));
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("2 / 3");
    fireEvent.click(screen.getByTestId("id-service-image-next"));
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("3 / 3");
    // Wrap-around → 1/3.
    fireEvent.click(screen.getByTestId("id-service-image-next"));
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("1 / 3");
    // Prev wraps backward.
    fireEvent.click(screen.getByTestId("id-service-image-prev"));
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("3 / 3");
  });

  it("single-image case hides prev/next AND counter", () => {
    render(<ProxyLightbox items={[IMAGES[0]]} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-0"));
    expect(screen.getByTestId("id-service-image-lightbox")).toBeTruthy();
    expect(screen.queryByTestId("id-service-image-prev")).toBeNull();
    expect(screen.queryByTestId("id-service-image-next")).toBeNull();
    expect(screen.queryByTestId("id-service-image-counter")).toBeNull();
  });

  it("videos are skipped from lightbox nav slots", () => {
    const mixed = [
      { id: "i1", url: "a.jpg", kind: "image" },
      { id: "v1", url: "v.mp4", kind: "video" },
      { id: "i2", url: "b.jpg", kind: "image" },
    ];
    render(<ProxyLightbox items={mixed} />);
    fireEvent.click(screen.getByTestId("id-service-image-thumb-0"));
    // Counter uses image slots only — 1 / 2 (not 1 / 3).
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("1 / 2");
    fireEvent.click(screen.getByTestId("id-service-image-next"));
    // Next hops OVER the video and lands on image 2.
    expect(screen.getByTestId("id-service-image-lightbox-img").getAttribute("src"))
      .toBe("b.jpg");
    expect(screen.getByTestId("id-service-image-counter").textContent)
      .toBe("2 / 2");
  });

  it("clicking a video thumbnail does NOT open the lightbox", () => {
    const mixed = [
      { id: "i1", url: "a.jpg", kind: "image" },
      { id: "v1", url: "v.mp4", kind: "video" },
    ];
    render(<ProxyLightbox items={mixed} />);
    // A video thumb still renders in the proxy (mirrors the source's
    // per-item .map — but ServiceLogPage never wraps videos in the
    // clickable image button). Clicking the "video slot" here in the
    // proxy WOULD open, but the lightbox render-guard `cur.kind !==
    // "video"` short-circuits the lightbox JSX so it never appears.
    fireEvent.click(screen.getByTestId("id-service-image-thumb-1"));
    expect(screen.queryByTestId("id-service-image-lightbox")).toBeNull();
  });
});
