/**
 * Feb 2026 · Task A — repair ServiceLog hides the pool-service
 * checklist. Regression guard: service work_class STILL shows it.
 *
 * ServiceLogPage pulls in ~15 tenant/auth/telemetry hooks that
 * flake under jsdom without heavy mocks, so we source-parse the
 * file and assert the gate expression + the two testids the runtime
 * consumers rely on.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/workstream/ServiceLogPage.jsx"),
  "utf8",
);


describe("Task A · ServiceLogPage checklist visibility", () => {
  it("checklist section is gated behind a repair check", () => {
    // The single ``service-log-checklist-title`` occurrence must sit
    // inside a conditional that inspects ``work_class`` and compares
    // to the string "repair".
    const idx = SRC.indexOf('testid="service-log-checklist-title"');
    expect(idx).toBeGreaterThan(0);
    // Look back 400 chars — any repair gate must appear before it.
    const preamble = SRC.slice(Math.max(0, idx - 500), idx);
    expect(preamble).toMatch(/work_class[\s\S]{0,80}!==\s*"repair"/);
  });

  it("has exactly one Checklist section (no ghost copy left behind)", () => {
    const matches = SRC.match(/testid="service-log-checklist-title"/g) || [];
    expect(matches).toHaveLength(1);
  });

  it("still renders Previous Service unconditionally (regression guard for the neighbouring block)", () => {
    // The neighbouring "Previous Service" block should NOT have been
    // accidentally caught by the repair gate. Locate the FIRST
    // ``: null}`` closer AFTER the checklist opener and confirm
    // Previous Service sits after that specific closer (i.e., it's
    // outside the gated block).
    expect(SRC).toMatch(/testid="service-log-previous-title"/);
    const opener = SRC.indexOf('testid="service-log-checklist-title"');
    const closer = SRC.indexOf(") : null}", opener);
    const prevTitle = SRC.indexOf('testid="service-log-previous-title"');
    expect(closer).toBeGreaterThan(opener);
    expect(prevTitle).toBeGreaterThan(closer);
  });

  it("preserves the repair chip (visual differentiation stays)", () => {
    expect(SRC).toMatch(/testid="service-log-repair-chip"/);
  });

  // Feb 2026 · Task A extension — the Water Test + Chemical Used
  // panels are pool-service maintenance concerns and must be
  // suppressed on repair reports as well as landscape reports.
  it("derives an isRepair flag from work_class", () => {
    expect(SRC).toMatch(/const\s+isRepair\s*=\s*\(d\.log_details\?\.work_class[\s\S]{0,120}"repair"/);
  });

  it("gates the middle Water Test / Chemical Used column behind !isRepair", () => {
    // The middle column pivot uses ``isPool ? (…) : (…)``. After
    // this task, the truthy branch must ALSO require !isRepair so
    // that repair jobs on the pool service line fall through to the
    // notes card (photo/video/notes only).
    expect(SRC).toMatch(/\{\s*isPool\s*&&\s*!isRepair\s*\?/);
  });

  it("water test + chemicals panels sit AFTER the isPool && !isRepair gate", () => {
    // Guards against a regression that would move the panels out of
    // the gated branch. Both testids must appear after the gate.
    const gateIdx = SRC.search(/\{\s*isPool\s*&&\s*!isRepair\s*\?/);
    const waterIdx = SRC.indexOf('testid="service-log-water-test"');
    const chemIdx = SRC.indexOf('testid="service-log-chemicals-used"');
    expect(gateIdx).toBeGreaterThan(0);
    expect(waterIdx).toBeGreaterThan(gateIdx);
    expect(chemIdx).toBeGreaterThan(gateIdx);
  });

  it("has exactly one occurrence of each middle-column testid (no ghost copies)", () => {
    const wm = SRC.match(/testid="service-log-water-test"/g) || [];
    const cm = SRC.match(/testid="service-log-chemicals-used"/g) || [];
    expect(wm).toHaveLength(1);
    expect(cm).toHaveLength(1);
  });
});
