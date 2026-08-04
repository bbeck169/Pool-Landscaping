/**
 * Phase 50.1 · Feb-2026 — AI Avatar image overlay parity guard.
 *
 * When the caller passes an ``src`` (from a persona's ``avatar_url``),
 * ``<AIAvatar>`` must layer the static image on top of the shared
 * Lottie backdrop. When ``src`` is null / undefined, only the Lottie
 * layer must render — no broken ``<img>`` placeholder.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Local ``lottie-react`` mock so the assertions can pin ``data-loop``
// + ``data-autoplay`` while the shared setup.js mock (which returns
// ``null``) is overridden here.
vi.mock("lottie-react", () => ({
  __esModule: true,
  default: (props) => (
    <div
      data-testid="lottie-mock"
      data-loop={String(props.loop)}
      data-autoplay={String(props.autoplay)}
    />
  ),
}));

import AIAvatar from "@/components/ai/AIAvatar";

describe("Phase 50.1 · <AIAvatar> image overlay parity", () => {
  it("renders BOTH Lottie backdrop AND static <img> when avatar_url is present", () => {
    render(
      <AIAvatar
        src="/avatars/personas/billy.jpg"
        alt="Billy"
        testId="ai-lottie-avatar-billy"
      />,
    );
    // Lottie backdrop
    expect(screen.getByTestId("lottie-mock")).toBeInTheDocument();
    // Static image on top
    const img = document.querySelector('img[src="/avatars/personas/billy.jpg"]');
    expect(img).not.toBeNull();
    expect(img.getAttribute("alt")).toBe("Billy");
    // Wrapper wired up with the requested testId
    expect(screen.getByTestId("ai-lottie-avatar-billy")).toBeInTheDocument();
  });

  it("renders ONLY the Lottie backdrop when avatar_url is null / undefined", () => {
    const { container } = render(
      <AIAvatar testId="ai-lottie-avatar-no-image" />,
    );
    expect(screen.getByTestId("lottie-mock")).toBeInTheDocument();
    // No <img> element at all — falling back to Lottie-only avoids
    // showing a broken-image icon.
    expect(container.querySelector("img")).toBeNull();
  });

  it("does not render an <img> when src is an empty string", () => {
    const { container } = render(
      <AIAvatar src="" testId="ai-lottie-avatar-empty-src" />,
    );
    // Empty string is falsy in JSX -> no <img>. Guarantees the
    // backend null-safety contract (avatar_url may be null) doesn't
    // paint a broken-image icon if a rogue empty string slips in.
    expect(container.querySelector("img")).toBeNull();
  });

  it("layers the img on top of the Lottie with absolute positioning", () => {
    render(
      <AIAvatar
        src="/avatars/personas/emmie.jpg"
        alt="Emmie"
        size={80}
        testId="ai-lottie-avatar-emmie"
      />,
    );
    const img = document.querySelector('img[src="/avatars/personas/emmie.jpg"]');
    expect(img).not.toBeNull();
    // Inline style asserts we're overlaying, not stacking.
    const style = img.getAttribute("style") || "";
    expect(style).toMatch(/position:\s*absolute/);
    expect(style).toMatch(/border-radius:\s*50%/);
  });
});
