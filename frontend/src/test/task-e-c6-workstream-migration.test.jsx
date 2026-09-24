/**
 * Task E · Feb-2026 · Commit 6/8 — Work Stream migration
 * source-body contract.
 *
 * Pins:
 *   • Filter bar → <NavyFilterBar> w/ K52.1 marker + page testid.
 *   • Both DatePicker sub-primitives (Since / Until) with labels.
 *   • Technician select — admin-only conditional preserved.
 *   • CustomerCombobox rendered inside NavyFilterBar.Combobox
 *     (passthrough shell — the child <CustomerCombobox> keeps
 *     its own type-ahead intact).
 *   • Sort select w/ label + ml-auto right alignment.
 *   • No Status filter — Phase 5A.2 removed it and Task E
 *     decision #2 kept the removal (spec item moot).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/workstream/WorkstreamPage.jsx"),
  "utf-8",
);


describe("Task E · Commit 6 — Work Stream migration contract", () => {
  it("mounts NavyFilterBar with the K52.1 marker and workstream-filter-bar testid", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar[\s\S]{0,200}data-testid="workstream-filter-bar"/
    );
    expect(SRC).toMatch(/data-k52-navy-strip="true"/);
  });

  it("delegates Since + Until to NavyFilterBar.DatePicker with labels + testids", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar\.DatePicker[\s\S]{0,400}label="Since"[\s\S]{0,400}data-testid="ws-filter-since"/
    );
    expect(SRC).toMatch(
      /<NavyFilterBar\.DatePicker[\s\S]{0,400}label="Until"[\s\S]{0,400}data-testid="ws-filter-until"/
    );
  });

  it("keeps the Technician select behind the isAdmin gate (admin-only visibility preserved)", () => {
    // The isAdmin ternary wraps the <NavyFilterBar.Select> whose
    // testid is ws-filter-tech, matching pre-migration behavior.
    expect(SRC).toMatch(
      /\{isAdmin \? \(\s*<NavyFilterBar\.Select[\s\S]{0,400}data-testid="ws-filter-tech"/
    );
  });

  it("wraps <CustomerCombobox> in NavyFilterBar.Combobox passthrough shell", () => {
    // Combobox is the passthrough variant — it just applies the
    // label + minWidth wrapping; the child CustomerCombobox
    // keeps its own type-ahead behavior + ws-filter-customer
    // testid intact.
    expect(SRC).toMatch(
      /<NavyFilterBar\.Combobox[\s\S]{0,200}label="Customer"[\s\S]{0,200}<CustomerCombobox/
    );
    expect(SRC).toMatch(/testid="ws-filter-customer"/);
  });

  it("delegates Sort to NavyFilterBar.Select with label + ml-auto right alignment + testid", () => {
    expect(SRC).toMatch(
      /<NavyFilterBar\.Select[\s\S]{0,400}label="Sort"[\s\S]{0,400}data-testid="ws-sort"/
    );
    // ml-auto pushes Sort to the right edge of the strip
    // (matches the pre-migration bare-flex layout).
    const sortIdx = SRC.indexOf('data-testid="ws-sort"');
    expect(sortIdx).toBeGreaterThan(-1);
    const sortBlock = SRC.slice(Math.max(0, sortIdx - 400), sortIdx + 300);
    expect(sortBlock).toMatch(/className="ml-auto"/);
  });

  it("confirms the Status filter stays REMOVED (Phase 5A.2 kept, decision #2)", () => {
    // No <NavyFilterBar.Select data-testid="ws-filter-status" or
    // similar — Phase 5A.2 removed it and Task E kept it out.
    expect(SRC).not.toMatch(/data-testid="ws-filter-status"/);
  });
});
