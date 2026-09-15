/**
 * Phase CHEM4 — isPrimary body suppression + additional-body header labels.
 *
 * Tests:
 *  1. Body 0 (isPrimary=true) → Chemistry Readings NOT rendered.
 *  2. Body 0 (isPrimary=true) → Chemicals Used NOT rendered.
 *  3. Body 1 (isPrimary=false, spa) → Chemistry Readings + Chemicals both render.
 *  4. Body 1 (spa) → header "Additional Body of Water Chemicals" + sub-header "Spa".
 *  5. Body 1 (fountain) → sub-header "Fountain".
 *  6. Body 1 (unknown type) → sub-header falls back to raw value.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import WaterBodyPanel from "../src/components/checklist/WaterBodyPanel";

const makeBody = (type: string, overrides?: any) => ({
  id: "test-body",
  type,
  label: "",
  sequence: 0,
  readings: [],
  chemicals_used: [],
  notes: "",
  ...overrides,
});

const noop = () => {};

describe("Phase CHEM4 — isPrimary suppression + additional-body headers", () => {

  it("isPrimary=true → Chemistry Readings section NOT rendered", () => {
    const { queryByTestId, queryByText } = render(
      <WaterBodyPanel
        body={makeBody("pool")}
        index={0}
        locked={false}
        canRemove={false}
        isPrimary={true}
        onChange={noop}
        onRemove={noop}
      />,
    );
    expect(queryByText("Chemistry Readings")).toBeNull();
    expect(queryByTestId("reading-row-0-free_chlorine")).toBeNull();
  });

  it("isPrimary=true → Chemicals Used section NOT rendered", () => {
    const { queryByText, queryByTestId } = render(
      <WaterBodyPanel
        body={makeBody("pool")}
        index={0}
        locked={false}
        canRemove={false}
        isPrimary={true}
        onChange={noop}
        onRemove={noop}
      />,
    );
    expect(queryByText("Additional Body of Water Chemicals")).toBeNull();
    expect(queryByText("Chemicals Used")).toBeNull();
    expect(queryByTestId("water-body-chem-header-0")).toBeNull();
  });

  it("isPrimary=false (spa) → Chemistry Readings + Chemicals both render", () => {
    const { getByText, getByTestId } = render(
      <WaterBodyPanel
        body={makeBody("spa")}
        index={1}
        locked={false}
        canRemove={true}
        isPrimary={false}
        onChange={noop}
        onRemove={noop}
      />,
    );
    expect(getByText("Chemistry Readings")).toBeTruthy();
    expect(getByTestId("water-body-chem-header-1")).toBeTruthy();
  });

  it('isPrimary=false (spa) → header "Additional Body of Water Chemicals" + sub-header "Spa"', () => {
    const { getByTestId } = render(
      <WaterBodyPanel
        body={makeBody("spa")}
        index={1}
        locked={false}
        canRemove={true}
        isPrimary={false}
        onChange={noop}
        onRemove={noop}
      />,
    );
    expect(getByTestId("water-body-chem-header-1").props.children).toBe(
      "Additional Body of Water Chemicals",
    );
    expect(getByTestId("water-body-chem-subheader-1").props.children).toBe("Spa");
  });

  it('isPrimary=false (fountain) → sub-header "Fountain"', () => {
    const { getByTestId } = render(
      <WaterBodyPanel
        body={makeBody("fountain")}
        index={2}
        locked={false}
        canRemove={true}
        isPrimary={false}
        onChange={noop}
        onRemove={noop}
      />,
    );
    expect(getByTestId("water-body-chem-subheader-2").props.children).toBe("Fountain");
  });

  it("isPrimary=false (unknown type) → sub-header falls back to raw value", () => {
    const { getByTestId } = render(
      <WaterBodyPanel
        body={makeBody("lagoon")}
        index={3}
        locked={false}
        canRemove={true}
        isPrimary={false}
        onChange={noop}
        onRemove={noop}
      />,
    );
    // BODY_TYPE_LABELS won't have "lagoon", so raw value is used
    expect(getByTestId("water-body-chem-subheader-3").props.children).toBe("lagoon");
  });
});
