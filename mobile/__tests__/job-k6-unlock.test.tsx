/**
 * CLOSED-JOB-EDIT-UNLOCK mobile (1b68cec61) — K6 edit unlock on completed jobs.
 * Evaluates the role set + gate expression lifted verbatim from checklist.tsx.
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/job/[id]/checklist.tsx"), "utf-8");
const roles = JSON.parse(SRC.match(/K6_UNLOCK_ROLES = new Set\((\[[\s\S]*?\])\)/)![1].replace(/,\s*\]/, "]"));
const K6 = new Set<string>(roles);
const gate = (role: string, locked: boolean, status: string) => {
  const canEditCompleted = !locked ? false : K6.has(role || "") && status === "completed";
  return { canEditCompleted, effectiveLocked: locked && !canEditCompleted };
};

describe("K6 edit unlock", () => {
  it("technician on a submitted+completed job → canEditCompleted, editable", () => {
    expect(gate("technician", true, "completed")).toEqual({ canEditCompleted: true, effectiveLocked: false });
    expect(gate("admin", true, "completed").effectiveLocked).toBe(false);
  });

  it("boundary: customer / unknown role stays locked; non-completed stays locked", () => {
    expect(gate("customer", true, "completed")).toEqual({ canEditCompleted: false, effectiveLocked: true });
    expect(gate("", true, "completed").effectiveLocked).toBe(true);
    expect(gate("technician", true, "in_progress").effectiveLocked).toBe(true);
  });

  it("forms and media receive effectiveLocked, not the raw locked flag", () => {
    expect(SRC).toContain("const effectiveLocked = locked && !canEditCompleted;");
    expect(SRC).not.toMatch(/locked=\{locked\}|readonly=\{locked\}/);
    expect((SRC.match(/locked=\{effectiveLocked\}/g) || []).length).toBeGreaterThanOrEqual(4);
  });
});
