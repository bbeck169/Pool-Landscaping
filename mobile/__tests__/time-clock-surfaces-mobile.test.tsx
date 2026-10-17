/**
 * TD-64 Phase 2b · per-render-site regression — every mobile Time Clock
 * surface for the 3 personas. Pool tech → not rendered (short-circuit, not
 * hidden); landscape tech → as before; admin → role rules (unchanged).
 */
import React from "react";
import { Text } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

let mockUser: any = null;
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUser, logout: jest.fn() }) }));
jest.mock("expo-router", () => {
  const RN = require("react-native");
  return {
    Redirect: ({ href }: any) => <RN.Text testID="redirect">{href}</RN.Text>,
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    useFocusEffect: () => {},
  };
});
const mockGet = jest.fn(async (url: string) => {
  if (url === "/timeclock/mine-status") return { clocked_in: false };
  if (url.startsWith("/timeclock/me/today")) return { open_punch: null, worked_minutes: 0 };
  if (url.startsWith("/timeclock/me/week")) return { days: [], total_minutes: 0 };
  if (url.startsWith("/timeclock")) return { punches: [], days: [] };
  return [];
});
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), post: jest.fn(async () => ({})) }, getAuthToken: async () => "t" }));
jest.mock("@/src/services/offlineWrite", () => ({ offlineWrite: jest.fn(async () => ({ queued: false })) }));
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: "denied" })),
  getCurrentPositionAsync: jest.fn(), Accuracy: { Balanced: 3, High: 4 },
}));

