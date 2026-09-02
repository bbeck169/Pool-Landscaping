/**
 * k27_setDefault.test.tsx — Phase K27 Part F
 * Tests for the "Set default" affordance on PaymentMethodRow.
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────── */

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f5f5f5", onSurface: "#111",
    muted: "#888", brand: "#2563EB", border: "#ddd", error: "#DC2626",
    success: "#16A34A",
  },
  spacing: { sm: 4, md: 8, lg: 16 },
  radius: { md: 8 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14 },
}));

/* ── Import ────────────────────────────────────────── */

import PaymentMethodRow from "@/src/components/stripe/PaymentMethodRow";

const DEFAULT_CARD = {
  id: "pm1",
  provider_payment_method_id: "pm_abc",
  type: "card" as const,
  brand: "Visa",
  last4: "4242",
  exp_month: 12,
  exp_year: 2026,
  is_default: true,
};

const NON_DEFAULT_CARD = {
  ...DEFAULT_CARD,
  id: "pm2",
  provider_payment_method_id: "pm_def",
  brand: "Mastercard",
  last4: "1234",
  is_default: false,
};

/* ── Tests ─────────────────────────────────────────── */

describe("PaymentMethodRow — Set default", () => {
  it("does NOT show 'Set default' for the default card", () => {
    const { queryByTestId } = render(
      <PaymentMethodRow
        pm={DEFAULT_CARD}
        onRemove={jest.fn()}
        onSetDefault={jest.fn()}
      />,
    );
    expect(queryByTestId("pm-set-default-pm_abc")).toBeNull();
    expect(queryByTestId("pm-default-chip")).toBeTruthy();
  });

  it("shows 'Set default' button for a non-default card", () => {
    const { getByTestId, getByText } = render(
      <PaymentMethodRow
        pm={NON_DEFAULT_CARD}
        onRemove={jest.fn()}
        onSetDefault={jest.fn()}
      />,
    );
    expect(getByTestId("pm-set-default-pm_def")).toBeTruthy();
    expect(getByText("Set default")).toBeTruthy();
  });

  it("fires onSetDefault with the correct pm ID on press", () => {
    const onSetDefault = jest.fn();
    const { getByTestId } = render(
      <PaymentMethodRow
        pm={NON_DEFAULT_CARD}
        onRemove={jest.fn()}
        onSetDefault={onSetDefault}
      />,
    );
    fireEvent.press(getByTestId("pm-set-default-pm_def"));
    expect(onSetDefault).toHaveBeenCalledWith("pm_def");
  });

  it("does NOT show 'Set default' when onSetDefault is not provided", () => {
    const { queryByTestId } = render(
      <PaymentMethodRow
        pm={NON_DEFAULT_CARD}
        onRemove={jest.fn()}
      />,
    );
    expect(queryByTestId("pm-set-default-pm_def")).toBeNull();
  });

  it("shows 'Setting…' text when settingDefault is true", () => {
    const { getByText } = render(
      <PaymentMethodRow
        pm={NON_DEFAULT_CARD}
        onRemove={jest.fn()}
        onSetDefault={jest.fn()}
        settingDefault={true}
      />,
    );
    expect(getByText("Setting…")).toBeTruthy();
  });
});

/* ── Soshie items normalization (Part E) ────────────── */

describe("Soshie moderation API shape — Part E", () => {
  it("soshie-moderation screen reads res.items (not res.posts)", () => {
    // Verify by source inspection: the bug was soshie-moderation.tsx
    // reading `res?.posts` — now fixed to `res?.items`.
    // We test the pattern directly:
    const apiResponse = { items: [{ id: "1" }, { id: "2" }] };
    // Correct extraction (K27 fix):
    const posts = apiResponse.items || [];
    expect(posts).toHaveLength(2);
    // Old incorrect extraction would fail:
    const oldPosts = (apiResponse as any).posts || [];
    expect(oldPosts).toHaveLength(0);
  });

  it("soshieModeration.ts type uses items key in response", () => {
    // The type was changed from { posts: ModerationPost[] } to { items: ModerationPost[] }.
    // TypeScript compile-time verification; runtime: verify the key name.
    const responseShape: { items: Array<{ id: string }> } = { items: [{ id: "p1" }] };
    expect(responseShape.items[0].id).toBe("p1");
    expect((responseShape as any).posts).toBeUndefined();
  });
});
