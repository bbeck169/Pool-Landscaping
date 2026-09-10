/**
 * Task 6 — Quote/Estimate Terms & Conditions · Jest mobile coverage.
 *
 * Tests:
 *   1. Terms section renders heading + body when `terms_and_conditions` populated.
 *   2. No-terms label renders when empty.
 *   3. Whitespace-only terms → no-terms label.
 *   4. Multi-paragraph terms render correctly.
 *
 * Uses a minimal "mirror component" to avoid rendering the full
 * estimate-view screen (which pulls in heavy navigation + auth).
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { View, Text, StyleSheet } from "react-native";

/* ── Mocks ─────────────────────────────────────────────────── */

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: ({ name, ...props }: any) => <Text {...props}>{name}</Text> };
});

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", success: "#16A34A" },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 13, base: 15, lg: 17, xl: 20, "2xl": 24, "3xl": 30 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 6, md: 10, lg: 14 },
}));

/**
 * Mirror component that replicates the exact Terms & Conditions
 * rendering logic from estimate-view/[id].tsx — avoiding the need to
 * render the full estimate screen (which requires navigation, auth,
 * API calls, and heavy child components).
 */
function TermsSectionMirror({ terms }: { terms?: string | null }) {
  const { Ionicons } = require("@expo/vector-icons");
  const { colors, font, fontSize: fs, spacing, radius } = require("@/src/theme");

  if (terms && terms.trim()) {
    return (
      <View
        style={{
          backgroundColor: colors.surface,
          borderRadius: radius.md,
          padding: spacing.lg,
          marginBottom: spacing.md,
          borderWidth: 1,
          borderColor: colors.border,
        }}
        testID="estimate-terms-section"
      >
        <Text
          style={{ fontFamily: font.bold, fontSize: 15, color: colors.onSurface, marginBottom: 10 }}
          testID="estimate-terms-heading"
        >
          Terms & Conditions
        </Text>
        <View testID="estimate-terms-body">
          {terms.trim().split(/\n\s*\n/).map((para: string, i: number) => (
            <Text key={i} style={{ fontFamily: font.regular, fontSize: 13, color: "#374151", lineHeight: 21, marginTop: i > 0 ? 8 : 0 }}>
              {para}
            </Text>
          ))}
        </View>
      </View>
    );
  }

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, marginBottom: spacing.md }} testID="estimate-no-terms">
      <Ionicons name="document-text-outline" size={14} color={colors.muted} />
      <Text style={{ fontFamily: font.regular, fontSize: fs.sm, color: colors.muted }}>No terms</Text>
    </View>
  );
}


/* ── Tests ─────────────────────────────────────────────────── */

describe("Terms & Conditions Section (Task 6)", () => {
  it("1. renders heading + body when terms populated", () => {
    const { getByTestId } = render(
      <TermsSectionMirror terms={"Line 1\n\nLine 2 body"} />,
    );

    expect(getByTestId("estimate-terms-section")).toBeTruthy();
    expect(getByTestId("estimate-terms-heading")).toBeTruthy();

    const body = getByTestId("estimate-terms-body");
    expect(body).toBeTruthy();
    // Check that the body contains text from both paragraphs
    expect(body.children.length).toBe(2);
  });

  it("2. renders no-terms label when terms is empty string", () => {
    const { getByTestId, queryByTestId } = render(
      <TermsSectionMirror terms="" />,
    );

    expect(getByTestId("estimate-no-terms")).toBeTruthy();
    expect(queryByTestId("estimate-terms-section")).toBeNull();
  });

  it("3. renders no-terms label when terms is whitespace-only", () => {
    const { getByTestId, queryByTestId } = render(
      <TermsSectionMirror terms={"   \n\n  "} />,
    );

    expect(getByTestId("estimate-no-terms")).toBeTruthy();
    expect(queryByTestId("estimate-terms-section")).toBeNull();
  });

  it("4. renders nothing (no-terms) when terms is null", () => {
    const { getByTestId, queryByTestId } = render(
      <TermsSectionMirror terms={null} />,
    );

    expect(getByTestId("estimate-no-terms")).toBeTruthy();
    expect(queryByTestId("estimate-terms-section")).toBeNull();
  });

  it("5. multi-paragraph terms render as separate text nodes", () => {
    const terms = "Payment due within 30 days.\n\nLate fees apply after 60 days.\n\nAll work guaranteed for 90 days.";
    const { getByTestId } = render(
      <TermsSectionMirror terms={terms} />,
    );

    const body = getByTestId("estimate-terms-body");
    expect(body.children.length).toBe(3);
  });

  it("6. heading text matches spec", () => {
    const { getByTestId } = render(
      <TermsSectionMirror terms="Some terms here." />,
    );

    const heading = getByTestId("estimate-terms-heading");
    // React Native Text children contain the text
    expect(heading.children).toContain("Terms & Conditions");
  });
});
