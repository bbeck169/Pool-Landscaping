/**
 * Fleet chip tap-target fix (Option A).
 * - (app) shell owns the top safe-area inset ONCE when the fleet chip row
 *   renders (wrapper `app-shell-top-inset` paddingTop = insets.top, chip row
 *   keeps its 4pt) and hands top:0 to SyncBanner + tab screens → no double gap.
 * - GlobalMenu / AI dock render outside the override → real insets.
 * - Chip Pressable hitSlop {12,12,16,16}; testID + modal unchanged.
 */
import React from "react";
import { StyleSheet } from "react-native";
import { render, fireEvent } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

const TOP = 37;
let mockRole = "admin";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole }, loading: false }) }));
jest.mock("expo-router", () => {
  const RN = require("react-native");
  const { useSafeAreaInsets: useInsets } = require("react-native-safe-area-context");
  function MockTabs({ children }: any) { return <RN.View testID="tabs">{children}</RN.View>; }
  function MockTabScreen() { return <RN.Text testID="tab-screen-inset-top">{String(useInsets().top)}</RN.Text>; }
  MockTabs.Screen = MockTabScreen;
  return { Tabs: MockTabs, Redirect: () => null };
});
jest.mock("@/src/components/SyncBanner", () => ({
  SyncBanner: () => {
    const { useSafeAreaInsets: use } = require("react-native-safe-area-context");
    const RN = require("react-native");
    return <RN.Text testID="syncbanner-inset-top">{String(use().top)}</RN.Text>;
  },
}));
jest.mock("@/src/components/tools/GlobalMenu", () => ({
  GlobalMenu: () => {
    const { useSafeAreaInsets: use } = require("react-native-safe-area-context");
    const RN = require("react-native");
    return <RN.Text testID="globalmenu-inset-top">{String(use().top)}</RN.Text>;
  },
}));
jest.mock("@/src/components/ai/AIDockDrawer", () => () => null);
jest.mock("@/src/events/aiDockEvents", () => ({ aiDockEvents: { onOpen: () => () => {} } }));
jest.mock("@/src/services/pushNotifications", () => ({ registerForPushNotifications: jest.fn(async () => {}) }));
jest.mock("@/src/hooks/useUnreadCount", () => ({ useUnreadCount: () => 0 }));
jest.mock("@/src/components/LandscapeTechClockInGate", () => ({ children }: any) => children);
jest.mock("@/src/services/fleet/locationEmitter", () => ({ getEmitterStatus: () => "stopped", onStatusChange: () => () => {} }));

import AppLayout from "@/app/(app)/_layout";
import FleetStatusChip from "@/src/components/fleet/FleetStatusChip";

const METRICS = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: TOP, bottom: 34, left: 0, right: 0 } };
const wrap = (ui: React.ReactElement) => render(<SafeAreaProvider initialMetrics={METRICS}>{ui}</SafeAreaProvider>);
const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const txt = (q: any, id: string) => q.getAllByTestId(id).map((e: any) => String(e.props.children));

beforeEach(() => { mockRole = "admin"; });

describe("(app) shell — chip row clears the status bar, inset applied once", () => {
  it.each(["admin", "super_admin", "technician"])("%s: chip sits at insets.top + 4; children get top:0", (role) => {
    mockRole = role;
    const q = wrap(<AppLayout />);
    const shellPad = flat(q.getByTestId("app-shell-top-inset")).paddingTop;
    const rowPad = flat(q.getByTestId("fleet-chip-row")).paddingTop;
    expect(shellPad).toBe(TOP);
    expect(rowPad).toBe(4);
    expect(shellPad + rowPad).toBeGreaterThanOrEqual(TOP); // chip clears the inset
    expect(q.getByTestId("fleet-status-chip")).toBeTruthy();
    // No double-apply: SyncBanner + every tab screen (Header etc.) see top 0
    expect(txt(q, "syncbanner-inset-top")).toEqual(["0"]);
    expect(new Set(txt(q, "tab-screen-inset-top"))).toEqual(new Set(["0"]));
    // GlobalMenu (outside the override, absolute + Modal) keeps the real inset
    expect(txt(q, "globalmenu-inset-top")).toEqual([String(TOP)]);
  });

  it.each(["manager", "owner"])("%s (no fleet row): layout byte-identical — no wrapper padding, real insets downstream", (role) => {
    mockRole = role;
    const q = wrap(<AppLayout />);
    expect(q.getByTestId("app-shell-top-inset").props.style).toBeNull();
    expect(q.queryByTestId("fleet-chip-row")).toBeNull();
    expect(txt(q, "syncbanner-inset-top")).toEqual([String(TOP)]);
    expect(new Set(txt(q, "tab-screen-inset-top"))).toEqual(new Set([String(TOP)]));
  });
});

describe("FleetStatusChip — tap target", () => {
  it("Pressable keeps testID fleet-status-chip with hitSlop top/bottom ≥ 12, left/right ≥ 16", () => {
    const q = wrap(<FleetStatusChip />);
    const chip = q.getByTestId("fleet-status-chip");
    expect(chip.props.hitSlop).toEqual({ top: 12, bottom: 12, left: 16, right: 16 });
    const { top, bottom, left, right } = chip.props.hitSlop;
    expect(Math.min(top, bottom)).toBeGreaterThanOrEqual(12);
    expect(Math.min(left, right)).toBeGreaterThanOrEqual(16);
  });

  it("pressing the chip still opens the fleet-status modal (regression guard)", () => {
    const q = wrap(<FleetStatusChip />);
    expect(q.queryByTestId("fleet-status-modal-label")).toBeNull();
    fireEvent.press(q.getByTestId("fleet-status-chip"));
    expect(q.getByTestId("fleet-status-modal-label")).toBeTruthy();
  });

  it("chip visual style unchanged (no padding/height added; label + dot render)", () => {
    const q = wrap(<FleetStatusChip />);
    const st = flat(q.getByTestId("fleet-status-chip"));
    expect(st.height).toBeUndefined();
    expect(st.minHeight).toBeUndefined();
    expect(q.getByText(/.+/)).toBeTruthy();
  });
});

describe("OptimizeRouteModal keeps a real top inset inside the top:0 shell", () => {
  it("uses max(context top, initialWindowMetrics top)", () => {
    const src = require("fs").readFileSync(require("path").resolve(__dirname, "../src/components/schedule/OptimizeRouteModal.tsx"), "utf8");
    expect(src).toContain("const modalTop = Math.max(insets.top, initialWindowMetrics?.insets.top ?? 0);");
    expect(src).toContain("paddingTop: modalTop + spacing.sm");
  });
});

