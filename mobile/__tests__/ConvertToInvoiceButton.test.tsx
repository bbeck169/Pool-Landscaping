/**
 * ConvertToInvoiceButton — tests for mobile parity with web f5dd1eb0a.
 *
 * 1. Renders Convert button for admin/manager/owner/super_admin.
 * 2. Does NOT render for technician/customer/dispatcher/null.
 * 3. Converted state → View-invoice link, hides Convert button.
 * 4. 201 handler navigates to invoice.
 * 5. 409 with invoice_id → navigates.
 * 6. 409 without invoice_id → no navigation.
 * 7. Role check is case-insensitive.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import ConvertToInvoiceButton from "@/src/components/quotes/ConvertToInvoiceButton";

/* ── Mocks ─────────────────────────────────────────────────────── */

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), back: jest.fn() }),
}));

const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: { post: (...args: any[]) => mockApiPost(...args) },
}));

const mockShowToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#1B1F5C", surface: "#fff", border: "#ddd",
    success: "#16A34A", warning: "#F59E0B",
    onSurface: "#111", onSurfaceSecondary: "#666", muted: "#999",
    surfaceSecondary: "#f5f5f5", brandTertiary: "#E8E8FF",
    surfaceTertiary: "#eee",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 18, xl: 22 },
}));

/* ── Setup ─────────────────────────────────────────────────────── */
beforeEach(() => {
  jest.clearAllMocks();
  mockApiPost.mockResolvedValue({ invoice_id: "inv-123", invoice_number: "INV-001" });
});

/* ── Tests ──────────────────────────────────────────────────────── */
describe("ConvertToInvoiceButton", () => {
  it("1. renders Convert button for admin/manager/owner/super_admin", () => {
    for (const role of ["admin", "super_admin", "owner", "manager"]) {
      const { queryByTestId, unmount } = render(
        <ConvertToInvoiceButton docType="quote" docId="q1" userRole={role} />,
      );
      expect(queryByTestId("qd-convert-to-invoice")).toBeTruthy();
      expect(queryByTestId("qd-view-converted-invoice")).toBeNull();
      unmount();
    }
  });

  it("2. does NOT render for technician/customer/dispatcher/null", () => {
    for (const role of ["technician", "customer", "dispatcher", null, undefined]) {
      const { queryByTestId, unmount } = render(
        <ConvertToInvoiceButton docType="quote" docId="q1" userRole={role as any} />,
      );
      expect(queryByTestId("qd-convert-to-invoice")).toBeNull();
      expect(queryByTestId("qd-view-converted-invoice")).toBeNull();
      unmount();
    }
  });

  it("3. converted state → View-invoice link, hides Convert button", () => {
    const { queryByTestId, getByTestId } = render(
      <ConvertToInvoiceButton
        docType="quote"
        docId="q1"
        convertedInvoiceId="inv-existing"
        userRole="admin"
      />,
    );
    expect(queryByTestId("qd-convert-to-invoice")).toBeNull();
    expect(getByTestId("qd-view-converted-invoice")).toBeTruthy();
  });

  it("4. 201 handler navigates to invoice", async () => {
    mockApiPost.mockResolvedValue({ invoice_id: "inv-new", invoice_number: "INV-002" });

    const onConverted = jest.fn();
    const { getByTestId } = render(
      <ConvertToInvoiceButton docType="quote" docId="q1" userRole="admin" onConverted={onConverted} />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("qd-convert-to-invoice"));
    });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/quotes/q1/convert-to-invoice", {});
      expect(mockPush).toHaveBeenCalledWith("/quote/inv-new");
      expect(onConverted).toHaveBeenCalledWith("inv-new");
      expect(mockShowToast).toHaveBeenCalledWith("Converted to invoice", "success");
    });
  });

  it("5. 409 with invoice_id → navigates to existing invoice", async () => {
    mockApiPost.mockRejectedValue({
      status: 409,
      body: { detail: { code: "already_converted", invoice_id: "inv-409" } },
    });

    const { getByTestId } = render(
      <ConvertToInvoiceButton docType="quote" docId="q2" userRole="manager" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("qd-convert-to-invoice"));
    });

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/quote/inv-409");
      expect(mockShowToast).toHaveBeenCalledWith("Already converted — opening invoice", "info");
    });
  });

  it("6. 409 without invoice_id → no navigation, warning toast", async () => {
    mockApiPost.mockRejectedValue({
      status: 409,
      body: { detail: { code: "already_converted" } },
    });

    const { getByTestId } = render(
      <ConvertToInvoiceButton docType="estimate" docId="e1" userRole="admin" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("est-convert-to-invoice"));
    });

    await waitFor(() => {
      expect(mockPush).not.toHaveBeenCalled();
      expect(mockShowToast).toHaveBeenCalledWith(
        "This document was already converted to an invoice",
        "warning",
      );
    });
  });

  it("7. role check is case-insensitive", () => {
    for (const role of ["Admin", "SUPER_ADMIN", "Owner", "MANAGER"]) {
      const { queryByTestId, unmount } = render(
        <ConvertToInvoiceButton docType="estimate" docId="e2" userRole={role} />,
      );
      expect(queryByTestId("est-convert-to-invoice")).toBeTruthy();
      unmount();
    }
  });

  it("uses est- prefix for estimate docType testIDs", () => {
    const { queryByTestId } = render(
      <ConvertToInvoiceButton docType="estimate" docId="e3" userRole="admin" />,
    );
    expect(queryByTestId("est-convert-to-invoice")).toBeTruthy();
    expect(queryByTestId("qd-convert-to-invoice")).toBeNull();
  });

  it("shows view-invoice with est- prefix when estimate is converted", () => {
    const { queryByTestId, getByTestId } = render(
      <ConvertToInvoiceButton
        docType="estimate"
        docId="e4"
        convertedInvoiceId="inv-est"
        userRole="owner"
      />,
    );
    expect(queryByTestId("est-convert-to-invoice")).toBeNull();
    expect(getByTestId("est-view-converted-invoice")).toBeTruthy();
  });
});
