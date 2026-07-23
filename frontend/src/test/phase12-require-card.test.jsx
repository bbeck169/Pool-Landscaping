/**
 * Phase 12 · Feb 2026 — Frontend unit tests for the card-on-file
 * requirement UI.
 *
 *   1. Toggle flip sets an explicit override and reveals the
 *      "Reset to tenant default" ghost button.
 *   2. Warning banner is hidden when the customer has a card on
 *      file (or the requirement is off), and the send-link button
 *      is not present in that state.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CardOnFileControl from "@/components/customers/CardOnFileControl";
import CardOnFileWarningBanner from "@/components/customers/CardOnFileWarningBanner";


const _origFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn();
  process.env.REACT_APP_BACKEND_URL = "https://example.test";
});


describe("CardOnFileControl", () => {
  it("clicking the toggle from override=null sets an explicit override "
     + "and reveals the reset button", async () => {
    // 1st fetch → PATCH override=false response.
    global.fetch.mockResolvedValueOnce({
      ok: true,
      text: async () => JSON.stringify({
        id: "c1",
        require_card_on_file_override: false,
        effective_require_card_on_file: false,
        has_card_on_file: false,
        saved_payment_methods_count: 0,
      }),
      json: async () => ({
        id: "c1",
        require_card_on_file_override: false,
        effective_require_card_on_file: false,
        has_card_on_file: false,
        saved_payment_methods_count: 0,
      }),
    });
    const onSaved = vi.fn();
    // tenantDefault=true → toggle currently shows "on" (effective).
    // Tapping should persist the opposite (false).
    const initial = {
      id: "c1",
      require_card_on_file_override: null,
      effective_require_card_on_file: true,
      has_card_on_file: false,
      saved_payment_methods_count: 0,
    };
    const { rerender } = render(
      <CardOnFileControl customer={initial} tenantDefault={true}
                          onSaved={onSaved} />,
    );
    // Ghost "Reset" button not visible while override is null.
    expect(screen.queryByTestId("card-on-file-reset-default-btn"))
      .toBeNull();
    expect(screen.getByTestId("card-on-file-tenant-default-hint"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByTestId("card-on-file-toggle"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    // Backend request went out with override=false.
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.method).toBe("PATCH");
    expect(JSON.parse(opts.body)).toEqual({
      require_card_on_file_override: false,
    });
    // Rerender with the returned doc — now the reset button appears.
    rerender(
      <CardOnFileControl
        customer={{ ...initial, require_card_on_file_override: false,
                    effective_require_card_on_file: false }}
        tenantDefault={true}
        onSaved={onSaved}
      />,
    );
    expect(screen.getByTestId("card-on-file-reset-default-btn"))
      .toBeInTheDocument();
    expect(screen.getByTestId("card-on-file-override-hint"))
      .toBeInTheDocument();
  });
});


describe("CardOnFileWarningBanner", () => {
  it("is not rendered when the customer already has a card on file", () => {
    render(
      <CardOnFileWarningBanner
        customer={{
          id: "c1",
          effective_require_card_on_file: true,
          has_card_on_file: true,
        }}
      />,
    );
    expect(screen.queryByTestId("card-on-file-warning-banner")).toBeNull();
    expect(screen.queryByTestId("card-on-file-send-link-btn")).toBeNull();
  });

  it("renders + shows the send-link button when required and no card", () => {
    render(
      <CardOnFileWarningBanner
        customer={{
          id: "c1",
          effective_require_card_on_file: true,
          has_card_on_file: false,
        }}
      />,
    );
    expect(screen.getByTestId("card-on-file-warning-banner"))
      .toBeInTheDocument();
    expect(screen.getByTestId("card-on-file-send-link-btn"))
      .toBeInTheDocument();
  });
});