jest.mock("@react-native-async-storage/async-storage", () => require("@react-native-async-storage/async-storage/jest/async-storage-mock"));
jest.mock("@react-native-community/netinfo", () => ({ addEventListener: () => () => {}, fetch: async () => ({ isConnected: true }) }));
jest.mock("@/src/services/gpsTracker", () => ({ start: jest.fn(), stop: jest.fn(), isRunning: () => false }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/components/nav/BreadcrumbBar", () => () => null);

import TimeClockRoute from "@/app/time-clock";
import LandscapeTechClockInGate from "@/src/components/LandscapeTechClockInGate";
import LandscapingClockWidget from "@/src/components/LandscapingClockWidget";
import LandscapingTimeClockRoute from "@/app/landscape-time-clock";
import { sectionsForRole, ADMIN_SECTIONS, TECH_SECTIONS, TIME_CLOCK_TILE_KEYS } from "@/src/components/tools/sections";

const POOL = { id: "p", role: "technician", department: "pool_tech", effective_department: "pool_tech", show_time_clock: false };
const LAND = { id: "l", role: "technician", department: "landscaping", effective_department: "landscaping", show_time_clock: true };
const ADMIN = { id: "a", role: "admin", department: null, effective_department: null, show_time_clock: false };
// Pre-denorm cohort: users.department null, BE resolved from technicians → true.
const LAND_DENORM = { id: "d", role: "technician", department: null, effective_department: "landscaping", show_time_clock: true };

const tileKeys = (secs: any[]) => secs.flatMap((s) => s.tiles.map((t: any) => t.key));

beforeEach(() => { mockGet.mockClear(); });

describe("#1 LandscapeTechClockInGate (shell-wide gate)", () => {
  const child = <Text testID="shell-children">app</Text>;
  it("pool tech → no gate, no clock probe", async () => {
    mockUser = POOL;
    const q = render(<LandscapeTechClockInGate>{child}</LandscapeTechClockInGate>);
    expect(q.getByTestId("shell-children")).toBeTruthy();
    expect(q.queryByTestId("landscape-clock-gate")).toBeNull();
    expect(mockGet).not.toHaveBeenCalledWith("/timeclock/mine-status");
  });
  it.each([["landscape", LAND], ["landscape (technicians.department fallback via /me)", LAND_DENORM]])("%s tech → gate shown", async (_n, u) => {
    mockUser = u;
    const q = render(<LandscapeTechClockInGate>{child}</LandscapeTechClockInGate>);
    await waitFor(() => q.getByTestId("landscape-clock-gate"));
    expect(q.queryByTestId("shell-children")).toBeNull();
  });
  it("admin → never gated", () => {
    mockUser = ADMIN;
    const q = render(<LandscapeTechClockInGate>{child}</LandscapeTechClockInGate>);
    expect(q.getByTestId("shell-children")).toBeTruthy();
  });
});

describe("#2 LandscapingClockWidget (dashboard + schedule)", () => {
  it("pool tech → not rendered (null), no fetch", async () => {
    mockUser = POOL;
    const q = render(<LandscapingClockWidget />);
    await act(async () => {});
    expect(q.queryByTestId("landscape-clock-widget")).toBeNull();
    expect(q.toJSON()).toBeNull();
  });
  it.each([["landscape", LAND], ["landscape_tech (newly covered)", { ...LAND, department: "landscape_tech", show_time_clock: undefined, effective_department: undefined }]])("%s → renders", async (_n, u) => {
    mockUser = u;
    const q = render(<LandscapingClockWidget />);
    await waitFor(() => q.getByTestId("landscape-clock-widget"));
  });
  it("admin → hidden (unchanged role rule)", async () => {
    mockUser = ADMIN;
    const q = render(<LandscapingClockWidget />);
    await act(async () => {});
    expect(q.toJSON()).toBeNull();
  });
});

describe("#3 /landscape-time-clock route (+ (app) re-export)", () => {
  it("pool tech deep link → Redirect to schedule, screen not rendered", () => {
    mockUser = POOL;
    const q = render(<LandscapingTimeClockRoute />);
    expect(q.getByTestId("redirect").props.children).toBe("/(app)/schedule/calendar");
    expect(q.queryByTestId("landscape-time-clock-screen")).toBeNull();
  });
  it.each([["landscape tech", LAND], ["admin", ADMIN]])("%s → screen renders, no redirect", async (_n, u) => {
    mockUser = u;
    const q = render(<LandscapingTimeClockRoute />);
    await waitFor(() => q.getByTestId("landscape-time-clock-screen"));
    expect(q.queryByTestId("redirect")).toBeNull();
  });
  it("(app)/landscape-time-clock re-exports the guarded route", () => {
    expect(require("@/app/(app)/landscape-time-clock").default).toBe(LandscapingTimeClockRoute);
  });
});

describe("#4 /time-clock route (+ (app) re-export) — guard wiring", () => {
  const fs = require("fs");
  const path = require("path");
  const SRC = fs.readFileSync(path.resolve(__dirname, "../app/time-clock.tsx"), "utf8");
  const APP = fs.readFileSync(path.resolve(__dirname, "../app/(app)/time-clock.tsx"), "utf8");
  it("pool tech deep link → Redirect to schedule (rendered), screen not mounted", () => {
    mockUser = POOL;
    const q = render(<TimeClockRoute />);
    expect(q.getByTestId("redirect").props.children).toBe("/(app)/schedule/calendar");
    expect(q.queryByTestId("time-clock-screen")).toBeNull();
    expect(require("@/app/(app)/time-clock").default).toBe(TimeClockRoute);
  });
  it("default export is the guard wrapper; screen hooks live in the inner component", () => {
    expect(SRC).toMatch(/export default function TimeClockRoute\(\) \{\n  const \{ user \} = useAuth\(\);\n  if \(isPoolTechWithoutTimeClock\(user as any\)\) return <Redirect href="\/\(app\)\/schedule\/calendar" \/>;\n  return <TimeClockScreen \/>;\n\}/);
    expect(SRC).toContain("\nfunction TimeClockScreen() {");
    expect(APP.trim()).toBe('export { default } from "../time-clock";');
  });
});

describe("#5 Tools hub tiles (Tools tab + global menu sheet)", () => {
  it("pool tech → no Time Clock tiles; other tech tiles intact", () => {
    const keys = tileKeys(sectionsForRole("technician", POOL));
    for (const k of TIME_CLOCK_TILE_KEYS) expect(keys).not.toContain(k);
    expect(keys).toEqual(tileKeys(TECH_SECTIONS).filter((k) => !TIME_CLOCK_TILE_KEYS.has(k)));
  });
  it("landscape tech → identical to TECH_SECTIONS (both clock tiles)", () => {
    expect(sectionsForRole("technician", LAND)).toBe(TECH_SECTIONS);
    expect(tileKeys(TECH_SECTIONS)).toEqual(expect.arrayContaining(["time-clock", "landscape-time-clock"]));
  });
  it("admin / super_admin → ADMIN_SECTIONS unchanged regardless of designation", () => {
    expect(sectionsForRole("admin", ADMIN)).toBe(ADMIN_SECTIONS);
    expect(sectionsForRole("super_admin", POOL)).toBe(ADMIN_SECTIONS);
  });
  it("both callers pass the user", () => {
    const fs = require("fs");
    const path = require("path");
    expect(fs.readFileSync(path.resolve(__dirname, "../app/(app)/tools.tsx"), "utf8")).toContain("sectionsForRole(role, user as any)");
    expect(fs.readFileSync(path.resolve(__dirname, "../src/components/tools/ToolsMenuBody.tsx"), "utf8")).toContain("sectionsForRole(role, user as any), [role, user]");
  });
});
