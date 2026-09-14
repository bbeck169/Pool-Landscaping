/**
 * Feb-2026 · Phase — Customer Equipment Library (canonical resource).
 *
 * Cases:
 *   1. Renders empty state when API returns no items.
 *   2. Admin sees "Add Equipment" button + can POST via modal.
 *   3. Cards render brand / model / serial / install_date fields.
 *   4. Customer role sees no "Add" button (read-only).
 *   5. Photo upload button POSTs to /api/files/upload with the
 *      customer_equipment linked-entity metadata.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, postSpy, patchSpy, deleteSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
  deleteSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    delete: (...a) => deleteSpy(...a),
    del: (...a) => deleteSpy(...a),
  },
}));

const { uploadSpy, deleteFileSpy } = vi.hoisted(() => ({
  uploadSpy: vi.fn(),
  deleteFileSpy: vi.fn(),
}));

vi.mock("@/api/files", () => ({
  uploadFile: (...a) => uploadSpy(...a),
  deleteFile: (...a) => deleteFileSpy(...a),
  buildAuthedDownloadUrl: (id) => `/api/files/${id}/download?auth=test`,
}));

vi.mock("../../lib/imageCompress", () => ({
  compressImageIfNeeded: async (f) => f,
}));

import CustomerEquipmentLibrary from "@/components/customers/CustomerEquipmentLibrary";

const ADMIN_USER = { id: "u-1", email: "admin@aquaterra.com", role: "admin" };
const TECH_USER = { id: "u-2", email: "tech@aquaterra.com", role: "technician" };
const CUSTOMER_USER = { id: "u-3", email: "cx@aquaterra.com", role: "customer" };

function mockLists({ items = [], types = ["Filter Pump", "Heater"] }) {
  getSpy.mockImplementation((path) => {
    if (path.startsWith("/customer-equipment")) {
      return Promise.resolve({ items, count: items.length });
    }
    if (path.startsWith("/equipment-types")) {
      return Promise.resolve({ types, photo_cap: 4, allowed_tags: [] });
    }
    return Promise.resolve({});
  });
}

describe("CustomerEquipmentLibrary — canonical resource", () => {
  beforeEach(() => {
    getSpy.mockReset();
    postSpy.mockReset();
    patchSpy.mockReset();
    deleteSpy.mockReset();
    uploadSpy.mockReset();
    deleteFileSpy.mockReset();
    window.confirm = vi.fn(() => true);
  });

  it("shows the empty state when no units exist", async () => {
    mockLists({ items: [] });
    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={ADMIN_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("equipment-empty")).toBeInTheDocument()
    );
  });

  it("admins see 'Add Equipment' and POST via the modal", async () => {
    mockLists({ items: [] });
    postSpy.mockResolvedValue({ id: "e-1" });
    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={ADMIN_USER} />);

    await waitFor(() =>
      expect(screen.getByTestId("equipment-add-btn")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("equipment-add-btn"));

    expect(screen.getByTestId("equipment-form-modal")).toBeInTheDocument();
    // Fill in the fields
    fireEvent.change(screen.getByTestId("equipment-type-select"), {
      target: { value: "Filter Pump" },
    });
    fireEvent.change(screen.getByTestId("equipment-brand-input"), {
      target: { value: "Pentair" },
    });
    fireEvent.change(screen.getByTestId("equipment-model-input"), {
      target: { value: "IntelliFlo" },
    });
    fireEvent.change(screen.getByTestId("equipment-serial-input"), {
      target: { value: "SN-42" },
    });

    fireEvent.click(screen.getByTestId("equipment-form-submit"));

    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/customer-equipment");
    expect(body).toMatchObject({
      customer_id: "c-1",
      equipment_type: "Filter Pump",
      brand: "Pentair",
      model: "IntelliFlo",
      serial_number: "SN-42",
    });
  });

  it("renders brand / model / serial / install_date fields on the card", async () => {
    mockLists({
      items: [
        {
          id: "e-9",
          equipment_type: "Heater",
          brand: "Raypak",
          model: "R406A",
          serial_number: "RS-9",
          install_date: "2024-04-01",
          photos: [],
        },
      ],
    });
    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={ADMIN_USER} />);

    await waitFor(() =>
      expect(screen.getByTestId("equipment-card-e-9")).toBeInTheDocument()
    );
    const fields = screen.getByTestId("equipment-card-fields-e-9");
    expect(fields.textContent).toContain("Brand:");
    expect(fields.textContent).toContain("Raypak");
    expect(fields.textContent).toContain("Model:");
    expect(fields.textContent).toContain("R406A");
    expect(fields.textContent).toContain("Serial:");
    expect(fields.textContent).toContain("RS-9");
    expect(fields.textContent).toContain("Installed:");
    expect(fields.textContent).toContain("2024-04-01");
  });

  it("customer role does not see the Add Equipment button", async () => {
    mockLists({ items: [] });
    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={CUSTOMER_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("customer-equipment-library")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("equipment-add-btn")).toBeNull();
  });

  it("tech role can upload a photo via /api/files/upload", async () => {
    mockLists({
      items: [
        {
          id: "e-2",
          equipment_type: "Filter Pump",
          brand: null,
          model: null,
          serial_number: null,
          install_date: null,
          photos: [],
        },
      ],
    });
    uploadSpy.mockResolvedValue({ id: "f-1", url: "/api/files/f-1/download" });

    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={TECH_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("equipment-card-e-2")).toBeInTheDocument()
    );

    const input = screen.getByTestId("equipment-photo-input-e-2");
    const file = new File(["abc"], "photo.jpg", { type: "image/jpeg" });
    Object.defineProperty(input, "files", { value: [file] });
    fireEvent.change(input);

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));
    expect(uploadSpy.mock.calls[0][0]).toMatchObject({
      purpose: "customer_equipment",
      linkedEntityType: "customer_equipment",
      linkedEntityId: "e-2",
    });
  });

  it("customer role does not see the photo upload control", async () => {
    mockLists({
      items: [
        {
          id: "e-3",
          equipment_type: "Filter",
          brand: null,
          model: null,
          serial_number: null,
          install_date: null,
          photos: [],
        },
      ],
    });
    render(<CustomerEquipmentLibrary customerId="c-1" currentUser={CUSTOMER_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("equipment-card-e-3")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("equipment-photo-upload-e-3")).toBeNull();
    expect(screen.queryByTestId("equipment-card-edit-e-3")).toBeNull();
    expect(screen.queryByTestId("equipment-card-delete-e-3")).toBeNull();
  });
});
