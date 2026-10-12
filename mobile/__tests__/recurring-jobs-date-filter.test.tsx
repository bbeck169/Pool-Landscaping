/**
 * Mobile · Recurring Jobs "Next" date-range filter — web parity with
 * frontend/src/test/recurring-jobs-date-filter.test.jsx (a87f4a525).
 *
 *   1. default (no range) shows every row incl. rows with no upcoming[]
 *   2. "Today" narrows to rows whose upcoming[0] === today
 *   3. "Next 7 Days" inclusive — today, +1, +6 in; +7 out
 *   4. custom start/end inclusive both ends; deselects the preset chip
 *   5. composes with the Active / Paused tab under AND (mobile has no
 *      search / category filter yet — follow-up parity story)
 *   6. Clear restores every row and removes the active chip
 *   + "Next: YYYY-MM-DD" / "Next: —" meta line, no-match message,
 *     autobilling-runs pill chip styling.
 */
import React from "react";
import { StyleSheet } from "react-native";
import { render, waitFor, act, fireEvent, within } from "@testing-library/react-native";
import { addDays, format } from "date-fns";

jest.setTimeout(20000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), patch: jest.fn(), del: jest.fn() } }));
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => require("react").useEffect(() => { const c = cb(); return typeof c === "function" ? c : undefined; }, [cb]),
}));
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
    Sheet: ({ visible, children }: any) => (visible ? <View>{children}</View> : null),
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
const row = (id: string, upcoming: string[] | undefined, extra: any = {}) => ({
  id, customer_name: id, frequency: "weekly", day_of_week: 0, price_cents: 1000, active: true, upcoming, ...extra,
});
const ACTIVE = [
  row("r-today", [iso(0), iso(7)]),
  row("r-plus1", [iso(1)]),
  row("r-plus6", [iso(6)]),
  row("r-plus7", [iso(7)]),
  row("r-past", [iso(-3)]),
  row("r-none", []),
  row("r-missing", undefined),
];
const PAUSED = [row("p-today", [iso(0)], { active: false }), row("p-plus20", [iso(20)], { active: false })];

const visible = (r: any) =>
  r.queryAllByTestId(/^recurring-row-/).map((n: any) => n.props.testID.replace("recurring-row-", ""));
const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};

async function mount() {
  const r = render(<RecurringJobsMobile />);
  await waitFor(() => expect(visible(r).length).toBeGreaterThan(0));
  return r;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockImplementation((url: string) =>
    Promise.resolve(url.includes("status=paused")
      ? { items: PAUSED, counts: { active: ACTIVE.length, paused: PAUSED.length } }
      : { items: ACTIVE, counts: { active: ACTIVE.length, paused: PAUSED.length } }));
});

describe("Mobile RecurringJobs · 'Next' column date-range filter", () => {
  it("1 · default state (no range) shows every row including rows with no upcoming[]", async () => {
    const r = await mount();
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id));
    expect(r.queryByTestId("recurring-jobs-date-clear")).toBeNull();
    for (const k of ["today", "this_week", "next_7_days", "next_30_days", "this_month"]) {
      expect(r.getByTestId(`recurring-jobs-date-preset-${k}`).props.accessibilityState).toMatchObject({ selected: false });
    }
    expect(r.getByTestId("recurring-next-r-today").props.children.join("")).toBe(`Next: ${iso(0)}`);
    expect(r.getByTestId("recurring-next-r-none").props.children.join("")).toBe("Next: —");
    expect(r.getByTestId("recurring-next-r-missing").props.children.join("")).toBe("Next: —");
  });

  it("2 · preset 'Today' narrows to rows whose upcoming[0] equals today", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    expect(visible(r)).toEqual(["r-today"]);
    expect(r.getByTestId("recurring-jobs-date-preset-today").props.accessibilityState).toMatchObject({ selected: true });
    expect(r.getByTestId("recurring-jobs-date-clear")).toBeTruthy();
  });

  it("3 · preset 'Next 7 Days' is inclusive — today, +1, +6 included; +7, past, empty excluded", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-next_7_days"));
    expect(visible(r)).toEqual(["r-today", "r-plus1", "r-plus6"]);
  });

  it("4 · custom start/end range is inclusive both ends and deselects the preset chip", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    const pick = async (tid: string, n: number) => {
      fireEvent.press(r.getByTestId(tid));
      const dtp = r.getByTestId("mock-dtp");
      await act(async () => { dtp.props.onChange({}, addDays(new Date(), n)); });
      fireEvent.press(r.getByTestId(`${tid}-done`));
    };
    await pick("recurring-jobs-date-start", 1);
    expect(r.getByTestId("recurring-jobs-date-preset-today").props.accessibilityState).toMatchObject({ selected: false });
    await pick("recurring-jobs-date-end", 6);
    expect(within(r.getByTestId("recurring-jobs-date-start")).getByText(iso(1))).toBeTruthy();
    expect(within(r.getByTestId("recurring-jobs-date-end")).getByText(iso(6))).toBeTruthy();
    expect(visible(r)).toEqual(["r-plus1", "r-plus6"]);
  });

  it("5 · composes with the Active / Paused tab under AND — filter survives a tab switch", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    expect(visible(r)).toEqual(["r-today"]);
    fireEvent.press(r.getByTestId("recurring-tab-paused"));
    await waitFor(() => expect(visible(r)).toEqual(["p-today"]));
    expect(mockApiGet).toHaveBeenCalledWith("/recurring-jobs?status=paused");
    expect(r.getByTestId("recurring-jobs-date-preset-today").props.accessibilityState).toMatchObject({ selected: true });
  });

  it("6 · clear button restores every row and removes the active chip", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-this_month"));
    expect(visible(r).length).toBeLessThan(ACTIVE.length);
    fireEvent.press(r.getByTestId("recurring-jobs-date-clear"));
    expect(visible(r)).toEqual(ACTIVE.map((x) => x.id));
    expect(r.getByTestId("recurring-jobs-date-preset-this_month").props.accessibilityState).toMatchObject({ selected: false });
    expect(r.queryByTestId("recurring-jobs-date-clear")).toBeNull();
  });

  it("zero matches → inline no-match message; Clear stays reachable", async () => {
    mockApiGet.mockImplementation(() => Promise.resolve({ items: [row("only-future", [iso(60)])], counts: { active: 1, paused: 0 } }));
    const r = await mount();
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    expect(visible(r)).toEqual([]);
    expect(r.getByTestId("recurring-jobs-date-no-match")).toBeTruthy();
    expect(r.getByTestId("recurring-jobs-date-clear")).toBeTruthy();
  });

  it("chips use the autobilling-runs pill filter style (inactive / active)", async () => {
    const r = await mount();
    const { colors, radius } = require("@/src/theme");
    const off = flat(r.getByTestId("recurring-jobs-date-preset-today"));
    expect([off.borderRadius, off.paddingHorizontal, off.paddingVertical, off.borderWidth]).toEqual([radius.pill, 12, 6, 1]);
    fireEvent.press(r.getByTestId("recurring-jobs-date-preset-today"));
    const on = flat(r.getByTestId("recurring-jobs-date-preset-today"));
    expect([on.backgroundColor, on.borderColor]).toEqual([colors.brandTertiary, colors.brand]);
  });
});
