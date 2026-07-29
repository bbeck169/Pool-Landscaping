/**
 * PB1 · Price Book Admin tests.
 *
 * - Wholesale + labor columns visible for admin
 * - Wholesale + labor columns hidden for non-admin (customer, technician)
 * - Edit sheet opens with wholesale + labor inputs for admin
 * - Edit sheet omits wholesale + labor for non-admin
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
}));

const mockGet = jest.fn();
const mockPatch = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    post: jest.fn().mockResolvedValue({ id: "new-item" }),
    patch: (...a: any[]) => mockPatch(...a),
    del: jest.fn().mockResolvedValue({}),
  },
}));

let mockRole = "super_admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: mockRole, name: "Admin" },
  }),
}));

jest.mock("expo-image", () => ({ Image: "Image" }));

jest.mock("@/src/components/ui", () => ({
  Loading: ({ testID }: any) => {
    const { Text } = require("react-native");
    return <Text testID={testID}>Loading</Text>;
  },
  EmptyState: ({ testID }: any) => {
    const { Text } = require("react-native");
    return <Text testID={testID}>Empty</Text>;
  },
  PrimaryButton: ({ title, onPress, testID, disabled }: any) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable testID={testID} onPress={onPress} disabled={disabled}>
        <Text>{title}</Text>
      </Pressable>
    );
  },
  Sheet: ({ visible, children, title, testID }: any) => {
    const { View, Text } = require("react-native");
    if (!visible) return null;
    return (
      <View testID={testID}>
        <Text>{title}</Text>
        {children}
      </View>
    );
  },
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text>{title}</Text>;
  },
  IconButton: ({ onPress, testID }: any) => {
    const { Pressable, Text } = require("react-native");
    return <Pressable testID={testID} onPress={onPress}><Text>+</Text></Pressable>;
  },
}));

jest.mock("@/src/components/ImportExport", () => ({
  ImportExport: () => null,
}));

jest.spyOn(require("react-native").Alert, "alert");

import PriceBook from "@/app/price-book";

const ITEMS = [
  {
    id: "item-1",
    name: "Pool Cleaning",
    category: "Service",
    unit: "each",
    unit_price: 100,
    wholesale_price: 30,
    labor_cost_default: 15,
  },
  {
    id: "item-2",
    name: "Filter Install",
    category: "Service",
    unit: "each",
    unit_price: 250,
    wholesale_price: 80,
    labor_cost_default: 40,
  },
];

describe("PB1 · Price Book Admin", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRole = "super_admin";
    mockGet.mockResolvedValue(ITEMS);
    mockPatch.mockResolvedValue({});
  });

  it("shows wholesale + labor columns for admin role", async () => {
    const { getByTestId } = render(<PriceBook />);
    await waitFor(() => {
      expect(getByTestId("item-wholesale-item-1")).toBeTruthy();
      expect(getByTestId("item-wholesale-item-2")).toBeTruthy();
    });
  }, 15000);

  it("hides wholesale + labor for customer role", async () => {
    mockRole = "customer";
    const { queryByTestId, getByTestId } = render(<PriceBook />);
    await waitFor(() => {
      expect(getByTestId("item-item-1")).toBeTruthy();
    });
    expect(queryByTestId("item-wholesale-item-1")).toBeNull();
  });

  it("hides wholesale + labor for technician role", async () => {
    mockRole = "technician";
    const { queryByTestId, getByTestId } = render(<PriceBook />);
    await waitFor(() => {
      expect(getByTestId("item-item-1")).toBeTruthy();
    });
    expect(queryByTestId("item-wholesale-item-1")).toBeNull();
  });

  it("opens edit sheet with wholesale + labor inputs for admin", async () => {
    const { getByTestId } = render(<PriceBook />);
    await waitFor(() => expect(getByTestId("item-item-1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("item-item-1"));
    });

    await waitFor(() => {
      expect(getByTestId("edit-item-sheet")).toBeTruthy();
      expect(getByTestId("edit-wholesale-price-input")).toBeTruthy();
      expect(getByTestId("edit-labor-cost-input")).toBeTruthy();
      expect(getByTestId("edit-unit-price-input")).toBeTruthy();
    });
  });

  it("edit sheet omits wholesale + labor inputs for technician", async () => {
    mockRole = "technician";
    const { getByTestId, queryByTestId } = render(<PriceBook />);
    await waitFor(() => expect(getByTestId("item-item-1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("item-item-1"));
    });

    await waitFor(() => {
      expect(getByTestId("edit-item-sheet")).toBeTruthy();
      expect(getByTestId("edit-unit-price-input")).toBeTruthy();
    });
    expect(queryByTestId("edit-wholesale-price-input")).toBeNull();
    expect(queryByTestId("edit-labor-cost-input")).toBeNull();
  });

  it("PATCHes item on save with wholesale + labor for admin", async () => {
    const { getByTestId } = render(<PriceBook />);
    await waitFor(() => expect(getByTestId("item-item-1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("item-item-1"));
    });

    await waitFor(() => expect(getByTestId("edit-wholesale-price-input")).toBeTruthy());

    await act(async () => {
      fireEvent.changeText(getByTestId("edit-wholesale-price-input"), "35");
      fireEvent.changeText(getByTestId("edit-labor-cost-input"), "20");
    });

    await act(async () => {
      fireEvent.press(getByTestId("save-edit-button"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/items/item-1",
        expect.objectContaining({ wholesale_price: 35, labor_cost_default: 20 }),
      );
    });
  });

  it("renders retail price for all roles", async () => {
    mockRole = "customer";
    const { getByText } = render(<PriceBook />);
    await waitFor(() => {
      expect(getByText("$100.00")).toBeTruthy();
      expect(getByText("$250.00")).toBeTruthy();
    });
  });
});
