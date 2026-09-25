/**
 * Feb-2026 · UncategorizedItemsReport — Bulk Hard-Delete Vitest.
 *
 * Locks the frontend behaviour of the two-stage bulk hard-delete
 * flow on the /reports/uncategorized-items page:
 *
 *   1. Hard-Delete button visibility — hidden when nothing is
 *      selected; visible inside the bulk toolbar once ≥ 1 row is
 *      selected; label shows the selected count.
 *
 *   2. TypedConfirmModal DELETE keyword gate — confirm button is
 *      disabled until the operator types "DELETE" exactly; a
 *      wrong keyword keeps the button disabled.
 *
 *   3. Paid-invoice pre-warning gate — selecting a row on a paid
 *      invoice routes the flow through the amber warning modal
 *      FIRST; the TypedConfirmModal only opens after the operator
 *      clicks "I understand, continue"; the POST payload then
 *      carries acknowledged_lock_bypass=true.
 *
 *   4. Toast counts — after a successful POST the sonner
 *      toast.success is called with the deleted / skipped tally
 *      in the title and a skip-code breakdown in the description.
 *
 *   5. Undo click — the toast action.onClick invokes POST
 *      /reports/uncategorized-items/bulk-hard-delete/<bulk_op_id>
 *      /undo with an empty body; the response is toasted via
 *      toast.info and load() is re-triggered.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── shared mocks ─────────────────────────────────────────────
const _apiGet = vi.fn();
const _apiPost = vi.fn();
const _apiDel = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => _apiGet(...a),
    post: (...a) => _apiPost(...a),
    del: (...a) => _apiDel(...a),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

const _toastSuccess = vi.fn();
const _toastError = vi.fn();
const _toastInfo = vi.fn();
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: (...a) => _toastSuccess(...a),
    error: (...a) => _toastError(...a),
    info: (...a) => _toastInfo(...a),
  }),
}));


import UncategorizedItemsReport from "@/pages/reports/UncategorizedItemsReport";


// ── fixtures ─────────────────────────────────────────────────
const _rowUnpaid = {
  invoice_id: "inv-A",
  invoice_number: "INV-001",
  customer_name: "Ada Lovelace",
  customer_id: "c-1",
  created_at: "2026-02-15T10:00:00Z",
  line_item_index: 0,
  description: "Weekly pool service",
  quantity: 1,
  unit_price: 100,
  amount: 100,
  income_category_id: "",
  income_category_name: "",
  service_category_id: "",
  service_category_name: "",
  missing_income: true,
  missing_service: true,
  invoice_payment_status: "unpaid",
};
const _rowPaid = {
  invoice_id: "inv-B",
  invoice_number: "INV-002",
  customer_name: "Grace Hopper",
  customer_id: "c-2",
  created_at: "2026-02-14T10:00:00Z",
  line_item_index: 2,
  description: "Chemicals",
  quantity: 1,
  unit_price: 40,
  amount: 40,
  income_category_id: "",
  income_category_name: "",
  service_category_id: "",
  service_category_name: "",
  missing_income: true,
  missing_service: true,
  invoice_payment_status: "paid",
};

const _fixtureRows = [_rowUnpaid, _rowPaid];


function _defaultApiImpl(path) {
  if (path.startsWith("/income-categories")) {
    return Promise.resolve({ items: [] });
  }
  if (path.startsWith("/service-categories")) {
    return Promise.resolve({ items: [] });
  }
  if (path.startsWith("/reports/uncategorized-items")) {
    return Promise.resolve({
      items: _fixtureRows,
      total: _fixtureRows.length,
      range: "all",
      missing: "either",
    });
  }
  return Promise.resolve({ items: [], total: 0 });
}


function _mount(url = "/reports/uncategorized-items") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <UncategorizedItemsReport />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  _apiGet.mockReset();
  _apiPost.mockReset();
  _apiDel.mockReset();
  _toastSuccess.mockReset();
  _toastError.mockReset();
  _toastInfo.mockReset();
  _apiGet.mockImplementation(_defaultApiImpl);
});
afterEach(() => cleanup());


// ─────────────────────────────────────────────────────────────
// §1  Button visibility
// ─────────────────────────────────────────────────────────────
describe("Bulk hard-delete · button visibility", () => {
  it("Hard Delete button is hidden until at least one row is selected", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    // Bulk toolbar (and therefore hard-delete button) not yet in DOM.
    expect(screen.queryByTestId("uncategorized-bulk-toolbar")).toBeNull();
    expect(screen.queryByTestId("uncat-hard-delete-btn")).toBeNull();
  });

  it("selecting a row reveals the Hard Delete button with the selected count", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    const btn = await screen.findByTestId("uncat-hard-delete-btn");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toContain("1");
  });
});


// ─────────────────────────────────────────────────────────────
// §2  DELETE keyword gate
// ─────────────────────────────────────────────────────────────
describe("Bulk hard-delete · DELETE keyword gate", () => {
  it("confirm button is disabled until 'DELETE' is typed exactly", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));

    // Unpaid row → skips paid-warning gate, goes straight to typed-confirm.
    const modal = await screen.findByTestId("uncat-hard-delete-confirm-modal");
    expect(modal).toBeTruthy();
    const confirmBtn = screen.getByTestId("uncat-hard-delete-confirm-confirm");
    expect(confirmBtn).toBeDisabled();

    // Wrong keyword — still disabled.
    fireEvent.change(
      screen.getByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "delete" } }, // lowercase — must be case-sensitive
    );
    expect(confirmBtn).toBeDisabled();

    // Correct keyword arms the button.
    fireEvent.change(
      screen.getByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "DELETE" } },
    );
    expect(confirmBtn).not.toBeDisabled();
  });

  it("does not open the paid-warning modal for a selection with no paid invoices", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));

    // Confirm modal is shown; paid-warning is NOT.
    await screen.findByTestId("uncat-hard-delete-confirm-modal");
    expect(screen.queryByTestId("uncat-hard-delete-paid-warning")).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────
// §3  Paid-invoice pre-warning gate
// ─────────────────────────────────────────────────────────────
describe("Bulk hard-delete · paid-invoice pre-warning gate", () => {
  it("selecting a paid-invoice row routes to the amber warning modal first", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-B::2");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-B::2"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));

    // Paid-warning modal shown; typed-confirm modal NOT yet.
    await screen.findByTestId("uncat-hard-delete-paid-warning");
    expect(screen.queryByTestId("uncat-hard-delete-confirm-modal")).toBeNull();
    // Body copy mentions the paid count.
    expect(
      screen.getByTestId("uncat-hard-delete-paid-warning").textContent,
    ).toMatch(/paid invoice/i);
  });

  it("clicking 'I understand, continue' opens the typed-confirm modal", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-B::2");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-B::2"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));

    fireEvent.click(await screen.findByTestId(
      "uncat-hard-delete-paid-warning-acknowledge"));

    // Paid-warning closes; typed-confirm opens.
    await screen.findByTestId("uncat-hard-delete-confirm-modal");
    expect(screen.queryByTestId("uncat-hard-delete-paid-warning")).toBeNull();
  });

  it("POST payload carries acknowledged_lock_bypass=true when paid rows were acknowledged", async () => {
    _apiPost.mockResolvedValue({
      bulk_op_id: "bo-paid-1",
      requested: 1,
      deleted: 1,
      skipped: [],
    });
    _mount();
    await screen.findByTestId("uncategorized-row-inv-B::2");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-B::2"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));
    fireEvent.click(await screen.findByTestId(
      "uncat-hard-delete-paid-warning-acknowledge"));
    fireEvent.change(
      await screen.findByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "DELETE" } },
    );
    fireEvent.click(screen.getByTestId("uncat-hard-delete-confirm-confirm"));

    await waitFor(() => {
      expect(_apiPost).toHaveBeenCalled();
    });
    const call = _apiPost.mock.calls.find(
      (c) => c[0] === "/reports/uncategorized-items/bulk-hard-delete",
    );
    expect(call).toBeTruthy();
    const [, body] = call;
    expect(body.acknowledged_lock_bypass).toBe(true);
    expect(Array.isArray(body.rows)).toBe(true);
    expect(body.rows[0]).toMatchObject({
      invoice_id: "inv-B",
      line_item_index: 2,
      description: "Chemicals",
      unit_price: 40,
    });
  });
});


// ─────────────────────────────────────────────────────────────
// §4  Toast counts (deleted + skipped breakdown)
// ─────────────────────────────────────────────────────────────
describe("Bulk hard-delete · success toast counts", () => {
  it("toasts the deleted count + a skip-code breakdown", async () => {
    _apiPost.mockResolvedValue({
      bulk_op_id: "bo-1",
      requested: 2,
      deleted: 1,
      skipped: [
        { invoice_id: "inv-A", line_item_index: 5, code: "content_shifted" },
        { invoice_id: "inv-A", line_item_index: 6, code: "content_shifted" },
        { invoice_id: "inv-A", line_item_index: 7, code: "locked_paid" },
      ],
    });
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));
    fireEvent.change(
      await screen.findByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "DELETE" } },
    );
    fireEvent.click(screen.getByTestId("uncat-hard-delete-confirm-confirm"));

    await waitFor(() => expect(_toastSuccess).toHaveBeenCalled());
    const [msg, opts] = _toastSuccess.mock.calls[0];
    // Title: deleted count + skipped count.
    expect(msg).toMatch(/Deleted 1 line item/);
    expect(msg).toMatch(/3 skipped/);
    // Description: skip-code breakdown.
    expect(opts.description).toMatch(/2 content_shifted/);
    expect(opts.description).toMatch(/1 locked_paid/);
    // 10-second window per G.6a ruling.
    expect(opts.duration).toBe(10000);
  });

  it("only skips → toast still succeeds but without an Undo action", async () => {
    _apiPost.mockResolvedValue({
      bulk_op_id: "bo-2",
      requested: 1,
      deleted: 0,
      skipped: [
        { invoice_id: "inv-A", line_item_index: 5, code: "locked_paid" },
      ],
    });
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));
    fireEvent.change(
      await screen.findByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "DELETE" } },
    );
    fireEvent.click(screen.getByTestId("uncat-hard-delete-confirm-confirm"));

    await waitFor(() => expect(_toastSuccess).toHaveBeenCalled());
    const [msg, opts] = _toastSuccess.mock.calls[0];
    expect(msg).toMatch(/Nothing deleted/);
    // No undo action when nothing was actually deleted.
    expect(opts.action).toBeUndefined();
  });
});


// ─────────────────────────────────────────────────────────────
// §5  Undo click → hits the undo endpoint
// ─────────────────────────────────────────────────────────────
describe("Bulk hard-delete · undo action", () => {
  it("clicking the toast Undo POSTs to the undo endpoint and info-toasts the restored count", async () => {
    _apiPost.mockImplementation((path) => {
      if (path === "/reports/uncategorized-items/bulk-hard-delete") {
        return Promise.resolve({
          bulk_op_id: "bo-undo-1",
          requested: 1,
          deleted: 1,
          skipped: [],
        });
      }
      if (path.includes("/bulk-hard-delete/") && path.endsWith("/undo")) {
        return Promise.resolve({
          bulk_op_id: "bo-undo-1",
          audit_rows: 1,
          restored: 1,
          already_undone: 0,
          skipped: [],
        });
      }
      return Promise.resolve({});
    });
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    fireEvent.click(screen.getByTestId("uncategorized-row-select-inv-A::0"));
    fireEvent.click(await screen.findByTestId("uncat-hard-delete-btn"));
    fireEvent.change(
      await screen.findByTestId("uncat-hard-delete-confirm-input"),
      { target: { value: "DELETE" } },
    );
    fireEvent.click(screen.getByTestId("uncat-hard-delete-confirm-confirm"));

    await waitFor(() => expect(_toastSuccess).toHaveBeenCalled());
    const [, opts] = _toastSuccess.mock.calls[0];
    // Action wired with an Undo callback.
    expect(opts.action).toBeTruthy();
    expect(opts.action.label).toBe("Undo");

    // Invoke the Undo callback directly (same as clicking the toast action).
    await opts.action.onClick();

    // Undo endpoint hit with the correct bulk_op_id + empty body.
    const undoCall = _apiPost.mock.calls.find(
      (c) => typeof c[0] === "string"
        && c[0].includes("/bulk-hard-delete/bo-undo-1/undo"),
    );
    expect(undoCall).toBeTruthy();
    expect(undoCall[1]).toEqual({});

    // Info toast with the restored count.
    await waitFor(() => expect(_toastInfo).toHaveBeenCalled());
    expect(_toastInfo.mock.calls[0][0]).toMatch(/Restored 1 line item/);
  });
});
