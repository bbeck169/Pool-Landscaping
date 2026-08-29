/**
 * Ship 2 · CustomerDeleteModal — 3-button modal unit tests.
 *
 * Asserts the correct buttons, styling, callbacks, and busy states.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return {
    Ionicons: ({ name, ...rest }: any) => <Text testID={`icon-${name}`} {...rest} />,
  };
});

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", border: "#ddd", onSurface: "#333",
    surfaceSecondary: "#f5f5f5", onSurfaceSecondary: "#666",
    brand: "#0af", brandTertiary: "#e0f7ff", muted: "#888",
  },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16, pill: 999 },
}));

import CustomerDeleteModal from "@/src/components/customers/CustomerDeleteModal";

describe("CustomerDeleteModal (Ship 2)", () => {
  const defaultProps = {
    visible: true,
    customerName: "John Doe",
    busyMode: null as "soft" | "hard" | null,
    onCancel: jest.fn(),
    onSoftDelete: jest.fn(),
    onHardDelete: jest.fn(),
  };

  beforeEach(() => {
    defaultProps.onCancel.mockClear();
    defaultProps.onSoftDelete.mockClear();
    defaultProps.onHardDelete.mockClear();
  });

  it("renders all 3 buttons with correct testIDs", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    expect(tree.getByTestId("customer-delete-cancel-btn")).toBeTruthy();
    expect(tree.getByTestId("customer-delete-soft-btn")).toBeTruthy();
    expect(tree.getByTestId("customer-delete-hard-btn")).toBeTruthy();
  });

  it("hard button is styled with red background (#B91C1C)", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    const hardBtn = tree.getByTestId("customer-delete-hard-btn");
    // The flattened style array will contain backgroundColor: "#B91C1C"
    const style = Array.isArray(hardBtn.props.style)
      ? Object.assign({}, ...hardBtn.props.style.filter(Boolean))
      : hardBtn.props.style;
    expect(style.backgroundColor).toBe("#B91C1C");
  });

  it("hard button contains the shield icon", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    // Our Ionicons mock renders <Text testID="icon-shield" />
    expect(tree.getByTestId("icon-shield")).toBeTruthy();
  });

  it("tapping Cancel invokes onCancel", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    fireEvent.press(tree.getByTestId("customer-delete-cancel-btn"));
    expect(defaultProps.onCancel).toHaveBeenCalledTimes(1);
  });

  it("tapping Soft Delete invokes onSoftDelete", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    fireEvent.press(tree.getByTestId("customer-delete-soft-btn"));
    expect(defaultProps.onSoftDelete).toHaveBeenCalledTimes(1);
  });

  it("tapping Hard Delete invokes onHardDelete", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    fireEvent.press(tree.getByTestId("customer-delete-hard-btn"));
    expect(defaultProps.onHardDelete).toHaveBeenCalledTimes(1);
  });

  it("has NO text-input for type-to-confirm anywhere in the modal", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    const inputs = tree.root.findAllByType(
      require("react-native").TextInput
    );
    expect(inputs).toHaveLength(0);
  });

  it('when busyMode="hard", hard button shows busy label; others are disabled', () => {
    const tree = render(
      <CustomerDeleteModal {...defaultProps} busyMode="hard" />
    );
    const hardBtn = tree.getByTestId("customer-delete-hard-btn");
    // Flatten text content
    const hardText = tree.getByTestId("customer-delete-hard-btn");
    const allText = getAllText(hardText);
    expect(allText).toContain("Hard-deleting");

    // Cancel + Soft should be disabled
    const cancelBtn = tree.getByTestId("customer-delete-cancel-btn");
    const softBtn = tree.getByTestId("customer-delete-soft-btn");
    // TouchableOpacity passes disabled as accessibilityState
    expect(
      cancelBtn.props.accessibilityState?.disabled ||
      cancelBtn.props.disabled
    ).toBeTruthy();
    expect(
      softBtn.props.accessibilityState?.disabled ||
      softBtn.props.disabled
    ).toBeTruthy();
  });

  it('when busyMode="soft", soft button shows "Soft-deleting…"', () => {
    const tree = render(
      <CustomerDeleteModal {...defaultProps} busyMode="soft" />
    );
    const softText = getAllText(tree.getByTestId("customer-delete-soft-btn"));
    expect(softText).toContain("Soft-deleting");
  });

  it("renders title with customer name", () => {
    const tree = render(<CustomerDeleteModal {...defaultProps} />);
    const title = tree.getByTestId("customer-delete-title");
    const titleText = getAllText(title);
    expect(titleText).toContain("Delete");
    expect(titleText).toContain("John Doe");
  });
});

/** Recursively extract text from a RNTL element */
function getAllText(el: any): string {
  if (!el) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(getAllText).join("");
  const kids = el.props?.children;
  if (kids != null) return getAllText(kids);
  return "";
}
