/**
 * Phase J1 · Feb-2026 — checklist-type priority chain (web).
 *
 * Locks in that `getChecklistType` consults **Job Title / Service
 * Type** BEFORE the assigned tech's department, with an explicit
 * `checklist_kind` override still winning above everything.
 *
 * Mirror suite: backend/tests/test_checklist_kind_priority.py
 */

import { describe, it, expect } from "vitest";
import { getChecklistType } from "../lib/checklistType.js";

describe("Phase J1 · getChecklistType priority chain", () => {
  it("landscaping service_type + Pool-department tech → landscaping", () => {
    expect(
      getChecklistType({
        service_type: "Lawn mow + trim",
        technician_department: "pool",
      })
    ).toBe("landscaping");
  });

  it("pool service_type + Landscaping-department tech → pool", () => {
    expect(
      getChecklistType({
        service_type: "Weekly pool chem service",
        technician_department: "landscaping",
      })
    ).toBe("pool");
  });

  it("no service_type signal + Landscaping tech → landscaping (falls back to tech dept)", () => {
    expect(
      getChecklistType({
        service_type: "General visit",
        title: "Site walk",
        technician_department: "landscaping",
      })
    ).toBe("landscaping");
  });

  it("explicit checklist_kind override wins over service_type and tech dept", () => {
    expect(
      getChecklistType({
        checklist_kind: "pool",
        // Service type + tech both scream landscape — override still wins.
        service_type: "landscape cleanup",
        technician_department: "landscaping",
      })
    ).toBe("pool");
  });

  it("no signals at all → pool (safe default preserved)", () => {
    expect(getChecklistType({})).toBe("pool");
  });
});
