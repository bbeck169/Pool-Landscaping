/**
 * Feb-2026 · P44 — "No payment on file" filter chip + row action.
 *
 * Pins:
 *   1. Chip renders with the canonical testid + count badge.
 *   2. Default OFF; toggling emits ``has_payment_method=false`` on
 *      the list fetch and writes ``has_payment_method=0`` to the URL.
 *   3. Count badge hydrates from a standalone ``count_only`` call.
 *   4. Composes AND with the missing-address chip in a single fetch.
 *   5. URL hydration: ``?has_payment_method=0`` → chip pre-selected.
 *   6. Row action button is visible for rows with
 *      ``has_card_on_file=false`` and hidden for rows with
 *      ``has_card_on_file=true``.
 *   7. Clicking the row action POSTs to
 *      ``/customers/{id}/send-card-add-link`` and emits a
 *      success-toast copy that includes the customer contacts.
 *   8. Info banner renders only when the filter is ON.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin", effectiveRole: "admin" }),
}));

import CustomersList from "@/pages/customers/CustomersList";

const _row = (over = {}) => ({
  id: "cust-" + Math.random().toString(36).slice(2, 8),
  name: "Test Customer",
  email: "t@test.com",
  phone: "+16025551212",
  is_active: true,
  has_card_on_file: false,
  effective_require_card_on_file: false,
  saved_payment_methods_count: 0,
  ...over,
});

function _installMockGet({ items = [], noPaymentCount = 5 } = {}) {
  mockGet.mockImplementation((path) => {
    if (path === "/customers?count_only=true&has_payment_method=false") {
      return Promise.resolve({ count: noPaymentCount });
    }
    if (path.includes("count_only=true")) return Promise.resolve({ count: 0 });
    return Promise.resolve({
      items, total: items.length, page: 1, page_size: 50,
      total_pages: items.length ? 1 : 0,
    });
  });
}

function _renderAt(url = "/customers", opts = {}) {
  _installMockGet(opts);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CustomersList />
    </MemoryRouter>);
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
});

describe("CustomersList · P44 no-payment filter + row action", () => {
  it("renders the chip with the canonical testid", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-no-payment-filter")).toBeTruthy());
  });

  it("chip is OFF by default and shows the hydrated count", async () => {
    _renderAt("/customers", { noPaymentCount: 12 });
    await waitFor(() => {
      const chip = screen.getByTestId("customers-no-payment-filter");
      expect(chip.getAttribute("aria-pressed")).toBe("false");
      const cnt = screen.getByTestId("customers-no-payment-count");
      expect(cnt.textContent).toMatch(/12/);
    });
    const calls = mockGet.mock.calls.map((c) => c[0]);
    expect(calls).toContain(
      "/customers?count_only=true&has_payment_method=false",
    );
  });

  it("clicking the chip fires a fetch with has_payment_method=false", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-no-payment-filter")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-no-payment-filter"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toContain("has_payment_method=false");
    });
  });

  it("URL hydration: ?has_payment_method=0 pre-selects the chip", async () => {
    _renderAt("/customers?has_payment_method=0");
    await waitFor(() => {
      const chip = screen.getByTestId("customers-no-payment-filter");
      expect(chip.getAttribute("aria-pressed")).toBe("true");
    });
    const listCalls = mockGet.mock.calls.map((c) => c[0])
      .filter((p) => p.startsWith("/customers?") && !p.includes("count_only"));
    expect(listCalls[0]).toContain("has_payment_method=false");
  });

  it("composes AND with the missing-address chip", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    fireEvent.click(screen.getByTestId("customers-no-payment-filter"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls
        .filter((p) => p.startsWith("/customers?") && !p.includes("count_only"))
        .pop();
      expect(listCall).toContain("missing_address=true");
      expect(listCall).toContain("has_payment_method=false");
    });
  });

  it("info banner renders only when the filter is ON", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-no-payment-filter")).toBeTruthy());
    expect(screen.queryByTestId("customers-no-payment-banner")).toBeNull();
    fireEvent.click(screen.getByTestId("customers-no-payment-filter"));
    await waitFor(() => expect(
      screen.getByTestId("customers-no-payment-banner")).toBeTruthy());
  });

  it("row action button is visible only for rows without a payment method", async () => {
    const withCard = _row({ id: "cwc", name: "Has Card",
                              has_card_on_file: true,
                              saved_payment_methods_count: 1 });
    const noCard = _row({ id: "cno", name: "No Card",
                            has_card_on_file: false,
                            saved_payment_methods_count: 0 });
    _renderAt("/customers", { items: [withCard, noCard] });
    await waitFor(() => expect(
      screen.getByTestId("add-card-btn-cno")).toBeTruthy());
    // New label reads "Add card" (P44-iteration rename).
    expect(screen.getByTestId("add-card-btn-cno").textContent)
      .toMatch(/Add card/);
    expect(screen.queryByTestId("add-card-btn-cwc")).toBeNull();
    // Legacy testid alias preserved so any external e2e that
    // references the old name still finds the element.
    expect(
      screen.getByTestId("add-card-btn-cno").getAttribute("data-testid-legacy"),
    ).toBe("customer-row-send-payment-link-btn-cno");
  });

  it("clicking the row action POSTs the send-card-add-link endpoint", async () => {
    const noCard = _row({ id: "cno", name: "No Card",
                            email: "b@b.com", phone: "+16025551212",
                            has_card_on_file: false,
                            saved_payment_methods_count: 0 });
    _renderAt("/customers", { items: [noCard] });
    await waitFor(() => expect(
      screen.getByTestId("add-card-btn-cno")).toBeTruthy());
    mockPost.mockResolvedValueOnce({
      ok: true, sent_email: true, sent_sms: true,
      email_recipient: "b@b.com", sms_recipient: "+16025551212",
    });
    fireEvent.click(screen.getByTestId("add-card-btn-cno"));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/customers/cno/send-card-add-link", {},
      );
    });
  });

  it("row layout puts the customer name before the Add card pill", async () => {
    const noCard = _row({ id: "cno", name: "Zeta Customer",
                            has_card_on_file: false,
                            saved_payment_methods_count: 0 });
    _renderAt("/customers", { items: [noCard] });
    const btn = await waitFor(() =>
      screen.getByTestId("add-card-btn-cno"));
    // Customer name span sits in the same row cell — the name node
    // must appear earlier in document order than the pill for the
    // "name first" invariant to hold.
    const row = btn.closest("tr") || btn.parentElement;
    const nameNode = row?.querySelector('span.font-semibold');
    expect(nameNode?.textContent).toMatch(/Zeta Customer/);
    // documentPosition: DOCUMENT_POSITION_FOLLOWING = 4
    expect(
      nameNode.compareDocumentPosition(btn) & 4,
    ).toBeTruthy();
  });
});
