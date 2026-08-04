/**
 * Phase 50 · Feb-2026 — AI avatar component + Lottie mount guard.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock the Lottie module — we don't want to actually animate in a test.
vi.mock("lottie-react", () => ({
  default: (props) => (
    <div data-testid="lottie-mock" data-loop={String(props.loop)} data-autoplay={String(props.autoplay)} />
  ),
}));

import AIAvatar from "@/components/ai/AIAvatar";

describe("Phase 50 · AIAvatar", () => {
  it("mounts a Lottie component with loop+autoplay", () => {
    render(<AIAvatar src="/avatars/personas/emmie.jpg" alt="Emmie" testId="emmie-avatar" />);
    const l = screen.getByTestId("lottie-mock");
    expect(l).toBeInTheDocument();
    expect(l.getAttribute("data-loop")).toBe("true");
    expect(l.getAttribute("data-autoplay")).toBe("true");
    expect(screen.getByTestId("emmie-avatar")).toBeInTheDocument();
  });

  it("renders the static image on top of the Lottie backdrop", () => {
    render(<AIAvatar src="/x.jpg" alt="X" />);
    const img = document.querySelector('img[src="/x.jpg"]');
    expect(img).not.toBeNull();
  });

  it("component source imports the shared Lottie JSON (no per-employee JSONs)", () => {
    const src = readFileSync(
      resolve(__dirname, "../components/ai/AIAvatar.jsx"),
      "utf8",
    );
    expect(src).toContain('from "@/assets/lottie/ai/idle.json"');
    expect(src).toContain('from "lottie-react"');
  });
});
