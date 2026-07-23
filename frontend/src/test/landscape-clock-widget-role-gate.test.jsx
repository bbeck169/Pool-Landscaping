/**
 * Feb-2026 · Role gate for the top-of-page Landscape Time Clock widget.
 *
 *   1. Admin / super_admin — widget renders null (bar is hidden). The
 *      bar is pure noise on the admin dashboard; previously it was
 *      force-shown even when the admin had no landscape department.
 *   2. Landscape tech (department "landscaping") — widget renders the
 *      full bar (data-testid="landscape-clock-widget"). Techs need
 *      access to punch in/out.
 *
 * We stub `useAuth` and `@/api` so the widget mounts without hitting
 * the network. `api.get` is stubbed to resolve to empty payloads —
 * enough for the render path to reach the bar or return null.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Hoist-safe user swap — the mock reads from the module scope on every
// render, so each test can rewrite `currentUser` before mounting.
let currentUser = null;
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: currentUser }),
}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ punches: [], seconds: 0, items: [] }),
    post: vi.fn().mockResolvedValue({}),
  },
}));

import LandscapingClockWidget from "@/components/LandscapingClockWidget";

const renderWidget = () =>
  render(
    <MemoryRouter>
      <LandscapingClockWidget />
    </MemoryRouter>
  );

beforeEach(() => {
  currentUser = null;
});

describe("LandscapingClockWidget role gate", () => {
  it("renders null for admin (bar hidden — no timer, no clock-in button)", () => {
    currentUser = { role: "admin", department: "landscaping" };
    const { container } = renderWidget();
    // Even with landscape department, admin should NOT see the bar.
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("landscape-clock-widget")).toBeNull();
  });

  it("renders null for super_admin", () => {
    currentUser = { role: "super_admin", department: "both" };
    const { container } = renderWidget();
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("landscape-clock-widget")).toBeNull();
  });

  it("renders the bar for a landscape tech (role=pool_tech, dept=landscaping)", async () => {
    currentUser = { role: "pool_tech", department: "landscaping" };
    renderWidget();
    // Bar is visible with the standard testid.
    const bar = await screen.findByTestId("landscape-clock-widget");
    expect(bar).toBeInTheDocument();
    // "Off the clock" copy renders because the stubbed today payload
    // has no open punch.
    expect(screen.getByText(/off the clock/i)).toBeInTheDocument();
  });

  it("renders the bar for a manager with landscape department", async () => {
    currentUser = { role: "manager", department: "both" };
    renderWidget();
    const bar = await screen.findByTestId("landscape-clock-widget");
    expect(bar).toBeInTheDocument();
  });

  it("renders null for a pool_tech without landscape department", () => {
    currentUser = { role: "pool_tech", department: "pool" };
    const { container } = renderWidget();
    expect(container.firstChild).toBeNull();
  });
});
