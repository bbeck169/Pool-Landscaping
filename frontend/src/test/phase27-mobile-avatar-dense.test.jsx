/**
 * Phase 27 · Feb-2026 — Mobile avatar swap for dense layouts vitest.
 *
 * jsdom can't render Expo RN, so we source-inspect the mobile files
 * (same approach the Phase 23/25 suites use) and lock the contract:
 *
 *   1. Mobile per-job card source (`mobile/app/(app)/schedule/calendar.tsx`)
 *      imports and mounts the shared `<TechAvatar />` at size `xs`.
 *   2. Mobile dispatch board source (if present) either (a) imports
 *      TechAvatar or (b) demonstrably renders only unassigned jobs
 *      (in which case there's no tech identity to swap).
 *   3. Existing Phase 25 label-clip assertions still hold — the
 *      JobTrackerTiles label style contract is intact.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const CALENDAR_SRC = fs.readFileSync(
  path.resolve(
    __dirname, "../../../mobile/app/(app)/schedule/calendar.tsx",
  ),
  "utf-8",
);

const TILES_SRC = fs.readFileSync(
  path.resolve(
    __dirname, "../../../mobile/app/(app)/schedule/JobTrackerTiles.tsx",
  ),
  "utf-8",
);

const MOBILE_DISPATCH_BOARD = path.resolve(
  __dirname, "../../../mobile/app/(app)/dispatch/board.tsx",
);
const DISPATCH_BOARD_EXISTS = fs.existsSync(MOBILE_DISPATCH_BOARD);
const DISPATCH_BOARD_SRC = DISPATCH_BOARD_EXISTS
  ? fs.readFileSync(MOBILE_DISPATCH_BOARD, "utf-8")
  : "";

describe("Phase 27 · Mobile schedule per-job card avatar", () => {
  it("imports the shared mobile TechAvatar component", () => {
    // The mobile TechAvatar lives at
    // `mobile/components/common/TechAvatar.tsx`. The relative
    // import from `mobile/app/(app)/schedule/calendar.tsx` is
    // `../../../components/common/TechAvatar`.
    expect(CALENDAR_SRC).toMatch(
      /import\s+TechAvatar\s+from\s+["']\.\.\/\.\.\/\.\.\/components\/common\/TechAvatar["']/,
    );
  });

  it("mounts <TechAvatar size='xs' /> inside the JobRow header", () => {
    expect(CALENDAR_SRC).toMatch(/<TechAvatar[\s\S]*?size=["']xs["']/);
  });

  it("guards the avatar behind a technician-identity conditional", () => {
    // We only want to render the chip when the job actually has an
    // assigned tech — otherwise the visual is redundant and pushes
    // the customer line for no reason.
    expect(CALENDAR_SRC).toMatch(
      /job\.technician_name\s*\|\|\s*job\.assigned_technician_name/,
    );
  });

  it("attaches a per-job testID (`grid-tech-avatar-${job.id}`) for QA", () => {
    expect(CALENDAR_SRC).toMatch(/grid-tech-avatar-\$\{job\.id\}/);
  });
});

describe("Phase 27 · Mobile dispatch board avatar (conditional)", () => {
  it("mobile dispatch board either references TechAvatar or renders only unassigned jobs", () => {
    if (!DISPATCH_BOARD_EXISTS) {
      // No file → nothing to check.
      expect(true).toBe(true);
      return;
    }
    const referencesTechAvatar = /TechAvatar/.test(DISPATCH_BOARD_SRC);
    // The current Phase-17 board.tsx renders only unassigned jobs
    // (filter: `!j.technician_id && !j.assigned_to`), so there IS no
    // tech identity to display. Either surface (avatar present OR
    // unassigned-only filter present) satisfies the contract.
    const isUnassignedOnly =
      /!\s*j\.technician_id\s*&&\s*!\s*j\.assigned_to/.test(DISPATCH_BOARD_SRC);
    expect(referencesTechAvatar || isUnassignedOnly).toBe(true);
  });
});

describe("Phase 27 · Regression — Phase 25 label-clip assertions still hold", () => {
  // Cheap re-check so a Phase-27 refactor that accidentally reverted
  // any Phase-25 style would fail loudly in this suite too.
  it("JobTrackerTiles label still lineHeight >= fontSize + 4", () => {
    const body = TILES_SRC.match(/label\s*:\s*\{([\s\S]*?)\}\s*,/)[1];
    const fontSize = parseInt(body.match(/fontSize\s*:\s*(\d+)/)[1], 10);
    const lineHeight = parseInt(body.match(/lineHeight\s*:\s*(\d+)/)[1], 10);
    expect(lineHeight).toBeGreaterThanOrEqual(fontSize + 4);
  });

  it("JobTrackerTiles label still has includeFontPadding: true", () => {
    expect(TILES_SRC).toMatch(/includeFontPadding\s*:\s*true/);
  });

  it("Tile paddingBottom (20) still >= borderRadius (16)", () => {
    const body = TILES_SRC.match(/tile\s*:\s*\{([\s\S]*?)\}\s*,/)[1];
    const br = parseInt(body.match(/borderRadius\s*:\s*(\d+)/)[1], 10);
    const pb = parseInt(body.match(/paddingBottom\s*:\s*(\d+)/)[1], 10);
    expect(pb).toBeGreaterThanOrEqual(br);
  });

  it("JobTrackerTiles label still lives outside the SVG viewBox", () => {
    const svgOpen = TILES_SRC.indexOf("<Svg");
    const svgClose = TILES_SRC.indexOf("</Svg>");
    const insideSvg = TILES_SRC.slice(svgOpen, svgClose);
    expect(insideSvg.includes("${testID}-label")).toBe(false);
  });
});
