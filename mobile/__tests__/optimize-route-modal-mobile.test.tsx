/**
 * Phase B mobile parity — Optimize Route modal (web 2f14a7ea5 + e5d6fa01e).
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockPost = jest.fn();
jest.mock("@/src/api", () => ({ api: { post: (...a: any[]) => mockPost(...a) } }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
let mockDragEnd: ((e: { data: any[] }) => void) | null = null;
jest.mock("react-native-draggable-flatlist", () => {
  const RN = require("react-native");
  const List = (p: any) => {
    mockDragEnd = p.onDragEnd;
    return (
      <RN.View testID={p.testID}>
        {p.data.map((item: any, i: number) => (
          <RN.View key={p.keyExtractor(item)}>{p.renderItem({ item, drag: jest.fn(), isActive: false, getIndex: () => i })}</RN.View>
        ))}
      </RN.View>
    );
  };
  return { __esModule: true, default: List, ScaleDecorator: (p: any) => p.children };
});

import OptimizeRouteModal, { seedOrder, droppedBannerText } from "@/src/components/schedule/OptimizeRouteModal";
import { haversineMeters, totalHaversineMeters, classifyMiles, formatRouteHeader } from "@/src/utils/routeHaversine";

// ~0.1° lat ≈ 6.9 mi apart along a meridian.
const JOBS = [
  { id: "a", customer_name: "Alpha", location_lat: 33.0, location_lng: -112.0 },
  { id: "b", customer_name: "Bravo", location_lat: 33.1, location_lng: -112.0 },
  { id: "c", customer_name: "Charlie", location_lat: 33.3, location_lng: -112.0 },
];
const OPT = { ordered_job_ids: ["c", "a", "b"], total_distance_m: 3218.688, total_duration_s: 600, dropped_job_ids: [], warnings: [] };
const badges = (q: any) => ["a", "b", "c"].map((id) => [id, q.getByTestId(`optimize-route-badge-${id}`).props.children]);

beforeEach(() => { mockPost.mockReset(); mockDragEnd = null; });

describe("routeHaversine (port of web helpers)", () => {
  it("haversine + total skip coord-less stops; null-safe", () => {
    expect(haversineMeters(null, 1, 2, 3)).toBe(0);
    expect(haversineMeters(33, -112, 33.1, -112)).toBeCloseTo(11119.5, 0);
    expect(totalHaversineMeters([JOBS[0], { id: "x" }, JOBS[1]])).toBeCloseTo(11119.5, 0);
    expect(totalHaversineMeters([JOBS[0]])).toBe(0);
  });
  it("classifyMiles: <5 trivial · 5–20 short · >20 long", () => {
    expect([classifyMiles(4.99), classifyMiles(5), classifyMiles(20), classifyMiles(20.01)]).toEqual(["trivial", "short", "short", "long"]);
  });
  it("formatRouteHeader: server seconds override, else 35 km/h estimate", () => {
    expect(formatRouteHeader(3218.688, 600)).toBe("Estimated ~0h 10m · 2.0mi · trivial");
    expect(formatRouteHeader(35000)).toBe("Estimated ~1h 0m · 21.7mi · long");
  });
  it("seedOrder ranks by optimized ids; unknown ids sink", () => {
    expect(seedOrder([...JOBS, { id: "z" }], ["c", "a"]).map((j) => j.id)).toEqual(["c", "a", "b", "z"]);
  });
});

describe("OptimizeRouteModal", () => {
  const open = async (resp: any = OPT, tech: string | null = "t1") => {
    mockPost.mockImplementation((url: string) => (url === "/schedule/optimize-route" ? Promise.resolve(resp) : Promise.resolve({})));
    const q = render(<OptimizeRouteModal visible jobs={JOBS} date="2026-10-14" technicianId={tech} onClose={jest.fn()} />);
    await act(async () => {});
    return q;
  };

  it("1. fetch-on-open: POST optimize-route {date, technician_id}; renders optimized order", async () => {
    const q = await open();
    expect(mockPost).toHaveBeenCalledWith("/schedule/optimize-route", { date: "2026-10-14", technician_id: "t1" });
    expect(badges(q)).toEqual([["a", 2], ["b", 3], ["c", 1]]);
    expect(q.queryByTestId("optimize-route-loading")).toBeNull();
  });

  it("2. header uses server totals + classification while order matches server", async () => {
    const q = await open();
    expect(q.getByTestId("optimize-route-header").props.children).toBe("Estimated ~0h 10m · 2.0mi · trivial");
  });

  it("3. drag reorder → header recomputes from client haversine", async () => {
    const q = await open();
    await act(async () => { mockDragEnd!({ data: [JOBS[0], JOBS[1], JOBS[2]] }); });
    expect(badges(q)).toEqual([["a", 1], ["b", 2], ["c", 3]]);
    expect(q.getByTestId("optimize-route-header").props.children).toBe(formatRouteHeader(totalHaversineMeters(JOBS)));
    expect(q.getByTestId("optimize-route-header").props.children).toMatch(/· 20\.7mi · long$/);
  });

  it("3b. up/down buttons reorder + recompute", async () => {
    const q = await open();
    fireEvent.press(q.getByTestId("optimize-route-down-c")); // c,a,b → a,c,b
    expect(badges(q)).toEqual([["a", 1], ["b", 3], ["c", 2]]);
    expect(q.getByTestId("optimize-route-header").props.children).toBe(formatRouteHeader(totalHaversineMeters([JOBS[0], JOBS[2], JOBS[1]])));
  });

  it("4. Reverse Order flips the list + recomputes header; sits left of Save", async () => {
    const q = await open();
    fireEvent.press(q.getByTestId("optimize-route-reverse"));
    expect(badges(q)).toEqual([["a", 2], ["b", 1], ["c", 3]]); // b,a,c
    expect(q.getByTestId("optimize-route-header").props.children).toBe(formatRouteHeader(totalHaversineMeters([JOBS[1], JOBS[0], JOBS[2]])));
    const SRC = fs.readFileSync(path.resolve(__dirname, "../src/components/schedule/OptimizeRouteModal.tsx"), "utf-8");
    expect(SRC.indexOf('testID="optimize-route-reverse"')).toBeLessThan(SRC.indexOf('testID="optimize-route-save"'));
  });

  it("5. dropped-job yellow banner only when dropped_job_ids present", async () => {
    const q = await open({ ...OPT, dropped_job_ids: ["x1", "x2"] });
    expect(q.getByTestId("optimize-route-dropped-banner")).toBeTruthy();
    expect(q.getByText(droppedBannerText(2)!)).toBeTruthy();
    expect(droppedBannerText(1)).toMatch(/^1 job skipped/);
    const q2 = await open();
    expect(q2.queryByTestId("optimize-route-dropped-banner")).toBeNull();
  });

  it("6. Save → POST /jobs/reorder with the in-modal order (existing reorder API)", async () => {
    const q = await open();
    fireEvent.press(q.getByTestId("optimize-route-reverse"));
    await act(async () => { fireEvent.press(q.getByTestId("optimize-route-save")); });
    expect(mockPost).toHaveBeenLastCalledWith("/jobs/reorder", { ordered_job_ids: ["b", "a", "c"], date: "2026-10-14", tech_user_id: "t1" });
  });

  it("7. optimize failure → inline error, no list", async () => {
    mockPost.mockRejectedValueOnce(new Error("Directions down"));
    const q = render(<OptimizeRouteModal visible jobs={JOBS} date="2026-10-14" onClose={jest.fn()} />);
    await act(async () => {});
    expect(q.getByTestId("optimize-route-error").props.children).toBe("Directions down");
    expect(q.queryByTestId("optimize-route-list")).toBeNull();
  });
});

describe("calendar wiring", () => {
  const CAL = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf-8");
  it("Bulk Actions 'Optimize Route' is adminOnly; modal mounted only for isAdmin", () => {
    expect(CAL).toMatch(/key: "optimize-route", label: "Optimize Route"[^\n]*adminOnly: true/);
    expect(CAL).toContain("{isAdmin ? (\n        <OptimizeRouteModal");
    expect(CAL).toContain('technicianId={techFilter !== "all" ? techFilter : null}');
  });
});
