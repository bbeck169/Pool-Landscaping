/**
 * Phase CHEM5 — Unified water-body forms + header labels.
 *
 * Supersedes CHEM4 isPrimary suppression. After CHEM5, ALL bodies
 * (including isPrimary=true) render Chemistry Readings and Chemicals.
 *
 * Tests:
 *  1. Body 0 (isPrimary=true) → Chemistry Readings IS rendered.
 *  2. Body 0 (isPrimary=true) → Chemicals section IS rendered, header = "Pool".
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

describe("Phase CHEM5 — unified water-body forms + header labels", () => {

  it("isPrimary=true → Chemistry Readings section IS rendered", () => {
    const { getByText, getByTestId } = render(
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
    expect(getByText("Chemistry Readings")).toBeTruthy();
    // Pool bodies should show reading rows
    expect(getByTestId("reading-row-0-free_chlorine")).toBeTruthy();
  });

  it('isPrimary=true → Chemicals section IS rendered with header "Pool"', () => {
    const { getByTestId } = render(
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
    const header = getByTestId("water-body-chem-header-0");
    expect(header).toBeTruthy();
    expect(header.props.children).toBe("Pool");
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
