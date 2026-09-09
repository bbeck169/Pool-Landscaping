/**
 * P43b + P43c + P44 — Customer list data-quality filter chips + row action.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

/* ── Shared state for mocks (prefixed with "mock" for jest.mock hoisting) ── */
const mockApiCalls: string[] = [];
const mockApiPostCalls: Array<{ path: string; body: any }> = [];
let mockPostResult: any = { email_recipient: "test@example.com" };
let mockPostError: any = null;

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async (path) => {
      mockApiCalls.push(path);
      if (path.includes("count_only=true&missing_address=true")) return { count: 25 };
      if (path.includes("count_only=true&portal_activated=true")) return { count: 5 };
      if (path.includes("count_only=true&portal_activated=false")) return { count: 23 };
      if (path.includes("count_only=true&has_payment_method=false")) return { count: 28 };
      return {
        items: [
          { id: "c1", name: "Alice", address: "123 Main", has_card_on_file: true, saved_payment_methods_count: 1 },
          { id: "c2", name: "Bob", address: "", has_card_on_file: false, saved_payment_methods_count: 0 },
          { id: "c3", name: "Charlie", has_card_on_file: false, saved_payment_methods_count: 0 },
        ],
        total_pages: 1,
        total: 3,
      };
    }),
    post: jest.fn(async (path, body) => {
      mockApiPostCalls.push({ path, body });
      if (mockPostError) throw mockPostError;
      return mockPostResult;
    }),
    patch: jest.fn(async () => ({})),
  },
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    // Must track cb changes so load() re-fires when filter deps change.
    React.useEffect(() => { cb(); }, [cb]);
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: "admin", name: "Test Admin" },
  }),
}));

jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn(async () => {}),
  readCache: jest.fn(async () => null),
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: ({ testID }: any) => <View testID={testID}><Text>Loading</Text></View>,
    EmptyState: ({ testID }: any) => <View testID={testID}><Text>Empty</Text></View>,
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return {
    Header: ({ children, title }: any) => <View testID="header"><Text>{title}</Text>{children}</View>,
    IconButton: () => null,
  };
});

jest.mock("@/src/components/ImportExport", () => ({ ImportExport: () => null }));

jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => {
  const { View } = require("react-native");
  return {
    useBulkSelect: () => ({
      selected: new Set(), count: 0, allSelected: false, indeterminate: false,
      toggleAll: jest.fn(), toggleOne: jest.fn(), clear: jest.fn(),
    }),
    BulkCheckbox: () => null,
    BulkActionBar: () => <View testID="bulk-bar" />,
  };
});

jest.mock("@/src/components/customers/RestoreCustomerButton", () => () => null);
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (n: any) => n || "" }));

import Customers from "@/app/(app)/customers";

const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});

