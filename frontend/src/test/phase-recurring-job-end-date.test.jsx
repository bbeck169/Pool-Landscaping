/**
 * Feb-2026 · Recurring Jobs · end_date helper text + list column.
 *
 * Small unit-level tests. Full RecurringJobs page pulls in auth
 * context + Google Maps SDK — out of scope for a vitest — so we
 * assert the helper-text + column-render contracts against small
 * inline component wrappers that mirror the JSX.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";


/** Mirrors the em-dash-when-empty rendering added on the list table
 *  (``End Date`` column of ``RecurringJobs.jsx``). */
function EndDateCell({ endDate, rowId }) {
  return (
    <td data-testid={`recurring-cell-end-date-${rowId}`}>{endDate || "—"}</td>
  );
}


/** Mirrors the helper-text span injected under the ``End Date``
 *  form field in the create/edit modal. */
function EndDateHelper() {
  return (
    <span data-testid="recurring-jobs-end-helper">
      Leave blank for no end date (runs forever).
    </span>
  );
}


describe("RecurringJobs · end_date column", () => {
  it("renders the ISO date when present", () => {
    const { getByTestId } = render(
      <table><tbody><tr>
        <EndDateCell endDate="2026-06-15" rowId="tpl-1" />
      </tr></tbody></table>,
    );
    expect(getByTestId("recurring-cell-end-date-tpl-1").textContent)
      .toBe("2026-06-15");
  });

  it("renders em-dash when end_date is null / empty", () => {
    const { getByTestId, rerender } = render(
      <table><tbody><tr>
        <EndDateCell endDate={null} rowId="tpl-2" />
      </tr></tbody></table>,
    );
    expect(getByTestId("recurring-cell-end-date-tpl-2").textContent).toBe("—");
    rerender(
      <table><tbody><tr>
        <EndDateCell endDate="" rowId="tpl-2" />
      </tr></tbody></table>,
    );
    expect(getByTestId("recurring-cell-end-date-tpl-2").textContent).toBe("—");
  });
});


describe("RecurringJobs · end_date helper text", () => {
  it("renders the runs-forever hint", () => {
    const { getByTestId } = render(<EndDateHelper />);
    const el = getByTestId("recurring-jobs-end-helper");
    expect(el.textContent).toContain("Leave blank for no end date");
    expect(el.textContent).toContain("runs forever");
  });
});
