/**
 * Guard test — Expo Web chemistry UI trim.
 *
 * Asserts:
 *  1. The "Chemicals Used" block does NOT render on web.
 *  2. The "Chemical Readings" heading does NOT render on web.
 *  3. The yellow classify prompt DOES render on web (when template is generic).
 *  4. Native (non-web) still renders both removed sections.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { Platform } from "react-native";

/* ── Minimal mocks ─────────────────────────────────────────────────── */

// Mock theme
jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#2563EB", muted: "#9CA3AF", onSurface: "#111827",
    error: "#EF4444", surface: "#FFFFFF", border: "#E5E7EB",
    surfaceSecondary: "#F9FAFB", warning: "#F59E0B",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 12 },
  font: { regular: "System", medium: "System", bold: "System" },
  fontSize: { xs: 11, sm: 13, md: 15, lg: 18, xl: 22 },
  money: (v: number) => `$${(v || 0).toFixed(2)}`,
}));

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: (p: any) => <Text>{p.name}</Text> };
});

jest.mock("@/src/lib/waterBodies", () => ({
  BODY_TYPE_LABELS: { pool: "Pool" },
  BODY_TYPE_TINTS: { pool: { bg: "#EFF6FF", fg: "#1D4ED8", border: "#BFDBFE" } },
  READING_ALLOWLIST: { pool: ["free_chlorine"] },
  READING_LABELS: { free_chlorine: { name: "Free Chlorine", unit: "ppm", short: "FC" } },
  READING_REQUIRED: { pool: ["free_chlorine"] },
  CHEMICAL_ALLOWLIST: { pool: ["trichlor_tabs", "muriatic_acid"] },
  CHEMICAL_LABELS: {
    trichlor_tabs: { name: "Trichlor Tabs", unit: "tabs" },
    muriatic_acid: { name: "Muriatic Acid", unit: "oz" },
  },
}));

// Minimal mock for PoolChecklistForm deps
jest.mock("expo-image-picker", () => ({ launchImageLibraryAsync: jest.fn() }));
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
    put: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    delete: jest.fn().mockResolvedValue({}),
  },
}));
jest.mock("@/src/components/checklist/ReadingChipRow", () => {
  const { View, Text } = require("react-native");
  return { __esModule: true, default: (p: any) => <View><Text>ReadingChipRow</Text></View> };
});
jest.mock("@/src/lib/expandChemistryLabel", () => ({
  expandChemistryLabel: (s: string) => s,
}));
jest.mock("@/src/components/checklist/ChemicalDropdownStack", () => {
  const { View, Text } = require("react-native");
  const C = (p: any) => <View><Text>ChemicalDropdownStack</Text></View>;
  C.snapRecommendationToPreset = jest.fn();
  return { __esModule: true, default: C, snapRecommendationToPreset: jest.fn() };
});
jest.mock("@/src/components/checklist/ChemicalPickerSheet", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View /> };
});
jest.mock("react-native-draggable-flatlist", () => {
  const { View } = require("react-native");
  const D = (p: any) => <View>{(p.data || []).map((item: any, i: number) => p.renderItem({ item, drag: jest.fn(), isActive: false, getIndex: () => i }))}</View>;
  const ScaleDecorator = (p: any) => <View>{p.children}</View>;
  return { __esModule: true, default: D, ScaleDecorator };
});

/* ── Import components under test ──────────────────────────────────── */

import WaterBodyPanel from "@/src/components/checklist/WaterBodyPanel";
import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";

/* ── Helpers ────────────────────────────────────────────────────────── */

const makeBody = () => ({
  id: "b1",
  type: "pool" as const,
  label: "Backyard Pool",
  readings: [],
  chemicals_used: [{ product_slug: "trichlor_tabs", amount: 3, unit: "tabs", product_name: "Trichlor Tabs" }],
  notes: "",
});

/* ── Tests ──────────────────────────────────────────────────────────── */

