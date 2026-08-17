// Feb-2026 P0 fix · Pricebook Add-item modal — 400 unwrap + client
// guard against ``supplier_prices_without_income_category``.
//
// Root cause: user could reach a state where ``supplier_prices`` had
// entries but ``income_category_id`` was empty. Backend correctly
// 400s; frontend was dumping the raw JSON string onto the toast.
// This locks in the fix: guarded save(), disabled Save button, and
// structured-error unwrap.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const OPS = resolve(__dirname, "../pages/ops/OpsHub.jsx");
const src = readFileSync(OPS, "utf8");

describe("Feb-2026 P0 · Pricebook Add-item 400 fix", () => {
  it("save() guards supplier_prices+empty income_category before hitting the API", () => {
    expect(src).toMatch(
      /supplier_prices\.length > 0 && !form\.income_category_id/,
    );
    expect(src).toMatch(
      /Pick an Income Category before entering supplier prices/,
    );
  });

  it("unwraps the structured 400 detail into human toasts", () => {
    // Each known backend error code has a human copy in the catch block.
    expect(src).toContain("supplier_prices_without_income_category");
    expect(src).toContain("supplier_income_category_mismatch");
    expect(src).toContain("unknown_supplier");
    expect(src).toContain("duplicate_supplier_slug");
    expect(src).toContain("invalid_cost_cents");
    // The parsed-JSON path shouldn't just fall through to e.message.
    expect(src).toContain("JSON.parse(msg)");
    expect(src).toContain('parsed?.detail ?? parsed');
  });

  it("disables the Save button in the pathological state", () => {
    // The disabled= expression now includes an income_category
    // OR-guard when any supplier price is filled in.
    expect(src).toContain(
      "Object.values(form.supplier_prices || {})",
    );
    expect(src).toMatch(/some\(\(v\) => String\(v \?\? ""\)\.trim\(\) !== ""\)/);
  });

  it("still passes cost as cents (Math.round(dollars * 100))", () => {
    expect(src).toContain("Math.round(dollars * 100)");
  });
});
