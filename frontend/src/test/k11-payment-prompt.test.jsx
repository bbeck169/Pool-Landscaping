/**
 * Phase K11 · Feb-2026 — Portal payment-method prompt UI contracts.
 *
 * Covers:
 *   1. Modal renders "Add a payment method" when prompt_kind=missing.
 *   2. Modal renders "Update your card" + expiring list when
 *      prompt_kind=expiring.
 *   3. Modal renders nothing when prompt_kind=none.
 *   4. Session marker prevents second render in same session.
 *   5. Snooze button POSTs the correct kind.
 *   6. Impersonation JWT hides the modal entirely.
 *   7. Banner renders on prompt_kind !== "none".
 *   8. Banner hides on impersonation.
 *   9. Banner inline dismiss hides for current render.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, postSpy, navigateSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
  },
  TOKEN_KEY: "token",
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
}));

// Fake JWT builder — payload is base64url-encoded JSON.
function _jwt(payload) {
  const enc = (obj) => btoa(JSON.stringify(obj))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `dummy.${enc(payload)}.sig`;
}

beforeEach(() => {
  getSpy.mockReset();
  postSpy.mockReset();
  navigateSpy.mockReset();
  sessionStorage.clear();
});
afterEach(() => cleanup());

import PaymentMethodPromptModal from "@/components/portal/PaymentMethodPromptModal";
import PaymentMethodPromptBanner from "@/components/portal/PaymentMethodPromptBanner";

describe("PaymentMethodPromptModal", () => {
  it("renders Add-a-payment-method modal for prompt_kind=missing", async () => {
    getSpy.mockResolvedValueOnce({ prompt_kind: "missing",
                                    expiring_cards: [],
                                    snoozed_until: null });
    render(<PaymentMethodPromptModal />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-modal")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("k11-prompt-title").textContent)
      .toBe("Add a payment method");
    expect(screen.getByTestId("k11-prompt-cta").textContent).toContain("Add card");
  });

  it("renders Update-your-card modal for prompt_kind=expiring with list", async () => {
    getSpy.mockResolvedValueOnce({
      prompt_kind: "expiring",
      expiring_cards: [
        { payment_method_id: "pm_a", brand: "Visa", last4: "4242",
          exp_month: 3, exp_year: 2026, days_until_expiry: 22 },
      ],
      snoozed_until: null,
    });
    render(<PaymentMethodPromptModal />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-modal")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("k11-prompt-title").textContent)
      .toBe("Update your card");
    const list = screen.getByTestId("k11-prompt-expiring-list");
    expect(list.textContent).toContain("Visa ending 4242");
    expect(list.textContent).toContain("22 days");
    expect(screen.getByTestId("k11-prompt-cta").textContent).toContain("Update card");
  });

  it("renders nothing for prompt_kind=none", async () => {
    getSpy.mockResolvedValueOnce({ prompt_kind: "none",
                                    expiring_cards: [],
                                    snoozed_until: null });
    render(<PaymentMethodPromptModal />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("k11-prompt-modal")).toBeNull();
  });

  it("session marker prevents a second render in the same session", async () => {
    sessionStorage.setItem("k11_prompt_shown", "1");
    render(<PaymentMethodPromptModal />);
    await new Promise((r) => setTimeout(r, 20));
    expect(getSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId("k11-prompt-modal")).toBeNull();
  });

  it("snooze button POSTs the correct kind then closes the modal", async () => {
    getSpy.mockResolvedValueOnce({ prompt_kind: "missing",
                                    expiring_cards: [],
                                    snoozed_until: null });
    postSpy.mockResolvedValueOnce({ snoozed_until: "2026-02-02T00:00:00Z" });
    render(<PaymentMethodPromptModal />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-modal")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("k11-prompt-snooze"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/portal/payment-method/prompt-snooze");
    expect(body).toEqual({ kind: "missing" });
    await waitFor(() =>
      expect(screen.queryByTestId("k11-prompt-modal")).toBeNull(),
    );
  });

  it("hides entirely when impersonation JWT is present in sessionStorage", async () => {
    sessionStorage.setItem("portal_token",
      _jwt({ role: "customer", sub: "u1",
             act: { sub: "admin-1", name: "Admin" } }));
    render(<PaymentMethodPromptModal />);
    await new Promise((r) => setTimeout(r, 20));
    expect(getSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId("k11-prompt-modal")).toBeNull();
  });
});

describe("PaymentMethodPromptBanner", () => {
  it("renders banner on prompt_kind=missing", async () => {
    getSpy.mockResolvedValueOnce({ prompt_kind: "missing",
                                    expiring_cards: [] });
    render(<PaymentMethodPromptBanner />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-banner")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("k11-prompt-banner").textContent)
      .toContain("Add a payment method");
    expect(screen.getByTestId("k11-prompt-banner-cta").textContent)
      .toContain("Add card");
  });

  it("renders banner on prompt_kind=expiring with brand/last4", async () => {
    getSpy.mockResolvedValueOnce({
      prompt_kind: "expiring",
      expiring_cards: [{ payment_method_id: "pm_a", brand: "Visa",
                          last4: "4242", exp_month: 3, exp_year: 2026,
                          days_until_expiry: 15 }],
    });
    render(<PaymentMethodPromptBanner />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-banner")).toBeInTheDocument(),
    );
    const txt = screen.getByTestId("k11-prompt-banner").textContent;
    expect(txt).toContain("Visa ending 4242");
    expect(txt).toContain("expires soon");
  });

  it("renders banner during active snooze via original_prompt_kind", async () => {
    getSpy.mockResolvedValueOnce({
      prompt_kind: "none",
      original_prompt_kind: "missing",
      expiring_cards: [],
      snoozed_until: "2026-02-02T00:00:00Z",
    });
    render(<PaymentMethodPromptBanner />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-banner")).toBeInTheDocument(),
    );
  });

  it("hides entirely on impersonation", async () => {
    sessionStorage.setItem("portal_token",
      _jwt({ role: "customer", sub: "u1",
             act: { sub: "admin-1", name: "Admin" } }));
    render(<PaymentMethodPromptBanner />);
    await new Promise((r) => setTimeout(r, 20));
    expect(getSpy).not.toHaveBeenCalled();
    expect(screen.queryByTestId("k11-prompt-banner")).toBeNull();
  });

  it("inline dismiss hides banner for the current render", async () => {
    getSpy.mockResolvedValueOnce({ prompt_kind: "missing",
                                    expiring_cards: [] });
    render(<PaymentMethodPromptBanner />);
    await waitFor(() =>
      expect(screen.getByTestId("k11-prompt-banner")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("k11-prompt-banner-dismiss"));
    await waitFor(() =>
      expect(screen.queryByTestId("k11-prompt-banner")).toBeNull(),
    );
  });
});
