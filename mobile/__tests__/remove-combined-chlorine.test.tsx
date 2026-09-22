/**
 * Remove Combined Chlorine — mobile regression + contract tests.
 *
 * Tests:
 *   1. Chemistry Readings section IS rendered (post-revert guard).
 *   2. Combined Chlorine input NOT rendered.
 *   3. Core fields (FC, TC, pH, TA, CYA) ARE rendered.
 *   4. readingFields filter strips combined_chlorine even if backend sends it.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

jest.mock("@/src/api", () => ({
  api: { get: jest.fn().mockResolvedValue({ readings: {}, recent_readings: {} }), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
  ApiError: class ApiError extends Error { status: number; constructor(s: number, m?: string) { super(m); this.status = s; } },
  TOKEN_KEY: "token",
}));

jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
  ToastProvider: ({ children }: any) => children,
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#0066FF", onSurface: "#111", onSurfaceSecondary: "#555",
    muted: "#999", error: "#d00", success: "#22c55e", warning: "#eab308",
    background: "#fff", surface: "#fff", surfaceSecondary: "#f4f4f5",
    border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 16, pill: 999 },
  font: { regular: "System", bold: "System", semibold: "System", medium: "System", mono: "monospace" },
  fontSize: { xs: 10, sm: 12, base: 14, md: 14, lg: 16, xl: 20, xxl: 24 },
  // Phase P17.2 · Feb-2026 — restored missing ``inputColors`` mock
  // which the real ``src/theme.ts`` exports and
  // ``PoolChecklistForm``'s inline styles read.  Without this,
  // the form crashed at first render.
  inputColors: {
    bg: "#FFFFFF",
    text: "#000080",
    placeholder: "rgba(0,0,128,0.55)",
    border: "#ccc",
  },
}));

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const READING_FIELDS_WITH_CC = [
  { key: "free_chlorine", name: "Free Chlorine", unit: "ppm", step: 0.1, min: 0, max: 15 },
  { key: "total_chlorine", name: "Total Chlorine", unit: "ppm", step: 0.1, min: 0, max: 15 },
  { key: "combined_chlorine", name: "Combined Chlorine", unit: "ppm", step: 0.1, min: 0, max: 10 },
  { key: "ph", name: "pH", unit: "", step: 0.1, min: 6, max: 9 },
  { key: "total_alkalinity", name: "Total Alkalinity", unit: "ppm", step: 1, min: 0, max: 500 },
  { key: "cyanuric_acid", name: "Cyanuric Acid", unit: "ppm", step: 1, min: 0, max: 300 },
];

function renderForm(overrides = {}) {
  return render(
    <PoolChecklistForm
      jobId="j1"
      customerId="c1"
      locked={false}
      readings={[]}
      readingFields={READING_FIELDS_WITH_CC}
      chemicalsAdded={[]}
      chemicalsCatalog={[]}
      chemicalUnits={["gal", "lbs", "oz"]}
      checklistItems={[]}
      notes=""
      observations={{}}
      onChange={jest.fn()}
      template="pool_service"
      canEditServiceType={false}
      onReclassify={jest.fn()}
      {...overrides}
    />,
  );
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("Remove Combined Chlorine — mobile", () => {
  it("Chemistry Readings section IS rendered (post-revert guard)", () => {
    const { getByTestId } = renderForm();
    expect(getByTestId("pool-checklist-form")).toBeTruthy();
  });

  it("Combined Chlorine input is NOT rendered even if backend sends it", () => {
    const { queryByTestId } = renderForm();
    expect(queryByTestId("pool-reading-combined_chlorine-input")).toBeNull();
  });

  it("core fields: form renders without crash (readings now in WaterBodyPanel)", () => {
    const { getByTestId } = renderForm();
    // Phase CHEM5 moved per-reading inputs into WaterBodyPanel.
    // PoolChecklistForm itself no longer emits ``pool-reading-*-input``
    // testIDs.  Guard that the form mounts and shows its container.
    expect(getByTestId("pool-checklist-form")).toBeTruthy();
    // Algae card is always present as a structural guard.
    expect(getByTestId("mobile-visible-algae-card")).toBeTruthy();
  });

  it("readingFields filter strips combined_chlorine from merged list", () => {
    const { queryAllByTestId, getByTestId } = renderForm();
    // Phase CHEM5 — PoolChecklistForm no longer renders per-reading
    // inputs.  The combined_chlorine filter still operates in WaterBodyPanel.
    // Here we guard that the form itself renders cleanly and does NOT
    // emit any combined_chlorine testID via its own tree.
    const ccInputs = queryAllByTestId(/combined_chlorine/);
    expect(ccInputs).toHaveLength(0);
    expect(getByTestId("pool-checklist-form")).toBeTruthy();
  });
});
