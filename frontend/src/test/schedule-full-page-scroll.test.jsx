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
import { assertNoScrollTrap } from "@/test/helpers/assertNoScrollTrap";


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
  it("outermost container passes the shared scroll-trap guard", () => {
    render(
      <MemoryRouter initialEntries={["/schedule"]}>
        <CalendarSchedule />
      </MemoryRouter>,
    );
    const root = screen.getByTestId("calendar-schedule");
    // Now uses <SafeScrollContainer> — the shared helper enforces
    // the same guarantees as the pre-refactor hand-rolled assertions.
    assertNoScrollTrap(root);
    // Sanity: SafeScrollContainer's `pb-24` base still applies.
    expect(root.className).toMatch(/\bpb-24\b/);
  });
});
