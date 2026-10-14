/**
 * Phase B.5 mobile parity (web 9eb08b5c1) — per-tech numbered pins,
 * per-tech color coding, legend. Live Tech (a388d76eb) + Multi-Property
 * (1ec8153a0) must coexist.
 */
import React from "react";
import { render, act, fireEvent } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: jest.fn() } }));
let mockRole = "technician";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { expoConfig: { android: { config: { googleMaps: { apiKey: "K" } } } } } }));
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  Accuracy: { Balanced: 3 },
}));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("react-native-maps", () => {
  const RN = require("react-native");
  const R = require("react");
  return {
    __esModule: true,
    default: R.forwardRef((p: any, ref: any) => <RN.View ref={ref} testID={p.testID || "map-view"}>{p.children}</RN.View>),
    Marker: (p: any) => <RN.Pressable testID={p.testID} onPress={p.onPress}>{p.children}</RN.Pressable>,
  };
});
const mockPins: Record<string, any> = {};
jest.mock("@/src/components/maps/TeardropPin", () => {
  const actual = jest.requireActual("@/src/components/maps/TeardropPin");
  const RN = require("react-native");
  return {
    ...actual,
    __esModule: true,
    default: (p: any) => { mockPins[p.testID] = p; return <RN.View testID={p.testID} />; },
  };
});

import ScheduleMap from "@/src/components/schedule/ScheduleMap.native";
import { buildPerTechSequence, perTechStopCounts } from "@/src/utils/perTechSequence";
import { buildTechColorMap, crewHuedColor, crewHuedColorFromTech, UNASSIGNED_PIN_COLOR } from "@/src/utils/crewPalette";
import { deriveDarker } from "@/src/components/maps/TeardropPin";

const c = (lat: number) => ({ location_lat: lat, location_lng: -112 });
const JOBS = [
  { id: "m3", technician_id: "mike", scheduled_at: "2026-10-14T11:00", ...c(33.3) },
  { id: "m1", technician_id: "mike", route_index: 0, ...c(33.1) },
  { id: "m2", technician_id: "mike", scheduled_at: "2026-10-14T09:00", ...c(33.2) },
  { id: "l1", technician_id: "luis", scheduled_at: "2026-10-14T08:00", ...c(33.4) },
  { id: "l2", technician_id: "luis", scheduled_at: "2026-10-14T10:00", coord_source: "customer", property_id: "p9", ...c(33.5) },
  { id: "u1", status: "scheduled", ...c(33.6) },
] as any[];
const TECHS = [{ id: "mike", name: "Mike", display_color_hex: "#0EA5E9" }, { id: "luis", name: "Luis" }];
const CREWS = [{ id: "crew-a", tech_ids: ["luis"] }];
const pin = (id: string) => mockPins[`schedule-map-teardrop-${id}`];

beforeEach(() => {
  for (const k of Object.keys(mockPins)) delete mockPins[k];
  mockGet.mockReset().mockResolvedValue({ pings: [] });
  mockRole = "technician";
});

describe("buildPerTechSequence", () => {
  it("1. per-tech independent numbering — each tech restarts at 1", () => {
    const seq = buildPerTechSequence(JOBS);
    expect([seq.get("m1"), seq.get("m2"), seq.get("m3")]).toEqual([1, 2, 3]);
    expect([seq.get("l1"), seq.get("l2")]).toEqual([1, 2]);
    expect(seq.get("u1")).toBe(1); // unassigned bucket
  });

  it("2. hybrid source: route_index → scheduled_at → id tiebreak", () => {
    const seq = buildPerTechSequence([
      { id: "b", technician_id: "t" }, { id: "a", technician_id: "t" },
      { id: "s", technician_id: "t", scheduled_at: "2026-10-14T07:00" },
      { id: "r", technician_id: "t", route_index: 5 },
    ]);
    // route_index first; then the scheduled-vs-unscheduled pair falls to id tiebreak
    expect(seq.get("r")).toBe(1);
    expect(["a", "b", "s"].map((k) => seq.get(k))).toEqual([2, 3, 4]);
  });

  it("3. count-but-hide: coord-less stops still consume a number", () => {
    const jobs = [
      { id: "x1", technician_id: "t", route_index: 0, ...c(33) },
      { id: "x2", technician_id: "t", route_index: 1 }, // no coords
      { id: "x3", technician_id: "t", route_index: 2, ...c(33.2) },
    ];
    render(<ScheduleMap jobs={jobs as any} techs={[{ id: "t", name: "T" }]} />);
    expect(pin("x1").label).toBe(1);
    expect(pin("x2")).toBeUndefined();
    expect(pin("x3").label).toBe(3);
  });
});

