/**
 * Feb-2026 · Tech Schedule full-page scroll — vitest guard.
 *
 * Mirrors the pattern established by the Dispatch Board fix: the
 * outermost page container MUST NOT carry ``overflow: hidden`` /
 * ``overflow-y: scroll`` / ``height: 100vh`` / ``max-height`` so the
 * document scrolls naturally when the weather widget + tech legend +
 * calendar + day-summary cards exceed the viewport.
 *
 * The react-big-calendar itself owns its internal time-of-day
 * scroll — that's fine and expected. This test only pins the outer
 * container's styles.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// Stub heavy dependencies so the mount only exercises the outer
// container render path.
vi.mock("@/api", () => ({
  api: { get: vi.fn().mockResolvedValue([]), post: vi.fn(), patch: vi.fn(), put: vi.fn() },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "technician", id: "u1", name: "Mike" } }),
}));
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: () => null,
  APIProvider: ({ children }) => children,
  useMap: () => null,
  useMapsLibrary: () => null,
  AdvancedMarker: () => null,
  Pin: () => null,
  InfoWindow: () => null,
}));
vi.mock("react-big-calendar", () => ({
  Calendar: () => <div data-testid="rbc-stub" />,
  Views: {},
  dateFnsLocalizer: () => ({}),
}));
vi.mock("react-big-calendar/lib/addons/dragAndDrop", () => ({
  default: (X) => X,
}));
vi.mock("@/pages/schedule/TechWeatherWidget", () => ({
  default: () => null,
}));


import CalendarSchedule from "@/pages/schedule/CalendarSchedule";


beforeEach(() => {
  // Wipe any stale styles.
  document.head.innerHTML = "";
});


describe("CalendarSchedule — full-page scroll (outer container)", () => {
  it("outermost container does NOT have overflow: hidden / scroll or height: 100vh", () => {
    render(
      <MemoryRouter initialEntries={["/schedule"]}>
        <CalendarSchedule />
      </MemoryRouter>,
    );
    const root = screen.getByTestId("calendar-schedule");
    const styles = window.getComputedStyle(root);
    // The trap symptoms.
    expect(styles.overflow).not.toBe("hidden");
    expect(styles.overflowY).not.toBe("scroll");
    expect(styles.overflowY).not.toBe("hidden");
    expect(styles.height).not.toBe("100vh");
    // The tailwind classes on the outer div — assertion-friendly.
    expect(root.className).toMatch(/pb-24/);
    expect(root.className).not.toMatch(/\bh-screen\b/);
    expect(root.className).not.toMatch(/\bmax-h-\[?/);
  });
});
