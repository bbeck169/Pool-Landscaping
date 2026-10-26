/**
 * Ticket II · Feb-2026 · Commit B (FE) — Auto-Billing New Plan modal
 * pricebook combobox.
 *
 * Covers the FE contract introduced by Commit B:
 *   1. The pricebook search input + dropdown render in the modal.
 *   2. Typing filters the catalogue list by name/category.
 *   3. Clicking an item fills service name + amount +
 *      pricebook_item_id in the submit payload.
 *   4. Amount field remains editable after selection (operator can
 *      override the pricebook unit_price).
 *   5. Picking a NEW item re-fills service + amount (reset path).
 *   6. The "Clear" affordance appears post-selection and empties
 *      pricebook_item_id without closing the modal.
 *   7. Backward-compat — the free-text Service input is still
 *      mounted + editable (operator can type a label without
 *      picking a pricebook item at all).
 *
 * We use source-string + stub-render patterns to avoid the full
 * FinancePages tree mount (which hangs jsdom per prior test files
 * like ``InvoiceAgingReport.jsx`` + ``InvoicesList.td93*``).  The
 * AutoBilling component mounts in isolation with its ``api``
 * dependencies stubbed.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";

const _apiGet = vi.fn();
const _apiPost = vi.fn();
const _apiPut = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => _apiGet(...a),
    post: (...a) => _apiPost(...a),
    put: (...a) => _apiPut(...a),
  },
}));
// Stub sonner so the Toast surface doesn't matter here.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { AutoBilling } from "@/pages/finance/FinancePages";

const PRICEBOOK = [
  { id: "it-1", name: "Weekly Pool Cleaning", category: "Service",
    unit_price: 120, active: true },
  { id: "it-2", name: "Monthly Maintenance", category: "Service",
    unit_price: 480, active: true },
  { id: "it-3", name: "Chlorine Shock Treatment", category: "Chemical",
    unit_price: 45, active: true },
];

const CUSTOMERS = [
  { id: "cust-1", name: "Alice", is_active: true },
  { id: "cust-2", name: "Bob", is_active: true },
];

function _primeApi() {
  _apiGet.mockImplementation((url) => {
    if (url.startsWith("/billing-plans")) return Promise.resolve([]);
    if (url.startsWith("/customers")) return Promise.resolve(CUSTOMERS);
    if (url.startsWith("/pricebook-items")) {
      return Promise.resolve({ items: PRICEBOOK });
    }
    return Promise.resolve({});
  });
  _apiPost.mockResolvedValue({ ok: true, id: "new-plan-id" });
}

function _mount() {
  return render(
    <MemoryRouter>
      <AutoBilling />
    </MemoryRouter>,
  );
}

async function _openNewPlanModal() {
  // The "+ New plan" button opens the modal.  Fire a direct click
  // on the setShowNew trigger via its data-testid-free label.
  const btn = screen.getByRole("button", { name: /new plan/i });
  fireEvent.click(btn);
  await waitFor(() => expect(screen.getByTestId("new-plan-modal")).toBeTruthy());
}

beforeEach(() => {
  _apiGet.mockReset();
  _apiPost.mockReset();
  _apiPut.mockReset();
  _primeApi();
  // ``cmdk`` (used by CustomerCombobox) calls scrollIntoView when
  // the menu opens; jsdom doesn't ship that method on Elements.
  // Stub it globally for the duration of this suite.
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Ticket II · Pricebook combobox renders in New Plan modal", () => {
  it("search input + closed dropdown mount on modal open", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    expect(screen.getByTestId("new-plan-pricebook-wrap")).toBeTruthy();
    expect(screen.getByTestId("new-plan-pricebook-search")).toBeTruthy();
    // Dropdown is initially closed.
    expect(screen.queryByTestId("new-plan-pricebook-dropdown")).toBeNull();
  });

  it("focusing the search opens the dropdown with all items", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    await waitFor(() =>
      expect(screen.getByTestId("new-plan-pricebook-dropdown")).toBeTruthy(),
    );
    expect(screen.getByTestId("new-plan-pricebook-opt-it-1")).toBeTruthy();
    expect(screen.getByTestId("new-plan-pricebook-opt-it-2")).toBeTruthy();
    expect(screen.getByTestId("new-plan-pricebook-opt-it-3")).toBeTruthy();
  });

  it("typing filters the dropdown by name/category", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    const input = screen.getByTestId("new-plan-pricebook-search");
    fireEvent.change(input, { target: { value: "chlorine" } });
    await waitFor(() => {
      expect(screen.queryByTestId("new-plan-pricebook-opt-it-1")).toBeNull();
      expect(screen.queryByTestId("new-plan-pricebook-opt-it-2")).toBeNull();
      expect(screen.getByTestId("new-plan-pricebook-opt-it-3")).toBeTruthy();
    });
    // Category search also hits.
    fireEvent.change(input, { target: { value: "chemical" } });
    await waitFor(() =>
      expect(screen.getByTestId("new-plan-pricebook-opt-it-3")).toBeTruthy(),
    );
  });
});

describe("Ticket II · Selecting a pricebook item fills the form", () => {
  it("click → service + amount + pricebook_item_id all populated", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-1"));
    await waitFor(() =>
      expect(screen.getByTestId("new-plan-service").value)
        .toBe("Weekly Pool Cleaning"),
    );
    expect(Number(screen.getByTestId("new-plan-amount").value)).toBe(120);
    // Dropdown closes after selection; "Clear" affordance appears.
    expect(screen.queryByTestId("new-plan-pricebook-dropdown")).toBeNull();
    expect(screen.getByTestId("new-plan-pricebook-clear")).toBeTruthy();
  });

  it("picking a DIFFERENT item re-fills service + amount (reset path)", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-1"));
    await waitFor(() =>
      expect(screen.getByTestId("new-plan-service").value)
        .toBe("Weekly Pool Cleaning"),
    );
    // Reopen the dropdown and pick a different item.
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.change(screen.getByTestId("new-plan-pricebook-search"),
                     { target: { value: "monthly" } });
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-2"));
    await waitFor(() =>
      expect(screen.getByTestId("new-plan-service").value)
        .toBe("Monthly Maintenance"),
    );
    expect(Number(screen.getByTestId("new-plan-amount").value)).toBe(480);
  });

  it("amount is still editable after pricebook selection", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-1"));
    const amount = screen.getByTestId("new-plan-amount");
    expect(amount.disabled).toBe(false);
    fireEvent.change(amount, { target: { value: "199.99" } });
    expect(Number(amount.value)).toBeCloseTo(199.99, 2);
  });

  it("Clear button empties pricebook_item_id + search", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-1"));
    fireEvent.click(screen.getByTestId("new-plan-pricebook-clear"));
    await waitFor(() =>
      expect(screen.queryByTestId("new-plan-pricebook-clear")).toBeNull(),
    );
    expect(screen.getByTestId("new-plan-pricebook-search").value).toBe("");
  });
});

describe("Ticket II · Submit payload carries pricebook_item_id", () => {
  it("Create → POST body includes pricebook_item_id + snapshot fields", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    // Customer picker — set via combobox state exposed by the
    // ``new-plan-customer`` testid prefix.  The simplest driver
    // is to click the "Create" button after setting state via the
    // combobox; but CustomerCombobox renders a <select> or a
    // multi-step picker.  Instead, set a customer by direct
    // interaction — use the first customer option available.
    const customerBtn = screen.getByTestId("new-plan-customer");
    fireEvent.click(customerBtn);
    const custOption = await screen.findByText(/Alice/);
    fireEvent.click(custOption);
    // Pick a pricebook item.
    fireEvent.focus(screen.getByTestId("new-plan-pricebook-search"));
    fireEvent.click(await screen.findByTestId("new-plan-pricebook-opt-it-2"));
    // Submit.
    fireEvent.click(screen.getByTestId("create-plan-btn"));
    await waitFor(() =>
      expect(_apiPost).toHaveBeenCalledWith(
        "/billing-plans",
        expect.objectContaining({
          customer_id: "cust-1",
          service: "Monthly Maintenance",
          amount: 480,
          pricebook_item_id: "it-2",
        }),
      ),
    );
  });

  it("free-text fallback — Create without picking a pricebook item posts pricebook_item_id: null", async () => {
    _mount();
    await _openNewPlanModal();
    await waitFor(() =>
      expect(_apiGet).toHaveBeenCalledWith("/pricebook-items?active=true"),
    );
    // Pick a customer.
    fireEvent.click(screen.getByTestId("new-plan-customer"));
    fireEvent.click(await screen.findByText(/Bob/));
    // Skip the pricebook combobox; override the Service free-text.
    fireEvent.change(screen.getByTestId("new-plan-service"),
                     { target: { value: "Ad-hoc Service" } });
    fireEvent.click(screen.getByTestId("create-plan-btn"));
    await waitFor(() =>
      expect(_apiPost).toHaveBeenCalledWith(
        "/billing-plans",
        expect.objectContaining({
          customer_id: "cust-2",
          service: "Ad-hoc Service",
          pricebook_item_id: null,
        }),
      ),
    );
  });
});

describe("Ticket II · Source-level locks", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/finance/FinancePages.jsx"),
    "utf-8",
  );

  it("newPlan initial state carries pricebook_item_id: null", () => {
    // Both the useState init and the post-create reset.
    const inits = SRC.match(
      /useState\(\{\s*customer_id:[\s\S]{0,400}pricebook_item_id:\s*null\s*\}\)/g,
    );
    expect(inits).not.toBeNull();
    expect(inits.length).toBeGreaterThanOrEqual(1);
    const resets = SRC.match(
      /setNewPlan\(\{\s*customer_id:[\s\S]{0,400}pricebook_item_id:\s*null\s*\}\)/g,
    );
    expect(resets).not.toBeNull();
    expect(resets.length).toBeGreaterThanOrEqual(1);
  });

  it("useEffect on showNew ALSO fetches /pricebook-items", () => {
    expect(SRC).toMatch(/api\.get\("\/pricebook-items\?active=true"\)/);
  });

  it("free-text Service input is still mounted (backward compat)", () => {
    expect(SRC).toMatch(/data-testid="new-plan-service"/);
  });
});
