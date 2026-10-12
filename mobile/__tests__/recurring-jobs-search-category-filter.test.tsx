/**
 * Mobile · Recurring Jobs customer search + service-category filter —
 * web parity with frontend/src/pages/admin/RecurringJobs.jsx (R2 search,
 * P54 category) as AND-composed with the 52c3eb6fa date filter.
 *
 *   1. search only — customer name / company / email / phone, case-
 *      insensitive, 250 ms debounce; notes are NOT searched (web scope)
 *   2. category only — exact match on service_category_id; "All" = no-op;
 *      rows with no category drop out of a specific pick
 *   3. search + category compose under AND
 *   4. compose with date presets + the Active / Paused tab under AND
 *   5. clearing each filter independently restores the full list
 *      (web has no single "clear all" control)
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";
import { addDays, format } from "date-fns";

jest.setTimeout(20000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), patch: jest.fn(), del: jest.fn() } }));
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => require("react").useEffect(() => { const c = cb(); return typeof c === "function" ? c : undefined; }, [cb]),
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@/src/components/layout/AdminListPage", () => {
  const { View } = require("react-native");
  return {
    AdminListPage: ({ headerExtra, children, isEmpty, loading, testID }: any) => (
      <View testID={testID}>{headerExtra}{loading ? null : isEmpty ? <View testID="recurring-empty" /> : children}</View>
    ),
  };
});
jest.mock("@react-native-community/datetimepicker", () => {
  const { View } = require("react-native");
  return function MockPicker(p: any) { return <View testID="mock-dtp" {...p} />; };
});
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    PrimaryButton: ({ title, onPress, testID }: any) => <Pressable onPress={onPress} testID={testID}><Text>{title}</Text></Pressable>,
    Sheet: ({ visible, children, testID }: any) => (visible ? <View testID={testID}>{children}</View> : null),
  };
});
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: jest.fn() }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockInput(p: any) { return <TextInput {...p} />; };
});
jest.mock("@/src/components/services/MasterServiceCombobox", () => () => null);
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.customer_name || "Customer" }));

import RecurringJobsMobile from "@/app/finance/recurring-jobs";

const iso = (n: number) => format(addDays(new Date(), n), "yyyy-MM-dd");
const row = (id: string, extra: any = {}) => ({ id, frequency: "weekly", day_of_week: 0, price_cents: 1000, active: true, upcoming: [iso(0)], ...extra });
const ACTIVE = [
  row("a-ann", { customer_name: "Ann Pool", service_category_id: "cat-pool", upcoming: [iso(0)] }),
  row("a-bob", { customer_name: "Bob Lawn", service_category_id: "cat-lawn", upcoming: [iso(1)] }),
  row("a-acme", { customer_name: "Carl", customer_company_name: "ACME Pools", service_category_id: "cat-pool", upcoming: [iso(10)] }),
  row("a-email", { customer_name: "Dee", customer_email: "dee@annex.io", upcoming: [iso(0)] }),
  row("a-phone", { customer_name: "Eve", customer_phone: "555-0199", service_category_id: "cat-pool", upcoming: [] }),
  row("a-notes", { customer_name: "Fay", notes: "ann pool notes", service_category_id: "cat-lawn" }),
];
const PAUSED = [
  row("p-ann", { customer_name: "Ann Paused", service_category_id: "cat-pool", active: false, upcoming: [iso(0)] }),
  row("p-zed", { customer_name: "Zed", service_category_id: "cat-pool", active: false, upcoming: [iso(0)] }),
];
const CATS = { items: [
  { id: "cat-pool", name: "Pool" },
  { id: "cat-lawn", name: "Lawn" },
  { id: "cat-old", name: "Retired", is_archived: true },
] };

const visible = (r: any) => r.queryAllByTestId(/^recurring-row-/).map((n: any) => n.props.testID.replace("recurring-row-", ""));
async function mount() {
  const r = render(<RecurringJobsMobile />);
  await waitFor(() => expect(visible(r).length).toBeGreaterThan(0));
  return r;
}
async function search(r: any, text: string) {
  fireEvent.changeText(r.getByTestId("recurring-search-input"), text);
  await act(async () => { await new Promise((res) => setTimeout(res, 300)); });
}
function pickCategory(r: any, id: string) {
  fireEvent.press(r.getByTestId("recurring-jobs-service-category-filter"));
  fireEvent.press(r.getByTestId(`recurring-jobs-service-category-option-${id || "all"}`));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/service-categories") return Promise.resolve(CATS);
    const items = url.includes("status=paused") ? PAUSED : ACTIVE;
    return Promise.resolve({ items, counts: { active: ACTIVE.length, paused: PAUSED.length } });
  });
});

describe("Mobile RecurringJobs · customer search + service-category filter", () => {
  it("1 · search only — name / company / email / phone, case-insensitive, 250 ms debounce; notes not searched", async () => {
    const r = await mount();
    fireEvent.changeText(r.getByTestId("recurring-search-input"), "ANN");
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id)); // debounce: not yet applied
    await act(async () => { await new Promise((res) => setTimeout(res, 300)); });
    expect(visible(r)).toEqual(["a-ann", "a-email"]); // "a-notes" has "ann" only in notes
    await search(r, "  acme ");
    expect(visible(r)).toEqual(["a-acme"]);
    await search(r, "0199");
    expect(visible(r)).toEqual(["a-phone"]);
    await search(r, "nobody");
    expect(visible(r)).toEqual([]);
    expect(r.getByTestId("recurring-jobs-empty").props.children).toBe("No recurring jobs match your search.");
  });

  it("2 · category only — exact id match, archived hidden, 'All' is a no-op, uncategorised rows drop out", async () => {
    const r = await mount();
    expect(mockApiGet).toHaveBeenCalledWith("/service-categories");
    fireEvent.press(r.getByTestId("recurring-jobs-service-category-filter"));
    expect(r.queryByTestId("recurring-jobs-service-category-option-cat-old")).toBeNull();
    fireEvent.press(r.getByTestId("recurring-jobs-service-category-option-cat-pool"));
    expect(visible(r)).toEqual(["a-ann", "a-acme", "a-phone"]);
    expect(r.getByText("Pool")).toBeTruthy();
    pickCategory(r, "");
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id));
    expect(r.getByText("All categories")).toBeTruthy();
  });

  it("3 · search + category compose under AND", async () => {
    const r = await mount();
    await search(r, "ann");
    pickCategory(r, "cat-pool");
    expect(visible(r)).toEqual(["a-ann"]); // a-email matches search but has no category
    pickCategory(r, "cat-lawn");
    expect(visible(r)).toEqual([]);
    expect(r.getByTestId("recurring-jobs-empty")).toBeTruthy();
  });

  it("4 · composes with the date preset and the Active / Paused tab under AND", async () => {
    const r = await mount();
    pickCategory(r, "cat-pool");
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    expect(visible(r)).toEqual(["a-ann"]); // a-acme +10d and a-phone (no upcoming) excluded
    await search(r, "ann");
    expect(visible(r)).toEqual(["a-ann"]);
    fireEvent.press(r.getByTestId("recurring-tab-paused"));
    await waitFor(() => expect(visible(r)).toEqual(["p-ann"])); // p-zed fails search
    expect(mockApiGet).toHaveBeenCalledWith("/recurring-jobs?status=paused");
  });

  it("5 · clearing each filter independently restores the full list (no single 'Clear all', web parity)", async () => {
    const r = await mount();
    await search(r, "ann");
    pickCategory(r, "cat-pool");
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    expect(visible(r)).toEqual(["a-ann"]);
    expect(r.queryByText(/clear all/i)).toBeNull();
    fireEvent.press(r.getByTestId("recurring-search-clear"));
    await act(async () => { await new Promise((res) => setTimeout(res, 300)); });
    expect(r.queryByTestId("recurring-search-clear")).toBeNull();
    pickCategory(r, "");
    fireEvent.press(r.getByTestId("recurring-jobs-date-clear"));
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id));
    expect(r.queryByTestId("recurring-jobs-empty")).toBeNull();
  });

  it("category fetch failure → only 'All categories', list still renders", async () => {
    mockApiGet.mockImplementation((url: string) =>
      url === "/service-categories" ? Promise.reject(new Error("500")) : Promise.resolve({ items: ACTIVE, counts: { active: 6, paused: 0 } }));
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-service-category-filter"));
    expect(r.queryAllByTestId(/^recurring-jobs-service-category-option-/).map((n: any) => n.props.testID))
      .toEqual(["recurring-jobs-service-category-option-all"]);
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id));
  });
});
