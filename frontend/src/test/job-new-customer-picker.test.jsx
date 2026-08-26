/**
 * Feb-2026 · Customer picker UX contract on the New Job form.
 *
 * Locks the following properties so a future refactor can't
 * silently regress the P0 fix + the new active-only + searchable
 * picker behaviour:
 *
 *   1. Customer fetch call includes ``is_active=true`` so muted /
 *      inactive customers stay out of the picker.
 *   2. The picker uses shadcn ``Command`` + ``Popover`` primitives
 *      — no native ``<select>`` for the CUSTOMER field.
 *   3. The trigger button preserves ``data-testid="jf-customer"``
 *      so existing E2E / test-agent selectors keep resolving.
 *   4. Each row exposes ``data-testid="jf-customer-item-{id}"`` for
 *      deterministic row selection.
 *   5. Search input is present ("Search customers…" placeholder).
 *   6. The technician select and other selects are UNCHANGED — the
 *      swap is scoped strictly to the customer picker per PR spec.
 *
 * Structural (source-string) assertions match the codebase
 * convention for lightweight picker tests (see
 * ``customer-portal-invite-relocation.test.jsx``).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);

describe("JobNew — active-only + searchable customer picker", () => {
  it("customer fetch filters to active customers server-side", () => {
    expect(SRC).toMatch(/api\.get\("\/customers\?is_active=true"\)/);
    // The old un-filtered call is gone.
    expect(SRC).not.toMatch(/api\.get\("\/customers"\)\.then\(setCustomers/);
  });

  it("customer picker uses shadcn Command + Popover primitives", () => {
    expect(SRC).toMatch(
      /from\s*"@\/components\/ui\/popover"/,
    );
    expect(SRC).toMatch(
      /from\s*"@\/components\/ui\/command"/,
    );
    expect(SRC).toMatch(/<Popover\b/);
    expect(SRC).toMatch(/<CommandInput\b/);
    expect(SRC).toMatch(/<CommandItem\b/);
    expect(SRC).toMatch(/<CommandEmpty\b/);
  });

  it("no native <select> renders for the CUSTOMER field", () => {
    // The former inline pattern was:
    //   <label ...>CUSTOMER *</label>
    //   <select value={form.customer_id} ...>
    // Assert no ``<select>`` sits BETWEEN the CUSTOMER label and the
    // CustomerCombobox mount. Strip JSX comment blocks first — the
    // doc comment on the fix references the string "<select>" as
    // narrative.
    const custLabelIdx = SRC.indexOf("CUSTOMER *");
    expect(custLabelIdx).toBeGreaterThan(-1);
    const comboIdx = SRC.indexOf("<CustomerCombobox", custLabelIdx);
    expect(comboIdx).toBeGreaterThan(custLabelIdx);
    const custBlock = SRC
      .slice(custLabelIdx, comboIdx)
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, "");   // strip JSX comments
    expect(custBlock).not.toMatch(/<select\b/);
  });

  it("trigger + row testids are preserved", () => {
    expect(SRC).toMatch(/data-testid="jf-customer"/);
    expect(SRC).toMatch(
      /data-testid=\{`jf-customer-item-\$\{c\.id\}`\}/,
    );
    expect(SRC).toMatch(/data-testid="jf-customer-search"/);
  });

  it("search placeholder present", () => {
    expect(SRC).toMatch(/placeholder="Search customers…"/);
  });

  it("technician + service selects remain native <select> (scope guard)", () => {
    // Non-customer selects intentionally NOT migrated in this PR.
    // Lock the scope so a future picker sweep doesn't accidentally
    // pick up this file's other selects.
    expect(SRC).toMatch(/data-testid="jf-tech"/);
    // The tech field should still be a <select> — its block still
    // contains ``<select`` and its options are ``techs.map``.
    const techLabelIdx = SRC.indexOf("TECHNICIAN");
    expect(techLabelIdx).toBeGreaterThan(-1);
    const techBlock = SRC.slice(techLabelIdx, techLabelIdx + 1000);
    expect(techBlock).toMatch(/<select\b/);
    expect(techBlock).toMatch(/techs\.map/);
  });
});
