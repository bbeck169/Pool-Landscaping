/**
 * CHEM-DECIMAL-WEB · Feb-2026 — AI Dosing Recommendation panel
 * must expose a decimal-friendly keyboard contract on BOTH its
 * numeric inputs (pool volume + per-reading grid):
 *
 *   * ``type="text"`` so Chrome / Firefox / iOS Safari don't blank
 *     intermediate decimal states (``"7."``, ``".5"``) via the
 *     HTML5 ``number`` input validation gate.
 *   * ``inputMode="decimal"`` so Android soft keyboards reliably
 *     surface the decimal key.
 *   * ``pattern`` for Android compatibility fallback.
 *
 * Pre-fix: both inputs rendered ``type="number"`` which (per the
 * HTML5 spec) made ``e.target.value === ""`` for intermediate
 * decimal states — effectively locking users into integer entry
 * for pH / FC / salt / etc.  The CHECKLIST-DECIMAL-INPUT-FIX
 * follow-up (Feb-2026) switches the type attribute to text and
 * guards the keystroke handler with the same
 * ``/^\d*\.?\d*$/`` regex ``ReadingInputRow`` already uses.
 *
 * Source-level assertion (mirrors the K41 / K48 / REV-CONFIRM-FIX
 * pattern): read the raw JSX text and confirm the attributes are
 * present on BOTH call sites.  Avoids a full-mount harness while
 * still catching accidental removal in future edits.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const SRC = read("src/pages/customers/CustomerChemistry.jsx");

/* Slice the AI Dosing panel body — bounded by the panel heading
 * ``AI Dosing Recommendation`` and the ``Recommend`` button so
 * downstream catalog-section TextInputs can't accidentally
 * satisfy the assertions. */
const AI_DOSING = SRC.split("AI Dosing Recommendation")[1].split(
  "testid=\"cx-recommend\"",
)[0];

describe("CHEM-DECIMAL-WEB · AI Dosing panel · pool volume input", () => {
  it("carries type=\"text\" + inputMode=\"decimal\" + decimal-friendly pattern "
     + "(type=\"number\" is forbidden — eats intermediate decimal states)",
     () => {
    // Isolate the pool-volume TextInput block via its testid.
    const idx = AI_DOSING.indexOf('testid="cx-volume"');
    expect(idx).toBeGreaterThan(-1);
    const start = AI_DOSING.lastIndexOf("<TextInput", idx);
    const end = AI_DOSING.indexOf("/>", idx);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const block = AI_DOSING.slice(start, end + 2);
    expect(block).toMatch(/type="text"/);
    expect(block).not.toMatch(/type="number"/);
    expect(block).toMatch(/inputMode="decimal"/);
    expect(block).toMatch(/pattern="\[0-9\]\*\[\.,\]\?\[0-9\]\*"/);
  });
});

describe("CHEM-DECIMAL-WEB · AI Dosing panel · readings grid input", () => {
  it("per-reading TextInput carries type=\"text\" + inputMode=\"decimal\" + "
     + "decimal pattern", () => {
    // The readings-grid TextInput is identified by the dynamic
    // ``cx-reading-${r.k}`` testid.  Match on that template.
    const idx = AI_DOSING.indexOf("testid={`cx-reading-${r.k}`}");
    expect(idx).toBeGreaterThan(-1);
    const start = AI_DOSING.lastIndexOf("<TextInput", idx);
    const end = AI_DOSING.indexOf("/>", idx);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const block = AI_DOSING.slice(start, end + 2);
    expect(block).toMatch(/type="text"/);
    expect(block).not.toMatch(/type="number"/);
    expect(block).toMatch(/inputMode="decimal"/);
    expect(block).toMatch(/pattern="\[0-9\]\*\[\.,\]\?\[0-9\]\*"/);
  });
});

describe("CHEM-DECIMAL-WEB · regression lock", () => {
  it("no TextInput inside the AI Dosing panel is still missing inputMode=\"decimal\"", () => {
    // Count TextInput openings vs inputMode occurrences inside the
    // AI Dosing panel slice.  Pre-fix this was 2 vs 0; post-fix the
    // ratio must be 1:1 so future added inputs don't silently drift
    // off the decimal-keyboard contract.
    const textInputCount = (AI_DOSING.match(/<TextInput\b/g) || []).length;
    const inputModeCount = (
      AI_DOSING.match(/inputMode="decimal"/g) || []
    ).length;
    expect(textInputCount).toBeGreaterThanOrEqual(2);
    expect(inputModeCount).toBe(textInputCount);
  });

  it("no TextInput inside the AI Dosing panel renders type=\"number\" "
     + "(regression lock for the intermediate-decimal-eating bug)", () => {
    // Any ``type="number"`` reintroduction would re-break pH / FC /
    // salt entry on every browser — this contract is load-bearing.
    expect(AI_DOSING).not.toMatch(/type="number"/);
  });
});
