/**
 * Ticket AA · Feb-2026 · CombinedCategoryBadge vitest.
 *
 * Locks the combinatorial rendering of the read-only badge on the
 * CustomerDetail identity header:
 *   * zero properties                → "—"
 *   * all-Pool                       → "Pool"
 *   * all-Landscaping                → "Landscaping"
 *   * all-Both                       → "Both"
 *   * Pool + Landscaping             → "Pool + Landscaping"
 *   * Pool + Both                    → "Pool + Both"
 *   * Landscaping + Both             → "Landscaping + Both"
 *   * Pool + Landscaping + Both      → "Pool + Landscaping + Both"
 *   * inactive properties ignored
 *   * null properties contribute nothing
 *   * hover tooltip "Set category per property below"
 *   * no click handler (negative check — badge is read-only)
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  CombinedCategoryBadge, _computeCombinedCategory,
} from "@/components/customers/CombinedCategoryBadge";


const _p = (id, service_category, { active = true } = {}) => ({
  id, service_category, active,
});


describe("Ticket AA · CombinedCategoryBadge", () => {
  it("renders '—' when properties is empty", () => {
    render(<CombinedCategoryBadge properties={[]} />);
    const el = screen.getByTestId("customer-combined-category-badge");
    expect(el).toHaveTextContent("—");
    expect(el).toHaveAttribute("data-combined-category", "");
  });

  it("renders '—' when properties is null/undefined", () => {
    render(<CombinedCategoryBadge properties={null} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("—");
  });

  it("renders 'Pool' when every active property is pool", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "pool"), _p("b", "pool")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool");
  });

  it("renders 'Landscaping' when every active property is landscaping",
     () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "landscaping")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Landscaping");
  });

  it("renders 'Both' when every active property is both", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "both"), _p("b", "both")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Both");
  });

  it("renders 'Pool + Landscaping' on heterogeneous P + L mix", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "pool"), _p("b", "landscaping")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool + Landscaping");
  });

  it("renders 'Pool + Both' on P + B mix", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "pool"), _p("b", "both")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool + Both");
  });

  it("renders 'Landscaping + Both' on L + B mix", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "landscaping"), _p("b", "both")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Landscaping + Both");
  });

  it("renders 'Pool + Landscaping + Both' on P + L + B mix", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "pool"), _p("b", "landscaping"), _p("c", "both")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool + Landscaping + Both");
  });

  it("ignores inactive properties (matches dashboard aggregator)",
     () => {
    render(<CombinedCategoryBadge
      properties={[
        _p("a", "pool"),
        _p("b", "landscaping", { active: false }),
      ]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool");
  });

  it("ignores null-category properties", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", null), _p("b", "pool")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool");
  });

  it("renders '—' when all properties have null categories", () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", null), _p("b", "")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("—");
  });

  it("exposes 'Set category per property below' as hover tooltip",
     () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "pool")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveAttribute("title", "Set category per property below");
  });

  it("is NOT clickable (negative check — no button role, no " +
     "onClick handler bubbles out)",
     () => {
    render(<CombinedCategoryBadge properties={[_p("a", "pool")]} />);
    const el = screen.getByTestId("customer-combined-category-badge");
    // Not a <button>; no interactive role.
    expect(el.tagName.toLowerCase()).toBe("span");
    expect(el).not.toHaveAttribute("role", "button");
  });

  it("is case-insensitive (legacy 'Pool' / 'POOL' rows map to pool)",
     () => {
    render(<CombinedCategoryBadge
      properties={[_p("a", "Pool"), _p("b", "LANDSCAPING")]} />);
    expect(screen.getByTestId("customer-combined-category-badge"))
      .toHaveTextContent("Pool + Landscaping");
  });

  it("_computeCombinedCategory returns null for empty / all-null " +
     "inputs (surface-area contract)", () => {
    expect(_computeCombinedCategory([])).toBeNull();
    expect(_computeCombinedCategory(null)).toBeNull();
    expect(_computeCombinedCategory([_p("a", null)])).toBeNull();
  });
});
