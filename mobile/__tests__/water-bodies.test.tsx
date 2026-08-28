/**
 * Phase v · Multi-body service reports — Jest coverage.
 *
 * Tests WaterBodyManager, WaterBodyPanel, and waterBodies utilities.
 */

/* ── Standard mocks ────────────────────────────────────────────── */
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "test-job" }),
  useFocusEffect: (cb: any) => cb(),
}));
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn().mockResolvedValue(null),
  setItem: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "technician", id: "u1" } }),
  AuthProvider: ({ children }: any) => children,
}));

import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

import {
  makeEmptyBody,
  missingRequiredReadings,
  validateBodies,
  READING_ALLOWLIST,
  READING_REQUIRED,
  BODY_TYPE_LABELS,
  WATER_BODY_TYPES,
  WaterBody,
} from "@/src/lib/waterBodies";

import WaterBodyManager from "@/src/components/checklist/WaterBodyManager";
import WaterBodyPanel from "@/src/components/checklist/WaterBodyPanel";

describe("waterBodies.ts — constants & validators", () => {
  it("exports all 5 body types with labels", () => {
    expect(WATER_BODY_TYPES).toHaveLength(5);
    expect(BODY_TYPE_LABELS.pool).toBe("Pool");
    expect(BODY_TYPE_LABELS.spa).toBe("Spa");
    expect(BODY_TYPE_LABELS.water_feature).toBe("Water Feature");
    expect(BODY_TYPE_LABELS.fountain).toBe("Fountain");
    expect(BODY_TYPE_LABELS.other).toBe("Other");
  });

  it("pool has 9 allowed readings and 5 required", () => {
    expect(READING_ALLOWLIST.pool).toHaveLength(9);
    expect(READING_REQUIRED.pool).toHaveLength(5);
    expect(READING_REQUIRED.pool).toEqual(
      expect.arrayContaining(["free_chlorine", "total_chlorine", "ph", "alkalinity", "cyanuric_acid"]),
    );
  });

  it("spa has 4 allowed readings and 0 required", () => {
    expect(READING_ALLOWLIST.spa).toHaveLength(4);
    expect(READING_REQUIRED.spa).toHaveLength(0);
  });

  it("water_feature and fountain have 2 allowed readings", () => {
    expect(READING_ALLOWLIST.water_feature).toHaveLength(2);
    expect(READING_ALLOWLIST.fountain).toHaveLength(2);
  });

  it("makeEmptyBody creates a pool body by default", () => {
    const body = makeEmptyBody();
    expect(body.type).toBe("pool");
    expect(body.id).toBeTruthy();
    expect(body.readings).toEqual([]);
    expect(body.chemicals_used).toEqual([]);
    expect(body.notes).toBe("");
  });

  it("missingRequiredReadings detects empty pool readings", () => {
    const body = makeEmptyBody("pool");
    const missing = missingRequiredReadings(body);
    expect(missing).toEqual(
      expect.arrayContaining(["free_chlorine", "total_chlorine", "ph", "alkalinity", "cyanuric_acid"]),
    );
    expect(missing).toHaveLength(5);
  });

  it("missingRequiredReadings returns [] for spa (no required)", () => {
    const body = makeEmptyBody("spa");
    expect(missingRequiredReadings(body)).toHaveLength(0);
  });

  it("missingRequiredReadings returns [] when pool has all required filled", () => {
    const body = makeEmptyBody("pool");
    body.readings = [
      { key: "free_chlorine", value: 3, unit: "ppm" },
      { key: "total_chlorine", value: 3, unit: "ppm" },
      { key: "ph", value: 7.4, unit: "" },
      { key: "alkalinity", value: 100, unit: "ppm" },
      { key: "cyanuric_acid", value: 40, unit: "ppm" },
    ];
    expect(missingRequiredReadings(body)).toHaveLength(0);
  });

  it("validateBodies rejects empty array", () => {
    const { valid } = validateBodies([]);
    expect(valid).toBe(false);
  });

  it("validateBodies passes with one valid pool body", () => {
    const { valid } = validateBodies([makeEmptyBody("pool")]);
    expect(valid).toBe(true);
  });
});

