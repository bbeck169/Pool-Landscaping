/**
 * F1.2 · Feb-2026 — PortalAgreementRenew page vitest.
 *
 * Covers:
 *   1. Loading state → summary GET → ready render with plan card.
 *   2. Click "Renew Now" fires POST with the token from the URL.
 *   3. Success state renders the confirmation panel.
 *   4. 410 token_expired → error state with the expired message.
 *   5. 403 token_invalid → error state with the invalid message.
 *   6. 409 agreement_state_invalid → error state with the state message.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor }
       from "@testing-library/react";


const getMock  = vi.fn();
const postMock = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:  (...a) => getMock(...a),
    post: (...a) => postMock(...a),
  },
  TOKEN_KEY: "token",
}));


import PortalAgreementRenew from "@/pages/portal/PortalAgreementRenew";


function _render(url) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/customer-portal/agreements/:agreement_id/renew"
          element={<PortalAgreementRenew />}
        />
      </Routes>
    </MemoryRouter>,
  );
}


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});
afterEach(() => cleanup());


const HAPPY_SUMMARY = {
  agreement_id: "agr-1",
  plan_name: "Gold Maintenance",
  plan_kind: "maintenance",
  customer_name: "Jane Renewal",
  price_paid: 79,
  currency: "USD",
  status: "active",
  current_expires_at: "2026-05-15",
  next_expires_at: "2027-05-15",
  already_renewed: false,
};


describe("PortalAgreementRenew · rendering", () => {
  it("shows loading, then renders ready with plan name + price", async () => {
    getMock.mockResolvedValue(HAPPY_SUMMARY);
    _render("/customer-portal/agreements/agr-1/renew?token=abc");
    expect(screen.getByTestId("portal-renewal-loading")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-ready")).toBeInTheDocument());
    expect(screen.getByTestId("portal-renewal-plan-name").textContent)
      .toBe("Gold Maintenance");
    expect(screen.getByTestId("portal-renewal-price").textContent)
      .toContain("$79.00");
  });
});


describe("PortalAgreementRenew · renew flow", () => {
  it("clicking Renew fires POST with token and shows success", async () => {
    getMock.mockResolvedValue(HAPPY_SUMMARY);
    postMock.mockResolvedValue({
      ok: true, new_agreement_id: "agr-2",
      next_expires_at: "2027-05-15", plan_name: "Gold Maintenance",
      price_paid: 79,
    });
    _render("/customer-portal/agreements/agr-1/renew?token=abc");
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-ready")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("portal-renewal-cta"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/portal/agreements/agr-1/renew", { token: "abc" }));
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-success")).toBeInTheDocument());
    expect(screen.getByTestId("portal-renewal-success-next")).toBeInTheDocument();
  });
});


describe("PortalAgreementRenew · error branches", () => {
  it("410 token_expired renders the expired error panel", async () => {
    getMock.mockRejectedValue({ data: { detail: "token_expired" } });
    _render("/customer-portal/agreements/agr-1/renew?token=abc");
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-error-token_expired"))
        .toBeInTheDocument());
    expect(screen.getByTestId("portal-renewal-error-token_expired").textContent)
      .toMatch(/expired/i);
  });

  it("403 token_invalid renders the invalid error panel", async () => {
    getMock.mockRejectedValue({ data: { detail: "token_invalid" } });
    _render("/customer-portal/agreements/agr-1/renew?token=abc");
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-error-token_invalid"))
        .toBeInTheDocument());
    expect(screen.getByTestId("portal-renewal-error-token_invalid").textContent)
      .toMatch(/invalid/i);
  });

  it("409 agreement_state_invalid renders the state error panel", async () => {
    getMock.mockRejectedValue({ data: { detail: "agreement_state_invalid" } });
    _render("/customer-portal/agreements/agr-1/renew?token=abc");
    await waitFor(() =>
      expect(screen.getByTestId("portal-renewal-error-agreement_state_invalid"))
        .toBeInTheDocument());
    expect(screen.getByTestId("portal-renewal-error-agreement_state_invalid").textContent)
      .toMatch(/no longer available|already been renewed/i);
  });
});
