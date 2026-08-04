/**
 * Task RR/SS Phase 2 follow-on · Feb 2026 — PersonaAvatar Vitest.
 *
 * Renders under jsdom. Contract:
 *   1. When ``persona.avatar_url`` is set → <img> with matching src + alt.
 *   2. When ``avatar_url`` is null / undefined → emoji fallback via a
 *      role-region rendering ``avatar_emoji`` (or 🤖 if unset).
 *   3. When the image fails to load (onError) → falls back to emoji.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PersonaAvatar } from "@/components/personas/PersonaAvatar";

describe("PersonaAvatar", () => {
  it("renders <img> when persona.avatar_url is set", () => {
    render(
      <PersonaAvatar
        persona={{ key: "skedra", name: "Skedra",
                   avatar_url: "/avatars/personas/skedra.jpg",
                   avatar_emoji: "📅" }}
        size={40}
      />,
    );
    const img = screen.getByTestId("persona-avatar-skedra");
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe("/avatars/personas/skedra.jpg");
    expect(img.getAttribute("alt")).toBe("Skedra avatar");
  });

  it("renders emoji fallback when avatar_url is null", () => {
    render(
      <PersonaAvatar
        persona={{ key: "billy", name: "Billy",
                   avatar_url: null, avatar_emoji: "💳" }}
        size={40}
      />,
    );
    const node = screen.getByTestId("persona-avatar-billy");
    expect(node.tagName).toBe("DIV");
    expect(node.textContent).toContain("💳");
  });

  it("falls back to 🤖 when both avatar_url and avatar_emoji are missing", () => {
    render(
      <PersonaAvatar
        persona={{ key: "unknown-persona", name: "Unknown" }}
        size={32}
      />,
    );
    const node = screen.getByTestId("persona-avatar-unknown-persona");
    expect(node.textContent).toContain("🤖");
  });

  it("swaps to emoji fallback when the image errors out", () => {
    render(
      <PersonaAvatar
        persona={{ key: "casey", name: "Casey",
                   avatar_url: "/avatars/personas/casey.jpg",
                   avatar_emoji: "📇" }}
        size={40}
      />,
    );
    let node = screen.getByTestId("persona-avatar-casey");
    expect(node.tagName).toBe("IMG");
    // Simulate 404 / broken image.
    fireEvent.error(node);
    node = screen.getByTestId("persona-avatar-casey");
    expect(node.tagName).toBe("DIV");
    expect(node.textContent).toContain("📇");
  });

  it("honors size prop (renders with matching width/height style)", () => {
    render(
      <PersonaAvatar
        persona={{ key: "dexter", name: "Dexter", avatar_emoji: "🧮" }}
        size={64}
      />,
    );
    const node = screen.getByTestId("persona-avatar-dexter");
    expect(node.style.width).toBe("64px");
    expect(node.style.height).toBe("64px");
  });
});
