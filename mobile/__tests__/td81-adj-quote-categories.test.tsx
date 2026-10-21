/**
 * TD-81-adj b1 · quote/new.tsx reads GET /income-categories `{items, total}`.
 * Regression: mobile read the retired `.categories` key, so every tenant
 * saw only the 3 hard-coded chips. Those stay as the fetch-failure
 * fallback only (techs get 403 on this admin-gated endpoint).
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();

jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; detail: any = null; }
  return { api: { get: (u: string) => mockGet(u), post: jest.fn(), patch: jest.fn() }, ApiError };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("react-native-keyboard-controller", () => ({ KeyboardAwareScrollView: ({ children }: any) => children }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/ui", () => ({ PrimaryButton: () => null }));
jest.mock("@/app/customer/new", () => ({ Field: () => null }));
jest.mock("@/src/components/quotes/QuoteRecipientPicker", () => ({ __esModule: true, default: () => null }));

import QuoteForm from "@/app/quote/new";

// Live preview tenant shape (2026-10-21): 16 active categories.
const NAMES = [
  "Pool", "Chemicals", "Service Revenue (Demo)", "Landscaping", "Repair", "Late Fee", "Other", "Service Revenue",
  "Product Sales", "Recurring Maintenance", "One-time Project", "Warranty Work", "Labor Income", "Materials",
  "Other Income", "Seasonal",
];
const chipIds = (q: any) => q.queryAllByTestId(/^item-cat-0-/).map((n: any) => n.props.testID);

beforeEach(() => mockGet.mockReset());

it("B1 · renders all 16 tenant categories from {items, total}, first one defaulted", async () => {
  mockGet.mockImplementation(async (u: string) => {
    if (u === "/income-categories") return { items: NAMES.map((name, i) => ({ id: `c${i}`, name })), total: 16 };
    throw new Error(`unexpected GET ${u}`);
  });
  const q = render(<QuoteForm />);
  await waitFor(() => expect(chipIds(q)).toHaveLength(16));
  expect(chipIds(q)).toEqual(NAMES.map((n) => `item-cat-0-${n}`));
});

it("B2 · fetch failure (e.g. tech 403) keeps the 3 hard-coded fallback chips", async () => {
  mockGet.mockRejectedValue(Object.assign(new Error("Forbidden"), { status: 403 }));
  const q = render(<QuoteForm />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/income-categories"));
  expect(chipIds(q)).toEqual(["item-cat-0-Pool", "item-cat-0-Landscaping", "item-cat-0-Labor"]);
});
