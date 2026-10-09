/**
 * Phase 11 · Feb-2026 — EBIT labor subtraction contract tests.
 *
 * The current EBIT display component (``components/admin/EbitPanel.jsx``)
 * does NOT yet render a dedicated LABOR row — it reads
 * ``revenue / cogs / opex / depreciation / ebit`` directly. Phase 11
 * ships the data layer (``labor_cost_total`` + ``recurring_labor_cost``);
 * a Phase 12 FE ticket will add the display row + breakdown toggle
 * on top of that data.
 *
 * To keep the semantic lock meaningful in CI RIGHT NOW, this suite
 * does source-body contract checks against:
 *   * ``services.finance.ebit`` — verifies the arithmetic + field
 *     shape Phase 11 committed to.
 *   * ``services.recurring_labor_cost`` — verifies the prorating
 *     helper is in the right place for the FE breakdown fetch to
 *     target later.
 *
 * When the FE display row ships (Phase 12), the test cases below
 * get upgraded from static greps to live React Testing Library
 * assertions.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const _BACKEND_ROOT = path.resolve(
  process.cwd(), "..", "backend");

const EBIT_SRC = fs.readFileSync(
  path.resolve(_BACKEND_ROOT, "services/finance/ebit.py"),
  "utf-8",
);
const RLC_SRC = fs.readFileSync(
  path.resolve(_BACKEND_ROOT, "services/recurring_labor_cost.py"),
  "utf-8",
);


describe("Phase 11 · EBIT labor-cost contract (data layer)", () => {
  it("1. ``ebit`` arithmetic subtracts ``labor_cost_total`` from the bottom line", () => {
    // Phase 11 explicit requirement — EBIT bottom-line is now
    // ``revenue - cogs - opex - depreciation - labor_cost_total``.
    // Grep locks the exact arithmetic. Any refactor must re-apply
    // this expression or the ratchet fires.
    expect(EBIT_SRC).toMatch(
      /ebit\s*=\s*revenue\s*-\s*cogs\s*-\s*opex\s*-\s*depreciation\s*-\s*labor_cost_total/,
    );
  });

  it("2. ``compute_ebit`` emits ``recurring_labor_cost`` + ``labor_cost_total`` top-level fields", () => {
    // The response envelope gains two new float fields. Phase 10's
    // ``labor_cost`` is retained unchanged (hourly + per-pool only)
    // for backwards-compat; Phase 11 adds ``recurring_labor_cost``
    // + ``labor_cost_total = labor_cost + recurring_labor_cost``.
    expect(EBIT_SRC).toMatch(/"recurring_labor_cost":\s*round\(recurring_labor_cost_amount,\s*2\)/);
    expect(EBIT_SRC).toMatch(/"labor_cost_total":\s*round\(labor_cost_total_amount,\s*2\)/);
    // Phase 10 field stays verbatim.
    expect(EBIT_SRC).toMatch(/"labor_cost":\s*round\(labor_cost_amount,\s*2\)/);
  });

  it("3. Phase 11 recurring compute call is wired via the dedicated helper", () => {
    // ``services.recurring_labor_cost.compute_recurring_labor_cost``
    // is the single source of truth for prorated recurring costs.
    expect(EBIT_SRC).toMatch(
      /from services\.recurring_labor_cost import compute_recurring_labor_cost/,
    );
    expect(EBIT_SRC).toMatch(
      /recurring_labor_breakdown\s*=\s*await compute_recurring_labor_cost\(/,
    );
  });

  it("4. Prorating helper uses the 30.4375 average-month-days constant", () => {
    // Brief locks the prorating constant to ``365.25 / 12 =
    // 30.4375``. This grep catches any accidental drift to
    // 30, 31, or 30.5.
    expect(RLC_SRC).toMatch(/_AVG_DAYS_PER_MONTH\s*=\s*Decimal\("30\.4375"\)/);
  });

  it("5. Prorating helper response shape is stable (by_entry + total + range)", () => {
    expect(RLC_SRC).toMatch(/"by_entry":\s*by_entry/);
    expect(RLC_SRC).toMatch(/"total":\s*_quantise_money\(total\)/);
    expect(RLC_SRC).toMatch(/"range":\s*\{"start":\s*start_date,\s*"end":\s*end_date\}/);
    // Each row ships monthly_amount + months_in_window +
    // cost_in_window at the right precision.
    expect(RLC_SRC).toMatch(/"monthly_amount":\s*_quantise_money\(monthly\)/);
    expect(RLC_SRC).toMatch(/"months_in_window":\s*_quantise_months\(months\)/);
    expect(RLC_SRC).toMatch(/"cost_in_window":\s*_quantise_money\(cost\)/);
  });

  it("6. Inactive-entry carve-out: status==inactive always contributes 0", () => {
    expect(RLC_SRC).toMatch(
      /if status\s*==\s*"active":[\s\S]{0,120}cost\s*=\s*monthly\s*\*\s*months[\s\S]{0,80}total\s*\+=\s*cost[\s\S]{0,80}else:\s*\n\s*cost\s*=\s*Decimal\(0\)/,
    );
  });

  it("7. labor_cost (Phase 10 field) is NOT the same as labor_cost_total (Phase 11)", () => {
    // Backwards-compat lock — the Phase 10 field name stays
    // verbatim; Phase 11 adds a distinct ``labor_cost_total``.
    const matches = EBIT_SRC.match(/"labor_cost"\s*:/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(1);
    const matches2 = EBIT_SRC.match(/"labor_cost_total"\s*:/g) || [];
    expect(matches2.length).toBeGreaterThanOrEqual(1);
    // They must be computed from DIFFERENT variables (one is the
    // Phase 10 hourly+per-pool only; the other is their sum with
    // recurring).
    expect(EBIT_SRC).toMatch(/labor_cost_total_amount\s*=\s*labor_cost_amount\s*\+\s*recurring_labor_cost_amount/);
  });
});
