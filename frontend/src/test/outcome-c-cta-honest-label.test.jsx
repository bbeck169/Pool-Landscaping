/**
 * Feb-2026 · Outcome C — Honest label on the customer-detail "Estimate"
 * dropdown item. The click path lands the user in ``/quotes/new`` which
 * auto-creates a Quote (not an Estimate), so the visible label + helper
 * caption must reflect that.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { CustomerActionDropdowns } from "../components/customers/CustomerActionDropdowns";

describe("Outcome C · customer-page 'Estimate' CTA honest label", () => {
  const customer = {
    id: "cust-1",
    name: "Test Customer",
    emails: [{ address: "t@example.com", is_primary: true }],
    mobiles: [{ number_e164: "+15555550100", is_primary: true }],
  };

  const renderIt = () =>
    render(
      <MemoryRouter>
        <CustomerActionDropdowns
          customer={customer}
          onSend={() => {}}
          onQuickTask={() => {}}
          onSendServiceRecordsLink={() => {}}
        />
      </MemoryRouter>,
    );

  it("renders the 'Estimate → Quote' label (not bare 'Estimate')", async () => {
    const user = (await import("@testing-library/user-event")).default;
    renderIt();
    // Open the "+ Create" dropdown to reveal items.
    const trigger = screen.getByTestId("customer-create-menu-trigger");
    await user.setup().click(trigger);
    const item = await screen.findByTestId("customer-create-estimate");
    // The user-facing label must contain the arrow AND the word "Quote".
    expect(item.textContent).toMatch(/Estimate.*Quote/);
    // Helper caption must clarify the auto-convert nature.
    expect(item.textContent).toMatch(/Creates a quote you can send, sign, and collect on/);
  });
});
