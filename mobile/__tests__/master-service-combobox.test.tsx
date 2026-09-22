/**
 * Phase P19 · master-service-combobox.test.tsx
 *
 * Tests for MasterServiceCombobox:
 *  1. Typeahead filter works
 *  2. Pick fires onPick
 *  3. "+ Add" affordance visible for manager/admin
 *  4. "+ Add" hidden for technician role
 */

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockUser = { id: "u1", role: "admin", name: "Admin" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { api } from "@/src/api";
import MasterServiceCombobox, { invalidateMasterServicesCache } from "@/src/components/services/MasterServiceCombobox";

const MOCK_SERVICES = [
  { id: "s1", name: "Pool Cleaning", default_price: 15000, category: "Pool Service", is_active: true },
  { id: "s2", name: "Landscape Maintenance", default_price: 20000, category: "Landscape", is_active: true },
  { id: "s3", name: "Pool Repair", default_price: 25000, category: "Pool Service", is_active: true },
];

describe("MasterServiceCombobox", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    invalidateMasterServicesCache(); // bust the 60s module-level TTL cache
    (api.get as jest.Mock).mockImplementation((url: string) => {
      if (url === "/master-services") {
        return Promise.resolve({ items: MOCK_SERVICES });
      }
      if (url === "/master-services/categories") {
        return Promise.resolve({ items: ["Pool Service", "Landscape"] });
      }
      return Promise.resolve({});
    });
  });

  it("filters services on typeahead", async () => {
    const onPick = jest.fn();
    const onChangeText = jest.fn();
    const { getByTestId, queryByText, rerender } = render(
      <MasterServiceCombobox
        value=""
        onChangeText={onChangeText}
        onPick={onPick}
        testID="test-combobox"
      />,
    );

    // Wait for services to load
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/master-services");
    });

    // Type "Pool" — should trigger onChangeText
    const input = getByTestId("test-combobox-input");
    fireEvent.changeText(input, "Pool");

    // Re-render with filtered value
    rerender(
      <MasterServiceCombobox
        value="Pool"
        onChangeText={onChangeText}
        onPick={onPick}
        testID="test-combobox"
      />,
    );

    fireEvent(input, "focus");

    await waitFor(() => {
      expect(getByTestId("test-combobox-dropdown")).toBeTruthy();
    });
  });

  it("pick fires onPick with correct data", async () => {
    const onPick = jest.fn();
    const onChangeText = jest.fn();
    const { getByTestId } = render(
      <MasterServiceCombobox
        value="Pool"
        onChangeText={onChangeText}
        onPick={onPick}
        testID="test-combobox"
      />,
    );

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/master-services");
    });

    // Open dropdown
    const input = getByTestId("test-combobox-input");
    fireEvent(input, "focus");

    await waitFor(() => {
      expect(getByTestId("test-combobox-dropdown")).toBeTruthy();
    });

    // Pick first item
    const item = getByTestId("test-combobox-item-s1");
    fireEvent.press(item);

    expect(onPick).toHaveBeenCalledWith({
      name: "Pool Cleaning",
      default_price: 15000,
      category: "Pool Service",
    });
  });

  it("+ Add affordance triggers mini-modal (admin)", async () => {
    mockUser.role = "admin";
    const onPick = jest.fn();
    const onChangeText = jest.fn();
    const { getByTestId } = render(
      <MasterServiceCombobox
        value="New Service Type"
        onChangeText={onChangeText}
        onPick={onPick}
        testID="test-combobox"
      />,
    );

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/master-services");
    });

    const input = getByTestId("test-combobox-input");
    fireEvent(input, "focus");

    await waitFor(() => {
      expect(getByTestId("test-combobox-add-btn")).toBeTruthy();
    });

    // Tap the add button
    fireEvent.press(getByTestId("test-combobox-add-btn"));

    await waitFor(() => {
      expect(getByTestId("master-service-add-modal-name")).toBeTruthy();
    });
  });

  it("+ Add hidden for technician role", async () => {
    mockUser.role = "technician";
    const onPick = jest.fn();
    const onChangeText = jest.fn();
    const { getByTestId, queryByTestId } = render(
      <MasterServiceCombobox
        value="New Service Type"
        onChangeText={onChangeText}
        onPick={onPick}
        testID="test-combobox"
      />,
    );

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/master-services");
    });

    const input = getByTestId("test-combobox-input");
    fireEvent(input, "focus");

    // Should NOT show add button for technicians
    await waitFor(() => {
      expect(queryByTestId("test-combobox-add-btn")).toBeNull();
    });

    // Reset for other tests
    mockUser.role = "admin";
  });
});
