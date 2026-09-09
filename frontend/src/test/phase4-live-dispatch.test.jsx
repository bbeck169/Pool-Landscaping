/**
 * Feb-2026 · Live-Tech-Map · Phase 4 batched — component tests.
 *
 * Focused RTL suite for the three new/updated pieces:
 *   1. ``DispatchSchedulePanel`` — grouping, focus click, empty
 *      state, isolate dim.
 *   2. ``DispatchColorLegend`` — entries, isolate click, empty hide.
 *   3. ``LiveTechPinsLayer`` — stale-fade > 15 min, isolate dim,
 *      "Last seen" tooltip in the InfoWindow.
 *
 * The main-integration behaviour on ``DispatchBoardPage`` (30s
 * poll, ETag flow, filter chain wiring) is covered by an
 * integration test in a separate file to keep this suite tight.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

// react-google-maps' AdvancedMarker + InfoWindow use ``createPortal``
// under the hood, so unit tests need a stub that just renders
// children inline. This mirrors the pattern in
// ``src/test/dispatch-live-pins.test.jsx``.
vi.mock("../lib/maps", () => ({
  Map: ({ children }) => <div data-testid="stub-map">{children}</div>,
  AdvancedMarker: ({ children, position, onClick }) => (
    <div data-testid={`stub-marker-${position?.lat}-${position?.lng}`}
         data-position-lat={position?.lat} onClick={onClick}>
      {children}
    </div>
  ),
  InfoWindow: ({ children, position }) => (
    <div data-testid={`stub-infowindow-${position?.lat}-${position?.lng}`}>
      {children}
    </div>
  ),
  useMap: () => null,
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f7f7f7", onSurface: "#111",
    border: "#ddd", muted: "#666", brand: "#0EA5E9",
    brandTertiary: "#EFF6FF", onBrandTertiary: "#111",
  },
}));

vi.mock("@/utils/formatAddress", () => ({
  default: (a) => (typeof a === "string" ? a : (a?.line1 || "—")),
}));


// ═════════════════════════════════════════════════════════════════
// 1 · DispatchSchedulePanel
// ═════════════════════════════════════════════════════════════════
describe("DispatchSchedulePanel", () => {
  const _PINS = [
    { customer_id: "c1", name: "Alice", address: "1 Alpha St",
      is_scheduled_this_day: true, assigned_tech_ids: ["tA"],
      tech_color_hex: "#3B82F6" },
    { customer_id: "c2", name: "Bob",   address: "2 Beta St",
      is_scheduled_this_day: true, assigned_tech_ids: ["tA"],
      tech_color_hex: "#3B82F6" },
    { customer_id: "c3", name: "Carol", address: "3 Gamma St",
      is_scheduled_this_day: true, assigned_tech_ids: ["tB"],
      tech_color_hex: "#EF4444" },
    { customer_id: "c4", name: "Dave (unscheduled)", is_scheduled_this_day: false,
      assigned_tech_ids: ["tA"] },
  ];

  const _NAMES = { tA: "Alex R.", tB: "Bob M." };

  it("renders only scheduled pins, grouped by tech", async () => {
    const { default: Panel } = await import("@/pages/dispatch/DispatchSchedulePanel");
    render(<Panel pins={_PINS} techNameById={_NAMES} />);
    // 3 scheduled → 2 groups (Alex + Bob).
    expect(screen.getByTestId("dispatch-schedule-panel")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-schedule-group-tA")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-schedule-group-tB")).toBeInTheDocument();
    // 3 stop rows, no c4 (unscheduled).
    expect(screen.getAllByTestId(/dispatch-schedule-panel-item-/)).toHaveLength(3);
    expect(screen.queryByTestId("dispatch-schedule-panel-item-c4")).toBeNull();
  });

  it("empty state renders when no pins are scheduled", async () => {
    const { default: Panel } = await import("@/pages/dispatch/DispatchSchedulePanel");
    render(<Panel pins={[_PINS[3]]} dayLabel="Wed" />);
    const panel = screen.getByTestId("dispatch-schedule-panel");
    expect(panel.getAttribute("data-empty")).toBe("true");
    expect(panel.textContent).toMatch(/No jobs scheduled for Wed/);
  });

  it("clicking a row fires onFocusStop with the pin", async () => {
    const onFocus = vi.fn();
    const { default: Panel } = await import("@/pages/dispatch/DispatchSchedulePanel");
    render(<Panel pins={_PINS} techNameById={_NAMES} onFocusStop={onFocus} />);
    fireEvent.click(screen.getByTestId("dispatch-schedule-panel-item-c2"));
    expect(onFocus).toHaveBeenCalledWith(expect.objectContaining({ customer_id: "c2" }));
  });

  it("dims rows for non-isolated techs in tech mode", async () => {
    const { default: Panel } = await import("@/pages/dispatch/DispatchSchedulePanel");
    render(<Panel pins={_PINS} techNameById={_NAMES} isolatedTechId="tA" />);
    const c1 = screen.getByTestId("dispatch-schedule-panel-item-c1");
    const c3 = screen.getByTestId("dispatch-schedule-panel-item-c3");
    expect(c1.getAttribute("data-dimmed")).toBe("false");
    expect(c3.getAttribute("data-dimmed")).toBe("true");
  });

  it("groups by service_day when pinColorMode='service_day'", async () => {
    const pins = [
      { customer_id: "c1", name: "A", is_scheduled_this_day: true,
        service_day: "mon", assigned_tech_ids: [] },
      { customer_id: "c2", name: "B", is_scheduled_this_day: true,
        service_day: "wed", assigned_tech_ids: [] },
    ];
    const { default: Panel } = await import("@/pages/dispatch/DispatchSchedulePanel");
    render(<Panel pins={pins} pinColorMode="service_day" />);
    expect(screen.getByTestId("dispatch-schedule-group-mon")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-schedule-group-wed")).toBeInTheDocument();
    const panel = screen.getByTestId("dispatch-schedule-panel");
    expect(panel.getAttribute("data-pin-color-mode")).toBe("service_day");
  });
});

// ═════════════════════════════════════════════════════════════════
// 2 · DispatchColorLegend
// ═════════════════════════════════════════════════════════════════
describe("DispatchColorLegend", () => {
  const _PINS = [
    { customer_id: "c1", is_scheduled_this_day: true,
      assigned_tech_ids: ["tA"], tech_color_hex: "#3B82F6" },
    { customer_id: "c2", is_scheduled_this_day: true,
      assigned_tech_ids: ["tB"], tech_color_hex: "#EF4444" },
    { customer_id: "c3", is_scheduled_this_day: false,
      assigned_tech_ids: ["tC"], tech_color_hex: "#84CC16" },
  ];
  const _NAMES = { tA: "Alex R.", tB: "Bob M.", tC: "Carol L." };

  it("renders one entry per scheduled tech", async () => {
    const { default: Legend } = await import("@/pages/dispatch/DispatchColorLegend");
    render(<Legend pins={_PINS} techNameById={_NAMES} />);
    const container = screen.getByTestId("dispatch-color-legend");
    const items = within(container).getAllByRole("button");
    // c3 is unscheduled → tC excluded.
    expect(items).toHaveLength(2);
    expect(screen.getByTestId("dispatch-color-legend-item-tA")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-color-legend-item-tB")).toBeInTheDocument();
    expect(screen.queryByTestId("dispatch-color-legend-item-tC")).toBeNull();
  });

  it("hides itself when no scheduled entries", async () => {
    const { default: Legend } = await import("@/pages/dispatch/DispatchColorLegend");
    const { container } = render(<Legend pins={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("clicking a legend entry calls onIsolate with that key", async () => {
    const onIsolate = vi.fn();
    const { default: Legend } = await import("@/pages/dispatch/DispatchColorLegend");
    render(<Legend pins={_PINS} techNameById={_NAMES} onIsolate={onIsolate} />);
    fireEvent.click(screen.getByTestId("dispatch-color-legend-item-tA"));
    expect(onIsolate).toHaveBeenCalledWith("tA");
  });

  it("clicking the isolated entry clears the isolate (toggle-off)", async () => {
    const onIsolate = vi.fn();
    const { default: Legend } = await import("@/pages/dispatch/DispatchColorLegend");
    render(<Legend pins={_PINS} techNameById={_NAMES}
                   isolatedKey="tA" onIsolate={onIsolate} />);
    fireEvent.click(screen.getByTestId("dispatch-color-legend-item-tA"));
    expect(onIsolate).toHaveBeenCalledWith(null);
    // Marked active in the DOM.
    expect(screen.getByTestId("dispatch-color-legend-item-tA").getAttribute("data-active"))
      .toBe("true");
  });

  it("does not fire onIsolate in crew mode (Phase 5 nice-to-have)", async () => {
    const onIsolate = vi.fn();
    const pins = [
      { customer_id: "c1", is_scheduled_this_day: true,
        crew_label: "AM Crew", crew_color_hex: "#3B82F6" },
    ];
    const { default: Legend } = await import("@/pages/dispatch/DispatchColorLegend");
    render(<Legend pins={pins} pinColorMode="crew" onIsolate={onIsolate} />);
    fireEvent.click(screen.getByTestId("dispatch-color-legend-item-AM Crew"));
    expect(onIsolate).not.toHaveBeenCalled();
  });
});

// ═════════════════════════════════════════════════════════════════
// 3 · LiveTechPinsLayer (stale-fade + isolate)
// ═════════════════════════════════════════════════════════════════
describe("LiveTechPinsLayer (Phase 4.core)", () => {
  const _POS = [
    { user_id: "tA", user_name: "Alex R.", lat: 33.71, lon: -112.32,
      staleness_s: 60,        accuracy_m: 15 },   // fresh
    { user_id: "tB", user_name: "Bob M.", lat: 33.73, lon: -112.30,
      staleness_s: 20 * 60,   accuracy_m: 30 },   // stale (> 15 min)
  ];

  it("fades pins older than staleThresholdMs and flags data-stale", async () => {
    const { default: Layer } = await import("@/pages/dispatch/LiveTechPinsLayer");
    render(<Layer positions={_POS} staleThresholdMs={15 * 60 * 1000} />);
    const fresh = screen.getByTestId("dispatch-live-tech-tA");
    const stale = screen.getByTestId("dispatch-live-tech-tB");
    expect(fresh.getAttribute("data-stale")).toBe("false");
    expect(stale.getAttribute("data-stale")).toBe("true");
  });

  it("dims all techs except the isolated one", async () => {
    const { default: Layer } = await import("@/pages/dispatch/LiveTechPinsLayer");
    render(<Layer positions={_POS} isolatedTechId="tA" />);
    expect(screen.getByTestId("dispatch-live-tech-tA").getAttribute("data-dimmed")).toBe("false");
    expect(screen.getByTestId("dispatch-live-tech-tB").getAttribute("data-dimmed")).toBe("true");
  });

  it("InfoWindow shows 'Last seen HH:MM ago' tooltip on click", async () => {
    const { default: Layer } = await import("@/pages/dispatch/LiveTechPinsLayer");
    render(<Layer positions={_POS} />);
    fireEvent.click(screen.getByTestId("dispatch-live-tech-tB"));
    const info = screen.getByTestId("dispatch-live-tech-info-tB");
    expect(info).toBeInTheDocument();
    const seen = screen.getByTestId("dispatch-live-tech-lastseen-tB");
    expect(seen.textContent).toMatch(/Last seen 20m ago/);
  });
});
