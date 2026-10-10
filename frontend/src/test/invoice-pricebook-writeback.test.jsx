/**
 * Invoice pricebook writeback · Feb-2026
 *
 * Feb-2026 · Invoice inline edit sprint · Part C — verifies:
 *   * The per-line writeback checkbox is unchecked by default.
 *   * When toggled ON, the save payload carries
 *     ``pricebook_writeback: true`` on that specific line.
 *   * The label text reflects the update-vs-create semantics based
 *     on whether the line has a pricebook FK.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const postSpy = vi.fn().mockResolvedValue({ id: "inv-new-1" });
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/customers?is_active=true") {
        return [{ id: "cust-1", name: "TEST_cust", is_active: true }];
      }
      if (url === "/items") {
        return [{
          id: "pb-1", name: "Backwash Hose", unit_price: 42,
          category: "Pool", item_type: "product",
        }];
      }
      if (url === "/settings/terms") return { default_invoice_terms: "" };
      if (url === "/income-categories") {
        return { items: [{ id: "cat-pool", name: "Pool", color: "#0EA5E9" }] };
      }
      return {};
    }),
    post: (...args) => postSpy(...args),
  },
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u-test-admin", role: "admin",
                              email: "admin@test.local" },
                     loading: false }),
  AuthProvider: ({ children }) => children,
}));

import { invalidateCategoryCache } from "@/components/income/CategoryPicker";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";

async function tick() {
  await act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); });
}

function mount() {
  return render(
    <MemoryRouter initialEntries={["/invoices/new?customer_id=cust-1"]}>
      <QuoteInvoiceNew docType="invoice" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  invalidateCategoryCache();
  postSpy.mockClear();
});

describe("Invoice · pricebook writeback checkbox", () => {
  it("is unchecked by default", async () => {
    mount();
    await tick();
    const cb = screen.getByTestId("qf-line-0-writeback");
    expect(cb).not.toBeChecked();
  });

  it("label reads 'Also add this to the pricebook' for free-text lines", async () => {
    mount();
    await tick();
    const label = screen.getByTestId("qf-line-0-writeback-label");
    expect(label.textContent).toMatch(/add this to the pricebook/i);
  });

  it("label flips to 'Also save this to the pricebook' after selecting a pricebook item", async () => {
    mount();
    await tick();
    const desc = screen.getByTestId("qf-line-0-desc");
    fireEvent.change(desc, { target: { value: "Backwash Hose" } });
    await tick();
    const label = screen.getByTestId("qf-line-0-writeback-label");
    expect(label.textContent).toMatch(/save this to the pricebook/i);
  });

  it("sends pricebook_writeback=true in the save payload when checked", async () => {
    mount();
    await tick();
    // Customer pre-selected via the ?customer_id= query param — skip
    // the CustomerCombobox interaction in JSDOM.
    fireEvent.change(screen.getByTestId("qf-line-0-desc"),
                     { target: { value: "Widget" } });
    fireEvent.change(screen.getByTestId("qf-line-0-price"),
                     { target: { value: "12" } });
    fireEvent.click(screen.getByTestId("qf-line-0-cat-button"));
    await tick();
    fireEvent.click(screen.getByTestId("qf-line-0-cat-option-cat-pool"));
    fireEvent.click(screen.getByTestId("qf-line-0-writeback"));
    fireEvent.click(screen.getByTestId("qf-submit"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const body = postSpy.mock.calls[0][1];
    expect(body.line_items[0].pricebook_writeback).toBe(true);
  });
});
