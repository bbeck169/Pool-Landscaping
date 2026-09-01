/**
 * Phase I2 · Feb-2026 — AnalyticsMonthlyPage Top Blocked Phrases.
 *
 * Source-body contract check. Locks the invariants for the H7 → I2
 * coaching signal that surfaces the moderation pipeline's most
 * frequent block reasons for the selected month.
 *
 *   - Renders inside the Soshie card (only shown when total > 0).
 *   - Row testid pattern: ``soshie-blocked-phrase-<phrase-slug>``.
 *   - Empty state has its own testid.
 *   - Reads ``d.top_blocked_phrases`` (array of ``{ phrase, count }``).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/admin/AnalyticsMonthlyPage.jsx"),
  "utf-8",
);


describe("AnalyticsMonthlyPage · I2 Top Blocked Phrases table", () => {
  it("wrapper testid is ``soshie-blocked-phrases``", () => {
    expect(SRC).toMatch(/data-testid="soshie-blocked-phrases"/);
  });

  it("reads ``top_blocked_phrases`` from the Soshie payload", () => {
    expect(SRC).toMatch(/d\.top_blocked_phrases/);
  });

  it("iterates phrase + count rows, one testid per phrase", () => {
    // Testid derived from p.phrase with whitespace collapsed to
    // dashes — enables Playwright / vitest to grab a row by phrase
    // deterministically.
    expect(SRC).toMatch(
      /data-testid=\{`soshie-blocked-phrase-\$\{p\.phrase\.replace\(\/\\s\+\/g,\s*"-"\)\}`\}/,
    );
    // Row prints phrase name + count number.
    expect(SRC).toMatch(/\{p\.phrase\}/);
    expect(SRC).toMatch(/\{p\.count\}/);
  });

  it("empty state renders its own testid + copy", () => {
    expect(SRC).toMatch(/data-testid="soshie-blocked-phrases-empty"/);
    expect(SRC).toMatch(/No blocked phrases this month/);
  });

  it("empty-vs-populated branch is decided by list length", () => {
    // Ternary is `(d.top_blocked_phrases || []).length ? <table> : <empty>`.
    expect(SRC).toMatch(
      /\(d\.top_blocked_phrases\s*\|\|\s*\[\]\)\.length/,
    );
  });

  it("section title lives above the list", () => {
    expect(SRC).toMatch(/Top blocked phrases this month/);
  });

  it("only renders when the Soshie card has activity (total > 0 branch)", () => {
    // The blocked-phrases block lives inside the ``total > 0`` branch
    // of SoshieCard so a quiet month doesn't render an empty section.
    const soshieIdx = SRC.indexOf('data-testid="soshie-blocked-phrases"');
    expect(soshieIdx).toBeGreaterThan(-1);
    // Trace back and confirm we're inside the ``total > 0`` ternary
    // — the parent conditional lives ~200 lines above.
    const preamble = SRC.slice(0, soshieIdx);
    expect(preamble).toMatch(/total\s*>\s*0\s*\?\s*\(/);
  });
});


describe("I2 · regression guards for the H6 Soshie card", () => {
  it("preserves the cache-hit pill and decisions bar", () => {
    expect(SRC).toMatch(/data-testid="soshie-cache-pill"/);
    expect(SRC).toMatch(/data-testid="soshie-decisions-bar"/);
  });

  it("does not remove the empty-cell fallback for a zero-call month", () => {
    // EmptyCell takes ``testid`` prop and renders ``data-testid`` internally.
    expect(SRC).toMatch(/testid="soshie-empty"/);
  });
});