describe("Chemistry UI trim — Expo Web", () => {
  const ORIG_OS = Platform.OS;

  afterEach(() => {
    Object.defineProperty(Platform, "OS", { value: ORIG_OS, writable: true });
  });

  /* ━━ WaterBodyPanel ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

  it("WaterBodyPanel on WEB does NOT render 'Chemicals Used' block", () => {
    Object.defineProperty(Platform, "OS", { value: "web", writable: true });
    const { queryByText, queryByTestId } = render(
      <WaterBodyPanel
        body={makeBody()}
        index={0}
        locked={false}
        canRemove={false}
        onChange={jest.fn()}
        onRemove={jest.fn()}
      />
    );
    expect(queryByText("Chemicals Used")).toBeNull();
    expect(queryByText("Add chemical")).toBeNull();
    expect(queryByTestId("chem-row-0-0")).toBeNull();
    expect(queryByTestId("add-chemical-0")).toBeNull();
  });

  it("WaterBodyPanel on WEB still renders 'Chemistry Readings' and 'Notes'", () => {
    Object.defineProperty(Platform, "OS", { value: "web", writable: true });
    const { getByText } = render(
      <WaterBodyPanel
        body={makeBody()}
        index={0}
        locked={false}
        canRemove={false}
        onChange={jest.fn()}
        onRemove={jest.fn()}
      />
    );
    expect(getByText("Chemistry Readings")).toBeTruthy();
    expect(getByText("Notes")).toBeTruthy();
  });

  it("WaterBodyPanel on NATIVE renders 'Chemicals Used' block", () => {
    Object.defineProperty(Platform, "OS", { value: "ios", writable: true });
    const { getByText, getByTestId } = render(
      <WaterBodyPanel
        body={makeBody()}
        index={0}
        locked={false}
        canRemove={false}
        onChange={jest.fn()}
        onRemove={jest.fn()}
      />
    );
    expect(getByText("Chemicals Used")).toBeTruthy();
    expect(getByTestId("chem-row-0-0")).toBeTruthy();
  });

  /* ━━ PoolChecklistForm ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */

  it("PoolChecklistForm on WEB does NOT render 'Chemical Readings' heading", () => {
    Object.defineProperty(Platform, "OS", { value: "web", writable: true });
    const { queryByText } = render(
      <PoolChecklistForm
        jobId="test-job"
        customerId="cust-1"
        locked={false}
        readings={[]}
        readingFields={[]}
        chemicalsAdded={[]}
        chemicalsCatalog={[]}
        chemicalUnits={["oz", "lbs"]}
        checklistItems={[]}
        notes=""
        observations={{}}
        onChange={jest.fn()}
        template="generic"
        canEditServiceType={true}
        onReclassify={jest.fn()}
      />
    );
    // The heading "Chemical Readings" must NOT appear
    expect(queryByText("Chemical Readings")).toBeNull();
  });

  it("PoolChecklistForm on WEB still renders the yellow classify prompt when template=generic", () => {
    Object.defineProperty(Platform, "OS", { value: "web", writable: true });
    const { getByTestId, getByText } = render(
      <PoolChecklistForm
        jobId="test-job"
        customerId="cust-1"
        locked={false}
        readings={[]}
        readingFields={[]}
        chemicalsAdded={[]}
        chemicalsCatalog={[]}
        chemicalUnits={["oz", "lbs"]}
        checklistItems={[]}
        notes=""
        observations={{}}
        onChange={jest.fn()}
        template="generic"
        canEditServiceType={true}
        onReclassify={jest.fn()}
      />
    );
    // Yellow classify prompt must still be visible
    expect(getByTestId("pool-service-type-picker-block")).toBeTruthy();
    expect(getByText(/Set its Service Type to enable chemical readings/)).toBeTruthy();
    // Pills must be present
    expect(getByTestId("pool-service-type-set-pool-service")).toBeTruthy();
    expect(getByTestId("pool-service-type-set-landscape-service")).toBeTruthy();
    expect(getByTestId("pool-service-type-set-other")).toBeTruthy();
  });

  it("PoolChecklistForm on NATIVE renders 'Chemical Readings' heading", () => {
    Object.defineProperty(Platform, "OS", { value: "ios", writable: true });
    const { getByText } = render(
      <PoolChecklistForm
        jobId="test-job"
        customerId="cust-1"
        locked={false}
        readings={[]}
        readingFields={[]}
        chemicalsAdded={[]}
        chemicalsCatalog={[]}
        chemicalUnits={["oz", "lbs"]}
        checklistItems={[]}
        notes=""
        observations={{}}
        onChange={jest.fn()}
        template="generic"
        canEditServiceType={true}
        onReclassify={jest.fn()}
      />
    );
    expect(getByText("Chemical Readings")).toBeTruthy();
  });
});
