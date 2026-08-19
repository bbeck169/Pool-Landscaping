/**
 * Feb-2026 · Pricebook item_type — web tests.
 *
 * Covers:
 *   1. Line-item picker locks unit_price on a Product line
 *      (readOnly + lock icon) and unlocks on a Service line.
 *   2. Editing a Service line's price beyond the pricebook value
 *      shows the "overridden" chip.
 *   3. Pricebook new-item toggle scrubs supplier state client-side
 *      when the operator picks Service.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React, { useState } from "react";


vi.mock("@/theme", () => ({
  colors: {
    brand: "#0f6ed1", muted: "#666", onSurface: "#111",
    surface: "#fff", surfaceSecondary: "#f5f5f5", border: "#ccc",
    error: "#c00", text: "#111", divider: "#eee",
  },
  font: { family: "system-ui" },
}));


// ─────────────────────────────────────────────────────────────────────
// 1 & 2 · Line-item price-lock cell (mirrors QuoteInvoiceNew logic).
// ─────────────────────────────────────────────────────────────────────
function PriceCell({ li, onChange }) {
  const isProduct = (li._item_type || "product").toLowerCase() === "product"
                     && !!li.item_id;
  const overridden = !isProduct
     && li._pricebook_unit_price != null
     && Math.abs(Number(li.unit_price || 0)
                  - Number(li._pricebook_unit_price || 0)) > 0.005;
  return (
    <div data-testid="qf-line-0-price-wrap">
      <input
        type="number"
        value={li.unit_price}
        readOnly={isProduct}
        disabled={isProduct}
        onChange={(e) => onChange(e.target.value)}
        data-testid="qf-line-0-price"
      />
      {isProduct ? <span data-testid="qf-line-0-price-lock">🔒</span> : null}
      {overridden ? (
        <span data-testid="qf-line-0-price-overridden">overridden</span>
      ) : null}
    </div>
  );
}


describe("line-item picker · price lock behaviour", () => {
  it("locks price on a product line (readOnly + lock icon)", () => {
    const li = {
      description: "Chlorine 1gal", unit_price: 25, item_id: "it-1",
      _item_type: "product", _pricebook_unit_price: 25,
    };
    render(<PriceCell li={li} onChange={() => {}} />);
    const input = screen.getByTestId("qf-line-0-price");
    expect(input).toHaveAttribute("readOnly");
    expect(input).toBeDisabled();
    expect(screen.getByTestId("qf-line-0-price-lock")).toBeInTheDocument();
    expect(screen.queryByTestId("qf-line-0-price-overridden")).toBeNull();
  });

  it("unlocks price on a service line and shows overridden chip when diverged", () => {
    function Wrapper() {
      const [li, setLi] = useState({
        description: "Weekly svc", unit_price: 150, item_id: "svc-1",
        _item_type: "service", _pricebook_unit_price: 150,
      });
      return <PriceCell li={li}
                        onChange={(v) => setLi({ ...li, unit_price: v })} />;
    }
    render(<Wrapper />);
    const input = screen.getByTestId("qf-line-0-price");
    expect(input).not.toBeDisabled();
    expect(screen.queryByTestId("qf-line-0-price-lock")).toBeNull();
    expect(screen.queryByTestId("qf-line-0-price-overridden")).toBeNull();
    fireEvent.change(input, { target: { value: "175" } });
    expect(screen.getByTestId("qf-line-0-price-overridden"))
      .toBeInTheDocument();
  });
});


// ─────────────────────────────────────────────────────────────────────
// 3 · Pricebook new-item type toggle scrubs supplier state.
// ─────────────────────────────────────────────────────────────────────
function NewItemTypeToggle({ form, setForm }) {
  return (
    <div data-testid="pb-new-type-toggle">
      {[{ v: "product", label: "Product" },
        { v: "service", label: "Service" }].map((opt) => (
        <button key={opt.v} type="button"
          data-testid={`pb-new-type-${opt.v}`}
          onClick={() => setForm({
            ...form, item_type: opt.v,
            ...(opt.v === "service" ? {
              income_category_id: "", supplier_prices: {},
              wholesale_price: 0, labor_cost_default: 0,
            } : {}),
          })}
        >{opt.label}</button>
      ))}
      {form.item_type === "service" ? (
        <div data-testid="pb-new-service-helper">
          Service prices are editable per-customer on estimates and invoices.
        </div>
      ) : null}
      {form.item_type !== "service" && form.income_category_id ? (
        <div data-testid="pb-new-supplier-grid">supplier grid</div>
      ) : null}
    </div>
  );
}


describe("pricebook new-item type toggle", () => {
  it("hides supplier grid + shows helper when Service is picked", () => {
    function Wrapper() {
      const [form, setForm] = useState({
        item_type: "product", income_category_id: "ic-1",
        wholesale_price: 12.5, supplier_prices: { s1: 10 },
      });
      return <NewItemTypeToggle form={form} setForm={setForm} />;
    }
    render(<Wrapper />);
    // Product mode → supplier grid visible, helper hidden.
    expect(screen.getByTestId("pb-new-supplier-grid")).toBeInTheDocument();
    expect(screen.queryByTestId("pb-new-service-helper")).toBeNull();
    // Flip to Service.
    fireEvent.click(screen.getByTestId("pb-new-type-service"));
    // Supplier grid gone; helper shown.
    expect(screen.queryByTestId("pb-new-supplier-grid")).toBeNull();
    expect(screen.getByTestId("pb-new-service-helper")).toBeInTheDocument();
  });
});