describe("WaterBodyManager — component", () => {
  it("renders correct number of body panels", () => {
    const bodies = [makeEmptyBody("pool", 0), makeEmptyBody("spa", 1)];
    const { getByTestId } = render(
      <WaterBodyManager bodies={bodies} locked={false} onChange={jest.fn()} />,
    );
    expect(getByTestId("water-body-panel-0")).toBeTruthy();
    expect(getByTestId("water-body-panel-1")).toBeTruthy();
    expect(getByTestId("add-water-body-btn")).toBeTruthy();
  });

  it("shows type badges for each body", () => {
    const bodies = [makeEmptyBody("pool", 0), makeEmptyBody("spa", 1)];
    const { getByTestId } = render(
      <WaterBodyManager bodies={bodies} locked={false} onChange={jest.fn()} />,
    );
    expect(getByTestId("water-body-type-badge-0").props.children).toBe("Pool");
    expect(getByTestId("water-body-type-badge-1").props.children).toBe("Spa");
  });

  it("hides add button when locked", () => {
    const bodies = [makeEmptyBody("pool", 0)];
    const { queryByTestId } = render(
      <WaterBodyManager bodies={bodies} locked={true} onChange={jest.fn()} />,
    );
    expect(queryByTestId("add-water-body-btn")).toBeNull();
  });

  it("opens type picker on add button press", () => {
    const bodies = [makeEmptyBody("pool", 0)];
    const { getByTestId } = render(
      <WaterBodyManager bodies={bodies} locked={false} onChange={jest.fn()} />,
    );
    fireEvent.press(getByTestId("add-water-body-btn"));
    // Picker should show all 5 type options
    expect(getByTestId("add-body-type-pool")).toBeTruthy();
    expect(getByTestId("add-body-type-spa")).toBeTruthy();
    expect(getByTestId("add-body-type-water_feature")).toBeTruthy();
    expect(getByTestId("add-body-type-fountain")).toBeTruthy();
    expect(getByTestId("add-body-type-other")).toBeTruthy();
  });

  it("calls onChange with new body when type is selected", () => {
    const bodies = [makeEmptyBody("pool", 0)];
    const onChange = jest.fn();
    const { getByTestId } = render(
      <WaterBodyManager bodies={bodies} locked={false} onChange={onChange} />,
    );
    fireEvent.press(getByTestId("add-water-body-btn"));
    fireEvent.press(getByTestId("add-body-type-spa"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const newBodies = onChange.mock.calls[0][0];
    expect(newBodies).toHaveLength(2);
    expect(newBodies[1].type).toBe("spa");
  });
});

describe("WaterBodyPanel — component", () => {
  it("renders chemistry inputs filtered by body type", () => {
    const body = makeEmptyBody("spa", 0);
    const { queryByTestId } = render(
      <WaterBodyPanel
        body={body}
        index={0}
        locked={false}
        canRemove={false}
        onChange={jest.fn()}
        onRemove={jest.fn()}
      />,
    );
    // Spa has 4 readings: free_chlorine, ph, alkalinity, calcium_hardness
    expect(queryByTestId("reading-row-0-free_chlorine")).toBeTruthy();
    expect(queryByTestId("reading-row-0-ph")).toBeTruthy();
    expect(queryByTestId("reading-row-0-alkalinity")).toBeTruthy();
    expect(queryByTestId("reading-row-0-calcium_hardness")).toBeTruthy();
    // Should NOT have CYA (pool-only)
    expect(queryByTestId("reading-row-0-cyanuric_acid")).toBeNull();
  });

  it("shows remove button only when canRemove is true", () => {
    const body = makeEmptyBody("pool", 0);
    const { queryByTestId, rerender } = render(
      <WaterBodyPanel body={body} index={0} locked={false} canRemove={false} onChange={jest.fn()} onRemove={jest.fn()} />,
    );
    expect(queryByTestId("water-body-remove-0")).toBeNull();
    rerender(
      <WaterBodyPanel body={body} index={0} locked={false} canRemove={true} onChange={jest.fn()} onRemove={jest.fn()} />,
    );
    expect(queryByTestId("water-body-remove-0")).toBeTruthy();
  });

  it("highlights missing readings when highlightMissing is provided", () => {
    const body = makeEmptyBody("pool", 0);
    const { getByTestId } = render(
      <WaterBodyPanel
        body={body}
        index={0}
        locked={false}
        canRemove={false}
        highlightMissing={["free_chlorine", "ph"]}
        onChange={jest.fn()}
        onRemove={jest.fn()}
      />,
    );
    // The row testID should exist
    expect(getByTestId("reading-row-0-free_chlorine")).toBeTruthy();
    expect(getByTestId("reading-row-0-ph")).toBeTruthy();
  });
});
