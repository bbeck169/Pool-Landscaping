/**
 * Ship 2 · 409 toast when hard-deleting a customer with unpaid invoices.
 *
 * Smoke-tests the doDelete("hard") handler against a 409 response shape:
 *   { detail: { detail: "customer_has_unpaid_invoices", invoice_count: 2, ... } }
 */
import React from "react";
import { Alert } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiDel = jest.fn();
const mockApiPost = jest.fn();
const mockApiPatch = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    del: (...a: any[]) => mockApiDel(...a),
    post: (...a: any[]) => mockApiPost(...a),
    patch: (...a: any[]) => mockApiPatch(...a),
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: "admin", name: "Admin" },
    startImpersonation: jest.fn(),
  }),
}));

const mockPush = jest.fn();
const mockBack = jest.fn();
jest.mock("expo-router", () => {
  const ReactLib = require("react");
  return {
    useRouter: () => ({ push: mockPush, back: mockBack, replace: jest.fn() }),
    useLocalSearchParams: () => ({ id: "cust-123" }),
    useFocusEffect: (cb: any) => {
      ReactLib.useEffect(() => { cb(); }, []);
    },
    Redirect: () => null,
  };
});

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return {
    Ionicons: ({ name }: any) => <Text testID={`icon-${name}`}>{name}</Text>,
  };
});

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f5f5f5",
    border: "#ddd", brand: "#0af", brandTertiary: "#e0f7ff",
    onSurface: "#333", onSurfaceSecondary: "#666",
    muted: "#888", success: "#0f0", divider: "#eee",
  },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16, pill: 999 },
  money: (n: any) => `$${(n || 0).toFixed(2)}`,
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    PrimaryButton: ({ title, onPress }: any) => (
      <Pressable onPress={onPress}><Text>{title}</Text></Pressable>
    ),
    Sheet: ({ children }: any) => <View>{children}</View>,
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return {
    Header: () => <View testID="header" />,
    JobCard: () => <View />,
  };
});

jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => () => null);
jest.mock("@/src/components/customers/MultiContact", () => () => null);
jest.mock("@/src/components/customers/CustomerTasks", () => () => null);
jest.mock("@/src/components/customers/ServiceNotes", () => () => null);
jest.mock("@/src/components/customers/SendCreateSheet", () => () => null);
jest.mock("@/src/components/customers/CustomerTagsSection", () => () => null);
jest.mock("@/src/components/comms/DemoAccountToggle", () => () => null);
jest.mock("@/src/components/customers/MuteControlSheet", () => () => null);
jest.mock("@/src/components/customers/CustomerDeleteModal", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    __esModule: true,
    default: ({ visible, onHardDelete, onSoftDelete, onCancel }: any) => {
      if (!visible) return null;
      return (
        <View testID="customer-delete-modal">
          <Pressable testID="mock-hard-delete-trigger" onPress={onHardDelete}>
            <Text>Hard Delete</Text>
          </Pressable>
          <Pressable testID="mock-soft-delete-trigger" onPress={onSoftDelete}>
            <Text>Soft Delete</Text>
          </Pressable>
          <Pressable testID="mock-cancel-trigger" onPress={onCancel}>
            <Text>Cancel</Text>
          </Pressable>
        </View>
      );
    },
  };
});
jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (row: any) =>
    (typeof row === "string" ? row : row?.customer_name || row?.name) || "Unknown Customer",
}));
jest.mock("expo-image", () => ({ Image: () => null }));

// ── setup ────────────────────────────────────────────────────────────
const CUSTOMER = {
  id: "cust-123",
  name: "Jane Test",
  email: "jane@test.com",
  phone: "555-0100",
  address: "1 Test Dr",
  is_active: true,
  has_login: false,
  notes: "",
  pool_gallons: null,
  mobiles: [],
  emails: [],
  properties: [],
};

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiDel.mockReset();
  mockPush.mockReset();
  mockBack.mockReset();

  mockApiGet.mockImplementation((path: string) => {
    if (path.startsWith("/customers/cust-123/credits")) {
      return Promise.resolve({ balance_cents: 0, ledger: [] });
    }
    if (path.startsWith("/customers/cust-123/documents")) {
      return Promise.resolve([]);
    }
    if (path.startsWith("/customers/cust-123/properties")) {
      return Promise.resolve([]);
    }
    if (path.startsWith("/customers/cust-123/jobs")) {
      return Promise.resolve([]);
    }
    if (path.startsWith("/customers/cust-123")) {
      return Promise.resolve(CUSTOMER);
    }
    return Promise.resolve({});
  });
});

describe("Customer Detail · 409 hard-delete toast (Ship 2)", () => {
  it("shows alert with unpaid invoice count on 409 response", async () => {
    const alertSpy = jest.spyOn(Alert, "alert");

    // Make the DELETE call return a 409 with the expected shape
    mockApiDel.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            detail: "customer_has_unpaid_invoices",
            invoice_count: 2,
            invoice_ids: ["inv-1", "inv-2"],
          },
        },
      },
      status: 409,
    });

    const CustomerDetail = require("../app/customer/[id]").default;
    const tree = render(<CustomerDetail />);

    // Wait for customer to load
    await waitFor(() => {
      expect(tree.getByTestId("customer-delete-button")).toBeTruthy();
    });

    // Open the delete modal
    await act(async () => {
      const { fireEvent } = require("@testing-library/react-native");
      fireEvent.press(tree.getByTestId("customer-delete-button"));
    });

    // Wait for modal to appear
    await waitFor(() => {
      expect(tree.getByTestId("customer-delete-modal")).toBeTruthy();
    });

    // Click hard delete
    await act(async () => {
      const { fireEvent } = require("@testing-library/react-native");
      fireEvent.press(tree.getByTestId("mock-hard-delete-trigger"));
    });

    // Wait for the alert to be called
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalled();
    });

    // Find the 409 alert call
    const alertCalls = alertSpy.mock.calls;
    const matchingCall = alertCalls.find(
      (call) =>
        typeof call[1] === "string" &&
        /cannot hard-delete/i.test(call[1]) &&
        call[1].includes("2 unpaid invoice"),
    );
    expect(matchingCall).toBeTruthy();

    alertSpy.mockRestore();
  });
});
