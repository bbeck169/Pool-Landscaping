/**
 * CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — forward-compat ``employee``
 * role unlock + source-level contract that the K6 banner path
 * stays untouched.
 *
 * The runtime JobDetail bootstrap depends on ``useAuth`` +
 * ``useParams`` + ``api`` with a complex chain already covered
 * by the sibling K6 suite — we lock the semantic deltas here via
 * source inspection so a future refactor can't silently drop
 * "employee" or re-insert a 24h window check into
 * ``canEditCompleted``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../JobDetail.jsx"),
  "utf8",
);


describe("JobDetail · CLOSED-JOB-EDIT-UNLOCK contract", () => {
  it("K6_UNLOCK_ROLES set includes 'employee' forward-compat", () => {
    // Match the set literal and assert "employee" is present.
    const setStart = SRC.indexOf("const K6_UNLOCK_ROLES");
    expect(setStart).toBeGreaterThan(0);
    const setBlock = SRC.slice(setStart, setStart + 600);
    expect(setBlock).toMatch(/"employee"/);
    // All six staff roles still present (regression lock).
    for (const role of ["super_admin", "admin", "manager",
                                     "tech", "technician", "owner"]) {
      expect(setBlock).toMatch(new RegExp(`"${role}"`));
    }
  });

  it("canEditCompleted gate does NOT reference a 24h window / "
     + "hours-since-completion check (the central semantic of "
     + "CLOSED-JOB-EDIT-UNLOCK)", () => {
    const gateStart = SRC.indexOf("const canEditCompleted");
    expect(gateStart).toBeGreaterThan(0);
    // Extract the expression — stops at the next semicolon so we
    // only inspect the gate itself, not downstream render code.
    const semi = SRC.indexOf(";", gateStart);
    const gate = SRC.slice(gateStart, semi);
    // Pre-fix bug: a 24h window check would have surfaced via
    // one of these strings.  Regression lock.
    expect(gate).not.toMatch(/hoursSinceCompletion/i);
    expect(gate).not.toMatch(/hours_since_completion/);
    expect(gate).not.toMatch(/EDIT_WINDOW_HOURS/);
    expect(gate).not.toMatch(/24/);
    // Positive assertions — gate is EXACTLY the three clauses
    // (customer short-circuit, K6 whitelist, status gate).
    expect(gate).toMatch(/!isCustomer/);
    expect(gate).toMatch(/K6_UNLOCK_ROLES\.has/);
    expect(gate).toMatch(/job\?\.status\s*===\s*"completed"/);
  });

  it("customer role explicitly short-circuits even if a future "
     + "refactor adds 'customer' to the K6 set", () => {
    const gateStart = SRC.indexOf("const canEditCompleted");
    const gate = SRC.slice(gateStart, gateStart + 400);
    // ``!isCustomer`` is the FIRST clause — portal users can
    // never flip this gate true.
    expect(gate.indexOf("!isCustomer")).toBeLessThan(
      gate.indexOf("K6_UNLOCK_ROLES"),
    );
    // Regression lock: the gate expression itself must not
    // include the string ``"customer"`` as a value.
    expect(gate).not.toMatch(/"customer"/);
  });
});
