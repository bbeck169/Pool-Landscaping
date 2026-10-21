/**
 * TD-81 (B-narrow) · Revenue-by-Category drill-down Business Unit re-classify.
 * Web parity: DashboardDrillDownModal.jsx `commitBusinessUnit` (K48 + A2).
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPatch = jest.fn();
const mockPost = jest.fn();
const mockPush = jest.fn();
const mockToast = jest.fn();
let mockRole = "admin";

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), patch: (u: string, b: any) => mockPatch(u, b), post: (u: string, b: any) => mockPost(u, b) } }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

import RevenueByCategoryTile from "@/src/components/dashboard/RevenueByCategoryTile";

const RANGE = { start: "2026-10-01", end: "2026-10-31" };
const CATS = [{ id: "c-pool", name: "Pool" }, { id: "c-land", name: "Landscaping" }];
const ROW = { invoice_id: "inv-1", invoice_number: "INV-1", line_index: 0, description: "Weekly clean", extended: 120, category: "Uncategorized", business_unit: "", invoice_status: "paid", payment_status: "paid" };
let rows: any[] = [ROW];
let catsResp: any = { items: CATS, total: 2 };

beforeEach(() => {
  mockRole = "admin"; rows = [ROW]; catsResp = { items: CATS, total: 2 };
  mockPush.mockClear(); mockToast.mockClear();
  mockPatch.mockReset().mockResolvedValue({ id: "inv-1" });
  mockPost.mockReset().mockResolvedValue({ ok: true });
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u.startsWith("/admin/dashboard/revenue-by-category")) return { total: 120, items: [{ category: "Uncategorized", amount: 120, count: 1 }] };
    if (u.startsWith("/dashboard/income/by-category/rows")) return { rows, total: rows.length, next_cursor: null };
    if (u.startsWith("/income-categories")) { if (catsResp instanceof Error) throw catsResp; return catsResp; }
    throw new Error("unexpected " + u);
  });
});

const K = "income-row-inv-1-0";
const open = async () => {
  const q = render(<RevenueByCategoryTile range={RANGE} />);
  await waitFor(() => q.getByTestId("revenue-cat-legend-drill-Uncategorized"));
  fireEvent.press(q.getByTestId("revenue-cat-legend-drill-Uncategorized"));
  await waitFor(() => q.getByTestId(`${K}-bu-trigger`));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/income-categories?include_archived=false"));
  return q;
};
const pick = async (q: any, id: string) => {
  fireEvent.press(q.getByTestId(`${K}-bu-trigger`));
  await waitFor(() => q.getByTestId(`bu-option-${id}`));
  await act(async () => { fireEvent.press(q.getByTestId(`bu-option-${id}`)); });
};

describe("drill-down Re-classify", () => {
  it("row tap still opens the invoice; trigger opens picker with options from {items}", async () => {
    rows = [{ ...ROW, business_unit: "Landscaping" }];
    const q = await open();
    fireEvent.press(q.getByTestId(`${K}-bu-trigger`));
    await waitFor(() => q.getByTestId("bu-picker-sheet"));
    expect(q.getByTestId("bu-option-c-land").props.accessibilityState?.selected).toBe(true);
    expect(q.getByTestId("bu-option-c-pool").props.accessibilityState?.selected).toBe(false);
    fireEvent.press(q.getByTestId(K));
    expect(mockPush).toHaveBeenCalledWith("/quote/inv-1");
  });

  it("pick → minimal PATCH (admin A2) + audit companion; 'Moved to Pool' chip", async () => {
    const q = await open();
    await pick(q, "c-pool");
    expect(mockPatch).toHaveBeenCalledWith("/quotes/inv-1", { business_unit: "Pool", business_unit_id: "c-pool", confirm_edit_sent: true, acknowledged_lock_bypass: true });
    expect(mockPost).toHaveBeenCalledWith("/dashboard/drilldown/line-item-audit", {
      tile: "income-by-category", invoice_id: "inv-1", line_index: 0, field: "business_unit", before: "Uncategorized", after: "Pool",
    });
    await waitFor(() => q.getByTestId(`${K}-bu-moved`));
    expect(q.getByText("Moved to Pool")).toBeTruthy();
  });

  it("picking the current BU → no PATCH", async () => {
    rows = [{ ...ROW, business_unit: "Pool" }];
    const q = await open();
    await pick(q, "c-pool");
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it("void/cancelled → trigger disabled + locked note; no PATCH", async () => {
    rows = [{ ...ROW, invoice_status: "void" }];
    const q = await open();
    expect(q.getByTestId(`${K}-bu-trigger`).props.accessibilityState?.disabled).toBe(true);
    expect(q.getByTestId(`${K}-bu-locked`)).toBeTruthy();
    fireEvent.press(q.getByTestId(`${K}-bu-trigger`));
    expect(q.queryByTestId("bu-option-c-pool")).toBeNull();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it("PATCH rejects → rollback to original BU, inline error + toast, no chip", async () => {
    rows = [{ ...ROW, business_unit: "Landscaping" }];
    mockPatch.mockRejectedValueOnce(Object.assign(new Error("Conflict"), { detail: { error: "invoice_locked" } }));
    const q = await open();
    await pick(q, "c-pool");
    await waitFor(() => q.getByTestId(`${K}-error`));
    expect(q.getByText("invoice_locked")).toBeTruthy();
    expect(mockToast).toHaveBeenCalledWith("invoice_locked", "error");
    expect(q.queryByTestId(`${K}-bu-moved`)).toBeNull();
    fireEvent.press(q.getByTestId(`${K}-bu-trigger`));
    await waitFor(() => q.getByTestId("bu-option-c-land"));
    expect(q.getByTestId("bu-option-c-land").props.accessibilityState?.selected).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("audit companion failure does not block the save (best-effort)", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockPost.mockRejectedValueOnce(new Error("audit down"));
    const q = await open();
    await pick(q, "c-land");
    await waitFor(() => q.getByText("Moved to Landscaping"));
    expect(mockToast).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("close after a save → tile refetches; close without a save → no refetch", async () => {
    const tileCalls = () => mockGet.mock.calls.filter((c) => String(c[0]).startsWith("/admin/dashboard/revenue-by-category")).length;
    const q = await open();
    fireEvent.press(q.getByTestId("drilldown-income-by-category-close"));
    expect(tileCalls()).toBe(1);
    fireEvent.press(q.getByTestId("revenue-cat-legend-drill-Uncategorized"));
    await waitFor(() => q.getByTestId(`${K}-bu-trigger`));
    await pick(q, "c-pool");
    await waitFor(() => q.getByTestId(`${K}-bu-moved`));
    await act(async () => { fireEvent.press(q.getByTestId("drilldown-income-by-category-close")); });
    await waitFor(() => expect(tileCalls()).toBe(2));
  });

  it("income-categories fetch fails → picker shows empty state, no crash", async () => {
    catsResp = new Error("boom");
    const q = await open();
    fireEvent.press(q.getByTestId(`${K}-bu-trigger`));
    await waitFor(() => q.getByTestId("bu-picker-empty"));
    expect(mockPatch).not.toHaveBeenCalled();
  });
});
