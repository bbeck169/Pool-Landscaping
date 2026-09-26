/**
 * Feb-2026 · Regression test — Public magic-link EstimateView must
 * NOT render the "Invalid estimate link" error branch when the
 * ``/portal/quotes/via-token`` endpoint returns a valid payload.
 *
 * Tester surfaced a browser-automation failure where a
 * magic-link surface was showing the 401 error branch even though
 * the exact token succeeded via curl. Root-cause investigation:
 *
 *   * Backend endpoint ``GET /api/portal/quotes/via-token`` has no
 *     ``Depends(get_current_user)`` — a stale ``Authorization``
 *     header from a prior admin session does NOT trip it (verified
 *     with 4 curl variants: no auth, admin JWT, garbage JWT,
 *     magic-link JWT).
 *   * The frontend load path in ``EstimateView.jsx::load`` fires
 *     ``api.get("/portal/quotes/via-token?token=…")`` and sets
 *     ``err`` only on ``.catch``. No secondary hook has permission
 *     to mutate ``err`` — ``useTenantBranding`` silently swallows
 *     its own failures.
 *   * Not reproducible in the dev environment. Diagnostic
 *     ``data-error-source`` attribute added on the error branch so
 *     the next tester pass can pinpoint the failure mode.
 *
 * This test locks the happy path — if it ever fails, the customer
 * magic-link surface has regressed.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [{ get: () => "tok-abc" }],
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", muted: "#6B7280", onSurface: "#111827",
    border: "#E5E7EB", surface: "#FFFFFF",
    nav: { bg: "#1B1F5C", bgDeep: "#03002e" },
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

beforeEach(() => {
  getSpy.mockImplementation((path) => {
    if (typeof path === "string"
        && path.includes("/portal/tenant/branding")) {
      return Promise.resolve({
        tenant_id: "t-1",
        branding: {
          company_display_name: "Acme Pools",
          brand_primary_hex: "#0B4A6F",
          brand_secondary_hex: "#F97316",
        },
      });
    }
    if (typeof path === "string"
        && path.includes("/portal/quotes/via-token")) {
      return Promise.resolve({
        estimate_id: "q-live",
        status: "sent",
        decision: null,
        sent_at: "2026-02-14T00:00:00Z",
        company: { name: "Acme Pools" },
        bill_to: { name: "Real Cust", customer_number: "C-1" },
        property_address: "1 Reef St",
        header: {
          estimate_number: "EST-201",
          estimate_date: "2026-02-14",
          customer_number: "C-1",
        },
        title: "Backyard Overhaul",
        line_items: [
          { description: "Pavers", quantity: 100, unit_price: 40 },
        ],
        totals: {
          subtotal: 4000, taxes: 400, amount_paid: 0,
          total_estimated_cost: 4400,
          original_subtotal: 4000, original_total: 4400,
          adjusted_subtotal: 4000, adjusted_total: 4400,
          has_declined_lines: false, declined_line_count: 0,
        },
        notes: null,
        as_customer: true,
        customer_view: {
          customer_group_display: true,
          groups: [
            { category_id: "cat-a", group_key: "cat-a",
              label: "Hardscape", description: "",
              subtotal: 4000, active_subtotal: 4000,
              declined: false, declined_at: null, declined_by: null },
          ],
          subtotal: 4000, tax: 400, discount: 0, total: 4400,
          grouped_subtotal: 4000, grouped_active_subtotal: 4000,
          has_declined_groups: false, currency: "USD",
        },
      });
    }
    return Promise.resolve({});
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  getSpy.mockReset();
});

import PublicEstimateLanding from "@/pages/portal/PublicEstimateLanding";


describe("PublicEstimateLanding · /e/estimate?token=… regression", () => {
  it("renders the customer estimate view (no error branch)",
      async () => {
    render(<PublicEstimateLanding />);

    // Landing wrapper mounts immediately.
    await waitFor(() =>
      expect(
        screen.queryByTestId("public-estimate-landing"),
      ).toBeTruthy(),
    );

    // Customer estimate view fully renders — desktop shell + header.
    await waitFor(() =>
      expect(
        screen.queryByTestId("estimate-desktop-shell"),
      ).toBeTruthy(),
    );

    // No error branch was rendered.
    expect(
      screen.queryByTestId("estimate-view-error"),
    ).toBeNull();
    expect(
      screen.queryByText(/Invalid estimate link/i),
    ).toBeNull();
    expect(
      screen.queryByText(/Estimate link expired/i),
    ).toBeNull();

    // Grouped customer view visible (the group row from the payload).
    expect(
      screen.getByTestId("estimate-grouped-row-cat-a"),
    ).toBeTruthy();

    // Branded header band paints (Theme Refresh integration is
    // intact under the magic-link surface).
    expect(
      screen.getByTestId("doc-branded-header-band"),
    ).toBeTruthy();

    // The token was passed to the via-token endpoint.
    expect(getSpy).toHaveBeenCalledWith(
      expect.stringContaining("/portal/quotes/via-token?token=tok-abc"),
    );
  });

  it("error branch carries data-error-source diagnostic when the "
      + "backend 401s", async () => {
    // Simulate the exact failure the tester reported: backend
    // rejects the token, ``err`` becomes ``"Invalid estimate link"``.
    getSpy.mockImplementation((path) => {
      if (typeof path === "string"
          && path.includes("/portal/tenant/branding")) {
        // Branding hook silently catches — no state pollution.
        return Promise.reject(new Error("401"));
      }
      return Promise.reject(new Error("Invalid estimate link"));
    });
    render(<PublicEstimateLanding />);
    await waitFor(() =>
      expect(
        screen.queryByTestId("estimate-view-error"),
      ).toBeTruthy(),
    );
    // Diagnostic attribute is set so testers can distinguish this
    // failure mode from the empty-payload / network cases.
    expect(
      screen.getByTestId("estimate-view-error")
             .getAttribute("data-error-source"),
    ).toBe("backend-401");
  });
});
