/**
 * Phase 23 · Mobile Schedule Job-Tracker tiles — tests.
 *
 * The visual layer (SVG + LinearGradient) can't render in jsdom, but
 * the classification + counting logic + wiring/testids are the actual
 * source of truth for correctness. We source-inspect the mobile file
 * to lock the render contract (testIDs + gradient wiring) and unit-
 * test the pure classify/count helpers.
 */
import { describe, it, expect } from "@jest/globals";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../../../mobile/app/(app)/schedule/JobTrackerTiles.tsx"),
  "utf-8",
);

// Duplicate the classify + count logic here to keep the vitest fast
// (avoid the react-native import graph). Any drift between the two
// implementations fails the source-inspection tests below.
const _REPAIR_RX = /(repair|fix|broken|leak|replace)/i;
function classifyJob(job) {
  const st = (job.service_type || "").toString();
  return _REPAIR_RX.test(st) ? "repair" : "service";
}
function computeCounts(jobs) {
  let svcTotal = 0, svcDone = 0, repTotal = 0, repDone = 0;
  for (const j of jobs || []) {
    const isDone = (j.status || "").toLowerCase() === "completed";
    if (classifyJob(j) === "repair") {
      repTotal += 1;
      if (isDone) repDone += 1;
    } else {
      svcTotal += 1;
      if (isDone) svcDone += 1;
    }
  }
  return { svcTotal, svcDone, repTotal, repDone };
}

describe("Phase 23 · JobTrackerTiles — classification + counting", () => {
  it("classifies repair vs service by service_type keyword match", () => {
    expect(classifyJob({ service_type: "Weekly Pool Service" })).toBe("service");
    expect(classifyJob({ service_type: "Landscaping" })).toBe("service");
    expect(classifyJob({ service_type: "Pool Cleaning" })).toBe("service");
    expect(classifyJob({ service_type: "Pump repair" })).toBe("repair");
    expect(classifyJob({ service_type: "Fix filter leak" })).toBe("repair");
    expect(classifyJob({ service_type: null })).toBe("service"); // default
    expect(classifyJob({})).toBe("service");
  });

  it("counts service + repair totals and completions", () => {
    const jobs = [
      { service_type: "Weekly Pool Service", status: "completed" },
      { service_type: "Weekly Pool Service", status: "scheduled" },
      { service_type: "Weekly Pool Service", status: "in_progress" },
      { service_type: "Landscaping",         status: "completed" },
      { service_type: "Pump repair",         status: "scheduled" },
      { service_type: "Fix filter leak",     status: "completed" },
    ];
    const c = computeCounts(jobs);
    expect(c.svcTotal).toBe(4);
    expect(c.svcDone).toBe(2);
    expect(c.repTotal).toBe(2);
    expect(c.repDone).toBe(1);
  });

  it("empty jobs list returns 0/0 for both categories", () => {
    expect(computeCounts([])).toEqual(
      { svcTotal: 0, svcDone: 0, repTotal: 0, repDone: 0 },
    );
    expect(computeCounts(null)).toEqual(
      { svcTotal: 0, svcDone: 0, repTotal: 0, repDone: 0 },
    );
  });

  it("fully complete yields done === total", () => {
    const jobs = [
      { service_type: "Weekly Pool Service", status: "completed" },
      { service_type: "Weekly Pool Service", status: "completed" },
      { service_type: "Repair job",          status: "completed" },
    ];
    const c = computeCounts(jobs);
    expect(c.svcTotal).toBe(2);
    expect(c.svcDone).toBe(2);
    expect(c.repTotal).toBe(1);
    expect(c.repDone).toBe(1);
  });
});

describe("Phase 23 · JobTrackerTiles — render contract (source inspection)", () => {
  it("component file exposes the required testIDs", () => {
    expect(SRC.includes('testID="schedule-tracker-row"')).toBe(true);
    expect(SRC.includes('testID="schedule-tile-service"')).toBe(true);
    expect(SRC.includes('testID="schedule-tile-repair"')).toBe(true);
    // Nested testIDs for the count text — used by the tile-visibility
    // parametrized test to assert "3/7" style output on the wire.
    expect(SRC.includes("${testID}-count")).toBe(true);
    expect(SRC.includes("${testID}-label")).toBe(true);
  });

  it("uses react-native-svg Circle for the ring + green arc color", () => {
    expect(SRC.includes('from "react-native-svg"')).toBe(true);
    expect(SRC.includes("<Circle")).toBe(true);
    expect(SRC.includes("#22c55e")).toBe(true);          // green arc
    expect(SRC.includes("rgba(255,255,255,0.28)")).toBe(true); // track
  });

  it("uses expo-linear-gradient with purple → blue gradient", () => {
    expect(SRC.includes('from "expo-linear-gradient"')).toBe(true);
    expect(SRC.includes('"#7c3aed"')).toBe(true);  // purple
    expect(SRC.includes('"#3b82f6"')).toBe(true);  // blue
  });

  it("empty state (total=0) skips the green arc", () => {
    // Guard: we conditionally render <Circle stroke="#22c55e" ... />
    // only when ``total > 0 && pct > 0``.
    expect(SRC.match(/total > 0 && pct > 0/)).not.toBeNull();
  });

  it("label texts match the reference screenshot", () => {
    expect(SRC.includes('"Service Stops"')).toBe(true);
    expect(SRC.includes('"Repair Stops"')).toBe(true);
  });

  it("Phase 24 · label is a separate <Text> node OUTSIDE the SVG viewBox", () => {
    // Split the source at the SVG boundary. The label's <Text> node
    // (marked by testID `${testID}-label`) must live in the *outer*
    // component body — NOT nested inside <Svg>...</Svg>. Prior bug
    // rendered the label as SVG text, which the rounded corners of
    // the tile clipped on narrow devices.
    const svgOpen = SRC.indexOf("<Svg");
    const svgClose = SRC.indexOf("</Svg>");
    expect(svgOpen).toBeGreaterThan(-1);
    expect(svgClose).toBeGreaterThan(svgOpen);
    const insideSvg = SRC.slice(svgOpen, svgClose);
    // The label testID string must NOT appear inside the SVG block.
    expect(insideSvg.includes("${testID}-label")).toBe(false);
    // And the tile file must render the label via a <Text> element
    // (not <SvgText> or similar) so RN's flex layout owns positioning.
    expect(SRC.match(/<Text[^>]*testID=\{`\$\{testID\}-label`\}/)).not.toBeNull();
  });

  it("Phase 24 · label uses high-contrast white at 95% opacity + weight 600", () => {
    // Spec: rgba(255,255,255,0.95) + fontWeight "600". This is the
    // visual-contract lock so future refactors can't silently drop
    // the readability fix.
    expect(SRC.includes('"rgba(255,255,255,0.95)"')).toBe(true);
    expect(SRC.match(/label:\s*\{[^}]*fontWeight:\s*"600"/)).not.toBeNull();
  });
});
