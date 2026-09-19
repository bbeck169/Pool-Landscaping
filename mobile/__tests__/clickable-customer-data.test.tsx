/**
 * Clickable Customer Data — PhoneLink, AddressLink, CustomerLink tests.
 *
 * Mirrors the web Vitest suite for the 3 shared primitives.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Linking, Platform } from "react-native";

/* ── Mocks ──────────────────────────────────────────────────────────── */
jest.mock("expo-router", () => ({
  useRouter: () => ({
    push: mockRouterPush,
  }),
}));
const mockRouterPush = jest.fn();

jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
jest.spyOn(Linking, "canOpenURL").mockResolvedValue(true);

import PhoneLink from "@/src/components/customer/PhoneLink";
import AddressLink from "@/src/components/customer/AddressLink";
import CustomerLink from "@/src/components/customer/CustomerLink";

beforeEach(() => {
  jest.clearAllMocks();
  (Linking.openURL as jest.Mock).mockResolvedValue(true);
  (Linking.canOpenURL as jest.Mock).mockResolvedValue(true);
});

/* ── PhoneLink ──────────────────────────────────────────────────────── */
describe("PhoneLink", () => {
  it("renders tel: URI with normalized US 10-digit number", () => {
    const { getByTestId } = render(
      <PhoneLink phone="(555) 123-4567" testID="pl" />
    );
    fireEvent.press(getByTestId("pl"));
    expect(Linking.openURL).toHaveBeenCalledWith("tel:+15551234567");
  });

  it("normalizes 11-digit number starting with 1", () => {
    const { getByTestId } = render(
      <PhoneLink phone="1-555-123-4567" testID="pl" />
    );
    fireEvent.press(getByTestId("pl"));
    expect(Linking.openURL).toHaveBeenCalledWith("tel:+15551234567");
  });

  it("passes through international numbers", () => {
    const { getByTestId } = render(
      <PhoneLink phone="+442071234567" testID="pl" />
    );
    fireEvent.press(getByTestId("pl"));
    expect(Linking.openURL).toHaveBeenCalledWith("tel:+442071234567");
  });

  it("renders plain text for empty phone", () => {
    const { getByTestId } = render(<PhoneLink phone="" testID="pl" />);
    // Should render but not open dialer
    fireEvent.press(getByTestId("pl"));
    expect(Linking.openURL).not.toHaveBeenCalled();
  });

  it("renders plain text for null phone", () => {
    const { getByTestId } = render(<PhoneLink phone={null} testID="pl" />);
    fireEvent.press(getByTestId("pl"));
    expect(Linking.openURL).not.toHaveBeenCalled();
  });

  it("has correct accessibilityLabel", () => {
    const { getByTestId } = render(
      <PhoneLink phone="555-123-4567" testID="pl" />
    );
    expect(getByTestId("pl").props.accessibilityLabel).toBe("Call 555-123-4567");
  });
});

/* ── AddressLink ────────────────────────────────────────────────────── */
describe("AddressLink", () => {
  it("opens maps:// on iOS", () => {
    (Platform as any).OS = "ios";
    const { getByTestId } = render(
      <AddressLink address="123 Main St, Phoenix, AZ" testID="al" />
    );
    fireEvent.press(getByTestId("al"));
    expect(Linking.canOpenURL).toHaveBeenCalledWith(
      "maps://?q=123%20Main%20St%2C%20Phoenix%2C%20AZ"
    );
  });

  it("opens geo: on Android", async () => {
    (Platform as any).OS = "android";
    const { getByTestId } = render(
      <AddressLink address="123 Main St" testID="al" />
    );
    fireEvent.press(getByTestId("al"));
    await waitFor(() => {
      expect(Linking.canOpenURL).toHaveBeenCalledWith(
        "geo:0,0?q=123%20Main%20St"
      );
    });
  });

  it("opens Google Maps HTTPS on web", async () => {
    (Platform as any).OS = "web";
    const { getByTestId } = render(
      <AddressLink address="123 Main St" testID="al" />
    );
    fireEvent.press(getByTestId("al"));
    await waitFor(() => {
      expect(Linking.openURL).toHaveBeenCalledWith(
        "https://www.google.com/maps/search/?api=1&query=123%20Main%20St"
      );
    });
  });

  it("assembles AddressObject into comma-separated string", () => {
    (Platform as any).OS = "web";
    const { getByTestId } = render(
      <AddressLink
        address={{ line1: "123 Main", city: "Phoenix", state: "AZ", zip: "85001" }}
        testID="al"
      />
    );
    fireEvent.press(getByTestId("al"));
    expect(Linking.openURL).toHaveBeenCalledWith(
      expect.stringContaining("123%20Main%2C%20Phoenix%2C%20AZ%2C%2085001")
    );
  });

  it("renders plain text for empty address", () => {
    const { getByTestId } = render(<AddressLink address="" testID="al" />);
    fireEvent.press(getByTestId("al"));
    expect(Linking.openURL).not.toHaveBeenCalled();
  });

  it("renders plain text for null address", () => {
    const { getByTestId } = render(<AddressLink address={null} testID="al" />);
    fireEvent.press(getByTestId("al"));
    expect(Linking.openURL).not.toHaveBeenCalled();
  });

  it("has correct accessibilityLabel", () => {
    const { getByTestId } = render(
      <AddressLink address="123 Main St, Phoenix" testID="al" />
    );
    expect(getByTestId("al").props.accessibilityLabel).toBe(
      "Open in maps: 123 Main St, Phoenix"
    );
  });
});

/* ── CustomerLink ───────────────────────────────────────────────────── */
describe("CustomerLink", () => {
  it("navigates to /customer/{id} on press", () => {
    const { getByTestId } = render(
      <CustomerLink customerId="cust-42" name="John Doe" testID="cl" />
    );
    fireEvent.press(getByTestId("cl"));
    expect(mockRouterPush).toHaveBeenCalledWith("/customer/cust-42");
  });

  it("renders plain text for null customerId", () => {
    const { getByTestId } = render(
      <CustomerLink customerId={null} name="Jane" testID="cl" />
    );
    fireEvent.press(getByTestId("cl"));
    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  it("renders plain text for empty customerId", () => {
    const { getByTestId } = render(
      <CustomerLink customerId="" name="Jane" testID="cl" />
    );
    fireEvent.press(getByTestId("cl"));
    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  it("has correct accessibilityLabel from name", () => {
    const { getByTestId } = render(
      <CustomerLink customerId="c1" name="John Doe" testID="cl" />
    );
    expect(getByTestId("cl").props.accessibilityLabel).toBe("John Doe");
  });

  it("fallback accessibilityLabel when no name", () => {
    const { getByTestId } = render(
      <CustomerLink customerId="c1" testID="cl" />
    );
    expect(getByTestId("cl").props.accessibilityLabel).toBe("View customer");
  });
});
