/**
 * __tests__/mobile-customer-status-filter.test.tsx
 * Tests: segmented control renders, default Active, refetch on change, persistence.
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

const mockStorageGet = jest.fn(async () => "active");
const mockStorageSet = jest.fn(async () => {});
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

// Mock expo-router hooks that require navigation context.
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: () => any) => {
    const React = require("react");
    React.useEffect(() => { const cleanup = cb(); return cleanup; }, [cb]);
  },
  Link: ({ children }: any) => children,
}));

import Customers from "@/app/(app)/customers";

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
jest.mock("@/src/components/ImportExport", () => ({
  ImportExport: () => null,
}));
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({
    selected: new Set(),
    count: 0,
    allSelected: false,
    indeterminate: false,
    toggleAll: jest.fn(),
    toggleOne: jest.fn(),
    clear: jest.fn(),
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

describe("Customer Status Filter", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApiGet.mockResolvedValue([]);
    mockStorageGet.mockResolvedValue("active");
  });

  it("renders segmented control with Active/Inactive/All", async () => {
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customer-status-active")).toBeTruthy();
      expect(tree.getByTestId("customer-status-inactive")).toBeTruthy();
      expect(tree.getByTestId("customer-status-all")).toBeTruthy();
    });
    console.log("✅ CSF-T1: segmented control renders");
  });

  it("default fetch includes is_active=true", async () => {
    render(<Customers />);
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalled();
    });
    const url = mockApiGet.mock.calls[0]?.[0] || "";
    expect(url).toContain("is_active=true");
    console.log("✅ CSF-T2: default fetch includes is_active=true");
  });

  it("switching to Inactive triggers refetch with is_active=false", async () => {
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-status-inactive")).toBeTruthy(),
    );
    mockApiGet.mockClear();
    fireEvent.press(tree.getByTestId("customer-status-inactive"));
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalled();
    });
    const url = mockApiGet.mock.calls[0]?.[0] || "";
    expect(url).toContain("is_active=false");
    console.log("✅ CSF-T3: Inactive sets is_active=false");
  });

  it("switching to All omits is_active param", async () => {
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-status-all")).toBeTruthy(),
    );
    mockApiGet.mockClear();
    fireEvent.press(tree.getByTestId("customer-status-all"));
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalled();
    });
    const url = mockApiGet.mock.calls[0]?.[0] || "";
    expect(url).not.toContain("is_active");
    console.log("✅ CSF-T4: All omits is_active param");
  });

  it("persists filter to AsyncStorage on change", async () => {
    const tree = render(<Customers />);
    await waitFor(() =>
      expect(tree.getByTestId("customer-status-inactive")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("customer-status-inactive"));
    await waitFor(() => {
      expect(mockStorageSet).toHaveBeenCalledWith(
        "customerListFilter.status",
        "inactive",
      );
    });
    console.log("✅ CSF-T5: filter persisted to AsyncStorage");
  });
});
