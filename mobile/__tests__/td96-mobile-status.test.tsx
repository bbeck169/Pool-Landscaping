/**
 * TD-96-mobile-status · lead detail status tiles (app/leads/[id].tsx).
 * Regression: tiles compared/PATCHed title-case ("New"/"Contacted"/"Quoted"/"On Hold"/"Archived")
 * against snake_case data → Contacted/Quoted never rendered; Archive PATCHed "Archived" which the
 * BE normalizer maps to "new" (silent reset). Fix = web-parity 3-button grid new/contacted/quoted.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPatch = jest.fn();
const mockToast = jest.fn();

jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; detail: any = null; }
  return { api: { get: (u: string) => mockGet(u), post: jest.fn(), patch: (u: string, b: any) => mockPatch(u, b) }, ApiError };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "L1" }),
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => { cb(); }, []); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));

import LeadDetailScreen from "@/app/leads/[id]";

const BASE = { id: "L1", name: "Lena Lead", status: "new", phone: "", email: "", timeline: [], quotes_count: 0 };
let mockLead: any = BASE;

beforeEach(() => {
  mockLead = { ...BASE };
  mockToast.mockReset();
  mockGet.mockReset().mockImplementation(async (u: string) => (u === "/leads/L1" ? mockLead : { items: [], total: 0, limit: 10 }));
  mockPatch.mockReset().mockImplementation(async (_u: string, b: any) => ({ ...mockLead, ...b }));
});

const mount = async () => {
  const q = render(<LeadDetailScreen />);
  await waitFor(() => q.getByTestId("lead-actions"));
  return q;
};
const disabled = (q: any, s: string) => q.getByTestId(`lead-status-${s}`).props.accessibilityState?.disabled;

it("S1 · new lead → 3-tile grid, current tile disabled; no On Hold / Archive / legacy tiles", async () => {
  const q = await mount();
  expect([disabled(q, "new"), disabled(q, "contacted"), disabled(q, "quoted")]).toEqual([true, false, false]);
  for (const id of ["lead-action-onhold", "lead-action-archive", "lead-action-contacted", "lead-action-quoted"]) {
    expect(q.queryByTestId(id)).toBeNull();
  }
  expect(q.getByTestId("lead-action-close-won")).toBeTruthy();
  expect(q.getByTestId("lead-action-close-lost")).toBeTruthy();
});

it("S2 · tap Contacted → PATCH snake_case, toast uses display label, disabled state follows", async () => {
  const q = await mount();
  await act(async () => { fireEvent.press(q.getByTestId("lead-status-contacted")); });
  expect(mockPatch).toHaveBeenCalledWith("/leads/L1", { status: "contacted" });
  expect(mockToast).toHaveBeenCalledWith("Marked Contacted");
  await waitFor(() => expect(disabled(q, "contacted")).toBe(true));
  expect(disabled(q, "new")).toBe(false);
});

it("S3 · quoted lead → can move back to New (admin correction)", async () => {
  mockLead = { ...BASE, status: "quoted" };
  const q = await mount();
  expect(disabled(q, "quoted")).toBe(true);
  await act(async () => { fireEvent.press(q.getByTestId("lead-status-new")); });
  expect(mockPatch).toHaveBeenCalledWith("/leads/L1", { status: "new" });
  expect(mockToast).toHaveBeenCalledWith("Marked New");
});

it("S4 · source guard: no title-case status writes / compares", () => {
  const src = fs.readFileSync(path.join(__dirname, "../app/leads/[id].tsx"), "utf8");
  expect(src).not.toMatch(/setStatus\(\s*"(New|Contacted|Quoted|On Hold|Archived)"/);
  expect(src).not.toMatch(/lead\.status === "(New|Contacted|Quoted)"/);
});
