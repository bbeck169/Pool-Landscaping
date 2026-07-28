/**
 * F2b · Invoice/Estimate Attachments — mobile tests
 *
 * Mirrors the web spec structure:
 *   1. InvoiceAttachments renders with FileList
 *   2. Shows FileUpload for admin users
 *   3. Hides FileUpload for customer users
 *   4. canUploadInvoiceAttachment gate logic
 *   5. Renders inside invoice detail page
 *   6. Renders inside estimate detail page
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";
import { View, Text } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────────
jest.mock("@/src/api", () => ({
  api_base: () => "http://test/api",
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/api/files", () => ({
  ...jest.requireActual("@/src/api/files"),
  uploadFile: jest.fn(),
  deleteFile: jest.fn(),
  listFilesByEntity: jest.fn().mockResolvedValue([]),
  buildAuthedDownloadUrl: (id: string, t: string) => `http://test/api/files/${id}/download?auth=${t}`,
}));

jest.mock("expo-image-picker", () => ({
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
}));

jest.mock("expo-document-picker", () => ({
  getDocumentAsync: jest.fn(),
}));

jest.mock("expo-file-system/legacy", () => ({
  cacheDirectory: "/tmp/",
  downloadAsync: jest.fn(),
}));

jest.mock("expo-image", () => ({
  Image: (props: any) => {
    const { View: V } = require("react-native");
    return <V testID={props.testID} />;
  },
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626",
    border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555",
    surfaceSecondary: "#F9FAFB", surfaceTertiary: "#E4E4E7",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 8, md: 12, lg: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24 },
}));

import {
  InvoiceAttachments,
  canUploadInvoiceAttachment,
} from "../src/components/files/InvoiceAttachments";

// ── Tests ─────────────────────────────────────────────────────────

describe("canUploadInvoiceAttachment", () => {
  test("returns true for admin", () => {
    expect(canUploadInvoiceAttachment({ role: "admin" })).toBe(true);
  });
  test("returns true for super_admin", () => {
    expect(canUploadInvoiceAttachment({ role: "super_admin" })).toBe(true);
  });
  test("returns true for manager", () => {
    expect(canUploadInvoiceAttachment({ role: "manager" })).toBe(true);
  });
  test("returns false for customer", () => {
    expect(canUploadInvoiceAttachment({ role: "customer" })).toBe(false);
  });
  test("returns false for technician", () => {
    expect(canUploadInvoiceAttachment({ role: "technician" })).toBe(false);
  });
});

describe("InvoiceAttachments component", () => {
  test("renders with FileList for admin", async () => {
    const user = { role: "admin", name: "Admin" };
    const { getByTestId, getByText } = render(
      <InvoiceAttachments docId="inv-1" isInvoice user={user} />,
    );
    expect(getByTestId("doc-attachments-card")).toBeTruthy();
    expect(getByText(/Attachments/)).toBeTruthy();
    // FileUpload buttons should be visible for admin
    await waitFor(() => {
      expect(getByTestId("file-upload-root")).toBeTruthy();
    });
  }, 15000);

  test("hides FileUpload for customer role", async () => {
    const user = { role: "customer", name: "Cust" };
    const { getByTestId, queryByTestId } = render(
      <InvoiceAttachments docId="inv-2" isInvoice user={user} />,
    );
    expect(getByTestId("doc-attachments-card")).toBeTruthy();
    // FileUpload buttons should NOT appear
    expect(queryByTestId("file-upload-root")).toBeNull();
    // FileList should still appear (loading or empty)
    await waitFor(() => {
      expect(
        queryByTestId("file-list-loading") || queryByTestId("file-list-empty"),
      ).toBeTruthy();
    });
  });

  test("shows estimate label when isInvoice=false", () => {
    const user = { role: "admin" };
    const { getByText } = render(
      <InvoiceAttachments docId="est-1" isInvoice={false} user={user} />,
    );
    expect(getByText(/estimate/)).toBeTruthy();
  });

  test("returns null when docId is empty", () => {
    const user = { role: "admin" };
    const { toJSON } = render(
      <InvoiceAttachments docId="" isInvoice user={user} />,
    );
    expect(toJSON()).toBeNull();
  });
});
