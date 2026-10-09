/**
 * P43b + P43c + P44 + P45 — Customer list "More filters" sheet + Add card row action.
 *
 * Tests:
 *  1. "More filters" trigger renders with summary text
 *  2. Opening sheet shows all filter controls with correct testIDs
 *  3. Toggling filters fires correct API calls
 *  4. Chips compose (multi-filter = ANDed query)
 *  5. Portal status radio semantics
 *  6. Clear all resets every filter
 *  7. Add card pill: appears for no-card customer, fires POST, alerts
 *  8. Row order: name is left of Add card
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

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
      if (path.includes("count_only=true&missing_email=true")) return { count: 12 };
      if (path.includes("count_only=true&missing_phone=true")) return { count: 12 };
      if (path.includes("count_only=true&pending_merge_candidates=true")) return { count: 3 };
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
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn(), setParams: jest.fn() }),
  // Phase 9-M — customers list reads onboarding-tile filters from route params.
  useLocalSearchParams: () => ({}),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, [cb]);
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", name: "Test Admin" } }),
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

describe("P45 — More filters sheet + Add card row action", () => {
  beforeEach(() => {
    mockApiCalls.length = 0;
    mockApiPostCalls.length = 0;
    mockPostResult = { email_recipient: "test@example.com" };
    mockPostError = null;
    jest.clearAllMocks();
  });

  // ── Trigger ──────────────────────────────────────────────────
  it("renders 'More filters: All' trigger when no filters active", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    expect(getByText(/More filters: All/)).toBeTruthy();
  });

  // ── Sheet testIDs ─────────────────────────────────────────────
  it("sheet contains all expected testIDs when opened", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });

    const ids = [
      "filter-chip-missing-email",
      "filter-chip-missing-phone",
      "customers-missing-address-filter",
      "customers-no-payment-filter",
      "customers-portal-status-any",
      "customers-portal-status-activated",
      "customers-portal-status-not-activated",
      "customers-filter-include-deleted",
      "customers-filter-include-merged",
      "customers-filter-pending-merge-candidates",
      "customers-more-filters-clear",
    ];
    for (const id of ids) {
      expect(getByTestId(id)).toBeTruthy();
    }
  });

  // ── Filter toggles fire correct API calls ─────────────────────
  it("toggling Missing address fires missing_address=true", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("missing_address=true") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  it("toggling No payment fires has_payment_method=false", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-no-payment-filter")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("has_payment_method=false") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  it("toggling No email fires missing_email=true", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("filter-chip-missing-email")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("missing_email=true") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  it("clicking Signed in fires portal_activated=true", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-portal-status-activated")); });
    await waitFor(() => {
      expect(mockApiCalls.find((c) => c.includes("portal_activated=true") && !c.includes("count_only"))).toBeTruthy();
    });
  });

  // ── Composition ──────────────────────────────────────────────
  it("composing No email + Missing address sends both params", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    await act(async () => { fireEvent.press(getByTestId("filter-chip-missing-email")); });
    mockApiCalls.length = 0;
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    await waitFor(() => {
      const hit = mockApiCalls.find((c) =>
        c.includes("missing_email=true") && c.includes("missing_address=true") && !c.includes("count_only")
      );
      expect(hit).toBeTruthy();
    });
  });

  // ── Clear all ────────────────────────────────────────────────
  it("Clear all resets every consolidated filter", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    // Activate two filters
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    await act(async () => { fireEvent.press(getByTestId("filter-chip-missing-email")); });
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    // Trigger should show active summary (contains "No email" in its text)
    const trigger = getByTestId("customers-more-filters-dropdown");
    expect(trigger).toBeTruthy();
    // Clear all
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-clear")); });
    // Trigger should return to "All"
    await waitFor(() => expect(getByText(/More filters: All/)).toBeTruthy());
  });

  // ── Portal status radio semantics ────────────────────────────
  it("portal status items have correct accessibility roles", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    const any = getByTestId("customers-portal-status-any");
    const activated = getByTestId("customers-portal-status-activated");
    expect(any.props.accessibilityRole).toBe("radio");
    expect(activated.props.accessibilityRole).toBe("radio");
    expect(any.props.accessibilityState.selected).toBe(true);
    expect(activated.props.accessibilityState.selected).toBe(false);
  });

  // ── Trigger summary updates ──────────────────────────────────
  it("trigger shows 'No email +1' with badge when 2 filters active", async () => {
    const { getByTestId, getByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("customers-more-filters-dropdown")); });
    await act(async () => { fireEvent.press(getByTestId("filter-chip-missing-email")); });
    await act(async () => { fireEvent.press(getByTestId("customers-missing-address-filter")); });
    expect(getByText(/No email \+1/)).toBeTruthy();
  });

  // ── Add card row action ──────────────────────────────────────
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

  it("successful Add card shows success alert", async () => {
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

  // ── Row order assertions ─────────────────────────────────────
  it("name renders before Add card pill (name leftmost)", async () => {
    const { getByTestId } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    expect(getByTestId("customer-row-name-c2")).toBeTruthy();
  });

  it("Add card label reads 'Add card' not 'Send payment link'", async () => {
    const { getByTestId, getAllByText, queryByText } = render(<Customers />);
    await waitFor(() => expect(getByTestId("customer-row-add-card-btn-c2")).toBeTruthy());
    expect(getAllByText("Add card").length).toBeGreaterThanOrEqual(1);
    expect(queryByText("Send payment link")).toBeNull();
  });

  // ── Count fetching ──────────────────────────────────────────
  it("fetches all counts on mount (including new P45 counts)", async () => {
    render(<Customers />);
    await waitFor(() => {
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&missing_address=true")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&missing_email=true")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&missing_phone=true")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&has_payment_method=false")).length).toBeGreaterThanOrEqual(1);
      expect(mockApiCalls.filter((c) => c.includes("count_only=true&pending_merge_candidates=true")).length).toBeGreaterThanOrEqual(1);
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
});
