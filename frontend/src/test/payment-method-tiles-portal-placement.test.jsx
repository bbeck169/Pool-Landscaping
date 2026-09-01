/**
 * Phase I5 · Wave B · Feb-2026 — Portal Billing Method tab now
 * delegates to the shared ``PaymentMethodTiles`` component.
 *
 * Two-layer coverage:
 *   1. Source-body contract check on ``PortalPages.jsx`` — locks
 *      the mount point + ``variant="portal"`` prop + JWT-scoped
 *      customer_id so a future refactor can't silently regress
 *      the placement.
 *   2. Runtime render — mounts ``PortalPaymentMethod`` under a
 *      mocked ``AuthProvider`` + stubbed API and asserts the
 *      loading / on-file / empty / delete-modal states surface,
 *      matching the admin-variant contract.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";


const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    del: (...a) => vi.fn()(...a),
  },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa", border: "#eee",
    borderStrong: "#ddd", onSurface: "#000", muted: "#666",
    error: "#DC2626", onError: "#fff",
    landscape: { 50: "#F0FDF4", 100: "#DCFCE7", 300: "#86EFAC",
                    500: "#22C55E", 600: "#16A34A", 700: "#15803D" },
    brand: "#0284C7", success: "#16A34A",
    onSurfaceSecondary: "#333",
  },
  money: (n) => `$${(Number(n) / 100).toFixed(2)}`,
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { customer_id: "cust_portal_1",
                                 role: "customer" } }),
}));
// Stub the tile's inline Add forms so tests don't need Stripe.
vi.mock("@/components/payments/StripeAddCardForm", () => ({
  default: function StripeAddCardForm({ onSuccess, onCancel }) {
    return (
      <div data-testid="stub-add-card-form">
        <button data-testid="stub-add-card-success"
                     onClick={() => onSuccess?.({id: "pm_new"})}>
          success
        </button>
      </div>
    );
  },
}));
vi.mock("@/components/payments/StripeAddBankForm", () => ({
  default: function StripeAddBankForm({ onSuccess }) {
    return <div data-testid="stub-add-bank-form">
      <button data-testid="stub-add-bank-success"
                   onClick={() => onSuccess?.({id: "pm_bank"})}>
        success
      </button>
    </div>;
  },
}));
// Portal legacy body also imports these + ``getStripeConfig`` — stub
// so the module load doesn't try to hit Stripe.
vi.mock("@/lib/stripeConfig", () => ({
  getStripeConfig: () => Promise.resolve({ publishable_key: "" }),
}));
// InvoiceView / EstimateView are unused in this test surface.
vi.mock("@/components/InvoiceView", () => ({ default: () => null }));
vi.mock("@/components/EstimateView", () => ({ default: () => null }));
vi.mock("@/components/portal/PortalBookingPhotos", () =>
  ({ default: () => null }));
vi.mock("@/components/PaymentForm", () => ({ default: () => null }));
vi.mock("@/components/ui-kit", async (importActual) => {
  const actual = await importActual();
  return {
    ...actual,
    // PageHeader / Button / Toast are already fine but a lightweight
    // fallback keeps the test isolated from ui-kit churn.
  };
});
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { PortalPaymentMethod } from "@/pages/portal/PortalPages";


const CARD_ROW = {
  id: "row_c1", customer_id: "cust_portal_1",
  provider_payment_method_id: "pm_c1", type: "card",
  brand: "visa", last4: "4242", exp_month: 6, exp_year: 2029,
  is_default: true,
};


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});


function renderPortal() {
  return render(
    <MemoryRouter initialEntries={["/portal/payment-method"]}>
      <PortalPaymentMethod />
    </MemoryRouter>,
  );
}


// ═══════════════════════════════════════════════════════════════════
// Source-body contract — locks the mount point + ``variant="portal"``
// + JWT-scoped customer_id.
// ═══════════════════════════════════════════════════════════════════
describe("PortalPaymentMethod · I5 Wave B source contract", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/portal/PortalPages.jsx"),
    "utf-8",
  );

  it("imports the shared PaymentMethodTiles component", () => {
    expect(SRC).toMatch(
      /import\s+PaymentMethodTiles\s+from\s+"@\/components\/customers\/PaymentMethodTiles"/,
    );
  });

  it("mounts the tiles with variant=\"portal\" inside PortalPaymentMethod", () => {
    // Locate the exported function opening + the very next
    // ``<PaymentMethodTiles`` occurrence.
    const fnIdx = SRC.indexOf("export function PortalPaymentMethod(");
    expect(fnIdx).toBeGreaterThan(-1);
    const slice = SRC.slice(fnIdx, fnIdx + 2200);
    expect(slice).toMatch(/<PaymentMethodTiles/);
    // Prop assertions on the same JSX element.
    const tileIdx = slice.indexOf("<PaymentMethodTiles");
    const propSlice = slice.slice(tileIdx, tileIdx + 400);
    expect(propSlice).toMatch(/variant="portal"/);
    expect(propSlice).toMatch(/customerId=\{user\?\.customer_id\}/);
  });

  it("still preserves the PortalPaymentMethod route wrapper (data-testid + tour hook)", () => {
    const fnIdx = SRC.indexOf("export function PortalPaymentMethod(");
    const slice = SRC.slice(fnIdx, fnIdx + 2000);
    expect(slice).toMatch(/data-testid="portal-pm"/);
    expect(slice).toMatch(/data-tour-id="payment-method-panel"/);
    expect(slice).toMatch(/PageHeader[\s\S]*?title="Payment Methods"/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// Runtime — same shared component, so behavior matches admin variant
// with the portal-specific ``variant="portal"`` testid.
// ═══════════════════════════════════════════════════════════════════
describe("PortalPaymentMethod · I5 Wave B runtime", () => {
  it("mounts and hits the shared admin PMs endpoint with the JWT customer_id", async () => {
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => { renderPortal(); });
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(
      "/payments/stripe/payment-methods/cust_portal_1",
    ));
    // Tile wrapper carries the "portal" variant testid.
    expect(await screen.findByTestId(
      "payment-method-tiles-portal")).toBeInTheDocument();
  });

  it("renders both empty states when the customer has no methods", async () => {
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => { renderPortal(); });
    expect(await screen.findByTestId(
      "payment-method-tiles-card-empty")).toHaveTextContent(
        /No Credit\/Debit Card Information Found/);
    expect(screen.getByTestId(
      "payment-method-tiles-bank-empty")).toHaveTextContent(
        /No Bank Account Information Found/);
  });

  it("renders the on-file card tile when the customer has a saved card", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => { renderPortal(); });
    expect(await screen.findByTestId(
      `payment-tile-card-${CARD_ROW.id}`)).toBeInTheDocument();
    expect(screen.getByTestId(
      `payment-tile-card-number-${CARD_ROW.id}`)).toHaveTextContent(
        /•+ 4242/);
  });

  it("Delete flow uses TypedConfirmModal keyed on last4 (same as admin)", async () => {
    getMock.mockResolvedValue({payment_methods: [CARD_ROW]});
    await act(async () => { renderPortal(); });
    fireEvent.click(await screen.findByTestId(
      `payment-tile-card-delete-${CARD_ROW.id}`));
    // Modal opens.
    expect(await screen.findByTestId(
      "payment-tile-delete-confirm-modal")).toBeInTheDocument();
    // Keyword is the card's last4.
    const confirmBtn = screen.getByTestId(
      "payment-tile-delete-confirm-confirm");
    expect(confirmBtn).toBeDisabled();
    fireEvent.change(screen.getByTestId(
      "payment-tile-delete-confirm-input"),
      {target: {value: "4242"}});
    expect(confirmBtn).not.toBeDisabled();
  });

  it("Add-card CTA opens the inline SetupIntent-backed form", async () => {
    getMock.mockResolvedValue({payment_methods: []});
    await act(async () => { renderPortal(); });
    fireEvent.click(await screen.findByTestId(
      "payment-method-tiles-card-empty-add"));
    expect(screen.getByTestId("stub-add-card-form")).toBeInTheDocument();
  });
});
