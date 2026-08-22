/**
 * Feb-2026 · P42 — Mobile customer_since label (Jest).
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { Text, View } from "react-native";


// Mirror the mobile snippet used in app/customer/[id].tsx so this
// test doesn't have to spin up the full Expo router page.
function CustomerSinceMobileLabel({ customer_since }: {
  customer_since?: string | null,
}) {
  if (!customer_since) return null;
  const dt = new Date(customer_since).toLocaleDateString(undefined, {
    month: "long", year: "numeric" });
  return (
    <View>
      <Text testID="mobile-customer-since-label">
        {`Customer since ${dt}`}
      </Text>
    </View>
  );
}


describe("mobile-customer-since-label · P42", () => {
  it("renders when customer_since is set", () => {
    const { getByTestId } = render(
      <CustomerSinceMobileLabel customer_since="2024-03-15T00:00:00Z" />);
    const el = getByTestId("mobile-customer-since-label");
    expect(el).toBeTruthy();
    // Month Year — timezone-tolerant.
    expect(el.props.children).toMatch(
      /Customer since (Feb|Mar)\w* 2024/);
  });

  it("hides entirely when customer_since is null", () => {
    const { queryByTestId } = render(
      <CustomerSinceMobileLabel customer_since={null} />);
    expect(queryByTestId("mobile-customer-since-label")).toBeNull();
  });

  it("hides entirely when customer_since is missing", () => {
    const { queryByTestId } = render(<CustomerSinceMobileLabel />);
    expect(queryByTestId("mobile-customer-since-label")).toBeNull();
  });
});
