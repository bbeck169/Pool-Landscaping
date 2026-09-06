/**
 * Phase K42 · Feb-2026 — Schedule tech-filter dropdown contract.
 *
 * Bug: filtering by tech "Ethan Smith" on the Schedule page returned
 * zero jobs even though jobs were assigned to him.  Root cause: the
 * dropdown option shipped ``t.user_id || t.id`` while the backend
 * ``scope_jobs_query`` matched exact-equals against
 * ``jobs.technician_id`` (which was persisted as ``technicians.id``).
 *
 * Fix — the dropdown MUST always ship the authoritative
 * ``technicians.id`` (``t.id``).  The backend K42 resolver still
 * accepts either variant defensively.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);

describe("K42 · Schedule tech-filter dropdown", () => {
  it("emits t.id (technicians.id) as the option value — NEVER t.user_id", () => {
    // Locate the dropdown block and assert on the specific line.
    // Pre-K42 shape (bug): value={t.user_id || t.id}
    // Post-K42 shape:      value={t.id}
    expect(SRC).not.toMatch(/value=\{t\.user_id \|\| t\.id\}/);
    expect(SRC).toMatch(/value=\{t\.id\}>\{t\.name \|\| t\.email\}<\/option>/);
  });

  it("hydrates the dropdown from /technicians (authoritative source)", () => {
    // Regression guard: the dropdown must NOT switch to
    // /users?role=technician which would emit users.id and re-open
    // the K42 bug.
    //
    // Phase Hygiene B · Feb-2026 — schedule loader now passes an explicit
    // timeout as the second arg to ``api.get`` — relax the regex to
    // accept an optional trailing arg.
    expect(SRC).toMatch(/api\.get\("\/technicians"(?:\s*,[^)]*)?\)/);
  });

  it("preserves the K42 rationale comment so a future refactor can't accidentally undo the fix", () => {
    expect(SRC).toMatch(/Phase K42[\s\S]{0,320}authoritative[\s\S]{0,200}technicians\.id/i);
  });
});


describe("K42 · Schedule filter — 'All techs' bucket", () => {
  it("first option is empty-string 'All techs' (or crew-scoped variant)", () => {
    expect(SRC).toMatch(/<option value="">\{crewId \? "Techs \(from crew\)" : "All techs"\}<\/option>/);
  });
});
