/**
 * ChaseStalledInvitesSheet — unit + integration tests.
 *
 * Dispatch A, Feature 1.
 *
 * Tests:
 *   1. Does not render when visible=false
 *   2. Fetches preview list when visible
 *   3. Fires correct endpoint on send
 *   4. Shows success toast on send
 *   5. Shows summary after send
 *   6. mapApiError on failure
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ------------------------------------------------------------------ */
/*  Mocks — use inline jest.fn() to avoid TDZ hoisting issues         */
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
    brand: "#0066FF", onSurface: "#111", muted: "#999",
    error: "#d00", background: "#fff", surface: "#fff", border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 16 },
  font: { regular: "System", bold: "System", semibold: "System", mono: "monospace" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20, xxl: 24 },
}));

jest.mock("@/src/utils/mapApiError", () => ({
  mapApiError: (e: any) => ({
    kind: e?.status === 429 ? "client" : "server",
    title: e?.status === 429 ? "Rate limited" : "Server error",
    message: e?.message || "Unknown error",
    status: e?.status ?? null,
  }),
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

/* Import mocked module to retrieve mock fn references */
import { api } from "@/src/api";
const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;

import ChaseStalledInvitesSheet from "@/src/components/customers/ChaseStalledInvitesSheet";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const STALLED_CUSTOMERS = [
  { id: "c1", name: "Robert Blake", email: "rb@example.com" },
  { id: "c2", name: "Maria Gomez", email: "mg@example.com" },
  { id: "c3", name: "Jane Doe", email: "jd@example.com" },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockResolvedValue(STALLED_CUSTOMERS);
  mockPost.mockResolvedValue({
    enqueued: 3,
    rate_limited: [],
    failed: [],
  });
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("ChaseStalledInvitesSheet", () => {
  it("does not render when visible=false", () => {
    const { queryByTestId } = render(
      <ChaseStalledInvitesSheet visible={false} onClose={jest.fn()} />,
    );
    expect(queryByTestId("chase-stalled-invites-modal")).toBeNull();
  });

  it("renders and loads preview list when visible", async () => {
    const { getByText } = render(
      <ChaseStalledInvitesSheet visible={true} onClose={jest.fn()} />,
    );

    await waitFor(() => {
      expect(getByText("Robert Blake")).toBeTruthy();
      expect(getByText("Maria Gomez")).toBeTruthy();
    });

    expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining("portal_invited=any"),
    );
    expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining("first_access=never"),
    );
    expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining("sort=stalest_first"),
    );
  });

  it("fires POST /admin/customers/portal-invite/bulk on send", async () => {
    const onClose = jest.fn();
    const { getByTestId, getByText } = render(
      <ChaseStalledInvitesSheet visible={true} onClose={onClose} />,
    );

    await waitFor(() => getByText("Robert Blake"));

    fireEvent.press(getByTestId("chase-invites-send-btn"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/admin/customers/portal-invite/bulk",
        expect.objectContaining({
          customer_ids: ["c1", "c2", "c3"],
          reason: "chase_stalled_invites",
        }),
      );
    });
  });

  it("shows success toast after send", async () => {
    const { getByTestId, getByText } = render(
      <ChaseStalledInvitesSheet visible={true} onClose={jest.fn()} />,
    );

    await waitFor(() => getByText("Robert Blake"));
    fireEvent.press(getByTestId("chase-invites-send-btn"));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Sent 3 portal invites.");
    });
  });

  it("shows summary phase after send", async () => {
    const { getByTestId, getByText } = render(
      <ChaseStalledInvitesSheet visible={true} onClose={jest.fn()} />,
    );

    await waitFor(() => getByText("Robert Blake"));
    fireEvent.press(getByTestId("chase-invites-send-btn"));

    await waitFor(() => {
      expect(getByTestId("chase-invites-summary")).toBeTruthy();
      expect(getByTestId("chase-invites-summary-enqueued")).toBeTruthy();
      expect(getByText("Sent 3")).toBeTruthy();
      expect(getByText("Rate-limited 0")).toBeTruthy();
      expect(getByText("Failed 0")).toBeTruthy();
    });
  });

  it("shows error toast when send fails", async () => {
    mockPost.mockRejectedValueOnce({ status: 429, message: "Too many requests" });
    const { getByTestId, getByText } = render(
      <ChaseStalledInvitesSheet visible={true} onClose={jest.fn()} />,
    );

    await waitFor(() => getByText("Robert Blake"));
    fireEvent.press(getByTestId("chase-invites-send-btn"));

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Too many requests", "error");
    });
  });
});
