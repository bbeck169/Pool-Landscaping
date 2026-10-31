/**
 * β-core 3 · askAlwaysPermission — explainer precedes the OS background
 * dialog; gated on fleet role; skipped when already granted / already asked.
 */
import { Platform } from "react-native";

const order: string[] = [];
let fgStatus = "granted";
let bgStatus = "denied";
let bgRequestResult = "granted";
let explainerAnswer: boolean = true;
const mockGetFg = jest.fn(async () => ({ status: fgStatus }));
const mockReqFg = jest.fn(async () => { order.push("os-foreground"); return { status: fgStatus }; });
const mockGetBg = jest.fn(async () => ({ status: bgStatus }));
const mockReqBg = jest.fn(async () => { order.push("os-background"); return { status: bgRequestResult }; });
const mockShowConfirm = jest.fn((opts: any) => {
  order.push("explainer");
  if (explainerAnswer) opts.onConfirm(); else opts.onCancel();
});
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: () => mockGetFg(),
  requestForegroundPermissionsAsync: () => mockReqFg(),
  getBackgroundPermissionsAsync: () => mockGetBg(),
  requestBackgroundPermissionsAsync: () => mockReqBg(),
}));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => mockShowConfirm(o) }));

import {
  askAlwaysPermission, _resetAlwaysAskSession, ALWAYS_EXPLAINER_MESSAGE, ALWAYS_EXPLAINER_TITLE,
} from "@/src/lib/askAlwaysPermission";

const TECH = { id: "t1", role: "technician" };
const originalOS = Platform.OS;
beforeEach(() => {
  order.length = 0; fgStatus = "granted"; bgStatus = "denied"; bgRequestResult = "granted"; explainerAnswer = true;
  [mockGetFg, mockReqFg, mockGetBg, mockReqBg, mockShowConfirm].forEach((m) => m.mockClear());
  _resetAlwaysAskSession();
  (Platform as any).OS = "ios";
});
afterAll(() => { (Platform as any).OS = originalOS; });

describe("askAlwaysPermission", () => {
  it("explainer renders BEFORE the OS background dialog, with the spec copy", async () => {
    expect(await askAlwaysPermission(TECH)).toBe("granted");
    expect(order).toEqual(["explainer", "os-background"]);
    const opts = mockShowConfirm.mock.calls[0][0];
    expect(opts.title).toBe(ALWAYS_EXPLAINER_TITLE);
    expect(opts.message).toBe("Background location keeps your fleet pings running when the app isn't open. We only track during your shift.");
    expect(ALWAYS_EXPLAINER_MESSAGE).toBe(opts.message);
    expect([opts.cancelLabel, opts.confirmLabel]).toEqual(["Not now", "Continue"]);
  });

  it("foreground requested first when not yet granted (iOS two-step)", async () => {
    fgStatus = "undetermined";
    mockReqFg.mockImplementationOnce(async () => { order.push("os-foreground"); return { status: "granted" }; });
    await askAlwaysPermission(TECH);
    expect(order).toEqual(["os-foreground", "explainer", "os-background"]);
  });

  it("foreground denied → no explainer, no background dialog", async () => {
    fgStatus = "denied";
    expect(await askAlwaysPermission(TECH)).toBe("denied");
    expect(mockShowConfirm).not.toHaveBeenCalled();
    expect(mockReqBg).not.toHaveBeenCalled();
  });

  it("'Not now' on the explainer → no OS background dialog", async () => {
    explainerAnswer = false;
    expect(await askAlwaysPermission(TECH)).toBe("dismissed");
    expect(mockReqBg).not.toHaveBeenCalled();
  });

  it("skipped when background already granted", async () => {
    bgStatus = "granted";
    expect(await askAlwaysPermission(TECH)).toBe("granted");
    expect(mockShowConfirm).not.toHaveBeenCalled();
    expect(mockReqBg).not.toHaveBeenCalled();
  });

  it("gated on fleet role (admins / customers / no user never prompted)", async () => {
    for (const u of [{ id: "a", role: "admin" }, { id: "c", role: "customer" }, null]) {
      expect(await askAlwaysPermission(u as any)).toBe("skipped");
    }
    expect(mockGetBg).not.toHaveBeenCalled();
    expect(mockShowConfirm).not.toHaveBeenCalled();
  });

  it("asked once per app session per user (second clock-in is silent)", async () => {
    explainerAnswer = false;
    await askAlwaysPermission(TECH);
    mockShowConfirm.mockClear();
    expect(await askAlwaysPermission(TECH)).toBe("skipped");
    expect(mockShowConfirm).not.toHaveBeenCalled();
  });

  it("web → skipped", async () => {
    (Platform as any).OS = "web";
    expect(await askAlwaysPermission(TECH)).toBe("skipped");
  });
});

describe("clock-in wiring (source lock)", () => {
  const fs = require("fs");
  const path = require("path");
  const R = (p: string) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
  it("ClockInCard asks after a successful clock-in only", () => {
    expect(R("src/components/ClockInCard.tsx")).toMatch(/await api\.post\(`\/attendance\/\$\{kind\}`, coords\);\s*if \(kind === "clock-in"\) askAlwaysPermission\(user\)/);
  });
  it("landscape clock asks after a successful punch-in only", () => {
    expect(R("app/landscape-time-clock.tsx")).toMatch(/if \(type === "in"\) askAlwaysPermission\(user\)/);
  });
  it("time-clock awaits the ask BEFORE GpsTracker.startTracking", () => {
    const src = R("app/time-clock.tsx");
    const ask = src.indexOf("await askAlwaysPermission(user);");
    expect(ask).toBeGreaterThan(-1);
    // the clock-in start (an earlier resume-on-mount start exists near the top)
    expect(src.indexOf("GpsTracker.startTracking(token)", ask)).toBeGreaterThan(ask);
  });
});
