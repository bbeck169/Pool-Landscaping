/**
 * scheduleCrewFilter.test.tsx — Phase K25
 * Tests for the CrewFilterBar rendering and crew_id refetch behavior.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────── */

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f5f5f5", onSurface: "#111",
    muted: "#888", brand: "#2563EB", brandTertiary: "#DBEAFE",
    border: "#ddd", onSurfaceSecondary: "#444",
  },
  spacing: { xs: 4, sm: 6, md: 8, lg: 16, xl: 24 },
  radius: { md: 8, lg: 12, pill: 100 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18 },
}));

/* ── Import under test ─────────────────────────────── */

import CrewFilterBar from "@/src/components/schedule/CrewFilterBar";

const CREWS = [
  { id: "c1", name: "Alpha Team", color: "#FF0000", members: [{ id: "t1", name: "Jim" }] },
  { id: "c2", name: "Bravo Team", color: "#00FF00", members: [{ id: "t2", name: "Bob" }] },
];

/* ── Tests ──────────────────────────────────────────── */

describe("CrewFilterBar", () => {
  it("renders 'All crews' label when no crew selected", () => {
    const { getByText, getByTestId } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="" onSelect={jest.fn()} memberNames={[]} />,
    );
    expect(getByTestId("crew-filter-bar")).toBeTruthy();
    expect(getByText("All crews")).toBeTruthy();
  });

  it("renders selected crew name when crew is selected", () => {
    const { getByText } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="c1" onSelect={jest.fn()} memberNames={["Jim"]} />,
    );
    expect(getByText("Alpha Team")).toBeTruthy();
  });

  it("shows member chips when crew selected", () => {
    const { getByTestId, getByText } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="c1" onSelect={jest.fn()} memberNames={["Jim"]} />,
    );
    expect(getByTestId("crew-member-chips")).toBeTruthy();
    expect(getByText("Jim")).toBeTruthy();
  });

  it("opens picker modal on press", async () => {
    const { getByTestId } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="" onSelect={jest.fn()} memberNames={[]} />,
    );
    fireEvent.press(getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(getByTestId("crew-filter-picker")).toBeTruthy();
    });
  });

  it("calls onSelect with crew id when crew is tapped in picker", async () => {
    const onSelect = jest.fn();
    const { getByTestId } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="" onSelect={onSelect} memberNames={[]} />,
    );
    fireEvent.press(getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(getByTestId("crew-filter-picker")).toBeTruthy();
    });
    fireEvent.press(getByTestId("crew-filter-c1"));
    expect(onSelect).toHaveBeenCalledWith("c1");
  });

  it("calls onSelect with empty string when 'All crews' tapped", async () => {
    const onSelect = jest.fn();
    const { getByTestId } = render(
      <CrewFilterBar crews={CREWS} selectedCrewId="c1" onSelect={onSelect} memberNames={["Jim"]} />,
    );
    fireEvent.press(getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(getByTestId("crew-filter-picker")).toBeTruthy();
    });
    fireEvent.press(getByTestId("crew-filter-all"));
    expect(onSelect).toHaveBeenCalledWith("");
  });

  it("shows empty message when no crews configured", async () => {
    const { getByTestId } = render(
      <CrewFilterBar crews={[]} selectedCrewId="" onSelect={jest.fn()} memberNames={[]} />,
    );
    fireEvent.press(getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(getByTestId("crew-filter-empty")).toBeTruthy();
    });
  });
});
