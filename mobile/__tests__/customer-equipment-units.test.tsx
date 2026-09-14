/**
 * Customer Equipment Units — Jest tests.
 *
 * 7 cases:
 *   1. Empty list renders "No equipment recorded yet."
 *   2. Equipment card renders all fields (type, brand, model, serial, install_date)
 *   3. Add Equipment button opens the form modal
 *   4. Form submit posts to POST /api/customer-equipment with correct payload
 *   5. Photo thumbnails render for equipment with photos
 *   6. Delete button opens confirmation modal
 *   7. Confirming delete calls DELETE /api/customer-equipment/{id}
 */
import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();
const mockDel = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
    patch: (...args: any[]) => mockPatch(...args),
    del: (...args: any[]) => mockDel(...args),
  },
}));

jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));

jest.mock("@/src/api/files", () => ({
  uploadFile: jest.fn().mockResolvedValue({ id: "file-1", url: "/files/file-1" }),
  FileRecord: {},
}));

jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  launchImageLibraryAsync: jest.fn().mockResolvedValue({
    canceled: true,
    assets: null,
  }),
}));

jest.mock("expo-image", () => {
  const { View } = require("react-native"); // eslint-disable-line @typescript-eslint/no-require-imports
  return {
    Image: ({ testID, ...props }: any) => {
      return <View testID={testID} {...props} />;
    },
  };
});

// eslint-disable-next-line import/first
import CustomerEquipmentUnits from "@/src/components/customers/CustomerEquipmentUnits";

// ── Helpers ────────────────────────────────────────────────────────
const SAMPLE_UNIT = {
  id: "eq-1",
  equipment_type: "Filter Pump",
  brand: "Pentair",
  model: "IntelliFlo VSF",
  serial_number: "SN-12345",
  install_date: "2024-06-15",
  notes: "Runs great",
  photos: [
    { id: "ph-1", filename: "pump.jpg", content_type: "image/jpeg", url: "/files/ph-1" },
    { id: "ph-2", filename: "plate.jpg", content_type: "image/jpeg", url: "/files/ph-2" },
  ],
};

// ── Tests ──────────────────────────────────────────────────────────
describe("CustomerEquipmentUnits", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    mockDel.mockReset();
  });

  it("renders empty state when API returns no equipment", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });

    const { getByTestId } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-empty")).toBeTruthy();
    });
    expect(mockGet).toHaveBeenCalledWith("/customer-equipment?customer_id=cust-1");
  });

  it("renders card with all fields for an equipment unit", async () => {
    mockGet.mockResolvedValueOnce({ items: [SAMPLE_UNIT] });

    const { getByTestId, getByText } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-card-0")).toBeTruthy();
    });
    expect(getByText("Filter Pump")).toBeTruthy();
    expect(getByText(/Pentair/)).toBeTruthy();
    expect(getByText(/IntelliFlo VSF/)).toBeTruthy();
    expect(getByText(/SN-12345/)).toBeTruthy();
    expect(getByText(/2024-06-15/)).toBeTruthy();
  });

  it("opens Add Equipment form when the add button is pressed", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });

    const { getByTestId } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-add-btn")).toBeTruthy();
    });
    fireEvent.press(getByTestId("equipment-add-btn"));

    await waitFor(() => {
      expect(getByTestId("equipment-form-modal")).toBeTruthy();
      expect(getByTestId("equipment-brand-input")).toBeTruthy();
      expect(getByTestId("equipment-model-input")).toBeTruthy();
      expect(getByTestId("equipment-serial-input")).toBeTruthy();
      expect(getByTestId("equipment-install-date-input")).toBeTruthy();
      expect(getByTestId("equipment-notes-input")).toBeTruthy();
    });
  });

  it("submits correct payload to POST /api/customer-equipment", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });
    mockPost.mockResolvedValueOnce({ id: "new-eq" });
    // After save, reload returns the new item
    mockGet.mockResolvedValueOnce({ items: [{ ...SAMPLE_UNIT, id: "new-eq" }] });

    const { getByTestId } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-add-btn")).toBeTruthy();
    });

    // Open form
    fireEvent.press(getByTestId("equipment-add-btn"));
    await waitFor(() => {
      expect(getByTestId("equipment-brand-input")).toBeTruthy();
    });

    // Open type picker and select "Filter Pump"
    fireEvent.press(getByTestId("equipment-type-picker"));
    await waitFor(() => {
      expect(getByTestId("equipment-type-option-filter-pump")).toBeTruthy();
    });
    fireEvent.press(getByTestId("equipment-type-option-filter-pump"));

    // Fill brand
    fireEvent.changeText(getByTestId("equipment-brand-input"), "Pentair");
    fireEvent.changeText(getByTestId("equipment-model-input"), "IntelliFlo");
    fireEvent.changeText(getByTestId("equipment-serial-input"), "SN-99");
    fireEvent.changeText(getByTestId("equipment-install-date-input"), "2025-01-01");

    // Submit
    fireEvent.press(getByTestId("equipment-form-submit"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/customer-equipment",
        expect.objectContaining({
          customer_id: "cust-1",
          equipment_type: "Filter Pump",
          brand: "Pentair",
          model: "IntelliFlo",
          serial_number: "SN-99",
          install_date: "2025-01-01",
        }),
      );
    });
  });

  it("renders photo thumbnails for equipment with photos", async () => {
    mockGet.mockResolvedValueOnce({ items: [SAMPLE_UNIT] });

    const { getByTestId } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-card-0")).toBeTruthy();
    });
    // 2 photos in SAMPLE_UNIT
    expect(getByTestId("equipment-photo-thumb-0")).toBeTruthy();
    expect(getByTestId("equipment-photo-thumb-1")).toBeTruthy();
  });

  it("opens delete confirmation modal when delete button is pressed", async () => {
    mockGet.mockResolvedValueOnce({ items: [SAMPLE_UNIT] });

    const { getByTestId, getByText } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-delete-btn-0")).toBeTruthy();
    });

    fireEvent.press(getByTestId("equipment-delete-btn-0"));

    await waitFor(() => {
      expect(getByText("Delete equipment?")).toBeTruthy();
      expect(getByTestId("equipment-delete-confirm-btn")).toBeTruthy();
      expect(getByTestId("equipment-delete-cancel-btn")).toBeTruthy();
    });
  });

  it("confirming delete calls DELETE /api/customer-equipment/{id}", async () => {
    mockGet.mockResolvedValueOnce({ items: [SAMPLE_UNIT] });
    mockDel.mockResolvedValueOnce({});
    // After delete, reload returns empty
    mockGet.mockResolvedValueOnce({ items: [] });

    const { getByTestId } = render(
      <CustomerEquipmentUnits customerId="cust-1" />,
    );

    await waitFor(() => {
      expect(getByTestId("equipment-delete-btn-0")).toBeTruthy();
    });

    // Open confirmation
    fireEvent.press(getByTestId("equipment-delete-btn-0"));
    await waitFor(() => {
      expect(getByTestId("equipment-delete-confirm-btn")).toBeTruthy();
    });

    // Confirm delete
    fireEvent.press(getByTestId("equipment-delete-confirm-btn"));

    await waitFor(() => {
      expect(mockDel).toHaveBeenCalledWith("/customer-equipment/eq-1");
    });
  });
});
