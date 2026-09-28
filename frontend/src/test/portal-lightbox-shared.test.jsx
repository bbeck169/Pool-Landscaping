/**
 * DTP-1 · Feb-2026 — Shared Portal Lightbox contract.
 *
 * Covers:
 *   * Image branch → ``{prefix}-image`` renders.
 *   * Video branch → ``{prefix}-video`` renders (kind="video").
 *   * ESC closes (fires ``onClose``).
 *   * Backdrop click closes.
 *   * ArrowRight cycles index; wraps around.
 *   * open=false renders nothing.
 *   * Single-item lightbox hides prev/next buttons.
 *   * Title element renders when title provided.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import Lightbox from "@/components/portal/Lightbox";

afterEach(() => cleanup());

describe("Portal Lightbox (shared)", () => {
  it("renders image with {prefix}-image testid when kind='image'", () => {
    render(
      <Lightbox
        items={[{ url: "a.jpg", kind: "image", title: "First" }]}
        initialIndex={0}
        open
        onClose={() => {}}
        testidPrefix="pl"
      />,
    );
    expect(screen.getByTestId("pl")).toBeTruthy();
    expect(screen.getByTestId("pl-image")).toBeTruthy();
    expect(screen.getByTestId("pl-title").textContent).toBe("First");
  });

  it("renders video branch with {prefix}-video testid when kind='video'", () => {
    render(
      <Lightbox
        items={[{ url: "v.mp4", kind: "video" }]}
        initialIndex={0}
        open
        onClose={() => {}}
        testidPrefix="pl"
      />,
    );
    expect(screen.getByTestId("pl-video")).toBeTruthy();
  });

  it("closes on ESC key (fires onClose)", () => {
    const onClose = vi.fn();
    render(
      <Lightbox
        items={[{ url: "a.jpg", kind: "image" }]}
        initialIndex={0}
        open
        onClose={onClose}
        testidPrefix="pl"
      />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on backdrop click (fires onClose)", () => {
    const onClose = vi.fn();
    render(
      <Lightbox
        items={[{ url: "a.jpg", kind: "image" }]}
        initialIndex={0}
        open
        onClose={onClose}
        testidPrefix="pl"
      />,
    );
    fireEvent.click(screen.getByTestId("pl"));
    expect(onClose).toHaveBeenCalled();
  });

  it("ArrowRight cycles index and wraps around", () => {
    render(
      <Lightbox
        items={[
          { url: "a.jpg", kind: "image", title: "A" },
          { url: "b.jpg", kind: "image", title: "B" },
        ]}
        initialIndex={0}
        open
        onClose={() => {}}
        testidPrefix="pl"
      />,
    );
    expect(screen.getByTestId("pl-title").textContent).toBe("A");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByTestId("pl-title").textContent).toBe("B");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(screen.getByTestId("pl-title").textContent).toBe("A");
  });

  it("returns null when open=false", () => {
    const { container } = render(
      <Lightbox
        items={[{ url: "a.jpg", kind: "image" }]}
        initialIndex={0}
        open={false}
        onClose={() => {}}
        testidPrefix="pl"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("hides prev/next buttons when items.length === 1", () => {
    render(
      <Lightbox
        items={[{ url: "a.jpg", kind: "image" }]}
        initialIndex={0}
        open
        onClose={() => {}}
        testidPrefix="pl1"
      />,
    );
    expect(screen.queryByTestId("pl1-prev")).toBeNull();
    expect(screen.queryByTestId("pl1-next")).toBeNull();
  });

  it("shows prev/next + counter when items.length > 1", () => {
    render(
      <Lightbox
        items={[
          { url: "a.jpg", kind: "image" },
          { url: "b.jpg", kind: "image" },
        ]}
        initialIndex={0}
        open
        onClose={() => {}}
        testidPrefix="pl2"
      />,
    );
    expect(screen.getByTestId("pl2-prev")).toBeTruthy();
    expect(screen.getByTestId("pl2-next")).toBeTruthy();
    expect(screen.getByTestId("pl2-counter").textContent).toBe("1 / 2");
  });
});
