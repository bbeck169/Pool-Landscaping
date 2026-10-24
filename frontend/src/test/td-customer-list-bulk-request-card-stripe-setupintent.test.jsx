/**
 * TD-customer-list-bulk-request-card-stripe-setupintent · Feb-2026.
 *
 * Supersedes Ticket I's vitest.  Covers:
 *   1. CustomersList.jsx source wiring — toolbar + modal mount.
 *   2. RequestCardOnFileModal rendered under test — new Stripe
 *      flow (no template picker; hardcoded preview; POST hits
 *      /customers/bulk-request-card-setup-intent).
 *   3. CustomerCardCapturePage source assertions —
 *      Elements provider options prove Link + wallets disabled.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import {
  describe, it, expect, vi, afterEach,
} from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, act } from "@testing-library/react";

const SRC_LIST = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomersList.jsx"), "utf8");
const SRC_CAPTURE = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/CustomerCardCapturePage.jsx"), "utf8");


describe("Ticket J · CustomersList + CustomerCardCapturePage source wiring", () => {
  it("CustomersList still imports and mounts RequestCardOnFileModal", () => {
    expect(SRC_LIST).toMatch(
      /import RequestCardOnFileModal from "@\/pages\/customers\/RequestCardOnFileModal";/,
    );
    expect(SRC_LIST).toMatch(/<RequestCardOnFileModal/);
    expect(SRC_LIST).toMatch(/customerIds=\{Array\.from\(selected\)\}/);
  });

  it("CustomerCardCapturePage disables Link + wallets on the Elements provider", () => {
    // The exact snapshot the ticket requires — proves Link is off
    // + no Apple/Google Pay auto-prompt.
    expect(SRC_CAPTURE).toMatch(
      /wallets: \{ link: "never", applePay: "never", googlePay: "never" \}/,
    );
  });

  it("CustomerCardCapturePage uses PaymentElement with layout:tabs (card-only)", () => {
    expect(SRC_CAPTURE).toMatch(
      /<PaymentElement options=\{\{ layout: "tabs" \}\} \/>/,
    );
  });

  it("CustomerCardCapturePage posts to /card-capture/{token}/confirm", () => {
    expect(SRC_CAPTURE).toMatch(
      /\/card-capture\/\$\{encodeURIComponent\(token\)\}\/confirm/,
    );
  });

  it("CustomerCardCapturePage surfaces token_expired / token_already_used copy", () => {
    expect(SRC_CAPTURE).toMatch(/token_already_used/);
    expect(SRC_CAPTURE).toMatch(/token_expired/);
    expect(SRC_CAPTURE).toMatch(/token_not_found/);
  });
});


// ─── RequestCardOnFileModal rendered under test ──────────────────
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({}),
    post: (...a) => postMock(...a),
    patch: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/components/ui-kit", () => ({
  Button: ({ children, onClick, disabled, "data-testid": tid }) => (
    <button onClick={onClick} disabled={disabled} data-testid={tid}>{children}</button>
  ),
  Modal: ({ open, children, "data-testid": tid }) =>
    open ? <div data-testid={tid}>{children}</div> : null,
}));

import RequestCardOnFileModal from "@/pages/customers/RequestCardOnFileModal";

afterEach(() => { cleanup(); postMock.mockReset(); });


describe("Ticket J · RequestCardOnFileModal (Stripe flow)", () => {
  it("renders recipient count + hardcoded email + sms previews (no template picker)", () => {
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1", "c-2", "c-3"]} onSent={() => {}} />);
    expect(screen.getByTestId("request-card-recipient-count").textContent)
      .toContain("3");
    // No template picker rendered — just the two previews.
    expect(screen.getByTestId("request-card-email-preview")).toBeTruthy();
    expect(screen.getByTestId("request-card-sms-preview")).toBeTruthy();
    expect(screen.queryByTestId("request-card-email-select")).toBeNull();
    expect(screen.queryByTestId("request-card-sms-select")).toBeNull();
  });

  it("POSTs /customers/bulk-request-card-setup-intent with customer_ids only (no template ids)", async () => {
    postMock.mockResolvedValue({
      results: [{ customer_id: "c-1", status: "sent_both",
                   email_status: "sent", sms_status: "sent" }],
      counts: { email_sent: 1, sms_sent: 1, skipped: 0, error: 0 },
    });
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1"]} onSent={() => {}} />);
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));

    const call = postMock.mock.calls.find(
      (c) => String(c[0]) === "/customers/bulk-request-card-setup-intent",
    );
    expect(call).toBeTruthy();
    expect(call[1]).toEqual({ customer_ids: ["c-1"] });
    // Legacy Ticket I keys must not reappear.
    expect(call[1].email_template_id).toBeUndefined();
    expect(call[1].sms_template_id).toBeUndefined();
  });

  it("renders the per-row summary on 200", async () => {
    postMock.mockResolvedValue({
      results: [
        { customer_id: "c-1", status: "sent_both",
          email_status: "sent", sms_status: "sent" },
        { customer_id: "c-2", status: "skipped_no_contact",
          email_status: "skipped", sms_status: "skipped" },
      ],
      counts: { email_sent: 1, sms_sent: 1, skipped: 1, error: 0 },
    });
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1", "c-2"]} onSent={() => {}} />);
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));
    await waitFor(() => expect(screen.getByTestId("request-card-summary")).toBeTruthy());
    expect(screen.getByTestId("summary-email-sent").textContent).toContain("1");
    expect(screen.getByTestId("summary-skipped").textContent).toContain("1");
  });

  it("surfaces categorised 403 tenant_isolation_breach errors inline", async () => {
    postMock.mockImplementation(() => {
      const err = new Error("Forbidden"); err.status = 403;
      err.data = { detail: {
        error: "tenant_isolation_breach",
        errors: [
          { customer_id: "c-foreign", reason: "foreign_tenant", tenant_id: "other" },
          { customer_id: "c-orphan", reason: "orphan" },
        ],
      }};
      return Promise.reject(err);
    });
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-foreign", "c-orphan"]} onSent={() => {}} />);
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));
    await waitFor(() =>
      expect(screen.getByTestId("request-card-error-panel")).toBeTruthy());
    expect(screen.getByTestId("request-card-error-foreign_tenant")).toBeTruthy();
    expect(screen.getByTestId("request-card-error-orphan")).toBeTruthy();
  });
});
