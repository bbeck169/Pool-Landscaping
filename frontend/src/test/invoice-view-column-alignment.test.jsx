/**
 * Feb 2026 · Invoice/Estimate line-item table — numeric column
 * headers must right-align on both desktop and mobile so
 * ``COST/RATE``, ``QTY/HR``, and ``TOTAL`` line up flush-right
 * with the numbers under them.
 *
 * Prior state — desktop scoped ``.iv-lines thead th`` at
 * ``text-align: left`` (specificity 0,0,3) which beat the
 * unscoped ``.iv-num { text-align: right }`` (specificity 0,0,1).
 * Mobile ``.iv-lines thead th`` only set padding + colors; the
 * default browser-alignment on ``<th>`` (typically centered) then
 * carried through. This suite pins the two new rules that fix
 * both surfaces.
 *
 * Static source-lint only — CSS matches read the ``.css`` file as
 * a string, no JSDOM / component mount required.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const DESKTOP_CSS = fs.readFileSync(
  path.resolve(__dirname, "../components/InvoiceView.css"),
  "utf8",
);
const MOBILE_CSS = fs.readFileSync(
  path.resolve(__dirname, "../components/documents/docMobile.css"),
  "utf8",
);

/** Strip line-ending whitespace variance before matching. */
function norm(s) { return s.replace(/[ \t]+/g, " "); }

describe("Invoice line-item table · numeric header alignment", () => {
  it("desktop ``InvoiceView.css`` right-aligns ``th.iv-num``", () => {
    // The rule must exist and target the header cell specifically
    // — not just ``.iv-num`` (which already existed for tbody cells
    // but was outranked in the header by the shared ``thead th``
    // left-align rule).
    expect(norm(DESKTOP_CSS)).toMatch(
      /\.iv-lines\s+thead\s+th\.iv-num\s*\{\s*text-align:\s*right;\s*\}/,
    );
    // The tbody body-cell rule stays intact so line values still
    // right-align.
    expect(norm(DESKTOP_CSS)).toMatch(
      /\.iv-num\s*\{\s*text-align:\s*right;\s*\}/,
    );
  });

  it("mobile ``docMobile.css`` right-aligns ``th.iv-num`` with !important", () => {
    // ``!important`` beats any competing mobile-scoped selector or
    // browser default on ``<th>``.
    expect(norm(MOBILE_CSS)).toMatch(
      /\.iv-lines\s+thead\s+th\.iv-num\s*\{\s*text-align:\s*right\s*!important;?\s*\}/,
    );
    // The body-cell rule (kept in place, adjacent to the new
    // header rule) still right-aligns the number cells.
    expect(norm(MOBILE_CSS)).toMatch(
      /\.iv-lines\s+tbody\s+td\.iv-num\s*\{\s*text-align:\s*right\s*!important/,
    );
  });

  it("Description column header is NOT globally re-aligned by this change", () => {
    // Neither file adds a ``.iv-desc`` (or ``.iv-lines thead
    // th:first-child``) alignment override. The Description column
    // stays inherited from the shared ``.iv-lines thead th
    // { text-align: left }`` rule on desktop, and from the mobile
    // ``.iv-lines tbody td:first-child`` max-width clamp on
    // mobile. This test guards against a future misfire that
    // accidentally aligns the Description column right too.
    expect(DESKTOP_CSS).not.toMatch(/th\.iv-desc\b[\s\S]{0,80}text-align:\s*right/);
    expect(DESKTOP_CSS).not.toMatch(
      /\.iv-lines\s+thead\s+th:first-child[\s\S]{0,80}text-align:\s*right/,
    );
    expect(MOBILE_CSS).not.toMatch(/th\.iv-desc\b[\s\S]{0,80}text-align:\s*right/);
    expect(MOBILE_CSS).not.toMatch(
      /\.iv-lines\s+thead\s+th:first-child[\s\S]{0,80}text-align:\s*right/,
    );
  });
});
