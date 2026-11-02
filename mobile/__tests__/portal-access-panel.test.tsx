/**
 * PortalAccessPanel — unit + integration tests.
 *
 * Dispatch B, Feature 3.
 *
 * Tests:
 *   1. Renders panel for admin with status row
 *   2. Hidden / not rendered for technician (parent gates)
 *   3. Send invite fires POST /customers/{id}/portal-invite
 *   4. Reset password modal opens and submits (auto mode)
 *   5. Reset password modal — explicit mode with password
 *   6. Revoke access confirmation Alert fires endpoint
 *   7. Send reset link confirmation Alert fires endpoint
 *   8. Copy reset link fires endpoint + clipboard (super_admin)
 *   9. Temp password card renders with Copy button
 *  10. mapApiError on 403 / 500 shows error toast
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

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
    brand: "#0066FF", brandTertiary: "#E0F2FE", onBrandTertiary: "#0369A1",
    onSurface: "#111", onSurfaceSecondary: "#555",
    muted: "#999", error: "#d00", background: "#fff", surface: "#fff",
    surfaceSecondary: "#f4f4f5", border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 16, pill: 999 },
  font: { regular: "System", bold: "System", semibold: "System", medium: "System", mono: "monospace" },
  fontSize: { xs: 10, sm: 12, base: 14, md: 14, lg: 16, xl: 20, xxl: 24 },
  // Mirrors src/theme.ts:74 — AppTextInput reads it at module load.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));

jest.mock("@/src/utils/mapApiError", () => ({
  mapApiError: (e: any) => ({
    kind: e?.status === 403 ? "forbidden" : "server",
    title: e?.status === 403 ? "Not authorized" : "Server error",
    message: e?.message || "Unknown error",
    status: e?.status ?? null,
  }),
  errorKindIcon: () => "warning-outline",
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("expo-clipboard", () => ({
  setStringAsync: jest.fn().mockResolvedValue(true),
}));

/* Import mocked module to retrieve mock fn references */
import { api } from "@/src/api";
const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;

import * as Clipboard from "expo-clipboard";
const mockClipboard = Clipboard.setStringAsync as jest.Mock;

import PortalAccessPanel from "@/src/components/customers/PortalAccessPanel";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STATUS_RESPONSE = {
  has_login: true,
  active: true,
  email: "john@example.com",
  last_portal_login_at: "2026-09-10T14:30:00Z",
  last_portal_login_ip: "192.168.1.1",
};

const HISTORY_RESPONSE = {
  events: [
    { id: "h1", event: "portal_login", created_at: "2026-09-10T14:30:00Z" },
    { id: "h2", event: "portal_reset", actor_email: "admin@co.com", created_at: "2026-09-09T10:00:00Z" },
  ],
};

const DEFAULT_PROPS = {
  customerId: "cust_123",
  customerEmail: "john@example.com",
  customerName: "John Doe",
  hasLogin: true,
  userRole: "admin",
  onRefresh: jest.fn(),
};

