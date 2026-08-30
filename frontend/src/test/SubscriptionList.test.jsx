/**
 * Phase B4 · Feb-2026 — SubscriptionsPanel list-view tests.
 *
 * Uses vi.mock on ``@/api`` so we don't hit a live backend.
 * Verifies:
 *   1. Rows render with the canonical testids.
 *   2. Empty state renders when there are no subscriptions.
 *   3. Read-only users don't see the Create / Edit / Cancel actions.
 *   4. Refresh button re-fires GET /subscriptions.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => {
  const state = { rowsResponse: null };
  const api = {
    get: vi.fn(async (path) => {
      if (path.startsWith("/subscriptions")) return state.rowsResponse;
      return null;
    }),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { __esModule: true, default: api, api, __state: state };
});

import SubscriptionsPanel from "@/pages/customers/SubscriptionsPanel";
import * as apiMod from "@/api";


describe("SubscriptionsPanel · list view", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
    apiMod.__state.rowsResponse = { total: 0, rows: [] };
  });

  it("renders the empty state when there are no subs", async () => {
    render(<SubscriptionsPanel customerId="cust-1" canWrite />);
    await waitFor(() =>
      expect(screen.getByTestId("subscriptions-empty")).toBeTruthy(),
    );
    expect(screen.getByTestId("subscriptions-title").textContent).toMatch(/Subscriptions/);
  });

  it("renders rows with canonical testids", async () => {
    apiMod.__state.rowsResponse = { total: 2, rows: [
      { stripe_subscription_id: "sub_A", price_id: "price_pro",
        status: "active", quantity: 1, current_period_end: "2026-03-15T00:00:00Z",
        cancel_at_period_end: false },
      { stripe_subscription_id: "sub_B", price_id: "price_lite",
        status: "past_due", quantity: 3, current_period_end: "2026-03-20T00:00:00Z",
        cancel_at_period_end: true },
    ]};
    render(<SubscriptionsPanel customerId="cust-1" canWrite />);
    await waitFor(() => expect(screen.getByTestId("subscriptions-list")).toBeTruthy());
    expect(screen.getByTestId("subscriptions-row-sub_A")).toBeTruthy();
    expect(screen.getByTestId("subscriptions-row-sub_B")).toBeTruthy();
    // Auto-cancel indicator only on sub_B.
    expect(screen.getByTestId("subscriptions-row-sub_B-autocancel")).toBeTruthy();
    expect(screen.queryByTestId("subscriptions-row-sub_A-autocancel")).toBeNull();
    // Action buttons visible when canWrite.
    expect(screen.getByTestId("subscriptions-row-sub_A-edit")).toBeTruthy();
    expect(screen.getByTestId("subscriptions-row-sub_A-cancel")).toBeTruthy();
    expect(screen.getByTestId("subscriptions-create-btn")).toBeTruthy();
  });

  it("hides mutation controls when canWrite=false", async () => {
    apiMod.__state.rowsResponse = { total: 1, rows: [
      { stripe_subscription_id: "sub_A", price_id: "price_x", status: "active",
        quantity: 1, current_period_end: "2026-03-15T00:00:00Z" },
    ]};
    render(<SubscriptionsPanel customerId="cust-1" canWrite={false} />);
    await waitFor(() => expect(screen.getByTestId("subscriptions-row-sub_A")).toBeTruthy());
    expect(screen.queryByTestId("subscriptions-create-btn")).toBeNull();
    expect(screen.queryByTestId("subscriptions-row-sub_A-edit")).toBeNull();
    expect(screen.queryByTestId("subscriptions-row-sub_A-cancel")).toBeNull();
  });

  it("refresh button re-fires GET /subscriptions", async () => {
    apiMod.__state.rowsResponse = { total: 0, rows: [] };
    render(<SubscriptionsPanel customerId="cust-1" canWrite />);
    await waitFor(() => expect(screen.getByTestId("subscriptions-empty")).toBeTruthy());
    apiMod.default.get.mockClear();
    fireEvent.click(screen.getByTestId("subscriptions-refresh"));
    await waitFor(() =>
      expect(apiMod.default.get).toHaveBeenCalledWith("/subscriptions?customer_id=cust-1"),
    );
  });
});
