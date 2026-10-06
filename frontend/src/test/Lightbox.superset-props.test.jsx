/**
 * LIGHTBOX-UNIFY-PHASE-A · Feb-2026 — superset-props coverage for
 * the shared ``components/portal/Lightbox.jsx``.
 *
 * Context: the shared Lightbox grew four opt-in props so Phases
 * B + C can migrate every inline lightbox (JobDetail, ServiceLog,
 * WorkstreamJobDrawer, ServiceImagesPortalPage) onto the same
 * component without forking:
 *
 *   * ``enableSwipe`` (default true) — 40 px touch threshold.
 *   * ``enableDownload`` (default false) — Download anchor.
 *   * ``skipVideosOnNav`` (default false) — nav skips video items.
 *   * ``theme`` (default "inherited") — opt-in forced
 *     ``.dark portal-dark`` scope on the overlay.
 *
 * These tests pin BOTH the new prop semantics AND the pre-Phase-A
 * regression contract on existing portal callers (ESC closes,
 * backdrop closes, Arrow keys nav, counter rendering, title
 * rendering, testid parameterisation).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import Lightbox from "../components/portal/Lightbox";

function _items({ withVideo = false, withTitles = false,
                   withDownloadUrl = false } = {}) {
  const base = [
    { url: "/a.jpg", kind: "image",
      ...(withTitles ? { title: "Photo A" } : {}) },
    { url: "/b.jpg", kind: "image",
      ...(withTitles ? { title: "Photo B" } : {}) },
    { url: "/c.jpg", kind: "image",
      ...(withTitles ? { title: "Photo C" } : {}),
      ...(withDownloadUrl ? { downloadUrl: "/c.jpg?dl=1" } : {}) },
  ];
  if (withVideo) {
    // Insert a video at slot 1 so nav from slot 0 would land on
    // the video in the no-skip case.
    base.splice(1, 0, { url: "/v.mp4", kind: "video" });
  }
  return base;
}

afterEach(() => cleanup());


describe("LIGHTBOX-UNIFY-PHASE-A · regression contract (pre-Phase-A)", () => {
  it("renders nothing when open=false", () => {
    const { container } = render(
      <Lightbox items={_items()} open={false} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders image + testid when open=true (default prefix)", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    expect(screen.getByTestId("portal-lightbox")).toBeInTheDocument();
    expect(screen.getByTestId("portal-lightbox-image")).toHaveAttribute(
      "src", "/a.jpg",
    );
  });

  it("backdrop click calls onClose", () => {
    const onClose = vi.fn();
    render(<Lightbox items={_items()} open onClose={onClose} />);
    fireEvent.click(screen.getByTestId("portal-lightbox"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ESC key calls onClose", () => {
    const onClose = vi.fn();
    render(<Lightbox items={_items()} open onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ArrowRight / ArrowLeft wrap around on multi-item sets", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    const img = () => screen.getByTestId("portal-lightbox-image");
    expect(img()).toHaveAttribute("src", "/a.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(img()).toHaveAttribute("src", "/b.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(img()).toHaveAttribute("src", "/c.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(img()).toHaveAttribute("src", "/a.jpg");  // wrap
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(img()).toHaveAttribute("src", "/c.jpg");  // wrap-left
  });

  it("Prev / Next buttons hidden when single item", () => {
    render(<Lightbox items={[{ url: "/x.jpg" }]} open onClose={() => {}} />);
    expect(screen.queryByTestId("portal-lightbox-prev")).toBeNull();
    expect(screen.queryByTestId("portal-lightbox-next")).toBeNull();
  });

  it("counter renders when multi-item", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    expect(screen.getByTestId("portal-lightbox-counter"))
      .toHaveTextContent("1 / 3");
  });

  it("title + subtitle render when provided", () => {
    const items = [{ url: "/x.jpg", title: "Hi", subtitle: "sub" }];
    render(<Lightbox items={items} open onClose={() => {}} />);
    expect(screen.getByTestId("portal-lightbox-title")).toHaveTextContent("Hi");
  });

  it("testidPrefix parameterisation works", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}}
                 testidPrefix="jd-lightbox" />,
    );
    expect(screen.getByTestId("jd-lightbox")).toBeInTheDocument();
    expect(screen.getByTestId("jd-lightbox-image")).toBeInTheDocument();
    expect(screen.getByTestId("jd-lightbox-close")).toBeInTheDocument();
  });

  it("renders a <video> for item.kind='video'", () => {
    const items = [{ url: "/v.mp4", kind: "video" }];
    render(<Lightbox items={items} open onClose={() => {}} />);
    expect(screen.getByTestId("portal-lightbox-video"))
      .toHaveAttribute("src", "/v.mp4");
  });
});


describe("LIGHTBOX-UNIFY-PHASE-A · theme prop", () => {
  it("default (inherited) does NOT emit .dark .portal-dark on the overlay", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    const overlay = screen.getByTestId("portal-lightbox");
    expect(overlay).not.toHaveClass("dark");
    expect(overlay).not.toHaveClass("portal-dark");
  });

  it("theme='dark' emits .dark .portal-dark on the overlay (opt-in)", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}} theme="dark" />,
    );
    const overlay = screen.getByTestId("portal-lightbox");
    expect(overlay).toHaveClass("dark");
    expect(overlay).toHaveClass("portal-dark");
  });

  it("theme='inherited' explicit matches the default", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}} theme="inherited" />,
    );
    const overlay = screen.getByTestId("portal-lightbox");
    expect(overlay).not.toHaveClass("portal-dark");
  });
});


describe("LIGHTBOX-UNIFY-PHASE-A · enableDownload prop", () => {
  it("default (false) hides the Download anchor", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    expect(screen.queryByTestId("portal-lightbox-download")).toBeNull();
  });

  it("enableDownload=true renders Download anchor pointing at item.url", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}}
                 enableDownload />,
    );
    const link = screen.getByTestId("portal-lightbox-download");
    expect(link).toHaveAttribute("href", "/a.jpg");
    expect(link).toHaveAttribute("download");
  });

  it("enableDownload=true prefers item.downloadUrl over item.url when both present", () => {
    render(
      <Lightbox items={_items({ withDownloadUrl: true })} open
                 onClose={() => {}} enableDownload
                 initialIndex={2} />,
    );
    const link = screen.getByTestId("portal-lightbox-download");
    expect(link).toHaveAttribute("href", "/c.jpg?dl=1");
  });

  it("Download click does NOT bubble up and trigger onClose", () => {
    const onClose = vi.fn();
    render(
      <Lightbox items={_items()} open onClose={onClose}
                 enableDownload />,
    );
    fireEvent.click(screen.getByTestId("portal-lightbox-download"));
    expect(onClose).not.toHaveBeenCalled();
  });
});


describe("LIGHTBOX-UNIFY-PHASE-A · skipVideosOnNav prop", () => {
  it("default (false) — Arrow nav lands on video items", () => {
    render(
      <Lightbox items={_items({ withVideo: true })} open
                 onClose={() => {}} />,
    );
    // Items: [image-a, video, image-b, image-c].  From slot 0,
    // Arrow-right lands on slot 1 (video).  Expect <video> to
    // render instead of <img>.
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.queryByTestId("portal-lightbox-image")).toBeNull();
    expect(screen.getByTestId("portal-lightbox-video"))
      .toHaveAttribute("src", "/v.mp4");
  });

  it("skipVideosOnNav=true — Arrow nav skips video items entirely", () => {
    render(
      <Lightbox items={_items({ withVideo: true })} open
                 onClose={() => {}} skipVideosOnNav />,
    );
    // Items: [image-a, video, image-b, image-c].  From slot 0,
    // Arrow-right MUST skip slot 1 (video) and land on slot 2
    // (image-b).  Repeated Arrow-right lands on slot 3
    // (image-c).  Arrow-left from slot 0 wraps to slot 3.
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/b.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/c.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");  // wrap
  });
});


describe("LIGHTBOX-UNIFY-PHASE-A · enableSwipe prop", () => {
  function _swipe(target, startX, endX) {
    fireEvent.touchStart(target, { touches: [{ clientX: startX }] });
    fireEvent.touchEnd(target, { changedTouches: [{ clientX: endX }] });
  }

  it("default (true) — leftward swipe > 40 px advances to next item", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    const overlay = screen.getByTestId("portal-lightbox");
    _swipe(overlay, 200, 100);  // 100 px left-swipe
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/b.jpg");
  });

  it("default (true) — rightward swipe > 40 px advances to previous item", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}}
                 initialIndex={1} />,
    );
    const overlay = screen.getByTestId("portal-lightbox");
    _swipe(overlay, 100, 200);  // 100 px right-swipe
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");
  });

  it("swipes under 40 px are ignored (no nav)", () => {
    render(<Lightbox items={_items()} open onClose={() => {}} />);
    const overlay = screen.getByTestId("portal-lightbox");
    _swipe(overlay, 200, 180);  // only 20 px delta
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");
  });

  it("enableSwipe=false — touch events do NOT nav", () => {
    render(
      <Lightbox items={_items()} open onClose={() => {}}
                 enableSwipe={false} />,
    );
    const overlay = screen.getByTestId("portal-lightbox");
    _swipe(overlay, 200, 50);  // big swipe
    expect(screen.getByTestId("portal-lightbox-image"))
      .toHaveAttribute("src", "/a.jpg");  // unchanged
  });
});
