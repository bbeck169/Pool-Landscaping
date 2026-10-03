/**
 * Phase 2 B2 · Feb-2026 · QuoteRecipientPicker — vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}));

import { api } from "@/api";
import {
  QuoteRecipientPicker,
  RecipientTypeBadge,
} from "@/components/quotes/QuoteRecipientPicker";

const SEARCH_ROWS = [
  { id: "c-1", kind: "customer", display_name: "Alice Customer",
    email: "alice@c.com", phone: "" },
  { id: "l-1", kind: "lead", display_name: "Bob Lead",
    email: "bob@l.com", phone: "" },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(SEARCH_ROWS);
});

describe("<RecipientTypeBadge/>", () => {
  it("renders 'Customer' when type=customer", () => {
    render(<RecipientTypeBadge type="customer" testid="t-badge" />);
    const el = screen.getByTestId("t-badge");
    expect(el).toHaveAttribute("data-recipient-type", "customer");
    expect(el).toHaveTextContent(/customer/i);
  });

  it("renders 'Lead' when type=lead", () => {
    render(<RecipientTypeBadge type="lead" testid="t-badge" />);
    const el = screen.getByTestId("t-badge");
    expect(el).toHaveAttribute("data-recipient-type", "lead");
    expect(el).toHaveTextContent(/lead/i);
  });

  it("falls back to Customer badge for null/unknown type (B2 back-compat)", () => {
    render(<RecipientTypeBadge type={null} testid="t-badge" />);
    const el = screen.getByTestId("t-badge");
    expect(el).toHaveAttribute("data-recipient-type", "customer");
    expect(el).toHaveTextContent(/customer/i);
  });
});

describe("<QuoteRecipientPicker/>", () => {
  it("mounts with the picker testid and renders placeholder when empty", () => {
    render(
      <QuoteRecipientPicker value={null} onChange={() => {}} />,
    );
    expect(screen.getByTestId("quote-recipient-picker")).toBeInTheDocument();
  });

  it("pre-populates with a 'Customer' badge when loaded from a legacy quote shape (customer_id only)", () => {
    // Simulates the parent (QuoteInvoiceNew / detail) normalizing a
    // legacy quote doc that only has ``customer_id`` into the
    // picker's {type:"customer", id, name} shape. The selected-
    // badge MUST render as "Customer" so Phase 2 backfill-equivalent
    // resolution works client-side BEFORE the server migration runs.
    render(
      <QuoteRecipientPicker
        value={{ type: "customer", id: "legacy-c", name: "Legacy Customer" }}
        onChange={() => {}}
      />,
    );
    const trigger = screen.getByTestId("quote-recipient-picker");
    expect(trigger).toHaveAttribute("data-recipient-type", "customer");
    const badge = screen.getByTestId("quote-recipient-picker-selected-badge");
    expect(badge).toHaveTextContent(/customer/i);
    expect(trigger).toHaveTextContent(/Legacy Customer/);
  });

  it("renders a 'Lead' selected-badge when value.type=lead", () => {
    render(
      <QuoteRecipientPicker
        value={{ type: "lead", id: "l-99", name: "Prospective Pete" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("quote-recipient-picker"))
      .toHaveAttribute("data-recipient-type", "lead");
    expect(screen.getByTestId("quote-recipient-picker-selected-badge"))
      .toHaveTextContent(/lead/i);
  });

  it("fetches /quote-recipients/search on open and renders mixed Customer+Lead rows with per-row badges", async () => {
    render(<QuoteRecipientPicker value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByTestId("quote-recipient-picker"));
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).toMatch(
      /^\/quote-recipients\/search\?q=&limit=20$/,
    );
    const custBadge = await screen.findByTestId(
      "quote-recipient-picker-item-customer-c-1-badge",
    );
    const leadBadge = await screen.findByTestId(
      "quote-recipient-picker-item-lead-l-1-badge",
    );
    expect(custBadge).toHaveTextContent(/customer/i);
    expect(leadBadge).toHaveTextContent(/lead/i);
  });

  it("picking a lead row fires onChange({type:'lead', id, name})", async () => {
    const onChange = vi.fn();
    render(<QuoteRecipientPicker value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("quote-recipient-picker"));
    const item = await screen.findByTestId(
      "quote-recipient-picker-item-lead-l-1",
    );
    fireEvent.click(item);
    expect(onChange).toHaveBeenCalledWith({
      type: "lead", id: "l-1", name: "Bob Lead",
    });
  });

  it("picking a customer row fires onChange({type:'customer', ...})", async () => {
    const onChange = vi.fn();
    render(<QuoteRecipientPicker value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("quote-recipient-picker"));
    const item = await screen.findByTestId(
      "quote-recipient-picker-item-customer-c-1",
    );
    fireEvent.click(item);
    expect(onChange).toHaveBeenCalledWith({
      type: "customer", id: "c-1", name: "Alice Customer",
    });
  });
});
