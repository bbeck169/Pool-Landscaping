/**
 * Phase B4 · Feb-2026 — SubscriptionCreateModal tests.
 *
 * Verifies:
 *   1. Prices + payment-methods lists populate the dropdowns.
 *   2. Submit fires POST /subscriptions with the expected body.
 *   3. Errors from the backend surface into the modal.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => {
  const responses = {};
  const api = {
    get: vi.fn(async (path) => responses[path] ?? null),
    post: vi.fn(async () => ({ id: "sub_created" })),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { __esModule: true, default: api, api, __responses: responses };
});

import { SubscriptionCreateModal } from "@/pages/customers/SubscriptionsPanel";
import * as apiMod from "@/api";


describe("SubscriptionCreateModal", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
    apiMod.default.post.mockClear();
    apiMod.__responses["/subscriptions/prices"] = {
      count: 2,
      rows: [
        { id: "price_pro", nickname: "Pro monthly", unit_amount: 2999,
          currency: "usd", recurring: { interval: "month" },
          product_id: "prod_A", product_name: "Pool Pro" },
        { id: "price_yearly", nickname: "Pro yearly", unit_amount: 29999,
          currency: "usd", recurring: { interval: "year" },
          product_id: "prod_A", product_name: "Pool Pro" },
      ],
    };
    apiMod.__responses["/payment-methods/cust-1"] = {
      payment_methods: [
        { provider_payment_method_id: "pm_card_1",
          card: { last4: "4242" } },
        { provider_payment_method_id: "pm_ach_1",
          us_bank_account: { bank_name: "Chase", last4: "6789" } },
      ],
    };
  });

  it("populates price + payment method dropdowns on open", async () => {
    render(<SubscriptionCreateModal customerId="cust-1"
                                       onClose={() => {}} onDone={() => {}} />);
    await waitFor(() => {
      const select = screen.getByTestId("subscriptions-create-price");
      expect(select.querySelectorAll("option").length).toBeGreaterThanOrEqual(3); // includes placeholder
    });
    const priceOpts = screen.getByTestId("subscriptions-create-price")
      .querySelectorAll("option");
    const priceLabels = Array.from(priceOpts).map((o) => o.textContent).join(" | ");
    expect(priceLabels).toMatch(/Pro monthly/);
    expect(priceLabels).toMatch(/Pro yearly/);
    const pmOpts = screen.getByTestId("subscriptions-create-pm")
      .querySelectorAll("option");
    const pmLabels = Array.from(pmOpts).map((o) => o.textContent).join(" | ");
    expect(pmLabels).toMatch(/4242/);
    expect(pmLabels).toMatch(/Chase/);
  });

  it("submit sends POST /subscriptions with the composed body", async () => {
    const onDone = vi.fn();
    render(<SubscriptionCreateModal customerId="cust-1"
                                       onClose={() => {}} onDone={onDone} />);
    await waitFor(() =>
      expect(screen.getByTestId("subscriptions-create-price").value).toBe("price_pro"),
    );
    // Change plan + quantity + trial + PM.
    fireEvent.change(screen.getByTestId("subscriptions-create-price"),
                      { target: { value: "price_yearly" } });
    fireEvent.change(screen.getByTestId("subscriptions-create-quantity"),
                      { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("subscriptions-create-pm"),
                      { target: { value: "pm_card_1" } });
    fireEvent.change(screen.getByTestId("subscriptions-create-trial"),
                      { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("subscriptions-create-submit"));
    await waitFor(() => expect(apiMod.default.post).toHaveBeenCalled());
    expect(apiMod.default.post).toHaveBeenCalledWith("/subscriptions", {
      customer_id: "cust-1",
      price_id: "price_yearly",
      quantity: 3,
      payment_method_id: "pm_card_1",
      trial_days: 7,
    });
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Subscription created"));
  });

  it("surfaces backend errors inside the modal", async () => {
    apiMod.default.post.mockRejectedValueOnce(
      new Error("stripe_create_failed: card_declined"),
    );
    render(<SubscriptionCreateModal customerId="cust-1"
                                       onClose={() => {}} onDone={() => {}} />);
    await waitFor(() =>
      expect(screen.getByTestId("subscriptions-create-price").value).toBe("price_pro"),
    );
    fireEvent.click(screen.getByTestId("subscriptions-create-submit"));
    await waitFor(() => {
      const err = screen.getByTestId("subscriptions-create-error");
      expect(err.textContent).toMatch(/card_declined/);
    });
  });

  it("submit is disabled until a price is chosen", async () => {
    // Force the initial priceId to stay empty by returning no prices.
    apiMod.__responses["/subscriptions/prices"] = { count: 0, rows: [] };
    render(<SubscriptionCreateModal customerId="cust-1"
                                       onClose={() => {}} onDone={() => {}} />);
    await waitFor(() =>
      expect(screen.getByTestId("subscriptions-create-price")).toBeTruthy(),
    );
    expect(screen.getByTestId("subscriptions-create-submit")).toBeDisabled();
  });
});
