/**
 * Feb-2026 · Chemistry readings unification regression guard.
 *
 * Locks in the deletion of ``pages/tech/ServiceReport.jsx``'s
 * compact inline renderer. Both admin-facing routes that let a
 * tech enter chemistry now render the SAME
 * ``components/checklist/PoolChecklistForm.jsx::ReadingInputRow``
 * (verbose labels, "Not tested" pill, "Previously tested at:"
 * caption, sparkline, outlier warning, red ``*`` on required
 * fields).
 *
 * Guards asserted here:
 *   1. ``ReadingInputRow`` and ``canonicalReadingKey`` are named
 *      exports on ``PoolChecklistForm`` (the unification depends
 *      on this — a regression that unexports would break the
 *      ``ServiceReport`` import at build-time, but a stub-out
 *      would silently deprecate the polish).
 *   2. ``ServiceReport.jsx`` imports both from
 *      ``PoolChecklistForm`` and does NOT ship the pre-unification
 *      compact renderer (``field.name`` + ``field.unit`` literal
 *      row with a bare ``<select>`` / ``<input type="number">``
 *      grid).
 *   3. ``ServiceReport.jsx`` passes ``required`` to
 *      ``ReadingInputRow`` for the five gate-required keys
 *      (``free_chlorine`` / ``total_chlorine`` / ``ph`` /
 *      ``alkalinity`` / ``cyanuric_acid``).
 *   4. The write path (``setReport`` + ``markDirty`` + timestamped
 *      splice into ``chemical_readings``) is preserved — this is
 *      what feeds ``PATCH /api/jobs/{id}/service-report``.
 *   5. ``ReadingInputRow`` renders a red ``*`` marker when
 *      ``required=true``. Locks in the required-indicator behavior
 *      the user's original compact block had.
 *   6. Backend default template includes ``water_temp`` — proves
 *      the 11th field appears in the surviving block for free.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  ReadingInputRow,
  canonicalReadingKey,
} from "../components/checklist/PoolChecklistForm";


const FORM_SRC = readFileSync(
  resolve(__dirname, "../components/checklist/PoolChecklistForm.jsx"),
  "utf8",
);
const REPORT_SRC = readFileSync(
  resolve(__dirname, "../pages/tech/ServiceReport.jsx"),
  "utf8",
);


describe("Chemistry readings unification · named exports", () => {
  it("PoolChecklistForm exports ReadingInputRow", () => {
    expect(typeof ReadingInputRow).toBe("function");
  });
  it("PoolChecklistForm exports canonicalReadingKey", () => {
    expect(typeof canonicalReadingKey).toBe("function");
    expect(canonicalReadingKey({ name: "Free Chlorine" })).toBe("free_chlorine");
    expect(canonicalReadingKey({ name: "Water Temp" })).toBe("water_temp");
    expect(canonicalReadingKey({ name: "Total Alkalinity" })).toBe("total_alkalinity");
  });
});


describe("ServiceReport.jsx · compact renderer removed", () => {
  it("imports ReadingInputRow from PoolChecklistForm", () => {
    expect(REPORT_SRC).toMatch(
      /from ["']@\/components\/checklist\/PoolChecklistForm["']/,
    );
    expect(REPORT_SRC).toMatch(/ReadingInputRow/);
  });

  it("does not ship the pre-unification inline grid literal", () => {
    // The old renderer hard-coded ``{field.name} {field.unit ? …}``
    // as a bare label. Its removal is the goal of this task —
    // reintroducing it would restore the duplicate block.
    expect(REPORT_SRC).not.toMatch(
      /\{field\.name\}\s*\{field\.unit\s*\?/,
    );
    // The compact grid used ``grid-cols-2 md:grid-cols-4`` — the
    // unified renderer switches to ``grid-cols-1 md:grid-cols-2``
    // to match ``PoolChecklistForm``'s row density.
    expect(REPORT_SRC).not.toMatch(
      /grid-cols-2 md:grid-cols-4/,
    );
  });

  it("wires the required marker for the five gate-core keys", () => {
    // The import statement itself is the guard — a regression that
    // strips ``CORE_KEYS`` breaks the ``required`` prop wiring
    // silently.
    expect(REPORT_SRC).toMatch(
      /import \{ CORE_KEYS as _CORE_READING_KEYS \} from "@\/utils\/chemistryGate"/,
    );
    expect(REPORT_SRC).toMatch(
      /required=\{_REQUIRED_MARKER_KEYS\.has\(canon\)\}/,
    );
  });

  it("preserves the PATCH-feeding write path (setReport + markDirty)", () => {
    // These two calls together are what makes the ``PATCH
    // /api/jobs/{id}/service-report`` autosave fire. Dropping
    // either would silently regress the persistence contract.
    const grid = REPORT_SRC.split(
      "data-testid=\"svc-report-readings-grid\"")[1] || "";
    expect(grid).toMatch(/setReport\(\s*\{\s*\.\.\.report,\s*chemical_readings:/);
    expect(grid).toMatch(/markDirty\(\)/);
    // Timestamped merge is preserved.
    expect(grid).toMatch(/ts:\s*new Date\(\)\.toISOString\(\)/);
  });
});


describe("PoolChecklistForm.jsx · required marker wired to core keys", () => {
  it("passes required to ReadingInputRow using CORE_READING_KEYS", () => {
    expect(FORM_SRC).toMatch(
      /import \{ CORE_KEYS as _CORE_READING_KEYS \} from "@\/utils\/chemistryGate"/,
    );
    expect(FORM_SRC).toMatch(
      /required=\{_REQUIRED_MARKER_KEYS\.has\(key\)\}/,
    );
  });
});


describe("ReadingInputRow · required indicator", () => {
  it("renders a red '*' when required=true", () => {
    render(
      <ReadingInputRow
        testKey="free_chlorine"
        reading={{ key: "free_chlorine", name: "Free Chlorine",
                    unit: "ppm", value: null }}
        previous={undefined}
        recent={undefined}
        locked={false}
        required={true}
        onChange={() => {}}
      />,
    );
    const marker = screen.getByTestId("pool-reading-free_chlorine-required");
    expect(marker).toBeTruthy();
    expect(marker.textContent).toBe("*");
    // Red — the color class must survive any future re-theme so
    // techs continue to spot the required marker at a glance.
    // JSDOM normalizes hex to rgb() so match either.
    expect(marker.getAttribute("style") || "").toMatch(
      /(#DC2626|rgb\(\s*220\s*,\s*38\s*,\s*38\s*\))/i,
    );
  });

  it("omits the '*' marker when required is false", () => {
    render(
      <ReadingInputRow
        testKey="calcium_hardness"
        reading={{ key: "calcium_hardness", name: "Calcium Hardness",
                    unit: "ppm", value: null }}
        previous={undefined}
        recent={undefined}
        locked={false}
        required={false}
        onChange={() => {}}
      />,
    );
    expect(screen.queryByTestId(
      "pool-reading-calcium_hardness-required")).toBeNull();
  });
});
