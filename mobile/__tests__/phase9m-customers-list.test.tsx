/**
 * Phase 9-M · Customers list — tile cleanup + clickable filters + slim list
 * (web parity 42e72c6a4 · Phase 9b, b5c09c9dc · Phase 9c).
 *
 *   2. Invited tile not rendered (and no Chase button)
 *   3. No top-cluster Portal Invite button
 *   4. 3 tiles tappable with correct selected state
 *   5. Tapping a tile updates route params + fetch URL; tap again clears
 *   6. List fetch URL carries slim=1 + page_size=50
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn(),
  },
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "admin" } }) }));

// Route-param store: setParams notifies subscribers so the screen
// re-renders exactly like expo-router does on router.setParams().
let mockParams: Record<string, string | undefined> = {};
const mockListeners = new Set<() => void>();
const mockSetParams = jest.fn((p: Record<string, string | undefined>) => {
  mockParams = { ...mockParams, ...p };
  mockListeners.forEach((l) => l());
});
jest.mock("expo-router", () => {
  const R = require("react");
  return {
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn(), setParams: mockSetParams }),
    useLocalSearchParams: () => R.useSyncExternalStore(
      (l: () => void) => { mockListeners.add(l); return () => mockListeners.delete(l); },
      () => mockParams,
    ),
    useFocusEffect: (cb: any) => { R.useEffect(() => { cb(); }, [cb]); },
  };
});
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ui", () => {
  const { View } = require("react-native");
  return { Loading: (p: any) => <View testID={p.testID} />, EmptyState: (p: any) => <View testID={p.testID} /> };
});
jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return { Header: (p: any) => <View testID="header">{p.right}</View>, IconButton: (p: any) => <View testID={p.testID} /> };
});
jest.mock("@/src/components/ImportExport", () => ({ ImportExport: () => null }));
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return (p: any) => <TextInput {...p} />;
});
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));
jest.mock("@/src/components/customers/RestoreCustomerButton", () => () => null);
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => {
  const { View } = require("react-native");
  return {
    useBulkSelect: () => ({ selected: new Set(), count: 0, toggleOne: () => {}, clear: () => {}, toggleAll: () => {} }),
    BulkCheckbox: () => <View />, BulkActionBar: () => <View />,
  };
});

import Customers from "@/app/(app)/customers";

const HEALTH = {
  cohorts: {
    invited: { count: 42, delta_30d: null },
    activated: { count: 15, delta_30d: 3 },
    signed_in: { count: 8, delta_30d: -2 },
    never_logged_in: { count: 30, delta_30d: null },
    active_with_card_on_file: { count: 11, delta_30d: 1 },
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = {};
  mockApiGet.mockImplementation(async (url: string) => {
    if (url.startsWith("/reports/portal-onboarding-health")) return HEALTH;
    if (url.includes("count_only=true")) return { count: 1 };
    return { items: [{ id: "c1", name: "Alpha" }], total_pages: 1 };
  });
});

const listCalls = () =>
  mockApiGet.mock.calls.map((c) => c[0] as string)
    .filter((u) => u.startsWith("/customers?") && !u.includes("count_only"));
const lastListParams = () => new URLSearchParams(listCalls().slice(-1)[0].split("?")[1]);

async function mount() {
  const r = render(<Customers />);
  await waitFor(() => r.getByTestId("onboarding-health-tile"));
  await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));
  return r;
}

describe("Phase 9-M · Customers list", () => {
  it("2. Invited tile + Chase button are not rendered", async () => {
    const r = await mount();
    expect(r.queryByTestId("onboarding-cohort-invited")).toBeNull();
    expect(r.queryByTestId("onboarding-tile-invited-chase-cta")).toBeNull();
    expect(r.queryByText("Invited")).toBeNull();
  });

  it("3. no top-cluster Portal Invite button", async () => {
    const r = await mount();
    expect(r.queryByTestId("customers-toolbar-portal-invite-btn")).toBeNull();
    expect(r.queryByText(/Portal Invite/i)).toBeNull();
  });

  it("4. three tiles render tappable with correct selected state from route params", async () => {
    mockParams = { first_access: "any" };
    const r = await mount();
    const ids = ["onboarding-cohort-activated", "onboarding-cohort-signed-in", "portal-onboarding-cards-on-file-tile"];
    ids.forEach((id) => expect(r.getByTestId(id).props.accessibilityRole).toBe("button"));
    expect(r.getByTestId("onboarding-cohort-signed-in").props.accessibilityState).toEqual({ selected: true });
    expect(r.getByTestId("onboarding-cohort-activated").props.accessibilityState).toEqual({ selected: false });
    expect(r.getByTestId("portal-onboarding-cards-on-file-tile").props.accessibilityState).toEqual({ selected: false });
    expect(lastListParams().get("first_access")).toBe("any");
  });

  it("5. tap activates → route params + fetch URL; tap other swaps; tap active clears", async () => {
    const r = await mount();
    await act(async () => { fireEvent.press(r.getByTestId("onboarding-cohort-activated")); });
    expect(mockSetParams).toHaveBeenLastCalledWith({ portal_activated: "1", first_access: undefined, has_payment_method: undefined });
    await waitFor(() => expect(lastListParams().get("portal_activated")).toBe("1"));
    expect(r.getByTestId("onboarding-cohort-activated").props.accessibilityState).toEqual({ selected: true });

    // Swap → Cards on file (also forces is_active=true).
    await act(async () => { fireEvent.press(r.getByTestId("portal-onboarding-cards-on-file-tile")); });
    expect(mockSetParams).toHaveBeenLastCalledWith({ portal_activated: undefined, first_access: undefined, has_payment_method: "true" });
    await waitFor(() => expect(lastListParams().get("has_payment_method")).toBe("true"));
    expect(lastListParams().get("is_active")).toBe("true");
    expect(lastListParams().get("portal_activated")).toBeNull();

    // Tap the active tile → clears.
    await act(async () => { fireEvent.press(r.getByTestId("portal-onboarding-cards-on-file-tile")); });
    expect(mockSetParams).toHaveBeenLastCalledWith({ portal_activated: undefined, first_access: undefined, has_payment_method: undefined });
    await waitFor(() => expect(lastListParams().get("has_payment_method")).toBeNull());
    expect(r.getByTestId("portal-onboarding-cards-on-file-tile").props.accessibilityState).toEqual({ selected: false });
  });

  it("6. list fetch carries slim=1 and page_size=50; filters preserved", async () => {
    await mount();
    const p = lastListParams();
    expect(p.get("slim")).toBe("1");
    expect(p.get("page_size")).toBe("50");
    expect(p.get("page")).toBe("1");
    expect(p.get("is_active")).toBe("true"); // default Active segment preserved
    expect(p.get("portal_invited")).toBeNull();
  });
});
