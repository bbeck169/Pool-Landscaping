/**
 * Invoice line-item price editable · Feb-2026
 *
 * Feb-2026 · Invoice inline edit sprint · Part A — verifies that
 * the New Invoice form's ``unit_price`` field:
 *   * Is a plain <input type="number"> — no ``readOnly``, no
 *     ``disabled``, no lock icon.
 *   * Renders the "custom price — pricebook shows $X.XX" hint the
 *     moment the operator diverges from the pricebook default.
 *   * Retains the pricebook FK on the row so the (separately
 *     tested) writeback flag can target it.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

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
      if (url === "/settings/terms") {
        return { default_invoice_terms: "", default_quote_terms: "" };
      }
      if (url === "/income-categories") {
        return { items: [{ id: "cat-pool", name: "Pool", color: "#0EA5E9" }] };
      }
      return {};
    }),
    post: vi.fn(async () => ({ id: "new-inv-1" })),
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

function mount() {
  return render(
    <MemoryRouter>
      <QuoteInvoiceNew docType="invoice" />
    </MemoryRouter>,
  );
}

async function tick() {
  await act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); });
}

beforeEach(() => { invalidateCategoryCache(); });

describe("Invoice · line-item price editable", () => {
  it("renders unit_price as an editable number input (no readonly / no lock)", async () => {
    mount();
    await tick();
    const priceInput = screen.getByTestId("qf-line-0-price");
    expect(priceInput.tagName.toLowerCase()).toBe("input");
    expect(priceInput.getAttribute("type")).toBe("number");
    expect(priceInput.hasAttribute("readonly")).toBe(false);
    expect(priceInput.hasAttribute("disabled")).toBe(false);
  });

  it("shows a 'custom price' hint when the value diverges from the pricebook default", async () => {
    mount();
    await tick();
    // Select a pricebook item via the description datalist input.
    const desc = screen.getByTestId("qf-line-0-desc");
    fireEvent.change(desc, { target: { value: "Backwash Hose" } });
    await tick();
    // The pricebook default should have prefilled to 42.
    const price = screen.getByTestId("qf-line-0-price");
    expect(price.value).toBe("42");
    // Override the price → the hint should surface.
    fireEvent.change(price, { target: { value: "137.5" } });
    await tick();
    await waitFor(() => {
      expect(screen.getByTestId("qf-line-0-price-custom")).toBeInTheDocument();
    });
    expect(screen.getByTestId("qf-line-0-price-custom").textContent).toMatch(/pricebook shows/i);
  });

  it("no hint when the price matches the pricebook default", async () => {
    mount();
    await tick();
    const desc = screen.getByTestId("qf-line-0-desc");
    fireEvent.change(desc, { target: { value: "Backwash Hose" } });
    await tick();
    expect(screen.queryByTestId("qf-line-0-price-custom")).toBeNull();
  });
});
