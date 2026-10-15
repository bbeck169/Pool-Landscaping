/**
 * TD-59 — pool-volume input on customer chemistry routes keystrokes through
 * the same `sanitizeDecimalInput` as the chemistry readings (Option A).
 *
 * Option A is intentional: "," is ALWAYS treated as the decimal separator, so
 * "20,000" becomes "20.000" (= 20 gal), not 20000. An operator who typed a
 * thousands separator sees a wildly-wrong magnitude and corrects it.
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) } }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "c1" }),
  useFocusEffect: () => {},
}));
jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return { Header: () => <View testID="header" /> };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockAppTextInput(p: any) { return <TextInput {...p} />; };
});

import CustomerChemistry from "@/app/customer/chemistry/[id]";

const setup = () => {
  const q = render(<CustomerChemistry />);
  const input = () => q.getByTestId("chemistry-volume-input");
  return { q, input };
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset().mockResolvedValue({});
});

describe("TD-59 pool volume uses sanitizeDecimalInput", () => {
  it("'7.6' passes through as '7.6'", () => {
    const { input } = setup();
    fireEvent.changeText(input(), "7.6");
    expect(input().props.value).toBe("7.6");
  });

  it("'20,000' → '20.000' (Option A: comma is the decimal separator) and posts volume_gal 20", async () => {
    const { q, input } = setup();
    fireEvent.changeText(input(), "20,000");
    expect(input().props.value).toBe("20.000");
    fireEvent.changeText(q.getByTestId("chemistry-reading-ph"), "7.5");
    await act(async () => { fireEvent.press(q.getByTestId("chemistry-recommend-btn")); });
    expect(mockPost).toHaveBeenCalledWith("/chemicals/dosing-recommendation", expect.objectContaining({ volume_gal: 20 }));
  });

  it("garbage is rejected (previous value kept); empty clears and falls back to 15000 on submit", async () => {
    const { q, input } = setup();
    fireEvent.changeText(input(), "20000");
    fireEvent.changeText(input(), "20000abc");
    expect(input().props.value).toBe("20000");
    fireEvent.changeText(input(), "2.0.0");
    expect(input().props.value).toBe("20000");
    fireEvent.changeText(input(), "");
    expect(input().props.value).toBe("");
    fireEvent.changeText(q.getByTestId("chemistry-reading-ph"), "7.5");
    await act(async () => { fireEvent.press(q.getByTestId("chemistry-recommend-btn")); });
    expect(mockPost).toHaveBeenCalledWith("/chemicals/dosing-recommendation", expect.objectContaining({ volume_gal: 15000 }));
  });
});
