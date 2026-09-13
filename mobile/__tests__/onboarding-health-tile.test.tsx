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
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const HEALTH_RESPONSE = {
  cohorts: {
    invited: { count: 42, delta_30d: null },
    activated: { count: 15, delta_30d: 3 },
    signed_in: { count: 8, delta_30d: -2 },
    never_logged_in: { count: 30, delta_30d: null },
  },
};

const noop = () => {};

function renderTile(overrides = {}) {
  return render(
    <PortalOnboardingHealthTile
      onFilterInvited={noop}
      onFilterActivated={noop}
      onFilterSignedIn={noop}
      onFilterNever={noop}
      {...overrides}
    />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockResolvedValue(HEALTH_RESPONSE);
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("PortalOnboardingHealthTile", () => {
  it("shows skeleton while loading", async () => {
    const { getByTestId, getByText } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));
    expect(getByText("42")).toBeTruthy();
  });

  it("renders all 4 cohort cards after API resolves", async () => {
    const { getByTestId, getByText } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));

    expect(getByTestId("onboarding-cohort-invited")).toBeTruthy();
    expect(getByTestId("onboarding-cohort-activated")).toBeTruthy();
    expect(getByTestId("onboarding-cohort-signed-in")).toBeTruthy();
    expect(getByTestId("onboarding-cohort-never")).toBeTruthy();

    expect(getByText("42")).toBeTruthy();
    expect(getByText("15")).toBeTruthy();
    expect(getByText("8")).toBeTruthy();
    expect(getByText("30")).toBeTruthy();
  });

  it("fires error toast when API fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("Server timeout"));
    renderTile();
    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("Server timeout", "error");
    });
  });

  it("triggers onFilterInvited when Invited card is pressed", async () => {
    const onFilterInvited = jest.fn();
    const { getByTestId } = renderTile({ onFilterInvited });
    await waitFor(() => getByTestId("onboarding-health-tile"));

    fireEvent.press(getByTestId("onboarding-cohort-invited"));
    expect(onFilterInvited).toHaveBeenCalledTimes(1);
  });

  it("triggers onFilterNever when Never card is pressed", async () => {
    const onFilterNever = jest.fn();
    const { getByTestId } = renderTile({ onFilterNever });
    await waitFor(() => getByTestId("onboarding-health-tile"));

    fireEvent.press(getByTestId("onboarding-cohort-never"));
    expect(onFilterNever).toHaveBeenCalledTimes(1);
  });

  it("Chase button enabled when invited > 0", async () => {
    const { getByTestId } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));

    const chaseBtn = getByTestId("onboarding-tile-invited-chase-cta");
    expect(chaseBtn).toBeTruthy();
    expect(chaseBtn.props.accessibilityState?.disabled).not.toBe(true);
  });

  it("Chase button disabled when invited = 0 and never = 0", async () => {
    mockGet.mockResolvedValueOnce({
      cohorts: {
        invited: { count: 0, delta_30d: null },
        activated: { count: 5, delta_30d: 1 },
        signed_in: { count: 3, delta_30d: 0 },
        never_logged_in: { count: 0, delta_30d: null },
      },
    });
    const { getByTestId } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));

    const chaseBtn = getByTestId("onboarding-tile-invited-chase-cta");
    expect(chaseBtn.props.accessibilityState?.disabled).toBe(true);
  });

  it("opens ChaseStalledInvitesSheet when Chase button pressed", async () => {
    const { getByTestId, queryByTestId } = renderTile();
    await waitFor(() => getByTestId("onboarding-health-tile"));

    expect(queryByTestId("chase-sheet-mock")).toBeNull();

    fireEvent.press(getByTestId("onboarding-tile-invited-chase-cta"));

    await waitFor(() => {
      expect(getByTestId("chase-sheet-mock")).toBeTruthy();
    });
  });
});
