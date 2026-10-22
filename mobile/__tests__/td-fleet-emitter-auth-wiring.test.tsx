/**
 * TD-fleet-emitter-auth-wiring · REAL <AuthProvider> (no useAuth mock).
 *
 * The Phase 1 suite mocked `useAuth`, which hid the bug where the emitter hook
 * ran above <AuthProvider> and never saw a user. Here only the network layer
 * (`@/src/api`), GPS (`expo-location`) and battery are mocked; login goes
 * through the real provider's `login()`.
 */
import React from "react";
import { AppState, Pressable, Text } from "react-native";
import fs from "fs";
import path from "path";
import { render, fireEvent, act, waitFor } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockPost = jest.fn();
const mockGet = jest.fn();
const mockReqPerm = jest.fn();
jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; }
  class ApiNetworkError extends Error {}
  return {
    api: { post: (u: string, b: any) => mockPost(u, b), get: (u: string) => mockGet(u) },
    ApiError, ApiNetworkError, TOKEN_KEY: "pool_crm_token", registerLogoutOn401: () => {},
  };
});
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: () => mockReqPerm(),
  getForegroundPermissionsAsync: async () => ({ status: "granted" }),
  getLastKnownPositionAsync: async () => ({ coords: { latitude: 33.45, longitude: -112.07, accuracy: 8, heading: 0, speed: 0 }, timestamp: Date.now() }),
}));
jest.mock("expo-battery", () => ({
  getBatteryLevelAsync: async () => 0.9,
  addBatteryLevelListener: () => ({ remove: jest.fn() }),
}));

import { AuthProvider, useAuth } from "@/src/auth";
import FleetEmitterRunner from "@/src/components/fleet/FleetEmitterRunner";
import * as E from "@/src/services/fleet/locationEmitter";

const TECH = { id: "t1", role: "technician", email: "mike@x.com", full_name: "Mike Rivera" };
const ADMIN = { id: "a1", role: "admin", email: "admin@x.com", full_name: "Ada Admin" };
let loginUser: any = TECH;

function LoginButton() {
  const { login, user } = useAuth();
  return (
    <Pressable testID="do-login" onPress={() => { login("x@x.com", "pw"); }}>
      <Text testID="who">{user?.role || "anon"}</Text>
    </Pressable>
  );
}
const pings = () => mockPost.mock.calls.filter((c) => c[0] === "/fleet/ping");

beforeEach(async () => {
  E.stopEmitter();
  await AsyncStorage.clear();
  loginUser = TECH;
  mockReqPerm.mockReset().mockResolvedValue({ status: "granted" });
  mockGet.mockReset().mockImplementation(async (u: string) => (u === "/auth/me" ? loginUser : {}));
  mockPost.mockReset().mockImplementation(async (u: string) =>
    u === "/auth/login" ? { access_token: "tok", user: loginUser } : { ok: true });
  Object.defineProperty(AppState, "currentState", { value: "active", configurable: true });
});
afterEach(() => E.stopEmitter());

const loginVia = async (tree: React.ReactElement) => {
  const q = render(tree);
  await act(async () => {});
  expect(pings()).toHaveLength(0); // logged out → nothing emitted
  await act(async () => { fireEvent.press(q.getByTestId("do-login")); });
  return q;
};

it("R1 · real login as a tech → runner (inside AuthProvider) boots the emitter and sends a GPS ping → active", async () => {
  await loginVia(<AuthProvider><FleetEmitterRunner /><LoginButton /></AuthProvider>);
  await waitFor(() => expect(pings().length).toBeGreaterThan(0));
  expect(pings()[0][1]).toEqual(expect.objectContaining({ lat: 33.45, lng: -112.07 }));
  await waitFor(() => expect(E.getEmitterStatus()).toBe("active"));
  expect(E.isEmitterRunning()).toBe(true);
});

it("R2 · bug-class lock: the SAME hook mounted ABOVE <AuthProvider> never sees the user → never starts", async () => {
  await loginVia(<><FleetEmitterRunner /><AuthProvider><LoginButton /></AuthProvider></>);
  await act(async () => {});
  expect(pings()).toHaveLength(0);
  expect(E.isEmitterRunning()).toBe(false);
  expect(mockReqPerm).not.toHaveBeenCalled();
});

it("R3 · real login as admin → no emitter, no pings (role gate unchanged)", async () => {
  loginUser = ADMIN;
  const q = await loginVia(<AuthProvider><FleetEmitterRunner /><LoginButton /></AuthProvider>);
  await waitFor(() => expect(q.getByTestId("who").props.children).toBe("admin"));
  expect(E.isEmitterRunning()).toBe(false);
  expect(pings()).toHaveLength(0);
});

it("R4 · real login as a tech who explicitly paused → stays paused, no pings, no permission prompt", async () => {
  await E.setPaused(true);
  await loginVia(<AuthProvider><FleetEmitterRunner /><LoginButton /></AuthProvider>);
  await act(async () => {});
  expect(E.getEmitterStatus()).toBe("paused");
  expect(pings()).toHaveLength(0);
  expect(mockReqPerm).not.toHaveBeenCalled();
});

it("R5 · real login as a tech with OS permission denied → OS wins: no_permission, no pings", async () => {
  mockReqPerm.mockResolvedValue({ status: "denied" });
  await loginVia(<AuthProvider><FleetEmitterRunner /><LoginButton /></AuthProvider>);
  await waitFor(() => expect(E.getEmitterStatus()).toBe("no_permission"));
  expect(pings()).toHaveLength(0);
});

it("W1 · app/_layout.tsx wiring: RootLayout no longer calls the hook; runner rendered inside <AuthProvider>", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../app/_layout.tsx"), "utf8");
  expect(src).not.toMatch(/^\s*useFleetEmitter\(\);/m);
  const jsx = src.slice(src.lastIndexOf("<AuthProvider>")); // the rendered tree, not comments
  const at = jsx.search(/^\s*<FleetEmitterRunner \/>\s*$/m);
  expect(at).toBeGreaterThan(-1);
  expect(at).toBeLessThan(jsx.indexOf("</AuthProvider>"));
  expect(src.match(/^\s*<FleetEmitterRunner \/>\s*$/gm)).toHaveLength(1); // mounted exactly once
});
