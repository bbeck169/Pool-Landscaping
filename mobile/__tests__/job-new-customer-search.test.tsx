/**
 * New Job · Select Customer sheet search (client-side; GET /customers
 * returns the bare array — no pagination).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockOfflineWrite = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async (p: string) => (p === "/customers" ? mockCustomers : p === "/technicians" ? [] : [])),
    post: jest.fn(),
  },
}));
jest.mock("@/src/services/offlineWrite", () => ({ offlineWrite: (...a: any[]) => mockOfflineWrite(...a) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("react-native-keyboard-controller", () => {
  const { ScrollView } = require("react-native");
  return { KeyboardAwareScrollView: (props: any) => <ScrollView {...props} /> };
});
jest.mock("@/app/customer/new", () => {
  const { TextInput } = require("react-native");
  return { Field: ({ value, onChangeText, testID }: any) => <TextInput value={value} onChangeText={onChangeText} testID={testID} /> };
});
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({}),
  useRouter: () => ({ back: jest.fn(), replace: jest.fn(), push: jest.fn() }),
}));

const mockCustomers = [
  { id: "c1", name: "Bill Wood", first_name: "Bill", last_name: "Wood", email: "bill@wood.com", phone: "(555) 010-2030" },
  { id: "c2", name: "Kevin Piska", first_name: "Kevin", last_name: "Piska", emails: [{ address: "kp@piska.io" }] },
  { id: "c3", name: "Kevin Smith", first_name: "Kevin", last_name: "Smith", mobiles: [{ number_e164: "+15559876543" }] },
  { id: "c4", name: "Jennifer Obrien", display_name: "Jen O" },
];

import NewJob, { customerMatches } from "@/app/job/new";

async function openSheet() {
  const q = render(<NewJob />);
  await act(async () => {});
  fireEvent.press(q.getByTestId("select-customer"));
  await waitFor(() => q.getByTestId("customer-sheet-search"));
  return q;
}
const visibleIds = (q: any) => mockCustomers.map((c) => c.id).filter((id) => q.queryByTestId(`pick-customer-${id}`));

beforeEach(() => mockOfflineWrite.mockReset());

describe("New Job · Select Customer search", () => {
  it("1 · search input renders at the top of the sheet with search keyboard props", async () => {
    const q = await openSheet();
    const input = q.getByTestId("customer-sheet-search");
    expect(input.props.placeholder).toBe("Search customers…");
    expect(input.props.autoCorrect).toBe(false);
    expect(input.props.autoCapitalize).toBe("none");
    expect(input.props.returnKeyType).toBe("search");
    expect(q.queryByTestId("customer-sheet-search-clear")).toBeNull();
    expect(visibleIds(q)).toEqual(["c1", "c2", "c3", "c4"]);
  });

  it("2 · typing filters case-insensitively (name, last name, email, display name)", async () => {
    const q = await openSheet();
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "KEVIN");
    expect(visibleIds(q)).toEqual(["c2", "c3"]);
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "smi");
    expect(visibleIds(q)).toEqual(["c3"]);
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "PISKA.IO");
    expect(visibleIds(q)).toEqual(["c2"]);
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "jen o");
    expect(visibleIds(q)).toEqual(["c4"]);
  });

  it("3 · no matches → empty-state copy", async () => {
    const q = await openSheet();
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "xyz");
    expect(visibleIds(q)).toEqual([]);
    expect(q.getByTestId("customer-sheet-empty").props.children).toBe("No customers match 'xyz'");
  });

  it("4 · clear button resets the filter", async () => {
    const q = await openSheet();
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "xyz");
    fireEvent.press(q.getByTestId("customer-sheet-search-clear"));
    expect(q.getByTestId("customer-sheet-search").props.value).toBe("");
    expect(q.queryByTestId("customer-sheet-empty")).toBeNull();
    expect(visibleIds(q)).toEqual(["c1", "c2", "c3", "c4"]);
  });

  it("5 · selecting a filtered row selects that customer (customer_id flows to save)", async () => {
    mockOfflineWrite.mockResolvedValueOnce({ queued: false });
    const q = await openSheet();
    fireEvent.changeText(q.getByTestId("customer-sheet-search"), "smith");
    fireEvent.press(q.getByTestId("pick-customer-c3"));
    fireEvent.changeText(q.getByTestId("job-title-input"), "Weekly clean");
    await act(async () => { fireEvent.press(q.getByTestId("save-job-button")); });
    expect(mockOfflineWrite).toHaveBeenCalledTimes(1);
    expect(mockOfflineWrite.mock.calls[0][0].payload.customer_id).toBe("c3");
    // Query resets on select → reopening shows the full list.
    fireEvent.press(q.getByTestId("select-customer"));
    await waitFor(() => q.getByTestId("customer-sheet-search"));
    expect(q.getByTestId("customer-sheet-search").props.value).toBe("");
  });
});

describe("customerMatches", () => {
  it("phone digits match (>= 3 digits) across phone + mobiles; short digit queries don't", () => {
    expect(customerMatches(mockCustomers[0], "010-20")).toBe(true);
    expect(customerMatches(mockCustomers[2], "987 65")).toBe(true);
    expect(customerMatches(mockCustomers[2], "55")).toBe(false);
    expect(customerMatches(mockCustomers[1], "  ")).toBe(true);
    expect(customerMatches({ id: "x" }, "bill")).toBe(false);
  });
});
