/**
 * PortalOnboardingHealthTile — unit + integration tests.
 *
 * Dispatch A, Feature 2.
 *
 * Tests:
 *   1. Renders as admin with cohort cards
 *   2. Shows skeleton while loading
 *   3. Handles error with mapApiError
 *   4. Card press triggers correct filter callback
 *   5. Chase button disabled when audience = 0
 *   6. Chase button opens sheet when audience > 0
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
    brand: "#0066FF", brandTertiary: "#E0F2FE", onSurface: "#111",
    muted: "#999", error: "#d00", background: "#fff", surface: "#fff",
    border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 16 },
  font: { regular: "System", bold: "System", semibold: "System", mono: "monospace" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20, xxl: 24 },
}));

jest.mock("@/src/utils/mapApiError", () => ({
  mapApiError: (e: any) => ({
    kind: "server",
    title: "Server error",
    message: e?.message || "Unknown error",
    status: e?.status ?? null,
  }),
  errorKindIcon: () => "warning-outline",
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("@/src/components/customers/ChaseStalledInvitesSheet", () => {
  const RN = require("react-native");
  const R = require("react");
  return {
    __esModule: true,
    default: (props: any) =>
      props.visible
        ? R.createElement(RN.View, { testID: "chase-sheet-mock" })
        : null,
  };
});

/* Import mocked module to retrieve mock fn references */
import { api } from "@/src/api";
const mockGet = api.get as jest.Mock;

import PortalOnboardingHealthTile from "@/src/components/customers/PortalOnboardingHealthTile";

/* ------------------------------------------------------------------ */
/*  Helpers — Phase 9-M 3-card shape                                   */
/* ------------------------------------------------------------------ */

const HEALTH_RESPONSE = {
  cohorts: {
    invited: { count: 42, delta_30d: null },
    activated: { count: 15, delta_30d: 3 },
    signed_in: { count: 8, delta_30d: -2 },
    never_logged_in: { count: 30, delta_30d: null },
    active_with_card_on_file: { count: 11, delta_30d: 1 },
  },
};

function renderTile(overrides: any = {}) {
  return render(
    <PortalOnboardingHealthTile activeKey={null} onToggle={jest.fn()} {...overrides} />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockResolvedValue(HEALTH_RESPONSE);
});

describe("PortalOnboardingHealthTile (Phase 9-M · 3 cards)", () => {
  it("renders Activated / Signed in / Cards on file after API resolves", async () => {
    const { getByTestId, getByText } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));
    expect(getByTestId("onboarding-cohort-activated")).toBeTruthy();
    expect(getByTestId("onboarding-cohort-signed-in")).toBeTruthy();
    expect(getByTestId("portal-onboarding-cards-on-file-tile")).toBeTruthy();
    expect(getByText("15")).toBeTruthy();
    expect(getByText("8")).toBeTruthy();
    expect(getByText("11")).toBeTruthy();
  });

  it("does NOT render the retired Invited / Never cards or the Chase button", async () => {
    const { getByTestId, queryByTestId, queryByText } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));
    expect(queryByTestId("onboarding-cohort-invited")).toBeNull();
    expect(queryByTestId("onboarding-cohort-never")).toBeNull();
    expect(queryByTestId("onboarding-tile-invited-chase-cta")).toBeNull();
    expect(queryByTestId("chase-sheet-mock")).toBeNull();
    expect(queryByText("42")).toBeNull();
  });

  it("fires error toast when API fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("Server timeout"));
    renderTile();
    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Server timeout", "error");
    });
  });

  it("onToggle receives the tapped tile key", async () => {
    const onToggle = jest.fn();
    const { getByTestId } = renderTile({ onToggle });
    await waitFor(() => getByTestId("onboarding-health-tile"));
    fireEvent.press(getByTestId("onboarding-cohort-activated"));
    fireEvent.press(getByTestId("onboarding-cohort-signed-in"));
    fireEvent.press(getByTestId("portal-onboarding-cards-on-file-tile"));
    expect(onToggle.mock.calls.map((c) => c[0])).toEqual(["activated", "signed_in", "active_with_card_on_file"]);
  });

  it("marks only the active tile as selected", async () => {
    const { getByTestId } = renderTile({ activeKey: "signed_in" });
    await waitFor(() => getByTestId("onboarding-health-tile"));
    expect(getByTestId("onboarding-cohort-signed-in").props.accessibilityState).toEqual({ selected: true });
    expect(getByTestId("onboarding-cohort-activated").props.accessibilityState).toEqual({ selected: false });
    expect(getByTestId("portal-onboarding-cards-on-file-tile").props.accessibilityState).toEqual({ selected: false });
  });
});
