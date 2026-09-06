/**
 * Phase B4 · Feb-2026 — SubscriptionCancelModal tests.
 *
 * Locks in:
 *   1. NO typed input inside the modal (sitewide typed-confirm ban).
 *   2. Radio choice between at_period_end (default) and immediate.
 *   3. Single click on the Confirm button fires DELETE with the
 *      selected mode.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => {
  const api = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(async () => ({ status: "canceled" })),
  };
  return { __esModule: true, default: api, api };
});

import { SubscriptionCancelModal } from "@/pages/customers/SubscriptionsPanel";
import * as apiMod from "@/api";


describe("SubscriptionCancelModal", () => {
  const row = { stripe_subscription_id: "sub_XYZ", price_id: "price_x",
                 quantity: 1, status: "active" };

  beforeEach(() => {
    apiMod.default.delete.mockClear();
  });

  it("renders zero text inputs inside the modal", () => {
    render(<SubscriptionCancelModal row={row}
                                      onClose={() => {}} onDone={() => {}} />);
    expect(screen.getByTestId("subscriptions-cancel-modal")).toBeTruthy();
    expect(document.querySelector("input[type=\"text\"]")).toBeNull();
    // The two radios ARE the only inputs — assert exactly two.
    const inputs = document.querySelectorAll("input");
    expect(inputs.length).toBe(2);
    expect(Array.from(inputs).every((i) => i.type === "radio")).toBe(true);
  });

  it("defaults to at_period_end and single-click fires DELETE with that mode", async () => {
    const onDone = vi.fn();
    render(<SubscriptionCancelModal row={row}
                                      onClose={() => {}} onDone={onDone} />);
    expect(screen.getByTestId("subscriptions-cancel-mode-period-end").checked).toBe(true);
    expect(screen.getByTestId("subscriptions-cancel-mode-immediate").checked).toBe(false);
    fireEvent.click(screen.getByTestId("subscriptions-cancel-submit"));
    await waitFor(() =>
      expect(apiMod.default.delete).toHaveBeenCalledWith(
        "/subscriptions/sub_XYZ?mode=at_period_end",
      ),
    );
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith(
        "Subscription set to cancel at period end",
      ),
    );
  });

  it("switching to immediate flips both the DELETE mode and the button label", async () => {
    const onDone = vi.fn();
    render(<SubscriptionCancelModal row={row}
                                      onClose={() => {}} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("subscriptions-cancel-mode-immediate"));
    expect(screen.getByTestId("subscriptions-cancel-mode-immediate").checked).toBe(true);
    expect(screen.getByTestId("subscriptions-cancel-submit").textContent)
      .toMatch(/immediately/i);
    fireEvent.click(screen.getByTestId("subscriptions-cancel-submit"));
    await waitFor(() =>
      expect(apiMod.default.delete).toHaveBeenCalledWith(
        "/subscriptions/sub_XYZ?mode=immediate",
      ),
    );
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Subscription canceled immediately"),
    );
  });

  it("Cancel/close button never calls DELETE", () => {
    render(<SubscriptionCancelModal row={row}
                                      onClose={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByTestId("subscriptions-cancel-close"));
    expect(apiMod.default.delete).not.toHaveBeenCalled();
  });

  it("surfaces backend errors and never calls onDone", async () => {
    apiMod.default.delete.mockRejectedValueOnce(new Error("stripe_cancel_failed"));
    const onDone = vi.fn();
    render(<SubscriptionCancelModal row={row}
                                      onClose={() => {}} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("subscriptions-cancel-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("subscriptions-cancel-error")).toBeTruthy();
    });
    expect(onDone).not.toHaveBeenCalled();
  });
});
