/**
 * Dashboard parity · `app/properties.tsx` (web PropertiesListPage mirror)
 * — target of Active Accounts / Pool / Landscaping / Both Service tiles.
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

let mockParams: any = {};
const mockPush = jest.fn();
const mockSetParams = jest.fn();
const mockGet = jest.fn(async (_u: string): Promise<any> => ({ items: [] }));

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) }, ApiError: class ApiError extends Error {} }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockParams,
  useRouter: () => ({ push: mockPush, back: jest.fn(), setParams: mockSetParams }),
}));
jest.mock("@/src/components/widgets", () => {
  const { View, Text, Pressable } = jest.requireActual("react-native");
  return {
    Header: (p: any) => <View><Text>{p.title}</Text></View>,
    FilterRow: (p: any) => (
      <View testID={p.testID}>
        {p.options.map((o: any) => (
          <Pressable key={o.key} testID={`${p.testID}-${o.key}`} onPress={() => p.onChange(o.key)}>
            <Text>{o.key === p.value ? `[${o.label}]` : o.label}</Text>
          </Pressable>
        ))}
      </View>
    ),
  };
});

import PropertiesList from "@/app/properties";

const PROPS = [
  { id: "p1", customer_id: "c1", label: "Main house", address: { line1: "1 Elm", city: "Austin", state: "TX" }, service_category: "pool", active: true },
  { id: "p2", customer_id: "c1", label: "", address: null, service_category: null, active: true },
  { id: "p3", customer_id: "c2", label: "Ranch", address: { line1: "9 Oak" }, service_category: "both", active: false },
];

function routeApi(customersIdsIn: any[] = [{ id: "c1", name: "Zed Pool" }]) {
  mockGet.mockImplementation(async (u: string) => {
    if (u.startsWith("/properties")) return { items: PROPS };
    if (u.startsWith("/customers?ids_in=")) return customersIdsIn; // BE ignores ids_in → bare list
    if (u.startsWith("/customers/c2")) return { id: "c2", name: "Amy Lawn" };
    throw new Error("unexpected " + u);
  });
}

beforeEach(() => {
  mockGet.mockReset(); mockPush.mockClear(); mockSetParams.mockClear();
  mockParams = {};
});

it("tile deep-link ?is_active=true&service_category=pool → GET /properties with both params; chips selected", async () => {
  mockParams = { is_active: "true", service_category: "pool" };
  routeApi();
  const q = render(<PropertiesList />);
  await waitFor(() => q.getByTestId("properties-list-grouped"));
  expect(mockGet).toHaveBeenCalledWith("/properties?is_active=true&service_category=pool");
  expect(q.getByText("[Active]")).toBeTruthy();
  expect(q.getByText("[Pool]")).toBeTruthy();
});

it("Active Accounts link (is_active only) → no service_category; default with no params is is_active=true", async () => {
  mockParams = {};
  routeApi();
  render(<PropertiesList />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/properties?is_active=true"));
});

it("groups by customer, hydrates names (ids_in + per-id fallback), sorts by name, renders row parts", async () => {
  routeApi();
  const q = render(<PropertiesList />);
  await waitFor(() => q.getByText("Amy Lawn"));
  expect(q.getByText("Zed Pool")).toBeTruthy();
  expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/^\/customers\?ids_in=c1%2Cc2$/));
  expect(mockGet).toHaveBeenCalledWith("/customers/c2?slim=1");
  // order: Amy (c2) before Zed (c1)
  const names = q.UNSAFE_root.findAll((n: any) => /^properties-group-name-/.test(String(n.props?.testID)) && typeof n.type === "string")
    .map((n: any) => n.props.testID);
  expect(names.filter((v: string, i: number, a: string[]) => a.indexOf(v) === i)).toEqual(["properties-group-name-c2", "properties-group-name-c1"]);
  expect(q.getByText("· 2 properties")).toBeTruthy();
  expect(q.getByText("· 1 property")).toBeTruthy();
  expect(q.getByText("(unlabelled)")).toBeTruthy();
  expect(q.getByText("No address")).toBeTruthy();
  expect(q.getByText("1 Elm, Austin, TX")).toBeTruthy();
  expect(q.getAllByTestId("property-category-chip-pool").length).toBeGreaterThan(0);
  expect(q.getAllByTestId("property-category-chip-unset").length).toBeGreaterThan(0);
  expect(q.getAllByTestId("property-category-chip-both").length).toBeGreaterThan(0);
  expect(q.getAllByTestId("property-active-badge-inactive").length).toBeGreaterThan(0);
});

it("row tap → customer profile Properties section", async () => {
  routeApi();
  const q = render(<PropertiesList />);
  await waitFor(() => q.getByTestId("property-row-p3"));
  fireEvent.press(q.getByTestId("property-row-p3"));
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/customer/[id]", params: { id: "c2", tab: "properties" } });
});

it("empty → web copy + Clear filters widens to all/all", async () => {
  mockParams = { service_category: "landscaping" };
  mockGet.mockImplementation(async () => ({ items: [] }));
  const q = render(<PropertiesList />);
  await waitFor(() => q.getByTestId("properties-list-empty"));
  expect(q.getByText("No properties match")).toBeTruthy();
  fireEvent.press(q.getByTestId("properties-list-clear-filters"));
  await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith("/properties"));
});

it("error (e.g. non-admin 403) → inline error, not a crash", async () => {
  mockGet.mockImplementation(async () => { throw new Error("nope"); });
  const q = render(<PropertiesList />);
  await waitFor(() => q.getByTestId("properties-list-error"));
});

it("search is debounced and sent as ?search=", async () => {
  jest.useFakeTimers();
  try {
    routeApi();
    const q = render(<PropertiesList />);
    fireEvent.changeText(q.getByTestId("properties-list-search"), "elm");
    await act(async () => { jest.advanceTimersByTime(350); });
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/properties?is_active=true&search=elm"));
  } finally {
    jest.useRealTimers();
  }
});
