/**
 * Invoice save errors · Feb-2026 · Inline row highlight
 *
 * Feb-2026 · Invoice inline edit sprint · Error handling — verifies:
 *   * A structured 400 with ``{error_code, line_index}`` surfaces
 *     as an INLINE row highlight (not a page toast that blocks work).
 *   * The Save button STAYS ENABLED so the operator can fix + retry
 *     without leaving the page.
 *   * The affected row's <CategoryPicker> gets the archived-warning
 *     styling via ``invalidReason=archived_category`` prop.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

class MockApiError extends Error {
  constructor(status, data) {
    super(data?.detail?.message || "Request failed");
    this.status = status;
    this.data = data;
  }
}

const postSpy = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/customers?is_active=true") {
        return [{ id: "cust-1", name: "TEST_cust", is_active: true }];
      }
      if (url === "/items") return [];
      if (url === "/settings/terms") return { default_invoice_terms: "" };
      if (url === "/income-categories") {
        return { items: [{ id: "cat-pool", name: "Pool", color: "#0EA5E9" }] };
      }
      return {};
    }),
    post: (...args) => postSpy(...args),
  },
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
  postSpy.mockReset();
});

async function fillLineAndSubmit() {
  // Customer pre-selected via query param — skip combobox interaction.
  fireEvent.change(screen.getByTestId("qf-line-0-desc"),
                   { target: { value: "Widget" } });
  fireEvent.change(screen.getByTestId("qf-line-0-price"),
                   { target: { value: "12" } });
  fireEvent.click(screen.getByTestId("qf-line-0-cat-button"));
  await tick();
  fireEvent.click(screen.getByTestId("qf-line-0-cat-option-cat-pool"));
  fireEvent.click(screen.getByTestId("qf-submit"));
}

describe("Invoice save errors · inline row highlight", () => {
  it("archived_category error highlights the offending row and keeps Save enabled", async () => {
    postSpy.mockRejectedValueOnce(new MockApiError(400, {
      detail: {
        error_code: "archived_category",
        line_index: 0,
        attempted_category: "Common",
        available_categories: ["Pool", "Landscape"],
        field: "line_items[0].category",
        message: "Unknown or archived category: 'Common'. Available…",
      },
    }));
    mount();
    await tick();
    await fillLineAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("qf-line-0-row-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("qf-line-0-row-error").textContent)
      .toMatch(/archived/i);
    // Save button MUST remain enabled — the operator fixes + retries.
    const submit = screen.getByTestId("qf-submit");
    expect(submit).not.toBeDisabled();
    // The category picker shows the archived warning chip.
    expect(screen.getByTestId("qf-line-0-cat-archived-warning")).toBeInTheDocument();
  });

  it("category_required error surfaces the same inline treatment", async () => {
    postSpy.mockRejectedValueOnce(new MockApiError(400, {
      detail: {
        error_code: "category_required",
        line_index: 0,
        field: "line_items[0].category",
        message: "Each income line item must have a category.",
      },
    }));
    mount();
    await tick();
    await fillLineAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("qf-line-0-row-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("qf-line-0-row-error").textContent)
      .toMatch(/required/i);
  });
});
