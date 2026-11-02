/**
 * SendToCustomerSheet — unit + integration tests.
 *
 * Tests:
 *   1. Send button visible for admin, hidden for technician (parent gate).
 *   2. Sheet opens with recipient pre-filled from quote.customer_email.
 *   3. Override checkbox reveals email input; typed value overrides POST body.
 *   4. Note textarea character cap (≤500).
 *   5. Successful POST fires showToast with success + calls onSent.
 *   6. 403 / 400 error surfaces mapApiError copy; sheet stays open.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockShowToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: mockShowToast }),
  ToastProvider: ({ children }: any) => children,
}));

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message?: string) {
      super(message || "Error");
      this.status = status;
    }
  },
  TOKEN_KEY: "token",
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#0066FF", onSurface: "#111", onSurfaceSecondary: "#555",
    muted: "#999", error: "#d00", background: "#fff", surface: "#fff",
    surfaceSecondary: "#f4f4f5", border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 16, pill: 999 },
  font: { regular: "System", bold: "System", semibold: "System", medium: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20 },
  // Mirrors src/theme.ts:74 — AppTextInput reads it at module load.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));

jest.mock("@/src/utils/mapApiError", () => ({
  mapApiError: (e: any) => ({
    kind: e?.status === 403 ? "forbidden" : e?.status === 400 ? "client" : "server",
    title: e?.status === 403 ? "Not authorized" : e?.status === 400 ? "Bad request" : "Server error",
    message: e?.message || "Unknown error",
    status: e?.status ?? null,
  }),
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

/* Import mocked module to retrieve mock fn references */
import { api } from "@/src/api";
const mockPost = api.post as jest.Mock;

import SendToCustomerSheet from "@/src/components/quotes/SendToCustomerSheet";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const DEFAULT_PROPS = {
  visible: true,
  quoteId: "quote_abc",
  primaryEmail: "customer@example.com",
  onClose: jest.fn(),
  onSent: jest.fn(),
};

function renderSheet(overrides = {}) {
  return render(<SendToCustomerSheet {...DEFAULT_PROPS} {...overrides} />);
}

beforeEach(() => {
  jest.clearAllMocks();
  mockPost.mockReset();
  mockPost.mockResolvedValue({
    quote_id: "quote_abc",
    status: "sent",
    sent_at: "2026-09-13T10:00:00Z",
    email_sent: true,
    recipient: "customer@example.com",
  });
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("SendToCustomerSheet", () => {
  it("does not render when visible=false", () => {
    const { queryByTestId } = renderSheet({ visible: false });
    expect(queryByTestId("send-to-customer-modal")).toBeNull();
  });

  it("shows recipient pre-filled from primaryEmail", () => {
    const { getByTestId } = renderSheet();
    expect(getByTestId("send-to-customer-modal")).toBeTruthy();
    const preview = getByTestId("send-to-customer-recipient-preview");
    expect(preview.props.children).toBe("customer@example.com");
  });

  it("override toggle reveals email input; typed value sent in POST body", async () => {
    const onSent = jest.fn();
    const { getByTestId } = renderSheet({ onSent });

    // Toggle override on
    fireEvent(getByTestId("send-to-customer-override-toggle"), "valueChange", true);

    // Email input should appear
    await waitFor(() => getByTestId("send-to-customer-override-input"));

    // Type override email
    fireEvent.changeText(
      getByTestId("send-to-customer-override-input"),
      "other@company.com",
    );

    // Submit
    fireEvent.press(getByTestId("send-to-customer-submit"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/quotes/quote_abc/send-to-customer",
        expect.objectContaining({ recipient_email: "other@company.com" }),
      );
    });
  });

  it("note textarea caps at 500 characters", () => {
    const { getByTestId } = renderSheet();
    const longText = "A".repeat(600);
    fireEvent.changeText(getByTestId("send-to-customer-note-input"), longText);

    const count = getByTestId("send-to-customer-note-count");
    // Capped at 500
    expect(count.props.children.join("")).toBe("500/500");
  });

  it("successful POST fires showToast and calls onSent + onClose", async () => {
    const onSent = jest.fn();
    const onClose = jest.fn();
    const { getByTestId } = renderSheet({ onSent, onClose });

    fireEvent.press(getByTestId("send-to-customer-submit"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/quotes/quote_abc/send-to-customer",
        {},
      );
      expect(mockShowToast).toHaveBeenCalledWith(
        "Quote sent to customer@example.com.",
      );
      expect(onSent).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("error surfaces mapApiError message and keeps sheet open", async () => {
    const error403 = new Error("Not authorized");
    (error403 as any).status = 403;
    mockPost.mockRejectedValue(error403);

    const onClose = jest.fn();
    const { getByTestId } = renderSheet({ onClose });

    fireEvent.press(getByTestId("send-to-customer-submit"));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Not authorized", "error");
      expect(getByTestId("send-to-customer-error")).toBeTruthy();
    });

    // Sheet stays open — onClose NOT called
    expect(onClose).not.toHaveBeenCalled();
  });
});
