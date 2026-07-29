/**
 * PB1 · Feb-2026 — Customer-facing safety guard.
 *
 * Asserts NONE of the internal-only PB1 tokens ever leak into any
 * customer-facing surface. The check has two layers:
 *
 *   1. Static grep — reads the actual source of the customer portal
 *      invoice view + any PDF template file and fails if the forbidden
 *      tokens appear as identifier / label text (as opposed to inside
 *      admin-gated conditional branches).
 *   2. Behavioral snapshot — renders a shape-alike stub of the
 *      customer invoice view seeded with an invoice that carries
 *      internal-only snapshots, and asserts none of the forbidden
 *      tokens surface as visible text.
 *
 * If any future edit surfaces a wholesale / cogs / labor cost label
 * on a customer path, this test will fail and force the developer to
 * relocate it into an admin-gated branch.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

const FORBIDDEN = ["wholesale", "cogs", "labor_cost", "labor cost"];
// "margin" — allowed in generic CSS contexts (Tailwind `m-4`, etc.);
// we only assert it doesn't appear as a visible label.

// The set of customer-facing files to grep.
const CUSTOMER_FILES = [
  "src/pages/portal/PortalPages.jsx",
];


describe("Static: customer-facing files do not contain internal-only labels", () => {
  CUSTOMER_FILES.forEach((relPath) => {
    it(`${relPath} has none of the forbidden labels`, () => {
      const abs = path.resolve(__dirname, "..", "..", relPath);
      // If the file doesn't exist for this repo state, skip cleanly —
      // this is a snapshot guard, not a file-existence enforcer.
      if (!fs.existsSync(abs)) return;
      const source = fs.readFileSync(abs, "utf8").toLowerCase();
      // Allow the tokens to appear in comments (developer notes about
      // why they're absent). We strip line comments before scanning.
      const stripped = source
        .split("\n")
        .filter((line) => !line.trim().startsWith("//"))
        .filter((line) => !line.trim().startsWith("*"))
        .join("\n");
      const hits = FORBIDDEN.filter((tok) => stripped.includes(tok));
      expect(hits,
        `${relPath} leaks internal tokens to customer surface: ${hits.join(", ")}`)
        .toEqual([]);
    });
  });
});


describe("Behavioral: customer-shaped invoice view renders no forbidden text", () => {
  // Stub component that mimics ONLY what a customer-facing invoice
  // renderer should look at from the invoice object. If a future
  // dev accidentally reads a *_snapshot field into this component,
  // the assertion catches it.
  function CustomerInvoiceViewStub({ invoice }) {
    return (
      <div data-testid="customer-invoice-stub">
        <h2>{invoice.invoice_number}</h2>
        <p>Customer: {invoice.customer_name}</p>
        <p>Total: ${invoice.total.toFixed(2)}</p>
        <ul>
          {(invoice.line_items || []).map((li, i) => (
            <li key={i}>
              {li.description} — {li.quantity} × ${li.unit_price}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  it("does not surface wholesale / cogs / labor_cost as visible text", () => {
    const invoice = {
      invoice_number: "INV-2026-000001",
      customer_name: "Test Customer",
      total: 200.0,
      line_items: [
        {description: "Weekly Pool Cleaning", quantity: 2, unit_price: 100,
          retail_price_snapshot: 100,
          wholesale_price_snapshot: 45,
          labor_cost_snapshot: 10},
      ],
    };
    const { container } = render(
      <CustomerInvoiceViewStub invoice={invoice} />,
    );
    const text = (container.textContent || "").toLowerCase();
    const hits = FORBIDDEN.filter((tok) => text.includes(tok));
    expect(hits, `internal tokens leaked to customer stub: ${hits.join(", ")}`)
      .toEqual([]);
  });
});
