/**
 * Ship 2 · Customers list — "Show deleted" filter chip + role gating.
 *
 * Tests:
 *   1. Chip visible for admin / owner / super_admin.
 *   2. Chip NOT visible for tech / customer roles.
 *   3. Toggling chip refetches with include_deleted=true.
 *   4. Soft-deleted row renders with strikethrough + Restore button.
 */
import React from "react";
import { render, act, waitFor, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockApiPatch = jest.fn();
const mockApiDel = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockApiGet(...args),
    post: (...args: any[]) => mockApiPost(...args),
    patch: (...args: any[]) => mockApiPatch(...args),
    del: (...args: any[]) => mockApiDel(...args),
  },
}));

// Dynamic role via a ref object the mock captures by reference
const authRef = { role: "admin" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: authRef.role }, token: "tok" }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    // Re-run when callback identity changes (mirrors real useFocusEffect)
    useEffect(() => { cb(); }, [cb]);
  },
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("@/src/theme", () => ({
  colors: {
    bg: "#000", card: "#111", surface: "#222", surfaceHover: "#333",
    surfaceSecondary: "#f5f5f5", onSurfaceSecondary: "#666",
    border: "#444", brand: "#0af", brandTertiary: "#0af",
    text: "#fff", muted: "#888", danger: "#f00", ok: "#0f0",
    warn: "#fa0", info: "#0af", success: "#0f0", onSurface: "#333",
    divider: "#eee",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, md: 14, lg: 16, xl: 20 },
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: (props: any) => (
      <View testID={props.testID || "loading"}><Text>Loading</Text></View>),
    EmptyState: (props: any) => (
      <View testID={props.testID || "empty"}><Text>{props.title}</Text></View>),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Pressable, Text } = require("react-native");
  return {
    Header: () => <View testID="header" />,
    IconButton: (props: any) => (
      <Pressable onPress={props.onPress} testID={props.testID}>
        <Text>{props.label || "btn"}</Text>
      </Pressable>),
  };
});

jest.mock("@/src/components/ImportExport", () => ({
  ImportExport: () => null,
}));

jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => {
  const { View } = require("react-native");
  return {
    useBulkSelect: () => ({
      selected: new Set<string>(),
      count: 0,
      allSelected: false,
      indeterminate: false,
      toggleOne: () => {},
      clear: () => {},
      toggleAll: () => {},
    }),
    BulkCheckbox: () => <View />,
    BulkActionBar: () => <View />,
  };
});

jest.mock("@/src/components/customers/RestoreCustomerButton", () => {
  const { Text } = require("react-native");
  return {
    __esModule: true,
    default: ({ customer }: any) => (
      <Text testID={`restore-customer-btn-${customer.id}`}>Restore</Text>
    ),
  };
});

jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (row: any) =>
    (typeof row === "string" ? row : row?.customer_name) || "Unknown Customer",
}));

import Customers from "@/app/(app)/customers";

// ── helpers ──────────────────────────────────────────────────────────
function envelope(customers: any[]) {
  return {
    items: customers,
    total: customers.length,
    page: 1,
    page_size: 100,
    total_pages: 1,
  };
}

const NORMAL_CUSTOMER = { id: "c1", name: "Alice", address: "123 Main St" };
const DELETED_CUSTOMER = {
  id: "c2",
  name: "Bob Deleted",
  address: "456 Oak Ave",
  deleted_at: "2026-08-01T12:00:00Z",
};

// ── tests ────────────────────────────────────────────────────────────
beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
  mockApiPatch.mockReset();
  mockApiDel.mockReset();
  authRef.role = "admin";

  mockApiGet.mockImplementation((path: string) => {
    if (path.startsWith("/customers?")) {
      return Promise.resolve(envelope([NORMAL_CUSTOMER, DELETED_CUSTOMER]));
    }
    return Promise.resolve({});
  });
});

describe("Customers list · Soft-deleted chip + role gate (Ship 2)", () => {
  it("filter chip visible for role=admin", async () => {
    authRef.role = "admin";
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customers-filter-include-deleted")).toBeTruthy();
    });
  });

  it("filter chip visible for role=super_admin", async () => {
    authRef.role = "super_admin";
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customers-filter-include-deleted")).toBeTruthy();
    });
  });

  it("filter chip visible for role=owner", async () => {
    authRef.role = "owner";
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customers-filter-include-deleted")).toBeTruthy();
    });
  });

  it("filter chip NOT visible for role=tech", async () => {
    authRef.role = "tech";
    const tree = render(<Customers />);
    // Wait for initial load to settle
    await waitFor(() => {
      expect(tree.getByTestId("customer-row-c1")).toBeTruthy();
    });
    expect(tree.queryByTestId("customers-filter-include-deleted")).toBeNull();
  });

  it("filter chip NOT visible for role=customer", async () => {
    authRef.role = "customer";
    const tree = render(<Customers />);
    await waitFor(() => {
      expect(tree.getByTestId("customer-row-c1")).toBeTruthy();
    });
    expect(tree.queryByTestId("customers-filter-include-deleted")).toBeNull();
  });

  it("toggling chip refetches with include_deleted=true", async () => {
    authRef.role = "admin";
    const tree = render(<Customers />);

    await waitFor(() => {
      expect(tree.getByTestId("customers-filter-include-deleted")).toBeTruthy();
    });

    // Clear initial fetch calls
    mockApiGet.mockClear();

    // Toggle the chip on
    await act(async () => {
      fireEvent.press(tree.getByTestId("customers-filter-include-deleted"));
    });

    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some(
          (p: any) =>
            typeof p === "string" &&
            p.startsWith("/customers?") &&
            p.includes("include_deleted=true"),
        ),
      ).toBe(true);
    });
  });

  it("soft-deleted row shows Restore button", async () => {
    authRef.role = "admin";
    const tree = render(<Customers />);

    await waitFor(() => {
      expect(tree.getByTestId("customer-row-c2")).toBeTruthy();
    });

    // Restore button rendered for the deleted customer
    expect(tree.getByTestId("restore-customer-btn-c2")).toBeTruthy();
  });

  it("soft-deleted row has diminished opacity styling", async () => {
    authRef.role = "admin";
    const tree = render(<Customers />);

    await waitFor(() => {
      expect(tree.getByTestId("customer-row-c2")).toBeTruthy();
    });

    // The row should have the deleted styling (opacity 0.6)
    const row = tree.getByTestId("customer-row-c2");
    const rowStyle = Array.isArray(row.props.style)
      ? Object.assign({}, ...row.props.style.filter(Boolean))
      : row.props.style;
    expect(rowStyle.opacity).toBe(0.6);
  });
});