describe("tech colors", () => {
  it("4. deterministic: same tech_id → same color; display_color_hex wins; crew hue differs from solo", () => {
    expect(crewHuedColor({ techId: "luis" })).toBe(crewHuedColor({ techId: "luis" }));
    expect(crewHuedColor({ techId: "luis" })).toMatch(/^#[0-9A-F]{6}$/);
    expect(crewHuedColorFromTech({ id: "mike", display_color_hex: "#0EA5E9" })).toBe("#0EA5E9");
    expect(crewHuedColor({ techId: "luis", crewId: "crew-a" })).not.toBe(crewHuedColor({ techId: "luis" }));
    expect(crewHuedColor({})).toBe(UNASSIGNED_PIN_COLOR);
    const m1 = buildTechColorMap(TECHS, CREWS);
    const m2 = buildTechColorMap([...TECHS].reverse(), CREWS);
    expect(m1.get("luis")).toBe(m2.get("luis"));
    expect(m1.get("luis")).toBe(crewHuedColor({ techId: "luis", crewId: "crew-a" }));
  });

  it("5. pins fill by tech color + numbered label; unassigned → slate; no techs prop → status colors (unchanged)", () => {
    const map = buildTechColorMap(TECHS, CREWS);
    render(<ScheduleMap jobs={JOBS} techs={TECHS} crews={CREWS} />);
    expect(pin("m2")).toMatchObject({ color: "#0EA5E9", label: 2 });
    expect(pin("l1")).toMatchObject({ color: map.get("luis"), label: 1 });
    expect(pin("u1").color).toBe(UNASSIGNED_PIN_COLOR);
    for (const k of Object.keys(mockPins)) delete mockPins[k];
    render(<ScheduleMap jobs={JOBS} />);
    expect(pin("u1").color).not.toBe(UNASSIGNED_PIN_COLOR);
    expect(pin("m1").label).toBe(1);
  });
});

describe("legend", () => {
  it("6. one row per tech with stop counts, sorted desc; hidden without techs / while a card is open", () => {
    const q = render(<ScheduleMap jobs={JOBS} techs={TECHS} crews={CREWS} />);
    expect(q.getByTestId("schedule-map-tech-legend-count-mike").props.children).toEqual([3, " stop", "s"]);
    expect(q.getByTestId("schedule-map-tech-legend-count-luis").props.children).toEqual([2, " stop", "s"]);
    expect(q.getByTestId("schedule-map-tech-legend-swatch-mike").props.style).toEqual(expect.arrayContaining([expect.objectContaining({ backgroundColor: "#0EA5E9" })]));
    expect(perTechStopCounts(JOBS).has("u1")).toBe(false);
    fireEvent.press(q.getByTestId("schedule-map-pin-m1"));
    expect(q.queryByTestId("schedule-map-tech-legend")).toBeNull();
    const q2 = render(<ScheduleMap jobs={JOBS} />);
    expect(q2.queryByTestId("schedule-map-tech-legend")).toBeNull();
  });

  it("7. filter change (jobs prop narrows) recomputes legend + numbering", () => {
    const q = render(<ScheduleMap jobs={JOBS} techs={TECHS} crews={CREWS} />);
    q.rerender(<ScheduleMap jobs={JOBS.filter((j) => j.technician_id === "luis" && j.id === "l2")} techs={TECHS} crews={CREWS} />);
    expect(q.queryByTestId("schedule-map-tech-legend-mike")).toBeNull();
    expect(q.getByTestId("schedule-map-tech-legend-count-luis").props.children).toEqual([1, " stop", ""]);
    expect(pin("l2").label).toBe(1);
  });
});

describe("coexistence", () => {
  it("8. Live Tech pins + Multi-Property approximate ring render alongside numbered tech pins", async () => {
    mockRole = "admin";
    mockGet.mockResolvedValue({ pings: [{ user_id: "mike", user_name: "Mike", lat: 33.15, lon: -112, captured_at: "x", age_seconds: 30, staleness: "live" }] });
    const q = render(<ScheduleMap jobs={JOBS} techs={TECHS} crews={CREWS} />);
    await act(async () => {});
    expect(q.getByTestId("schedule-map-live-tech-pin-mike")).toBeTruthy();
    expect(q.getByTestId("schedule-map-pin-m1")).toBeTruthy();
    const wrap = q.getByTestId("schedule-map-pin-wrap-l2").props.style;
    const luis = buildTechColorMap(TECHS, CREWS).get("luis")!;
    expect(wrap).toMatchObject({ borderStyle: "dashed", opacity: 0.7, borderColor: deriveDarker(luis) });
    expect(pin("l2").label).toBe(2);
  });
});
