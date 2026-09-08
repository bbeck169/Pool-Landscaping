/**
 * Hotfix M3 — D2D customer gate + Zillow enrichment tests.
 *
 * M3-A: Customers-nearby panel — NO-OP (mobile D2D has no customer layer).
 * M3-B: Pull property data button visible for tech + admin, functional.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
const mockApiGet = jest.fn(() => Promise.resolve([]));
const mockApiPost = jest.fn(() => Promise.resolve({}));
const mockApiPut = jest.fn(() => Promise.resolve({}));
const mockApiDel = jest.fn(() => Promise.resolve({}));

jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockApiGet(...args),
    post: (...args: any[]) => mockApiPost(...args),
    put: (...args: any[]) => mockApiPut(...args),
    del: (...args: any[]) => mockApiDel(...args),
  },
}));

jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: jest.fn(() => Promise.resolve("")),
    setItem: jest.fn(() => Promise.resolve()),
  },
}));

jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: jest.fn(() => Promise.resolve({ status: "granted" })),
  requestForegroundPermissionsAsync: jest.fn(() => Promise.resolve({ status: "granted" })),
  getCurrentPositionAsync: jest.fn(() => Promise.resolve({ coords: { latitude: 33.7, longitude: -112.3 } })),
  geocodeAsync: jest.fn(() => Promise.resolve([])),
  Accuracy: { Balanced: 3 },
}));

jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#007AFF", surface: "#fff", surfaceSecondary: "#F5F5F5", surfaceTertiary: "#E8E8E8",
    onSurface: "#000", onSurfaceSecondary: "#666", muted: "#999", border: "#E0E0E0",
    error: "#DC2626", success: "#16A34A",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "2xl": 40, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18, "2xl": 22 },
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ children }: any) => children,
}));

jest.mock("@/src/components/ui", () => ({
  Loading: () => null,
  Sheet: ({ visible, children }: any) => visible ? children : null,
  PrimaryButton: ({ onPress, testID, title }: any) => {
    const { Pressable, Text } = require("react-native");
    return <Pressable onPress={onPress} testID={testID}><Text>{title}</Text></Pressable>;
  },
  EmptyState: () => null,
}));

jest.mock("@/src/components/d2d/MapCanvas", () => () => null);
jest.mock("@/src/components/ZillowUsageChip", () => ({
  ZillowUsageChip: () => null,
  ZillowRateLimitedBanner: () => null,
}));

jest.mock("@/src/components/d2d/dispo", () => ({
  DISPO: {
    not_home: { label: "Not Home", color: "#999", icon: "home-outline" },
    interested: { label: "Interested", color: "#16A34A", icon: "checkmark" },
    sold: { label: "Sold", color: "#7C3AED", icon: "star" },
    not_interested: { label: "Not Interested", color: "#DC2626", icon: "close" },
    callback: { label: "Callback", color: "#F59E0B", icon: "call" },
  },
  ORDER: ["not_home", "interested", "sold", "not_interested", "callback"],
  leadStatusMeta: () => ({ label: "Open", color: "#0284C7" }),
}));

import D2DCanvass from "../app/d2d/index";

/* ── Helpers ───────────────────────────────────────────────────────── */
function setupMocks() {
  mockApiGet.mockImplementation((url: string) => {
    if (url.includes("/d2d/knocks")) return Promise.resolve([
      { id: "k1", address: "123 Palm St", disposition: "interested", lat: 33.7, lng: -112.3 },
      { id: "k2", address: "456 Oak Ave", disposition: "not_home", lat: 33.71, lng: -112.31, zillow_data: { estimated_value: 450000, sqft: 2200, bed_count: 4, bath_count: 3, year_built: 2005 } },
    ]);
    if (url.includes("/d2d/open-leads")) return Promise.resolve({ leads: [] });
    return Promise.resolve([]);
  });
}

/* ── Tests ─────────────────────────────────────────────────────────── */
describe("M3 — D2D customer gate + Zillow enrichment", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupMocks();
  });

  it("does NOT fetch /d2d/customers-nearby (Part A — no-op)", async () => {
    render(<D2DCanvass />);
    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c: any[]) => c[0]);
      expect(calls).not.toContain(expect.stringContaining("customers-nearby"));
    });
  });

  it("shows 'Pull property data' button when editing a knock without zillow_data", async () => {
    const { getByTestId, queryByTestId } = render(<D2DCanvass />);
    // Wait for loading to finish, then switch to doors tab
    await waitFor(() => expect(queryByTestId("d2d-loading")).toBeNull());
    fireEvent.press(getByTestId("d2d-tab-doors"));
    await waitFor(() => expect(queryByTestId("d2d-knock-k1")).toBeTruthy());
    fireEvent.press(getByTestId("d2d-knock-k1"));
    await waitFor(() => {
      expect(getByTestId("d2d-zillow-enrich-btn")).toBeTruthy();
      // Should NOT show data panel (no cached zillow_data on k1)
      expect(queryByTestId("d2d-zillow-data-panel")).toBeNull();
    });
  });

  it("shows cached Zillow data panel for knock with zillow_data", async () => {
    const { getByTestId, queryByTestId } = render(<D2DCanvass />);
    await waitFor(() => expect(queryByTestId("d2d-loading")).toBeNull());
    fireEvent.press(getByTestId("d2d-tab-doors"));
    await waitFor(() => expect(queryByTestId("d2d-knock-k2")).toBeTruthy());
    fireEvent.press(getByTestId("d2d-knock-k2"));
    await waitFor(() => {
      expect(getByTestId("d2d-zillow-enrich-btn")).toBeTruthy();
      expect(getByTestId("d2d-zillow-data-panel")).toBeTruthy();
    });
  });

  it("calls enrichment endpoint on button press", async () => {
    mockApiPost.mockResolvedValueOnce({
      zillow_data: { estimated_value: 500000, sqft: 1800, bed_count: 3, bath_count: 2 },
    });
    const { getByTestId, queryByTestId } = render(<D2DCanvass />);
    await waitFor(() => expect(queryByTestId("d2d-loading")).toBeNull());
    fireEvent.press(getByTestId("d2d-tab-doors"));
    await waitFor(() => expect(queryByTestId("d2d-knock-k1")).toBeTruthy());
    fireEvent.press(getByTestId("d2d-knock-k1"));
    await waitFor(() => expect(getByTestId("d2d-zillow-enrich-btn")).toBeTruthy());
    fireEvent.press(getByTestId("d2d-zillow-enrich-btn"));
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/d2d/prospects/k1/enrich-zillow", {});
    });
  });
});
