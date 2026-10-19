/**
 * TD-79 (web db3ef6d2f) — mobile customer profile Overview · invoice list
 * section (last 10 + "View all").
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, waitFor, fireEvent } from "@testing-library/react-native";

import { api } from "@/src/api";
import CustomerInvoiceList, { sortByCreatedDesc, OVERVIEW_INVOICE_CAP } from "@/src/components/customers/CustomerInvoiceList";

const mockPush = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: jest.fn() } }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));

const inv = (n: number, extra: any = {}) => ({
  id: `inv-${String(n).padStart(2, "0")}`, invoice_number: `INV-${n}`, title: `Service ${n}`,
  due_date: "2026-09-30", total: 100 + n, payment_status: "unpaid",
  created_at: `2026-08-${String(n).padStart(2, "0")}T10:00:00Z`, ...extra,
});
const rowIds = (q: any) =>
  q.UNSAFE_root.findAll((n: any) => typeof n.props?.testID === "string" && n.props.testID.startsWith("cd-overview-invoice-row-"))
    .map((n: any) => n.props.testID).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);

beforeEach(() => { (api.get as jest.Mock).mockReset(); mockPush.mockReset(); });

it("fetches /quotes?doc_type=invoice&customer_id=<cid>&limit=10&offset=0", async () => {
  (api.get as jest.Mock).mockResolvedValue({ rows: [], total_count: 0, has_more: false });
  render(<CustomerInvoiceList customerId="c 1" />);
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/quotes?doc_type=invoice&customer_id=c%201&limit=10&offset=0"));
});

it("sort: created_at DESC, id lex DESC tiebreak", () => {
  const out = sortByCreatedDesc([
    { id: "a", created_at: "2026-01-01" }, { id: "c", created_at: "2026-03-01" },
    { id: "b", created_at: "2026-03-01" }, { id: "z" },
  ]);
  expect(out.map((r) => r.id)).toEqual(["c", "b", "a", "z"]);
});

it("total_count > 10 → exactly 10 rows newest-first + View all → /invoices?customer_id=<cid>", async () => {
  const rows = Array.from({ length: 12 }, (_, i) => inv(i + 1));
  (api.get as jest.Mock).mockResolvedValue({ rows, total_count: 148, has_more: true });
  const q = render(<CustomerInvoiceList customerId="c1" />);
  await waitFor(() => expect(rowIds(q)).toHaveLength(OVERVIEW_INVOICE_CAP));
  expect(rowIds(q)[0]).toBe("cd-overview-invoice-row-inv-12");
  expect(q.getByTestId("cd-overview-invoices-count").props.children).toBe("  (148)");
  fireEvent.press(q.getByTestId("cd-overview-invoices-view-all"));
  expect(mockPush).toHaveBeenCalledWith("/invoices?customer_id=c1");
});

it("total_count ≤ 10 → all rows, no View all; row shows number/title/due/amount/status; tap → /quote/<id>", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    rows: [inv(1), inv(2, { title: "Import #259", service_description: "Weekly Pool", payment_status: "paid" }),
      inv(3, { payment_status: "overdue" }), inv(4, { payment_status: "pending_reconciliation" })],
    total_count: 4, has_more: false,
  });
  const q = render(<CustomerInvoiceList customerId="c1" />);
  await waitFor(() => expect(rowIds(q)).toHaveLength(4));
  expect(q.queryByTestId("cd-overview-invoices-view-all")).toBeNull();
  expect(q.getByText("Pending reconciliation")).toBeTruthy();
  expect(q.getByText("Weekly Pool")).toBeTruthy(); // shared Import #<n> resolver
  expect(q.getByText("INV-2 · Due 2026-09-30")).toBeTruthy();
  expect(q.getByText("$102.00")).toBeTruthy();
  expect(q.getByText("Paid")).toBeTruthy();
  expect(q.getByText("Overdue")).toBeTruthy();
  fireEvent.press(q.getByTestId("cd-overview-invoice-row-inv-02"));
  expect(mockPush).toHaveBeenCalledWith("/quote/inv-02");
});

it("exactly 10 → no View all (boundary)", async () => {
  (api.get as jest.Mock).mockResolvedValue({ rows: Array.from({ length: 10 }, (_, i) => inv(i + 1)), total_count: 10 });
  const q = render(<CustomerInvoiceList customerId="c1" />);
  await waitFor(() => expect(rowIds(q)).toHaveLength(10));
  expect(q.queryByTestId("cd-overview-invoices-view-all")).toBeNull();
});

it("bare-array payload fallback", async () => {
  (api.get as jest.Mock).mockResolvedValue([inv(1), inv(2)]);
  const q = render(<CustomerInvoiceList customerId="c1" />);
  await waitFor(() => expect(rowIds(q)).toHaveLength(2));
});

it("loading → spinner; empty → 'No invoices yet.'", async () => {
  let resolve: any;
  (api.get as jest.Mock).mockReturnValue(new Promise((r) => { resolve = r; }));
  const q = render(<CustomerInvoiceList customerId="c1" />);
  expect(q.getByTestId("cd-overview-invoices-loading")).toBeTruthy();
  resolve({ rows: [], total_count: 0 });
  await waitFor(() => q.getByTestId("cd-overview-invoices-empty"));
  expect(q.getByText("No invoices yet.")).toBeTruthy();
  expect(q.queryByTestId("cd-overview-invoices-count")).toBeNull();
});

it("error → inline error pill", async () => {
  (api.get as jest.Mock).mockRejectedValue(new Error("boom"));
  const q = render(<CustomerInvoiceList customerId="c1" />);
  await waitFor(() => q.getByTestId("cd-overview-invoices-error"));
  expect(q.getByText("boom")).toBeTruthy();
});

it("placement: admin-gated, after contact block, before payment-method card", () => {
  const src = fs.readFileSync(path.join(__dirname, "../app/customer/[id].tsx"), "utf8");
  const slot = src.indexOf('testID="customer-overview-invoices-slot"');
  expect(slot).toBeGreaterThan(src.indexOf("<MultiContact"));
  expect(slot).toBeLessThan(src.indexOf('testID="customer-payment-method"'));
  expect(src).toContain("<CustomerInvoiceList customerId={id as string} />");
});
