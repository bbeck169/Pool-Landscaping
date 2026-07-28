/**
 * Phase B1 · Feb 2026 — <UserAvatar> Vitest.
 *
 * Contract:
 *   1. profile_photo_url set → <img> rendered with matching src.
 *   2. profile_photo_url absent → initials badge rendered.
 *   3. Email-only user → initials derived from local part.
 *   4. onError of <img> → falls back to initials badge.
 *   5. computeInitials helper correctness.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { UserAvatar, computeInitials } from "@/components/UserAvatar";

describe("computeInitials", () => {
  it("uses first + last word first letters for multi-word names", () => {
    expect(computeInitials("Brian Beck")).toBe("BB");
    expect(computeInitials("mary jane watson")).toBe("MW");
  });
  it("falls back to first two letters for single-word names", () => {
    expect(computeInitials("Cher")).toBe("CH");
  });
  it("derives from email local part when name is missing", () => {
    expect(computeInitials("john.doe@example.com")).toBe("JD");
    expect(computeInitials("brian@plofv.com")).toBe("BR");
  });
  it("returns ? for empty input", () => {
    expect(computeInitials("")).toBe("?");
    expect(computeInitials(null)).toBe("?");
    expect(computeInitials(undefined)).toBe("?");
  });
});

describe("<UserAvatar>", () => {
  afterEach(() => cleanup());

  it("renders <img> when profile_photo_url is set", () => {
    render(
      <UserAvatar
        user={{ name: "Brian Beck", profile_photo_url: "/api/files/f-1/download" }}
        testid="ua"
      />,
    );
    const img = screen.getByTestId("ua-img");
    expect(img.tagName.toLowerCase()).toBe("img");
    expect(img.getAttribute("src")).toBe("/api/files/f-1/download");
    expect(screen.queryByTestId("ua-initials")).toBeNull();
  });

  it("renders initials when profile_photo_url is absent", () => {
    render(
      <UserAvatar
        user={{ name: "Brian Beck", profile_photo_url: null }}
        testid="ua"
      />,
    );
    expect(screen.getByTestId("ua-initials").textContent).toBe("BB");
    expect(screen.queryByTestId("ua-img")).toBeNull();
  });

  it("falls back to initials when the image fails to load", () => {
    render(
      <UserAvatar
        user={{ name: "Jane Doe", profile_photo_url: "/api/files/broken/download" }}
        testid="ua"
      />,
    );
    // Initially img is rendered
    const img = screen.getByTestId("ua-img");
    // Simulate onError
    fireEvent.error(img);
    // After error, initials are shown
    expect(screen.getByTestId("ua-initials").textContent).toBe("JD");
    expect(screen.queryByTestId("ua-img")).toBeNull();
  });

  it("supports numeric size prop", () => {
    const { container } = render(
      <UserAvatar user={{ name: "Ann" }} size={64} testid="ua" />,
    );
    const root = container.querySelector('[data-testid="ua"]');
    expect(root.style.width).toBe("64px");
    expect(root.style.height).toBe("64px");
  });

  it("supports size keyword (xs/sm/md/lg)", () => {
    const { container } = render(
      <UserAvatar user={{ name: "Ann" }} size="xs" testid="ua" />,
    );
    const root = container.querySelector('[data-testid="ua"]');
    expect(root.style.width).toBe("16px");
  });

  it("handles null user gracefully (?)", () => {
    render(<UserAvatar user={null} testid="ua" />);
    expect(screen.getByTestId("ua-initials").textContent).toBe("?");
  });
});
