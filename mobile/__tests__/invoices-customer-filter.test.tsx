/**
 * TD-79 (web db3ef6d2f) — mobile invoice list honours `?customer_id=<cid>`
 * (target of the customer-profile Overview "View all"). `/invoices/overview`
 * has no customer param, so the screen filters client-side; a clearable
 * chip shows the active customer filter.
 */
import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react-native";

import Invoices from "@/app/invoices";

let mockParams: any = {};
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async () => ({
      summary: null,
      invoices: [
        { id: "i1", customer_id: "c1", customer_name: "Alice Pool", title: "Weekly", total: 100, payment_status: "unpaid" },
        { id: "i2", customer_id: "c2", customer_name: "Bob Lawn", title: "Mow", total: 50, payment_status: "paid" },
        { id: "i3", customer_id: "c1", customer_name: "Alice Pool", title: "Acid wash", total: 300, payment_status: "paid" },
      ],
    })),
    post: jest.fn(),
  },
}));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useLocalSearchParams: () => mockParams,
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View } = jest.requireActual("react-native");
  return { Header: () => null, FilterRow: (p: any) => <View testID={p.testID} /> };
});

const rowIds = (q: any) =>
  q.UNSAFE_root.findAll((n: any) => typeof n.props?.testID === "string" && /^invoice-i\d$/.test(n.props.testID))
    .map((n: any) => n.props.testID)
    .filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);

it("?customer_id=c1 → only that customer's invoices + chip; Clear restores all", async () => {
  mockParams = { customer_id: "c1" };
  const q = render(<Invoices />);
  await waitFor(() => q.getByTestId("invoices-customer-filter-chip"));
  expect(q.getByText("Customer: Alice Pool")).toBeTruthy();
  await waitFor(() => expect(rowIds(q).sort()).toEqual(["invoice-i1", "invoice-i3"]));
  fireEvent.press(q.getByTestId("invoices-customer-filter-clear"));
  expect(q.queryByTestId("invoices-customer-filter-chip")).toBeNull();
  expect(rowIds(q).sort()).toEqual(["invoice-i1", "invoice-i2", "invoice-i3"]);
});

it("no param → unchanged list, no chip", async () => {
  mockParams = {};
  const q = render(<Invoices />);
  await waitFor(() => expect(rowIds(q)).toHaveLength(3));
  expect(q.queryByTestId("invoices-customer-filter-chip")).toBeNull();
});
