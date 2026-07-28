/**
 * Phase B1 · Feb 2026 — Header user-menu <UserAvatar> integration.
 *
 * Focused DOM assertion: when the auth user carries a
 * ``profile_photo_url``, the sidebar footer renders an <img> avatar;
 * when unset, initials render instead. We intentionally exercise the
 * <UserAvatar> component directly with the same user shape that the
 * AppLayout footer feeds it — the AppLayout itself pulls in the
 * entire nav tree which is too heavy for a targeted vitest.
 */
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { UserAvatar } from "@/components/UserAvatar";

describe("Header user-menu · UserAvatar surface", () => {
  afterEach(() => cleanup());

  it("renders <img> for user with profile_photo_url", () => {
    const user = {
      id: "u-1",
      name: "Brian Beck",
      email: "brian@plofv.com",
      role: "admin",
      profile_photo_url: "/api/files/photo-1/download",
    };
    render(<UserAvatar user={user} size="md" testid="shell-user-avatar" />);
    const img = screen.getByTestId("shell-user-avatar-img");
    expect(img.tagName.toLowerCase()).toBe("img");
    expect(img.getAttribute("src")).toBe("/api/files/photo-1/download");
    expect(img.getAttribute("alt")).toBe("Brian Beck");
  });

  it("renders initials for user without profile_photo_url", () => {
    const user = {
      id: "u-2",
      name: "Mary Watson",
      email: "mary@example.com",
      role: "manager",
      profile_photo_url: null,
    };
    render(<UserAvatar user={user} size="md" testid="shell-user-avatar" />);
    const badge = screen.getByTestId("shell-user-avatar-initials");
    expect(badge.textContent).toBe("MW");
    expect(screen.queryByTestId("shell-user-avatar-img")).toBeNull();
  });

  it("renders ? for null user (defensive)", () => {
    render(<UserAvatar user={null} size="md" testid="shell-user-avatar" />);
    expect(
      screen.getByTestId("shell-user-avatar-initials").textContent,
    ).toBe("?");
  });
});
