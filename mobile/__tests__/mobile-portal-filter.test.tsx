/**
 * __tests__/mobile-portal-filter.test.tsx
 * Tests: renders 3 options, default All, refetch with portal_status,
 * AsyncStorage persistence, stacks with Active/Inactive filter.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockApiGet = jest.fn(async () => []);
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn(async () => ({})),
    put: jest.fn(async () => ({})),
    patch: jest.fn(async () => ({})),
    del: jest.fn(async () => ({})),
  },
}));

const storageBag: Record<string, string> = {};
const mockStorageGet = jest.fn(async (key: string, fallback?: string) => storageBag[key] ?? fallback ?? null);
const mockStorageSet = jest.fn(async (key: string, val: string) => { storageBag[key] = val; });
jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: (...a: any[]) => mockStorageGet(...a),
    setItem: (...a: any[]) => mockStorageSet(...a),
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn(async () => {}),
  readCache: jest.fn(async () => null),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: () => any) => {
    const React = require("react");
    React.useEffect(() => { const cleanup = cb(); return cleanup; }, [cb]);
  },
  Link: ({ children }: any) => children,
}));
jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID}><Text>Loading</Text></View>,
    EmptyState: (p: any) => <View testID={p.testID}><Text>{p.title}</Text></View>,
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return {
    Header: (p: any) => <View testID="header"><Text>{p.title}</Text>{p.right}</View>,
    IconButton: (p: any) => <View testID={p.testID} />,
  };
});
jest.mock("@/src/components/ImportExport", () => ({ ImportExport: () => null }));
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({
    selected: new Set(), count: 0, allSelected: false, indeterminate: false,
    toggleAll: jest.fn(), toggleOne: jest.fn(), clear: jest.fn(),
  }),
  BulkCheckbox: () => null,
  BulkActionBar: () => null,
}));
jest.mock("@/src/components/customers/RestoreCustomerButton", () => {
  const { View } = require("react-native");
  return () => <View />;
});
jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (c: any) => c.name || "",
}));

import Customers from "@/app/(app)/customers";

describe("Portal Activation Filter — G4b", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Object.keys(storageBag).forEach((k) => delete storageBag[k]);
    mockApiGet.mockResolvedValue([]);
  });

  it("renders portal filter with 3 options", async () => {
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customer-portal-filter")).toBeTruthy();
      expect(tree.getByTestId("customer-portal-all")).toBeTruthy();
      expect(tree.getByTestId("customer-portal-activated")).toBeTruthy();
      expect(tree.getByTestId("customer-portal-not_activated")).toBeTruthy();
    });
    console.log("✅ PF-T1: portal filter renders 3 options");
  });

  it("default is 'All' — no portal_status param in initial fetch", async () => {
    render(<Customers />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    const url = mockApiGet.mock.calls[0][0] as string;
    expect(url).not.toContain("portal_status");
    console.log("✅ PF-T2: default All omits portal_status param");
  });

  it("selecting Activated triggers refetch with portal_status=activated", async () => {
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-portal-activated")).toBeTruthy(),
    );
    mockApiGet.mockClear();
    fireEvent.press(tree.getByTestId("customer-portal-activated"));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    const url = mockApiGet.mock.calls[0][0] as string;
    expect(url).toContain("portal_status=activated");
    console.log("✅ PF-T3: Activated sends portal_status=activated");
  });

  it("selecting Not activated sends portal_status=not_activated", async () => {
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-portal-not_activated")).toBeTruthy(),
    );
    mockApiGet.mockClear();
    fireEvent.press(tree.getByTestId("customer-portal-not_activated"));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    const url = mockApiGet.mock.calls[0][0] as string;
    expect(url).toContain("portal_status=not_activated");
    console.log("✅ PF-T4: Not activated sends portal_status=not_activated");
  });

  it("does NOT persist portal selection to AsyncStorage (K40)", async () => {
    // Phase K40 · Feb-2026 — persistence REMOVED. Every mount lands
    // on ``"all"``; changing the dropdown must NOT touch storage
    // for the ``customerListFilter.*`` namespace.
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-portal-activated")).toBeTruthy(),
    );
    mockStorageSet.mockClear();
    fireEvent.press(tree.getByTestId("customer-portal-activated"));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    const filterWrites = mockStorageSet.mock.calls.filter((args: any[]) =>
      typeof args[0] === "string" && args[0].startsWith("customerListFilter."),
    );
    expect(filterWrites).toHaveLength(0);
    console.log("✅ PF-T5 (K40): portal selection NOT persisted to AsyncStorage");
  });

  it("stacks with Active/Inactive filter (intersection)", async () => {
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customer-status-inactive")).toBeTruthy();
      expect(tree.getByTestId("customer-portal-activated")).toBeTruthy();
    });
    mockApiGet.mockClear();
    // Select Inactive status
    fireEvent.press(tree.getByTestId("customer-status-inactive"));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    mockApiGet.mockClear();
    // Then select Activated portal
    fireEvent.press(tree.getByTestId("customer-portal-activated"));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    const url = mockApiGet.mock.calls[0][0] as string;
    expect(url).toContain("is_active=false");
    expect(url).toContain("portal_status=activated");
    console.log("✅ PF-T6: stacks with Active/Inactive (intersection query)");
  });

  it("K40 · ignores any pre-existing storage value on mount (defaults to 'all')", async () => {
    // Phase K40 · Feb-2026 — a stale storage value from an older
    // build must NOT hydrate the filter. Seed the bag and assert
    // the API never sees ``portal_status=not_activated``.
    storageBag["customerListFilter.portalStatus"] = "not_activated";
    render(<Customers />);
    // Give the load() effect a full tick to fire.
    await waitFor(() => expect(mockApiGet).toHaveBeenCalled());
    // Wait a bit longer to ensure no re-fetch was scheduled by a
    // storage hydration effect (K40 removed that pathway).
    await new Promise((r) => setTimeout(r, 200));
    const calls = mockApiGet.mock.calls.map((c: any) => c[0] as string);
    const anyPortalCall = calls.some((u: string) => u.includes("portal_status="));
    expect(anyPortalCall).toBe(false);
    console.log("✅ PF-T7 (K40): stale storage value ignored on mount");
  });
});
