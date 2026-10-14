/**
 * Phase B · Feb-2026 — ReorderRouteModal: header classification +
 * dropped-job banner + "Reverse Order" button vitests.
 *
 * Covers (7 cases):
 *   1. Header renders server totals when `optimizeTotalMeters`/
 *      `optimizeTotalSeconds` are provided + the operator hasn't
 *      re-dragged — classification label picks `trivial` for <5 mi.
 *   2. Header classification label picks `short` for 5-20 mi.
 *   3. Header classification label picks `long` for >20 mi.
 *   4. Dropped-job yellow banner renders when `droppedJobIds` carries
 *      ≥ 1 id; copy mentions "Property Geocoding Health".
 *   5. Dropped-job banner is NOT rendered when `droppedJobIds` is empty.
 *   6. "Reverse Order" button reverses the current list order
 *      (verify first + last swap).
 *   7. "Reverse Order" triggers header recompute (switches from
 *      server-totals path to client-haversine path — mi value changes
 *      consistent with the reversed order).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const _h = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/api", () => ({ api: { post: _h.post } }));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  ReorderRouteModal,
  haversineMeters,
  totalHaversineMeters,
  classifyMiles,
} from "@/pages/schedule/ReorderRouteModal";

// Three jobs with real-ish Phoenix-area coords.
const JOBS = [
  { id: "j1", customer_name: "Alice",
    location_lat: 33.60, location_lng: -112.10, route_index: 0 },
  { id: "j2", customer_name: "Bob",
    location_lat: 33.63, location_lng: -112.11, route_index: 1 },
  { id: "j3", customer_name: "Carla",
    location_lat: 33.65, location_lng: -112.15, route_index: 2 },
];

beforeEach(() => {
  _h.post.mockReset();
  _h.post.mockResolvedValue({ ok: true, updated: 3, expected: 3 });
});


describe("ReorderRouteModal · Phase B", () => {
  // ──────────────────────────────────────────────────────────────
  // classifyMiles unit — guards against accidental threshold drift
  // ──────────────────────────────────────────────────────────────
  it("classifyMiles · < 5 mi → trivial", () => {
    expect(classifyMiles(0)).toBe("trivial");
    expect(classifyMiles(4.9)).toBe("trivial");
  });
  it("classifyMiles · 5-20 mi → short", () => {
    expect(classifyMiles(5)).toBe("short");
    expect(classifyMiles(20)).toBe("short");
  });
  it("classifyMiles · > 20 mi → long", () => {
    expect(classifyMiles(20.1)).toBe("long");
    expect(classifyMiles(100)).toBe("long");
  });

  // ──────────────────────────────────────────────────────────────
  // 1. Header renders server totals + trivial classification
  // ──────────────────────────────────────────────────────────────
  it("renders header with server totals + trivial label for <5 mi", () => {
    const miles = 3;
    const meters = Math.round(miles * 1609.344);
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={meters}
        optimizeTotalSeconds={300}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    const summary = screen.getByTestId("id-optimize-route-summary");
    expect(summary.textContent).toMatch(/3\.0mi/);
    expect(summary.textContent).toMatch(/trivial/);
  });

  // ──────────────────────────────────────────────────────────────
  // 2. Header classification picks short for 5-20 mi
  // ──────────────────────────────────────────────────────────────
  it("renders short label for 5-20 mi", () => {
    const meters = Math.round(12 * 1609.344);
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={meters}
        optimizeTotalSeconds={1200}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    const summary = screen.getByTestId("id-optimize-route-summary");
    expect(summary.textContent).toMatch(/12\.0mi/);
    expect(summary.textContent).toMatch(/short/);
  });

  // ──────────────────────────────────────────────────────────────
  // 3. Header classification picks long for > 20 mi
  // ──────────────────────────────────────────────────────────────
  it("renders long label for > 20 mi", () => {
    const meters = Math.round(35 * 1609.344);
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={meters}
        optimizeTotalSeconds={3600}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    const summary = screen.getByTestId("id-optimize-route-summary");
    expect(summary.textContent).toMatch(/35\.0mi/);
    expect(summary.textContent).toMatch(/long/);
  });

  // ──────────────────────────────────────────────────────────────
  // 4. Dropped-job yellow banner renders with ≥ 1 id
  // ──────────────────────────────────────────────────────────────
  it("renders dropped-job banner when droppedJobIds is non-empty", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={1609}
        optimizeTotalSeconds={120}
        droppedJobIds={["jx", "jy"]}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    const b = screen.getByTestId("reorder-route-dropped-banner");
    expect(b.textContent).toMatch(/2 jobs skipped/);
    expect(b.textContent).toMatch(/Property Geocoding Health/);
  });

  // ──────────────────────────────────────────────────────────────
  // 5. Dropped-job banner NOT rendered when empty
  // ──────────────────────────────────────────────────────────────
  it("does not render dropped-job banner when droppedJobIds is empty", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={1609}
        optimizeTotalSeconds={120}
        droppedJobIds={[]}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("reorder-route-dropped-banner")).toBeNull();
  });

  // ──────────────────────────────────────────────────────────────
  // 6. "Reverse Order" button swaps first + last
  // ──────────────────────────────────────────────────────────────
  it("clicking Reverse Order reverses the list order", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    // Pre-reverse: j1 is at position 1, j3 is at position 3.
    expect(screen.getByTestId("reorder-route-badge-j1").textContent).toBe("1");
    expect(screen.getByTestId("reorder-route-badge-j3").textContent).toBe("3");
    fireEvent.click(screen.getByTestId("reorder-route-reverse"));
    // Post-reverse: j1 ↔ j3 swap, middle (j2) stays at position 2.
    expect(screen.getByTestId("reorder-route-badge-j1").textContent).toBe("3");
    expect(screen.getByTestId("reorder-route-badge-j2").textContent).toBe("2");
    expect(screen.getByTestId("reorder-route-badge-j3").textContent).toBe("1");
  });

  // ──────────────────────────────────────────────────────────────
  // 7. Reverse triggers header recompute (switches to client-haversine)
  // ──────────────────────────────────────────────────────────────
  it("Reverse Order triggers client-side header recompute path", () => {
    // Seed the modal with implausibly-large server totals so we can
    // distinguish the server-totals path (100 mi) from the client-
    // haversine path (actual Phoenix-adjacent distance < 10 mi).
    const serverMeters = Math.round(100 * 1609.344);
    render(
      <ReorderRouteModal
        jobs={JOBS}
        initialOrder={["j1", "j2", "j3"]}
        optimizeTotalMeters={serverMeters}
        optimizeTotalSeconds={7200}
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    // Initial header uses server totals: "100.0mi · long".
    expect(screen.getByTestId("id-optimize-route-summary").textContent)
      .toMatch(/100\.0mi/);
    fireEvent.click(screen.getByTestId("reorder-route-reverse"));
    // Post-reverse header is client-haversine-computed → the mi
    // value is the real distance of the reversed sequence, which
    // is a small Phoenix-area number (sub-10 mi for these fixtures).
    const after = screen.getByTestId("id-optimize-route-summary").textContent;
    expect(after).not.toMatch(/100\.0mi/);
    // Classification should be "trivial" (sub-5mi) for these coords.
    const matched = after.match(/(\d+\.\d+)mi/);
    expect(matched).toBeTruthy();
    expect(Number(matched[1])).toBeLessThan(10);
  });

  // ──────────────────────────────────────────────────────────────
  // haversine helpers — direct unit guards
  // ──────────────────────────────────────────────────────────────
  it("haversineMeters returns a positive finite number for valid coords", () => {
    const m = haversineMeters(33.60, -112.10, 33.65, -112.15);
    expect(Number.isFinite(m)).toBe(true);
    expect(m).toBeGreaterThan(0);
  });
  it("totalHaversineMeters returns 0 for < 2 jobs", () => {
    expect(totalHaversineMeters([])).toBe(0);
    expect(totalHaversineMeters([{ id: "x",
      location_lat: 1, location_lng: 2 }])).toBe(0);
  });
});
