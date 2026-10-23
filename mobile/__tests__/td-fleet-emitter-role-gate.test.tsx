/**
 * TD-fleet-emitter-role-gate · fleet tracking eligible for all 6 BE ASSIGNABLE_ROLES.
 * Emitter start (hook), status chip and pause-toggle section share one role list
 * so a tracked user always sees the indicator + can pause (D2).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { AppState } from "react-native";
import { render, renderHook, act, waitFor } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockReqPerm = jest.fn();
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: () => mockReqPerm(),
  getForegroundPermissionsAsync: async () => ({ status: "granted" }),
  Accuracy: { Balanced: 3 },
  getCurrentPositionAsync: async () => ({ coords: { latitude: 1, longitude: 2, accuracy: 5, heading: 0, speed: 0 }, timestamp: 0 }),
}));
jest.mock("expo-battery", () => ({ getBatteryLevelAsync: async () => 0.9, addBatteryLevelListener: () => ({ remove: jest.fn() }) }));
jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; }
  class ApiNetworkError extends Error {}
  return { api: { post: jest.fn().mockResolvedValue({ ok: true }) }, ApiError, ApiNetworkError };
});
let mockRole = "technician";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));

import * as E from "@/src/services/fleet/locationEmitter";
import { useFleetEmitter } from "@/src/hooks/useFleetEmitter";
import FleetStatusChip from "@/src/components/fleet/FleetStatusChip";
import { FLEET_TECH_ROLES, isFleetTechRole } from "@/src/lib/fleetRoles";

const ALLOWED = ["technician", "tech", "landscaper", "landscape_tech", "pool_tech", "tech_both"];
const BLOCKED = ["admin", "manager", "customer", "super_admin", "owner"];

beforeEach(async () => {
  E.stopEmitter();
  await AsyncStorage.clear();
  mockReqPerm.mockReset().mockResolvedValue({ status: "granted" });
  Object.defineProperty(AppState, "currentState", { value: "active", configurable: true });
});
afterEach(() => E.stopEmitter());

it("G0 · role list mirrors BE services/technicians_core.ASSIGNABLE_ROLES (6 roles, same order)", () => {
  expect([...FLEET_TECH_ROLES]).toEqual(ALLOWED);
  for (const r of BLOCKED) expect(isFleetTechRole(r)).toBe(false);
  expect(isFleetTechRole(undefined)).toBe(false);
  expect(isFleetTechRole("")).toBe(false);
});

it.each(ALLOWED)("G1 · %s → emitter starts on login", async (role) => {
  mockRole = role;
  renderHook(() => useFleetEmitter());
  await waitFor(() => expect(E.isEmitterRunning()).toBe(true));
  expect(mockReqPerm).toHaveBeenCalledTimes(1);
});

it.each(BLOCKED)("G2 · %s → emitter never starts, no permission prompt", async (role) => {
  mockRole = role;
  renderHook(() => useFleetEmitter());
  await act(async () => {});
  expect(E.isEmitterRunning()).toBe(false);
  expect(mockReqPerm).not.toHaveBeenCalled();
});

it.each(ALLOWED)("G3 · %s sees the fleet status chip (tracked users always see the indicator)", (role) => {
  mockRole = role;
  const q = render(<FleetStatusChip />);
  expect(q.getByTestId("fleet-status-chip")).toBeTruthy();
});

it.each([["admin", true], ["super_admin", true], ["manager", false], ["customer", false], ["owner", false]] as const)(
  "G4 · %s chip visibility unchanged (admin debug chip kept) → %s", (role, visible) => {
    mockRole = role;
    const q = render(<FleetStatusChip />);
    expect(!!q.queryByTestId("fleet-status-chip")).toBe(visible);
  });

it("G5 · explicitly paused new-role tech (landscaper) stays paused (pause still honoured)", async () => {
  mockRole = "landscaper";
  await E.setPaused(true);
  renderHook(() => useFleetEmitter());
  await act(async () => {});
  expect(E.getEmitterStatus()).toBe("paused");
  expect(mockReqPerm).not.toHaveBeenCalled();
});

it("G6 · source lock: hook + chip + More pause-toggle section all use isFleetTechRole; no 2-role literals left", () => {
  const read = (p: string) => fs.readFileSync(path.resolve(__dirname, "..", p), "utf8");
  const hook = read("src/hooks/useFleetEmitter.ts");
  const chip = read("src/components/fleet/FleetStatusChip.tsx");
  const more = read("app/(app)/more.tsx");
  expect(hook.match(/isFleetTechRole\(role\)/g)).toHaveLength(2);
  expect(hook).not.toMatch(/role === "technician" \|\| role === "tech"/);
  expect(chip).toContain("!isFleetTechRole(role)");
  expect(chip).not.toMatch(/role !== "technician" && role !== "tech"/);
  expect(more).toMatch(/\{isFleetTechRole\(role\) && \(\s*<View style=\{styles\.section\}>\s*<Text style=\{styles\.sectionTitle\}>Fleet Tracking<\/Text>/);
});
