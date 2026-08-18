/**
 * Feb-2026 · Schedule Edit modal · assignable-user widen.
 *
 * Asserts the Technician dropdown labels non-technician roles with
 * a role suffix — so admin + super_admin + manager users are
 * visibly present alongside real techs.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/ScheduleJobEditModal.jsx"),
  "utf8",
);

describe("ScheduleJobEditModal · assignable-user widen", () => {
  it("suffixes admin / super_admin / manager options with role hint", () => {
    expect(src).toMatch(/r\s*===\s*["']super_admin["'].*Super Admin/);
    expect(src).toMatch(/r\s*===\s*["']admin["'].*Admin/);
    expect(src).toMatch(/r\s*===\s*["']manager["'].*Manager/);
  });

  it("renders every fetched tech option (no client-side role filter)", () => {
    // Regression guard — earlier versions may have filtered
    // ``techs.filter(t => t.role === "technician")``. That must
    // NOT come back.
    expect(src).not.toMatch(/techs\.filter\([^)]*role\s*===\s*["']technician["']/);
    // Each option should be keyed on t.id + label combines
    // ``t.name`` + role suffix.
    expect(src).toMatch(/\{t\.name\}\{suffix\}/);
  });
});
