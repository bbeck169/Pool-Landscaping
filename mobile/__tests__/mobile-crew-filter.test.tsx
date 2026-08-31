/**
 * __tests__/mobile-crew-filter.test.tsx
 * Tests: dropdown renders, crew selection, member chips, "All crews" reset.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", onSurface: "#000", surfaceSecondary: "#f4f4f5",
    surfaceTertiary: "#e4e4e7", border: "#e4e4e7", muted: "#717",
    brand: "#0284C7", brandTertiary: "#E0F2FE", error: "#DC2626",
    onSurfaceSecondary: "#6B7280",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radius: { sm: 8, md: 12, lg: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20 },
}));

import CrewFilterBar from "@/src/components/schedule/CrewFilterBar";

const CREWS = [
  { id: "c1", name: "East Side", tech_ids: ["t1", "t2"], color: "#059669" },
  { id: "c2", name: "West Side", tech_ids: ["t3"], color: "#2563EB" },
];

describe("CrewFilterBar", () => {
  it("renders 'All crews' label by default", () => {
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId=""
        onSelect={() => {}}
        memberNames={[]}
      />,
    );
    expect(tree.getByText("All crews")).toBeTruthy();
    console.log("✅ CF-T1: default label shows 'All crews'");
  });

  it("opens picker and shows all crew options", async () => {
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId=""
        onSelect={() => {}}
        memberNames={[]}
      />,
    );
    fireEvent.press(tree.getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(tree.getByTestId("crew-filter-picker")).toBeTruthy();
      expect(tree.getByTestId("crew-filter-c1")).toBeTruthy();
      expect(tree.getByTestId("crew-filter-c2")).toBeTruthy();
    });
    console.log("✅ CF-T2: picker shows all crews");
  });

  it("selecting a crew calls onSelect with crew id", async () => {
    const onSelect = jest.fn();
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId=""
        onSelect={onSelect}
        memberNames={[]}
      />,
    );
    fireEvent.press(tree.getByTestId("crew-filter-trigger"));
    await waitFor(() =>
      expect(tree.getByTestId("crew-filter-c1")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("crew-filter-c1"));
    expect(onSelect).toHaveBeenCalledWith("c1");
    console.log("✅ CF-T3: onSelect called with crew id");
  });

  it("selecting 'All crews' calls onSelect with empty string", async () => {
    const onSelect = jest.fn();
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId="c1"
        onSelect={onSelect}
        memberNames={["Alice", "Bob"]}
      />,
    );
    fireEvent.press(tree.getByTestId("crew-filter-trigger"));
    await waitFor(() =>
      expect(tree.getByTestId("crew-filter-all")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("crew-filter-all"));
    expect(onSelect).toHaveBeenCalledWith("");
    console.log("✅ CF-T4: 'All crews' resets filter");
  });

  it("shows member name chips when crew selected", () => {
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId="c1"
        onSelect={() => {}}
        memberNames={["Alice", "Bob"]}
      />,
    );
    expect(tree.getByTestId("crew-member-chips")).toBeTruthy();
    expect(tree.getByText("Alice")).toBeTruthy();
    expect(tree.getByText("Bob")).toBeTruthy();
    console.log("✅ CF-T5: member chips visible");
  });

  it("selected crew name shows as label", () => {
    const tree = render(
      <CrewFilterBar
        crews={CREWS}
        selectedCrewId="c1"
        onSelect={() => {}}
        memberNames={[]}
      />,
    );
    expect(tree.getByText("East Side")).toBeTruthy();
    console.log("✅ CF-T6: selected crew name as label");
  });

  it("handles empty crew list gracefully", async () => {
    const tree = render(
      <CrewFilterBar
        crews={[]}
        selectedCrewId=""
        onSelect={() => {}}
        memberNames={[]}
      />,
    );
    fireEvent.press(tree.getByTestId("crew-filter-trigger"));
    await waitFor(() => {
      expect(tree.getByTestId("crew-filter-empty")).toBeTruthy();
    });
    console.log("✅ CF-T7: empty crews handled");
  });
});