function renderPanel(overrides = {}) {
  return render(<PortalAccessPanel {...DEFAULT_PROPS} {...overrides} />);
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockReset();
  mockPost.mockReset();
  mockClipboard.mockReset().mockResolvedValue(true);
  mockGet.mockImplementation((url: string) => {
    if (url.includes("portal-status")) return Promise.resolve(STATUS_RESPONSE);
    if (url.includes("portal-history")) return Promise.resolve(HISTORY_RESPONSE);
    return Promise.resolve({});
  });
  mockPost.mockResolvedValue({ emailed: true, email: "john@example.com" });
  jest.spyOn(Alert, "alert");
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("PortalAccessPanel", () => {
  it("renders panel with status row and activity feed", async () => {
    const { getByTestId, getByText } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    expect(getByTestId("portal-status-row")).toBeTruthy();
    expect(getByTestId("portal-status-email")).toBeTruthy();
    expect(getByTestId("portal-status-active")).toBeTruthy();
    expect(getByTestId("portal-last-login")).toBeTruthy();
    expect(getByTestId("portal-history-list")).toBeTruthy();
    expect(getByText("Customer signed in")).toBeTruthy();
  });

  it("shows revoked badge when portal is revoked", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes("portal-status")) return Promise.resolve({ ...STATUS_RESPONSE, active: false });
      if (url.includes("portal-history")) return Promise.resolve(HISTORY_RESPONSE);
      return Promise.resolve({});
    });
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    expect(getByTestId("portal-status-revoked")).toBeTruthy();
  });

  it("sends invite via POST /customers/{id}/portal-invite", async () => {
    const onRefresh = jest.fn();
    const { getByTestId } = renderPanel({ onRefresh });
    await waitFor(() => getByTestId("portal-access-panel"));

    fireEvent.press(getByTestId("portal-send-invite-btn"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-invite");
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.stringContaining("Portal invite sent"),
      );
      expect(onRefresh).toHaveBeenCalled();
    });
  });

  it("opens reset modal and submits auto mode", async () => {
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    // Open reset modal
    fireEvent.press(getByTestId("portal-reset-password-btn"));
    await waitFor(() => getByTestId("portal-reset-modal"));

    // Auto mode is selected by default — submit
    fireEvent.press(getByTestId("portal-reset-submit-btn"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-reset", {});
    });
  });

  it("opens reset modal and submits explicit password", async () => {
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    fireEvent.press(getByTestId("portal-reset-password-btn"));
    await waitFor(() => getByTestId("portal-reset-modal"));

    // Switch to explicit mode
    fireEvent.press(getByTestId("portal-reset-mode-explicit"));
    await waitFor(() => getByTestId("portal-reset-password-input"));

    // Type password
    fireEvent.changeText(getByTestId("portal-reset-password-input"), "NewPass123");

    // Submit
    fireEvent.press(getByTestId("portal-reset-submit-btn"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-reset", { password: "NewPass123" });
    });
  });

  it("shows confirmation Alert on revoke and fires endpoint", async () => {
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    fireEvent.press(getByTestId("portal-revoke-btn"));

    expect(Alert.alert).toHaveBeenCalledWith(
      "Revoke portal access?",
      expect.stringContaining("lock"),
      expect.any(Array),
    );

    // Simulate pressing "Revoke" in the alert
    const alertCall = (Alert.alert as jest.Mock).mock.calls[0];
    const revokeBtn = alertCall[2].find((b: any) => b.text === "Revoke");
    expect(revokeBtn).toBeTruthy();

    await act(async () => {
      await revokeBtn.onPress();
    });

    expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-revoke");
    expect(mockShowToast).toHaveBeenCalledWith("Portal access revoked");
  });

  it("shows confirmation Alert on send reset link and fires endpoint", async () => {
    mockPost.mockResolvedValueOnce({ sent_to: "john@example.com" });
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    fireEvent.press(getByTestId("portal-send-reset-link-btn"));

    expect(Alert.alert).toHaveBeenCalledWith(
      "Send password reset link?",
      expect.stringContaining("reset"),
      expect.any(Array),
    );

    // Simulate pressing "Send reset link"
    const alertCall = (Alert.alert as jest.Mock).mock.calls[0];
    const sendBtn = alertCall[2].find((b: any) => b.text === "Send reset link");
    await act(async () => {
      await sendBtn.onPress();
    });

    expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-reset-link");
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.stringContaining("Reset link sent"),
    );
  });

  it("copy reset link visible for super_admin and fires endpoint + clipboard", async () => {
    mockPost.mockResolvedValue({ reset_url: "https://example.com/reset/abc123", token_ttl_minutes: 30 });
    const { getByTestId } = renderPanel({ userRole: "super_admin" });
    await waitFor(() => getByTestId("portal-access-panel"));

    // Copy reset link button should exist for super_admin
    const copyBtn = getByTestId("portal-copy-reset-link-btn");
    expect(copyBtn).toBeTruthy();

    fireEvent.press(copyBtn);

    // Simulate confirming the Alert
    const alertCall = (Alert.alert as jest.Mock).mock.calls[0];
    const confirmBtn = alertCall[2].find((b: any) => b.text === "Generate and copy");
    await act(async () => {
      await confirmBtn.onPress();
    });

    expect(mockPost).toHaveBeenCalledWith("/customers/cust_123/portal-reset-link-copy");
    await waitFor(() => {
      expect(mockClipboard).toHaveBeenCalledWith("https://example.com/reset/abc123");
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.stringContaining("Link copied"),
        "info",
      );
    });
  });

  it("copy reset link NOT visible for regular admin", async () => {
    const { getByTestId, queryByTestId } = renderPanel({ userRole: "admin" });
    await waitFor(() => getByTestId("portal-access-panel"));

    expect(queryByTestId("portal-copy-reset-link-btn")).toBeNull();
  });

  it("shows temp password card when invite returns password", async () => {
    mockPost.mockReset();
    mockPost.mockResolvedValue({
      password: "TmpPass99",
      login_url: "https://portal.example.com/login",
      email: "john@example.com",
    });
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    // Press send invite
    fireEvent.press(getByTestId("portal-send-invite-btn"));

    await waitFor(() => {
      expect(getByTestId("portal-temp-password-card")).toBeTruthy();
      expect(getByTestId("portal-temp-password-value")).toBeTruthy();
      expect(getByTestId("portal-temp-login-url")).toBeTruthy();
      expect(getByTestId("portal-copy-temp-password-btn")).toBeTruthy();
    });

    // Press copy
    fireEvent.press(getByTestId("portal-copy-temp-password-btn"));
    await waitFor(() => {
      expect(mockClipboard).toHaveBeenCalledWith("TmpPass99");
      expect(mockShowToast).toHaveBeenCalledWith("Copied to clipboard", "info");
    });
  });

  it("shows error toast via mapApiError on 403", async () => {
    const error403 = new Error("Not authorized");
    (error403 as any).status = 403;
    mockPost.mockReset();
    mockPost.mockRejectedValue(error403);
    const { getByTestId } = renderPanel();
    await waitFor(() => getByTestId("portal-access-panel"));

    fireEvent.press(getByTestId("portal-send-invite-btn"));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Not authorized", "error");
    });
  });
});
