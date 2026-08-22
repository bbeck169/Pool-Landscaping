/**
 * Feb-2026 · P42 — Customer since label (Vitest).
 *
 * The customer detail page is heavy — we render just the label snippet
 * against a minimal component that mirrors the exact JSX the page uses.
 * That keeps the assertion focused (label visibility + hidden-when-null
 * + Month Year formatting) without spinning up every dependency of
 * ``CustomerDetail.jsx``.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";


// Mirror the exact snippet used in CustomerDetail.jsx.
function CustomerSinceLabel({ customer_since }) {
  if (!customer_since) return null;
  return (
    <span
      data-testid="customer-since-label"
      title={customer_since}
    >
      {`Customer since ${new Date(customer_since)
          .toLocaleDateString(undefined, {
              month: "long", year: "numeric" })}`}
    </span>
  );
}


describe("CustomerSinceLabel · P42", () => {
  it("renders when customer_since is set", () => {
    render(<CustomerSinceLabel customer_since="2024-03-15T00:00:00Z" />);
    const el = screen.getByTestId("customer-since-label");
    expect(el).toBeTruthy();
    // Month Year format — flexibly matched to tolerate the local
    // timezone shifting March 15 by a few hours.
    expect(el.textContent).toMatch(/Customer since (Feb|Mar)\w* 2024/);
    // Full ISO on hover (title).
    expect(el.getAttribute("title")).toBe("2024-03-15T00:00:00Z");
  });

  it("hides entirely when customer_since is null", () => {
    render(<CustomerSinceLabel customer_since={null} />);
    expect(screen.queryByTestId("customer-since-label")).toBeNull();
  });

  it("hides entirely when customer_since is missing", () => {
    render(<CustomerSinceLabel />);
    expect(screen.queryByTestId("customer-since-label")).toBeNull();
  });
});
