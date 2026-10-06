/**
 * CHEM-DECIMAL-WEB · Feb-2026 — AI Dosing Recommendation panel
 * must expose ``inputMode="decimal"`` + a decimal-friendly
 * ``pattern`` on BOTH its numeric inputs (pool volume + per-
 * reading grid) so Android soft keyboards reliably surface the
 * decimal key.
 *
 * Pre-fix: both inputs rendered ``type="number"`` alone, which on
 * some Android/Chrome builds hoists the integer-only numeric pad.
 * Users could not type ``7.4`` into the pH recommendation reading
 * from a mobile browser.
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
  it("carries inputMode=\"decimal\" + decimal-friendly pattern alongside type=\"number\"", () => {
    // Isolate the pool-volume TextInput block via its testid.
    const idx = AI_DOSING.indexOf('testid="cx-volume"');
    expect(idx).toBeGreaterThan(-1);
    const start = AI_DOSING.lastIndexOf("<TextInput", idx);
    const end = AI_DOSING.indexOf("/>", idx);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const block = AI_DOSING.slice(start, end + 2);
    expect(block).toMatch(/type="number"/);
    expect(block).toMatch(/inputMode="decimal"/);
    expect(block).toMatch(/pattern="\[0-9\]\*\[\.,\]\?\[0-9\]\*"/);
  });
});

describe("CHEM-DECIMAL-WEB · AI Dosing panel · readings grid input", () => {
  it("per-reading TextInput carries inputMode=\"decimal\" + decimal pattern + step=\"0.1\"", () => {
    // The readings-grid TextInput is identified by the dynamic
    // ``cx-reading-${r.k}`` testid.  Match on that template.
    const idx = AI_DOSING.indexOf("testid={`cx-reading-${r.k}`}");
    expect(idx).toBeGreaterThan(-1);
    const start = AI_DOSING.lastIndexOf("<TextInput", idx);
    const end = AI_DOSING.indexOf("/>", idx);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const block = AI_DOSING.slice(start, end + 2);
    expect(block).toMatch(/type="number"/);
    expect(block).toMatch(/step="0\.1"/);
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
});
