/**
 * Clock-in gate regression (Oct-2026, incident #2) — pool tech still gated on iOS.
 *
 * Root cause: mobile restored the user from storage and NEVER re-read
 * /auth/me, so a server-side `users.department` change (→ pool_tech) never
 * reached LandscapeTechClockInGate until re-login. Web auth.jsx self-heals on
 * boot. Fix: AuthProvider.refreshUser() on boot + app foreground + schedule
 * focus; gate helpers tolerate service_category / service_cat / service_cats.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { Text, AppState } from "react-native";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) },
  TOKEN_KEY: "tok",
  registerLogoutOn401: jest.fn(),
}));
const mockStore: Record<string, any> = {};
const mockSetItem = jest.fn(async (k: string, v: any) => { mockStore[k] = v; });
jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: async (k: string, d: any) => (k in mockStore ? mockStore[k] : d),
    setItem: (k: string, v: any) => mockSetItem(k, v),
    removeItem: async (k: string) => { delete mockStore[k]; },
    secureGet: async (k: string, d: any) => (("secure:" + k) in mockStore ? mockStore["secure:" + k] : d),
    secureSet: async (k: string, v: any) => { mockStore["secure:" + k] = v; },
    secureRemove: async (k: string) => { delete mockStore["secure:" + k]; },
  },
}));
jest.mock("@/src/lib/offline/jwtCache", () => ({ persistJwtExpiry: jest.fn(async () => {}), clearJwtExpiry: jest.fn(async () => {}) }));
jest.mock("@/src/lib/offline/cache", () => ({ wipeCache: jest.fn(async () => {}), initCache: jest.fn(async () => {}) }));
jest.mock("@/src/lib/offline/apiCache", () => ({ writeThroughMe: jest.fn(async () => {}) }));
jest.mock("@/lib/technicianResolver", () => ({ clearTechnicianIdCache: jest.fn() }));
jest.mock("@/src/services/readCache", () => ({ clearAllCache: jest.fn(async () => {}) }));
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: "denied" })),
  getCurrentPositionAsync: jest.fn(),
  Accuracy: { Balanced: 3 },
}));

import { AuthProvider } from "@/src/auth";
import LandscapeTechClockInGate from "@/src/components/LandscapeTechClockInGate";
import { isPoolTech, isLandscapeTech } from "@/src/utils/clockInGate";

const ETHAN = { id: "u-ethan", email: "e@x", name: "Ethan Smith", role: "technician" };
const read = (p: string) => fs.readFileSync(path.resolve(__dirname, "..", p), "utf8");

let appStateCb: ((s: string) => void) | null = null;
beforeEach(() => {
  for (const k of Object.keys(mockStore)) delete mockStore[k];
  mockGet.mockReset();
  mockPost.mockReset().mockResolvedValue({});
  mockSetItem.mockClear();
  jest.spyOn(AppState, "addEventListener").mockImplementation((_e: any, cb: any) => {
    appStateCb = cb;
    return { remove: jest.fn() } as any;
  });
});

const boot = (cached: any) => {
  mockStore["pool_crm_user"] = JSON.stringify(cached);
  mockStore["secure:tok"] = "jwt";
  return render(
    <AuthProvider>
      <LandscapeTechClockInGate><Text testID="schedule-content">schedule</Text></LandscapeTechClockInGate>
    </AuthProvider>,
  );
};
const routes = (me: any, clockedIn = false) => mockGet.mockImplementation(async (url: string) => {
  if (url === "/auth/me") { if (me instanceof Error) throw me; return me; }
  if (url === "/timeclock/mine-status") return { clocked_in: clockedIn };
  throw new Error(url);
});

describe("isPoolTech / isLandscapeTech matrix", () => {
  const t = (extra: any) => ({ role: "technician", ...extra });
  it.each([
    ["department pool_tech", { department: "pool_tech" }],
    ["service_category pool", { service_category: "pool" }],
    ["service_cat Pool Service", { service_cat: "Pool Service" }],
    ["service_cats [pool]", { service_cats: ["pool"] }],
    ["case/separator: ' Pool-Technician '", { department: " Pool-Technician " }],
    ["service_category wins over stale department", { service_category: "pool", department: "landscaping" }],
  ])("pool → bypass: %s", (_n, extra) => {
    expect(isPoolTech(t(extra))).toBe(true);
    expect(isLandscapeTech(t(extra))).toBe(false);
  });

  it.each([
    ["department landscaping", { department: "landscaping" }],
    ["service_category landscape", { service_category: "landscape" }],
    ["service_cat Landscaper", { service_cat: "Landscaper" }],
    ["service_cats [pool, landscaping] (cross-trained)", { service_cats: ["pool", "landscaping"] }],
    ["both", { department: "both" }],
    ["cross-trained", { department: "Cross-Trained" }],
  ])("landscape → gated: %s", (_n, extra) => {
    expect(isLandscapeTech(t(extra))).toBe(true);
    expect(isPoolTech(t(extra))).toBe(false);
  });

  it("missing / unknown discriminator and non-technicians are neither (unchanged default)", () => {
    for (const u of [t({}), t({ department: null }), t({ department: "north" }), t({ service_cats: [] }), null, undefined]) {
      expect(isPoolTech(u as any)).toBe(false);
      expect(isLandscapeTech(u as any)).toBe(false);
    }
    expect(isLandscapeTech({ role: "admin", department: "landscaping" })).toBe(false);
    expect(isLandscapeTech({ role: "manager", department: "landscaping" })).toBe(false);
  });
});

describe("stale cached user self-heals via /auth/me (Ethan scenario)", () => {
  it("cached landscaping → /auth/me pool_tech: gate lifts, fresh user persisted", async () => {
    routes({ ...ETHAN, department: "pool_tech" });
    const q = boot({ ...ETHAN, department: "landscaping" });
    await waitFor(() => q.getByTestId("schedule-content"));
    expect(q.queryByTestId("landscape-clock-gate")).toBeNull();
    expect(mockGet).toHaveBeenCalledWith("/auth/me");
    expect(JSON.parse(mockStore["pool_crm_user"]).department).toBe("pool_tech");
  });

  it("cached pool_tech (correct) → never probes clock status, schedule renders", async () => {
    routes({ ...ETHAN, department: "pool_tech" });
    const q = boot({ ...ETHAN, department: "pool_tech" });
    await waitFor(() => q.getByTestId("schedule-content"));
    await act(async () => {});
    expect(mockGet).not.toHaveBeenCalledWith("/timeclock/mine-status");
  });

  it("landscape tech stays gated when /auth/me confirms landscaping", async () => {
    routes({ ...ETHAN, department: "landscaping" });
    const q = boot({ ...ETHAN, department: "landscaping" });
    await waitFor(() => q.getByText("Clock In to Start"));
    await act(async () => {});
    expect(q.queryByTestId("schedule-content")).toBeNull();
  });

  it("offline /auth/me keeps the cached user (no logout, no crash)", async () => {
    routes(new Error("Network request failed"));
    const q = boot({ ...ETHAN, department: "pool_tech" });
    await waitFor(() => q.getByTestId("schedule-content"));
    expect(JSON.parse(mockStore["pool_crm_user"]).department).toBe("pool_tech");
  });

  it("/auth/me for a different user id is ignored", async () => {
    routes({ ...ETHAN, id: "someone-else", department: "pool_tech" });
    const q = boot({ ...ETHAN, department: "landscaping" });
    await waitFor(() => q.getByText("Clock In to Start"));
    await act(async () => {});
    expect(mockSetItem).not.toHaveBeenCalled();
  });

  it("app foreground (AppState → active) re-reads /auth/me and lifts the gate", async () => {
    let me: any = { ...ETHAN, department: "landscaping" };
    mockGet.mockImplementation(async (url: string) => (url === "/auth/me" ? me : { clocked_in: false }));
    const q = boot({ ...ETHAN, department: "landscaping" });
    await waitFor(() => q.getByText("Clock In to Start"));
    me = { ...ETHAN, department: "pool_tech" }; // admin fixes dept while app is backgrounded
    await act(async () => { appStateCb?.("active"); });
    await waitFor(() => q.getByTestId("schedule-content"));
    expect(mockGet.mock.calls.filter((c) => c[0] === "/auth/me").length).toBeGreaterThanOrEqual(2);
  });
});

describe("navigation re-check + source field", () => {
  it("schedule calendar re-reads /auth/me inside its useFocusEffect", () => {
    const src = read("app/(app)/schedule/calendar.tsx");
    const block = src.slice(src.indexOf('logNav("schedule/calendar.focus"') - 60, src.indexOf('logNav("schedule/calendar.focus"') + 400);
    expect(block).toMatch(/useFocusEffect\(useCallback\(\(\) => \{/);
    expect(block).toContain("refreshUser?.();");
    expect(src).toContain("const { user, refreshUser } = useAuth();");
  });

  it("gate Clock In POSTs /timeclock/punch with source 'mobile'", async () => {
    routes({ ...ETHAN, department: "landscaping" });
    const q = boot({ ...ETHAN, department: "landscaping" });
    await waitFor(() => q.getByText("Clock In to Start"));
    await act(async () => { fireEvent.press(q.getByText("Clock In")); });
    expect(mockPost).toHaveBeenCalledWith("/timeclock/punch", expect.objectContaining({ punch_type: "in", source: "mobile" }));
  });

  it("every /timeclock/punch call site sends source 'mobile' (workforce endpoints take no source)", () => {
    const widget = read("src/components/LandscapingClockWidget.tsx");
    expect(widget).toMatch(/source: "mobile"/);
    expect(widget).not.toMatch(/source: "mobile_gate"/);
    expect(read("src/components/LandscapeTechClockInGate.tsx")).not.toMatch(/mobile_gate/);
  });
});
