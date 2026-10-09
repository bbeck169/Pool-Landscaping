/**
 * Phase 19 · Feature 1 — technician pay-rates edit UI (mobile parity
 * with web Phase 10 · 04f1f3749).
 *
 *   * "Edit pay rates" kebab item renders for admin / super_admin / owner
 *     on non-self, non-deleted TECH rows only
 *   * hidden for manager / technician viewers and for non-tech rows
 *   * hourly + per-pool inputs hydrate from the row doc
 *   * save → PATCH /users/{id} with 2-place decimal STRINGS; blank → null
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPatch = jest.fn(async () => ({}));
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: (...a: any[]) => (mockPatch as any)(...a),
    post: jest.fn(async () => ({})), put: jest.fn(async () => ({})),
  },
}));
let mockRole = "admin";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "me", role: mockRole } }) }));
const mockToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: () => <View testID="team-loading" />,
    EmptyState: () => <View testID="team-empty" />,
    PrimaryButton: ({ title, onPress, testID }: any) => <Pressable onPress={onPress} testID={testID}><Text>{title}</Text></Pressable>,
  };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return (p: any) => <TextInput {...p} />;
});
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({ selected: new Set(), count: 0, toggleOne: () => {}, clear: () => {}, toggleAll: () => {} }),
  BulkCheckbox: () => null, BulkActionBar: () => null,
}));

import Team from "@/app/team";
import { formatRate, rateToNumber } from "@/src/components/team/TechnicianPayRatesModal";

const ROWS = [
  { id: "me", name: "Me", email: "me@x", role: "admin" },
  { id: "t1", name: "Mike", email: "mike@x", role: "technician", hourly_rate: 22.5, per_pool_rate: "10" },
  { id: "t2", name: "Lana", email: "lana@x", role: "landscape_tech" },
  { id: "m1", name: "Mgr", email: "mgr@x", role: "manager" },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockGet.mockResolvedValue(ROWS);
});

async function openKebab(rowId: string) {
  const r = render(<Team />);
  await waitFor(() => r.getByTestId("team-list"));
  await act(async () => { fireEvent.press(r.getByTestId(`team-row-kebab-${rowId}`)); });
  return r;
}

describe("Phase 19 · pay rates — role gate", () => {
  it.each(["admin", "super_admin", "owner"])("%s sees 'Edit pay rates' on a tech row", async (role) => {
    mockRole = role;
    const r = await openKebab("t1");
    expect(r.getByTestId("team-row-edit-pay-btn-t1")).toBeTruthy();
  });

  it.each(["manager", "technician"])("%s viewer gets no pay-rate entry (no kebab at all)", async (role) => {
    mockRole = role;
    const r = render(<Team />);
    await waitFor(() => r.getByTestId("team-list"));
    expect(r.queryByTestId("team-row-kebab-t1")).toBeNull();
    expect(r.queryByTestId("team-row-edit-pay-btn-t1")).toBeNull();
  });

  it("non-tech rows (manager) never offer pay rates", async () => {
    mockRole = "super_admin";
    const r = await openKebab("m1");
    expect(r.queryByTestId("team-row-edit-pay-btn-m1")).toBeNull();
  });

  it("self row is excluded", async () => {
    mockRole = "admin";
    const r = render(<Team />);
    await waitFor(() => r.getByTestId("team-list"));
    expect(r.queryByTestId("team-row-kebab-me")).toBeNull();
  });
});

describe("Phase 19 · pay rates — modal + payload", () => {
  it("hydrates both inputs from the row and saves 2-place decimal strings", async () => {
    const r = await openKebab("t1");
    await act(async () => { fireEvent.press(r.getByTestId("team-row-edit-pay-btn-t1")); });
    const hourly = r.getByTestId("tech-pay-rate-hourly-input");
    const perPool = r.getByTestId("tech-pay-rate-per-pool-input");
    expect(hourly.props.value).toBe("22.5");
    expect(perPool.props.value).toBe("10");
    expect(hourly.props.keyboardType).toBe("decimal-pad");

    fireEvent.changeText(hourly, "25.50");
    fireEvent.changeText(perPool, "12.345");
    await act(async () => { fireEvent.press(r.getByTestId("tech-pay-rates-save")); });
    expect(mockPatch).toHaveBeenCalledWith("/users/t1", { hourly_rate: "25.50", per_pool_rate: "12.35" });
    expect(mockToast).toHaveBeenCalledWith("Pay rates saved for Mike", "success");
    await waitFor(() => expect(r.queryByTestId("tech-pay-rates-modal")).toBeNull());
  });

  it("blank inputs send null; letters are rejected by the decimal primitive", async () => {
    const r = await openKebab("t2");
    await act(async () => { fireEvent.press(r.getByTestId("team-row-edit-pay-btn-t2")); });
    const hourly = r.getByTestId("tech-pay-rate-hourly-input");
    fireEvent.changeText(hourly, "abc");
    expect(hourly.props.value).toBe("");
    await act(async () => { fireEvent.press(r.getByTestId("tech-pay-rates-save")); });
    expect(mockPatch).toHaveBeenCalledWith("/users/t2", { hourly_rate: null, per_pool_rate: null });
  });

  it("server error surfaces an error toast and keeps the modal open", async () => {
    mockPatch.mockRejectedValueOnce(new Error("Forbidden") as never);
    const r = await openKebab("t1");
    await act(async () => { fireEvent.press(r.getByTestId("team-row-edit-pay-btn-t1")); });
    await act(async () => { fireEvent.press(r.getByTestId("tech-pay-rates-save")); });
    expect(mockToast).toHaveBeenCalledWith("Forbidden", "error");
    expect(r.getByTestId("tech-pay-rates-modal")).toBeTruthy();
  });

  it("format helpers: toFixed(2) on send, tolerant parse on hydrate", () => {
    expect(formatRate(25.5)).toBe("25.50");
    expect(formatRate(null)).toBeNull();
    expect(rateToNumber("10.00")).toBe(10);
    expect(rateToNumber("")).toBeNull();
    expect(rateToNumber(undefined)).toBeNull();
  });
});