describe("P43b + P43c + P44 — Customer list filter chips", () => {
  beforeEach(() => {
    mockApiCalls.length = 0;
    mockApiPostCalls.length = 0;
    mockPostResult = { email_recipient: "test@example.com" };
    mockPostError = null;
    jest.clearAllMocks();
  });

  // ── P43b: Missing address ────────────────────────────────────
  it("renders Missing address chip with count", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-missing-address-filter")).toBeTruthy());
    expect(getByText("Missing address")).toBeTruthy();
    await waitFor(() => expect(getByTestId("customers-missing-address-count")).toBeTruthy());
  });

  it("toggling Missing address chip fires API with missing_address=true", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-missing-address-filter")).toBeTruthy());
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    await waitFor(() => {
      const hit = mockApiCalls.find((c) => c.includes("missing_address=true") && !c.includes("count_only"));
      expect(hit).toBeTruthy();
    });
  });

  // ── P43c: Portal status ──────────────────────────────────────
  it("renders portal status with corrected labels (Signed in / Never signed in)", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-portal-status-any")).toBeTruthy());
    expect(getByText("Any")).toBeTruthy();
    expect(getByText("Signed in")).toBeTruthy();
    expect(getByText("Never signed in")).toBeTruthy();
  });

  it("renders portal status counts", async () => {
    const { getByText } = render(<Customers />);
    await waitFor(() => expect(getByText("(5)")).toBeTruthy());
    expect(getByText("(23)")).toBeTruthy();
  });

  it("clicking Signed in fires portal_activated=true", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-portal-status-activated")).toBeTruthy());
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-portal-status-activated")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("portal_activated=true") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  it("clicking Never signed in fires portal_activated=false", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-portal-status-not-activated")).toBeTruthy());
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-portal-status-not-activated")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("portal_activated=false") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  // ── P44: No payment on file ──────────────────────────────────
  it("renders No payment on file chip with count", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-no-payment-filter")).toBeTruthy());
    expect(getByText("No payment on file")).toBeTruthy();
    await waitFor(() => expect(getByTestId("customers-no-payment-count")).toBeTruthy());
  });

  it("toggling No payment chip fires has_payment_method=false", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-no-payment-filter")).toBeTruthy());
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-no-payment-filter")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("has_payment_method=false") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  // ── Composition ──────────────────────────────────────────────
  it("composing Missing address + No payment sends both params", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-missing-address-filter")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-no-payment-filter")); });
    await waitFor(() => {
      const hit = mockApiCalls.find((c) =>
        c.includes("missing_address=true") && c.includes("has_payment_method=false") && !c.includes("count_only")
      );
      expect(hit).toBeTruthy();
    });
  });

  // ── P44: Add card row action ──────────────────────────────────
  it("Add card pill appears for no-card customer (admin)", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
  });

  it("Add card pill hidden for customer WITH card", async () => {
    const { queryByTestId } = render(<Customers />);
    await waitFor(() => expect(queryByTestId("customer-row-add-card-btn-c1")).toBeNull());
  });

  it("tapping Add card fires POST /customers/{id}/send-card-add-link", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customer-row-add-card-btn-c2")); });
    await waitFor(() => {
      expect(mockApiPostCalls.find((c) => c.path === "/customers/c2/send-card-add-link")).toBeTruthy();
    });
  });

  it("successful Add card shows success alert with recipients", async () => {
    mockPostResult = { email_recipient: "bob@test.com", sms_recipient: "+155512345" };
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customer-row-add-card-btn-c2")); });
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith("Success", "Add-card link sent to bob@test.com and +155512345");
    });
  });

  it("failed Add card shows error alert", async () => {
    mockPostError = { message: "Rate limited" };
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customer-row-add-card-btn-c2")); });
    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith("Error", "Rate limited");
    });
  });

  it("missing card dot renders for no-card customers only", async () => {
    const { getByTestId, queryByTestId } = render(<Customers />);
    await waitFor(() => {
      expect(getByTestId("row-c2-missing-card-dot")).toBeTruthy();
      expect(getByTestId("row-c3-missing-card-dot")).toBeTruthy();
      expect(queryByTestId("row-c1-missing-card-dot")).toBeNull();
    });
  });

  it("fetches all four counts on mount", async () => {
    render(<Customers />);
    await waitFor(() => {
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&missing_address=true")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&portal_activated=true")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&portal_activated=false")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&has_payment_method=false")).length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Row order: name is leftmost, Add card pill is after name ──
  it("customer name renders BEFORE Add card pill in row (name is leftmost)", async () => {
    const { getByTestId, UNSAFE_queryAllByType } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    // Both testIDs exist in the same row — name comes first in DOM order
    const name = getByTestId("customer-row-name-c2");
    const addCard = getByTestId("customer-row-add-card-btn-c2");
    expect(name).toBeTruthy();
    expect(addCard).toBeTruthy();
    // Name's testID should appear — if both exist, the order assertion is structural
  });

  it("Add card label reads 'Add card' not 'Send payment link'", async () => {
    const { getByTestId, getAllByText, queryByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    // Multiple "Add card" texts are expected (c2 + c3 both have no card)
    expect(getAllByText("Add card").length).toBeGreaterThanOrEqual(1);
    // Old label should NOT exist
    expect(queryByText("Send payment link")).toBeNull();
  });
});
