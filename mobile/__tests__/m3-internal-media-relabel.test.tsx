/**
 * Phase M4 — Checklist section order (supersedes M3).
 *
 * Internal Photos + Internal Videos are now at the VERY BOTTOM of the
 * scrollable content, below the template-specific form.
 *
 * Tests:
 *  1. "Internal Photos" title present, plain "Photos" absent.
 *  2. "Internal Videos" title present.
 *  3. Visit Media (checklist-sr-media-card) renders BEFORE the template form.
 *  4. Internal Photos (checklist-photos-card) renders AFTER the template form.
 *  5. Internal Videos (checklist-videos-card) renders AFTER Internal Photos.
 *  6. Internal Photos + Internal Videos are the LAST two card blocks before </ScrollView>.
 *  7. PhotoUploader buttons use "Photo" and "Library" labels (matching Visit Media).
 */
import * as fs from "fs";
import * as path from "path";

const CHECKLIST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/job/[id]/checklist.tsx"),
  "utf-8",
);

const PHOTO_UPLOADER_SRC = fs.readFileSync(
  path.resolve(__dirname, "../src/components/checklist/PhotoUploader.tsx"),
  "utf-8",
);

describe("Phase M4 — Internal media at bottom + PhotoUploader restyle", () => {
  it('has "Internal Photos" as card title, not plain "Photos"', () => {
    expect(CHECKLIST_SRC).toContain(">Internal Photos<");
    const cardTitleMatches = CHECKLIST_SRC.match(/>Photos</g);
    expect(cardTitleMatches).toBeNull();
  });

  it('has "Internal Videos" as card title', () => {
    expect(CHECKLIST_SRC).toContain(">Internal Videos<");
  });

  it("Visit Media renders BEFORE the template form", () => {
    const srMedia = CHECKLIST_SRC.indexOf('testID="checklist-sr-media-card"');
    const form = CHECKLIST_SRC.indexOf('testID={`checklist-form-');
    expect(srMedia).toBeGreaterThan(-1);
    expect(form).toBeGreaterThan(-1);
    expect(srMedia).toBeLessThan(form);
  });

  it("Internal Photos renders AFTER the template form", () => {
    const form = CHECKLIST_SRC.indexOf('testID={`checklist-form-');
    const photos = CHECKLIST_SRC.indexOf('testID="checklist-photos-card"');
    expect(form).toBeGreaterThan(-1);
    expect(photos).toBeGreaterThan(-1);
    expect(form).toBeLessThan(photos);
  });

  it("Internal Videos renders AFTER Internal Photos", () => {
    const photos = CHECKLIST_SRC.indexOf('testID="checklist-photos-card"');
    const videos = CHECKLIST_SRC.indexOf('testID="checklist-videos-card"');
    expect(photos).toBeGreaterThan(-1);
    expect(videos).toBeGreaterThan(-1);
    expect(photos).toBeLessThan(videos);
  });

  it("Internal Videos is the last card block before </ScrollView>", () => {
    const videos = CHECKLIST_SRC.indexOf('testID="checklist-videos-card"');
    // After the videos card, the next significant tag should be </ScrollView>
    const afterVideos = CHECKLIST_SRC.slice(videos);
    // Find the closing </View> of the videos card, then </ScrollView>
    const scrollEnd = afterVideos.indexOf("</ScrollView>");
    expect(scrollEnd).toBeGreaterThan(-1);
    // No other testID="checklist-*-card" should appear between videos card and ScrollView end
    const betweenSection = afterVideos.slice(0, scrollEnd);
    // Only the videos card itself should be present, no other card testIDs
    const otherCards = betweenSection.match(/testID="checklist-(?!videos-card)[^"]*-card"/g);
    expect(otherCards).toBeNull();
  });

  it("Internal blocks have internal-only binding comments", () => {
    expect(CHECKLIST_SRC).toContain("Internal-only — bound to job.photos");
    expect(CHECKLIST_SRC).toContain("Internal-only — bound to job.videos");
  });

  it('PhotoUploader buttons use "Photo" and "Library" labels', () => {
    // "Photo" button with camera icon
    expect(PHOTO_UPLOADER_SRC).toContain('>Photo<');
    // "Library" button with images icon
    expect(PHOTO_UPLOADER_SRC).toContain('>Library<');
    // Old "Camera" label should be gone
    expect(PHOTO_UPLOADER_SRC).not.toContain('>Camera<');
  });

  it("PhotoUploader button styles match Visit Media (uploadBtn/uploadRow pattern)", () => {
    // Uses the same style pattern as ServiceReportMediaUploader
    expect(PHOTO_UPLOADER_SRC).toContain("uploadRow");
    expect(PHOTO_UPLOADER_SRC).toContain("uploadBtn");
    expect(PHOTO_UPLOADER_SRC).toContain("uploadBtnText");
    // Dashed border style matching Visit Media
    expect(PHOTO_UPLOADER_SRC).toContain('borderStyle: "dashed"');
    expect(PHOTO_UPLOADER_SRC).toContain("borderWidth: 1.5");
    // Brand-colored icons
    expect(PHOTO_UPLOADER_SRC).toContain("color={colors.brand}");
  });
});
