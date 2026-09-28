/**
 * LSP-1 · Feb-2026 — LeadsDashboardPage row-level intent section.
 *
 * The dashboard renders a collapsible "Intent · N pages" strip
 * under every lead row that carries an ``intent_history`` array
 * (populated by the LS-C convert endpoint). This locks the JSX
 * seams O(1) via source-grep.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const DASH = read("src/pages/leads/LeadsDashboardPage.jsx");


describe("LSP-1 · LeadsDashboardPage row-level intent section", () => {
  it("renders a <details>/<summary> block gated on intent_history length", () => {
    expect(DASH).toMatch(/l\.intent_history\?\.length\s*>\s*0/);
    expect(DASH).toMatch(/<details/);
    expect(DASH).toMatch(/<summary/);
  });

  it("attaches a per-row testid `lead-row-intent-${l.id}`", () => {
    expect(DASH).toMatch(/data-testid=\{`lead-row-intent-\$\{l\.id\}`\}/);
  });

  it("shows First + Last timestamps + Top pages label", () => {
    expect(DASH).toMatch(/First:.*intent_history\[0\]/s);
    expect(DASH).toMatch(/Last:.*intent_history\[l\.intent_history\.length - 1\]/s);
    expect(DASH).toMatch(/Top pages:/);
  });

  it("top-pages list is deduped via new Set() and capped at 3", () => {
    expect(DASH).toMatch(/new Set\(l\.intent_history\.slice\(-25\)\.map/);
    expect(DASH).toMatch(/\.slice\(0,\s*3\)/);
  });

  it("wraps the row .map in a React.Fragment so the details block sits outside the grid", () => {
    expect(DASH).toMatch(/<React\.Fragment key=\{l\.id\}>/);
    expect(DASH).toMatch(/<\/React\.Fragment>/);
  });

  it("adds a top-of-page entry link to /leads/intent", () => {
    expect(DASH).toMatch(/to="\/leads\/intent"/);
    expect(DASH).toMatch(/data-testid="leads-intent-link"/);
  });

  it("Link is imported from react-router-dom", () => {
    expect(DASH).toMatch(/import \{ Link, useSearchParams \} from "react-router-dom"/);
  });
});
