/**
 * Phase M3 — Checklist section order: Visit Media → Internal Photos → Internal Videos.
 *
 * Instead of rendering the full checklist screen (which pulls in dozens
 * of heavy deps), we verify the source file's JSX directly via simple
 * string assertions on the compiled module source.
 *
 * Tests:
 *  1. "Internal Photos" title present, plain "Photos" absent.
 *  2. "Internal Videos" title present.
 *  3. Section order: checklist-sr-media-card → checklist-photos-card → checklist-videos-card.
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/job/[id]/checklist.tsx"),
  "utf-8",
);

describe("Phase M3 — Internal Photos/Videos relabel + relocate (source assertions)", () => {
  it('has "Internal Photos" as card title, not plain "Photos"', () => {
    // The card title should be "Internal Photos"
    expect(SRC).toContain(">Internal Photos<");
    // Plain "Photos" title should NOT appear as a standalone card title
    // (it may appear in comments or other contexts, but the card title pattern is ">Photos<")
    const cardTitleMatches = SRC.match(/>Photos</g);
    expect(cardTitleMatches).toBeNull();
  });

  it('has "Internal Videos" as card title', () => {
    expect(SRC).toContain(">Internal Videos<");
  });

  it("checklist-sr-media-card appears before checklist-photos-card", () => {
    const srIndex = SRC.indexOf('testID="checklist-sr-media-card"');
    const photosIndex = SRC.indexOf('testID="checklist-photos-card"');
    expect(srIndex).toBeGreaterThan(-1);
    expect(photosIndex).toBeGreaterThan(-1);
    expect(srIndex).toBeLessThan(photosIndex);
  });

  it("checklist-photos-card appears before checklist-videos-card", () => {
    const photosIndex = SRC.indexOf('testID="checklist-photos-card"');
    const videosIndex = SRC.indexOf('testID="checklist-videos-card"');
    expect(photosIndex).toBeGreaterThan(-1);
    expect(videosIndex).toBeGreaterThan(-1);
    expect(photosIndex).toBeLessThan(videosIndex);
  });

  it("checklist-videos-card appears before the template-specific form", () => {
    const videosIndex = SRC.indexOf('testID="checklist-videos-card"');
    const formIndex = SRC.indexOf('testID={`checklist-form-');
    expect(videosIndex).toBeGreaterThan(-1);
    expect(formIndex).toBeGreaterThan(-1);
    expect(videosIndex).toBeLessThan(formIndex);
  });
});
