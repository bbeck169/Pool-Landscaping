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
  it("emits the authoritative technician id as the option value — NEVER t.user_id", () => {
    // Pre-K42 shape (bug):        value={t.user_id || t.id}
    // Post-K42 shape:              value={t.id}
    // Post-P5 shape (Feb-2026):    value={_tid}   where
    //   _tid = _canonicalTechId(t) = t.technician_id || t.id
    // Whichever generation ships, ``t.user_id`` MUST NEVER be
    // the option value.
    expect(SRC).not.toMatch(/value=\{t\.user_id \|\| t\.id\}/);
    // Either the K42 or the P5 shape is acceptable — this test
    // only asserts the user_id shape is gone.
    const hasK42 = /value=\{t\.id\}>\{t\.name \|\| t\.email\}<\/option>/
      .test(SRC);
    const hasP5 = /value=\{_tid\}>\{t\.name \|\| t\.email\}<\/option>/
      .test(SRC);
    expect(hasK42 || hasP5).toBe(true);
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
    // K42 rationale OR its P5 successor (which pins the same
    // "authoritative technicians.id" invariant via
    // ``_canonicalTechId``) must remain in-source.
    const k42 = /Phase K42[\s\S]{0,320}authoritative[\s\S]{0,200}technicians\.id/i.test(SRC);
    const p5 = /Phase P5[\s\S]{0,600}canonical[\s\S]{0,200}technician_id/i.test(SRC);
    expect(k42 || p5).toBe(true);
  });
});


describe("K42 · Schedule filter — 'All techs' bucket", () => {
  it("first option is empty-string 'All techs' (or crew-scoped variant)", () => {
    expect(SRC).toMatch(/<option value="">\{crewId \? "Techs \(from crew\)" : "All techs"\}<\/option>/);
  });
});
