/**
 * Legacy Chemical Readings removal — regression tests.
 *
 * 3 cases:
 *   1. Pool checklist does NOT render the legacy "Chemical Readings" header
 *   2. Pool checklist does NOT render uppercase legacy field labels
 *   3. Structured Chemistry Readings section renders normally
 */
import React from "react";
import { render } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    put: jest.fn().mockResolvedValue({}),
    del: jest.fn().mockResolvedValue({}),
  },
}));

jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));

jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  launchImageLibraryAsync: jest.fn().mockResolvedValue({ canceled: true, assets: null }),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaView: ({ children }: any) => children,
  SafeAreaProvider: ({ children }: any) => children,
}));

jest.mock("react-native-draggable-flatlist", () => {
  const { View: RNView } = require("react-native"); // eslint-disable-line @typescript-eslint/no-require-imports
  return {
    __esModule: true,
    default: ({ data, renderItem }: any) => {
      return <RNView>{(data || []).map((item: any, index: number) => renderItem({ item, drag: () => {}, isActive: false, getIndex: () => index }))}</RNView>;
    },
    ScaleDecorator: ({ children }: any) => children,
  };
});

// eslint-disable-next-line import/first
import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";

// ── Tests ──────────────────────────────────────────────────────────

const SAMPLE_READINGS = [
  { key: "free_chlorine", name: "Free Chlorine", unit: "ppm", value: 2.5 },
  { key: "total_chlorine", name: "Total Chlorine", unit: "ppm", value: 3.0 },
  { key: "ph", name: "pH", unit: "", value: 7.4 },
  { key: "alkalinity", name: "Total Alkalinity", unit: "ppm", value: 80 },
  { key: "cyanuric_acid", name: "Cyanuric Acid", unit: "ppm", value: 40 },
];

const BASE_PROPS = {
  jobId: "job-1",
  customerId: "cust-1",
  locked: false,
  readings: SAMPLE_READINGS,
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["lbs", "gal", "oz", "tabs"],
  checklistItems: [],
  notes: "",
  onChange: jest.fn(),
};

describe("Legacy Chemical Readings removal", () => {
  it("does NOT render the legacy 'Chemical Readings' section title", () => {
    const { queryByText } = render(<PoolChecklistForm {...BASE_PROPS} />);
    // "Chemical Readings" was the legacy header; "Chemistry Readings" is the new one
    expect(queryByText("Chemical Readings")).toBeNull();
  });

  it("does NOT render legacy uppercase reading labels like 'TOTAL CHLORINE (PPM)'", () => {
    const { queryByText } = render(<PoolChecklistForm {...BASE_PROPS} />);
    // Legacy labels used ALL CAPS + unit in parens
    expect(queryByText(/TOTAL CHLORINE \(PPM\)/i)).toBeNull();
    expect(queryByText(/FREE CHLORINE \(PPM\)/i)).toBeNull();
    expect(queryByText(/CYANURIC ACID \(PPM\)/i)).toBeNull();
  });

  it("does NOT render individual ReadingChipRow inputs for flat readings", () => {
    const { queryByTestId } = render(<PoolChecklistForm {...BASE_PROPS} />);
    // ReadingChipRow testids follow the pattern `reading-chip-{key}`
    expect(queryByTestId("reading-chip-free_chlorine")).toBeNull();
    expect(queryByTestId("reading-chip-total_chlorine")).toBeNull();
    expect(queryByTestId("reading-chip-ph")).toBeNull();
    expect(queryByTestId("reading-chip-alkalinity")).toBeNull();
    expect(queryByTestId("reading-chip-cyanuric_acid")).toBeNull();
  });

  it("still renders the pool-checklist-form root testID", () => {
    const { getByTestId } = render(<PoolChecklistForm {...BASE_PROPS} />);
    expect(getByTestId("pool-checklist-form")).toBeTruthy();
  });
});
