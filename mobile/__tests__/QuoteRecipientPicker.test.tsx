/**
 * QuoteRecipientPicker.test.tsx — Phase 2 B2 mobile parity tests
 *
 * Covers:
 * - Trigger renders with testID
 * - Placeholder text when no value
 * - Selected badge when value provided
 * - Search input rendered in sheet
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import QuoteRecipientPicker, {
  RecipientTypeBadge,
} from "@/src/components/quotes/QuoteRecipientPicker";

// ── Mocks ────────────────────────────────────────────────────────
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue([
      {
        id: "cust-1",
        kind: "customer",
        display_name: "John Doe",
        email: "john@example.com",
        phone: "555-1234",
      },
      {
        id: "lead-1",
        kind: "lead",
        display_name: "Jane Lead",
        email: "jane@example.com",
      },
    ]),
  },
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable, ScrollView } = require("react-native");
  return {
    Sheet: ({
      visible,
      onClose,
      title,
      children,
      testID,
    }: any) =>
      visible ? (
        <View testID={testID}>
          {title ? <Text>{title}</Text> : null}
          <ScrollView>{children}</ScrollView>
        </View>
      ) : null,
  };
});

jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return {
    __esModule: true,
    default: (props: any) => <TextInput {...props} />,
  };
});

// ── Tests ────────────────────────────────────────────────────────

describe("RecipientTypeBadge", () => {
  it("renders Customer badge", () => {
    const { getByTestId, getByText } = render(
      <RecipientTypeBadge type="customer" testID="test-badge" />,
    );
    expect(getByTestId("test-badge")).toBeTruthy();
    expect(getByText("Customer")).toBeTruthy();
  });

  it("renders Lead badge", () => {
    const { getByTestId, getByText } = render(
      <RecipientTypeBadge type="lead" testID="test-badge" />,
    );
    expect(getByTestId("test-badge")).toBeTruthy();
    expect(getByText("Lead")).toBeTruthy();
  });

  it("defaults to Customer for unknown type", () => {
    const { getByText } = render(
      <RecipientTypeBadge type="unknown" testID="test-badge" />,
    );
    expect(getByText("Customer")).toBeTruthy();
  });
});

describe("QuoteRecipientPicker", () => {
  it("renders trigger with testID", () => {
    const { getByTestId } = render(
      <QuoteRecipientPicker value={null} onChange={jest.fn()} />,
    );
    expect(getByTestId("quote-recipient-picker")).toBeTruthy();
  });

  it("shows placeholder when no value", () => {
    const { getByText } = render(
      <QuoteRecipientPicker value={null} onChange={jest.fn()} />,
    );
    expect(getByText("Choose a customer or lead…")).toBeTruthy();
  });

  it("shows selected badge and name when value provided", () => {
    const { getByTestId, getByText } = render(
      <QuoteRecipientPicker
        value={{ type: "lead", id: "lead-1", name: "Jane Lead" }}
        onChange={jest.fn()}
      />,
    );
    expect(getByTestId("quote-recipient-picker-selected-badge")).toBeTruthy();
    expect(getByText("Jane Lead")).toBeTruthy();
  });

  it("opens sheet on press and shows search input", async () => {
    const { getByTestId } = render(
      <QuoteRecipientPicker value={null} onChange={jest.fn()} />,
    );
    fireEvent.press(getByTestId("quote-recipient-picker"));
    await waitFor(() => {
      expect(getByTestId("quote-recipient-sheet")).toBeTruthy();
      expect(getByTestId("quote-recipient-picker-search")).toBeTruthy();
    });
  });

  it("does not open when disabled", () => {
    const { getByTestId, queryByTestId } = render(
      <QuoteRecipientPicker value={null} onChange={jest.fn()} disabled />,
    );
    fireEvent.press(getByTestId("quote-recipient-picker"));
    expect(queryByTestId("quote-recipient-sheet")).toBeNull();
  });
});
