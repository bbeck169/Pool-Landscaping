/**
 * Phase T1 — AppTextInput sitewide theme test.
 *
 * Asserts the wrapper applies the canonical white-bg / navy-text /
 * muted-navy-placeholder style to every mounted TextInput.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import AppTextInput from "../src/components/ui/AppTextInput";

describe("AppTextInput — sitewide input theme", () => {
  it("renders with white background and navy text color", () => {
    const { getByTestId } = render(
      <AppTextInput testID="themed-input" placeholder="Type…" />,
    );
    const input = getByTestId("themed-input");

    // Flatten styles into a plain object
    const flatStyle = Array.isArray(input.props.style)
      ? Object.assign({}, ...input.props.style.filter(Boolean))
      : input.props.style || {};

    expect(flatStyle.backgroundColor).toBe("#FFFFFF");
    expect(flatStyle.color).toBe("#000080");
  });

  it("applies the canonical muted-navy placeholder color", () => {
    const { getByTestId } = render(
      <AppTextInput testID="themed-input" placeholder="Search…" />,
    );
    const input = getByTestId("themed-input");
    expect(input.props.placeholderTextColor).toBe("rgba(0,0,128,0.55)");
  });

  it("allows caller placeholderTextColor override when explicitly set", () => {
    const { getByTestId } = render(
      <AppTextInput
        testID="custom-placeholder"
        placeholderTextColor="#FF0000"
        placeholder="Red placeholder"
      />,
    );
    const input = getByTestId("custom-placeholder");
    expect(input.props.placeholderTextColor).toBe("#FF0000");
  });

  it("preserves caller styles while enforcing theme overrides", () => {
    const { getByTestId } = render(
      <AppTextInput
        testID="styled-input"
        style={{ padding: 10, borderWidth: 1, backgroundColor: "#EEEEEE" }}
        placeholder="With padding"
      />,
    );
    const input = getByTestId("styled-input");
    const flatStyle = Array.isArray(input.props.style)
      ? Object.assign({}, ...input.props.style.filter(Boolean))
      : input.props.style || {};

    // Theme overrides bg even if caller passed a different one
    expect(flatStyle.backgroundColor).toBe("#FFFFFF");
    expect(flatStyle.color).toBe("#000080");
    // Caller padding is preserved
    expect(flatStyle.padding).toBe(10);
    expect(flatStyle.borderWidth).toBe(1);
  });
});
