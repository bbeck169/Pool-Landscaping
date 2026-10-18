/**
 * CLOSED-JOB-EDIT-UNLOCK mobile (1b68cec61) — K6 edit unlock on completed jobs.
 * m-k6-lib — the role set + gate now live in src/lib/k6Unlock.ts (single
 * canonical mobile copy); checklist.tsx consumes it.
 */
import * as fs from "fs";
import * as path from "path";

import { K6_UNLOCK_ROLES, canEditCompletedJob } from "@/src/lib/k6Unlock";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/job/[id]/checklist.tsx"), "utf-8");
const gate = (role: string, locked: boolean, status: string) => {
  const canEditCompleted = !locked ? false : canEditCompletedJob(role, { status });
  return { canEditCompleted, effectiveLocked: locked && !canEditCompleted };
};

describe("K6 edit unlock", () => {
  it("role set = BE/web K6_UNLOCK_ROLES (8 roles incl. dispatcher · TD-78c)", () => {
    expect([...K6_UNLOCK_ROLES].sort()).toEqual(
      ["admin", "dispatcher", "employee", "manager", "owner", "super_admin", "tech", "technician"],
    );
    expect(gate("dispatcher", true, "completed")).toEqual({ canEditCompleted: true, effectiveLocked: false });
  });

  it("checklist consumes the lib — no inline duplicate set", () => {
    expect(SRC).toContain('from "@/src/lib/k6Unlock"');
    expect(SRC).toContain("const canEditCompleted = !locked ? false : canEditCompletedJob(role, job);");
    expect(SRC).not.toMatch(/K6_UNLOCK_ROLES = new Set/);
  });

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
