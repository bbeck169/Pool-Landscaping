/**
 * TD-87 · Feb-2026 — Schedule map pin labels: drop tech initials.
 *
 * Operator ask: route-stop pins used to render ``04-ES`` /
 * ``13-ES`` / ``02-03M`` (stop number + tech initials). The pin
 * COLOUR already identifies the tech via the legend swatch; the
 * initials suffix was redundant and crowded the pin disc.
 *
 * Post-TD-87:
 *   - On-pin visible label = pure zero-padded stop number
 *     (``01`` / ``04`` / ``13`` …).
 *   - Hover tooltip + aria-label still carry the full
 *     ``Stop NN — Ethan`` string for accessibility.
 *   - ``data-tech-initials`` attribute preserved for downstream
 *     consumers (legend row + older tests).
 *   - Legend rows + pin colours unchanged.
 *
 * This suite locks:
 *   - Formatter emits bare ``padded`` on the ``pinLabel`` branch.
 *   - No ``NN·II`` templating remains in the source.
 *   - ``techInitials`` is still resolved for the data-attribute
 *     (so legend consumers keep working).
 *   - The tooltip resolver (``stopTooltip``) still assembles the
 *     ``Stop NN — Ethan`` string, unchanged.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/ScheduleMap.jsx"),
  "utf8",
);

describe("TD-87 · ScheduleMap pin labels drop tech-initial suffix", () => {
  it("formatter emits bare ``padded`` on the pinLabel branch", () => {
    // Lock the simplified ternary → direct assignment.
    expect(SRC).toMatch(/pinLabel = padded;/);
  });

  it("legacy ``NN·II`` template is gone from the pinLabel branch", () => {
    // The pre-TD-87 shape was:
    //   pinLabel = techInitials
    //     ? `${padded}·${techInitials}`
    //     : padded;
    // Grep for the backtick-templated form.
    const stale = /pinLabel = techInitials\s*\n?\s*\?\s*`\$\{padded\}·\$\{techInitials\}`/;
    expect(SRC).not.toMatch(stale);
    // Also ensure the ``${padded}·${techInitials}`` template
    // literal does not appear anywhere else in the file (it was
    // only used on this one call-site).
    expect(SRC).not.toMatch(/\$\{padded\}·\$\{techInitials\}/);
  });

  it("techInitials is still resolved for the data-attribute branch", () => {
    // Lock the ``data-tech-initials`` attribute still gets the
    // resolver output so the legend row + older tests keep
    // working (the attribute is a data-channel for downstream
    // consumers; only the on-pin visible label was simplified).
    expect(SRC).toMatch(
      /const techInitials = job\.technician_id\s*\n?\s*\? resolveTechInitials\(job\.technician_id, techs\)\s*\n?\s*: "";/,
    );
    expect(SRC).toMatch(/data-tech-initials=\{techInitials \|\| ""\}/);
  });

  it("tooltip still assembles the ``Stop NN — <techFirstName>`` string", () => {
    // TD-87 is on-pin-label only; the tooltip is untouched.
    expect(SRC).toMatch(/Stop \$\{Number\.isFinite\(stopNum\)/);
    expect(SRC).toMatch(/\$\{stopNum\} — \$\{techFirstName\}/);
  });

  it("legend row still consumes resolveTechInitials (unchanged)", () => {
    // Operator spec: "Legend / tech-colour swatches (keep as-is)".
    // The legend path is a different code block that reads
    // resolveTechInitials via a separate call site — this grep
    // confirms it still exists so the operator-visible legend
    // is intact.
    expect(SRC).toMatch(/resolveTechInitials/);
  });

  it("stop-number padding is still zero-padded on < 10", () => {
    // Lock the zero-pad invariant so a refactor doesn't drop
    // leading zeros (operator spec: ``04`` stays ``04``, not ``4``).
    expect(SRC).toMatch(
      /stopNum < 10 \? `0\$\{stopNum\}` : String\(stopNum\)/,
    );
  });

  it("TD-87 docstring is linked for the next auditor", () => {
    // Audit cross-reference comment lives inside the formatter
    // block so a future refactor sees the TD-87 trail.
    expect(SRC).toMatch(/TD-87 · Feb-2026/);
  });
});
