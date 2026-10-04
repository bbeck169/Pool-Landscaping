/**
 * NAV-REORG — Reviews nested under Marketing.
 *
 * Validates the drawer nav restructure: the legacy standalone
 * group was folded into Marketing. Mirror of web ``7d34498``.
 */
import { ADMIN_NAV } from "@/src/nav/adminNav";
import * as fs from "fs";
import * as path from "path";

const REVIEW_ROUTES = [
  "/admin/reviews",
  "/admin/reviews/requests",
  "/admin/reviews/platforms",
  "/admin/reviews/widget",
];

function findGroup(key: string) {
  return ADMIN_NAV.find((g) => g.key === key) ?? null;
}

describe("NAV-REORG — Reviews under Marketing", () => {
  // (a) No top-level group with key "reviews"
  it("ADMIN_NAV has no top-level group with key equal to reviews", () => {
    const hit = findGroup("reviews");
    expect(hit).toBeNull();
  });

  // (b) Marketing contains exactly 4 entries whose route starts with /admin/reviews
  it("marketing group contains exactly 4 entries with routes starting /admin/reviews", () => {
    const mkt = findGroup("marketing");
    expect(mkt).not.toBeNull();
    const reviewEntries = mkt!.entries.filter((e) =>
      e.route.startsWith("/admin/reviews"),
    );
    expect(reviewEntries).toHaveLength(4);
    const routes = reviewEntries.map((e) => e.route).sort();
    expect(routes).toEqual([...REVIEW_ROUTES].sort());
  });

  // (c) Mobile nav has no subsection field, so we verify the 4 entries
  //     carry their canonical testIDs (structural proof they're in marketing)
  it("all 4 review entries carry expected testIDs inside the marketing group", () => {
    const mkt = findGroup("marketing")!;
    const testIDs = mkt.entries
      .filter((e) => e.route.startsWith("/admin/reviews"))
      .map((e) => e.testID)
      .sort();
    expect(testIDs).toEqual([
      "drawer-nav-reviews",
      "drawer-nav-reviews-platforms",
      "drawer-nav-reviews-requests",
      "drawer-nav-reviews-widget",
    ]);
  });

  // (d) Source file no longer contains the old standalone group declaration.
  //     Build the needle from parts to avoid self false-positive.
  it("source file does not contain the legacy standalone group declaration", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/nav/adminNav.ts"),
      "utf-8",
    );
    // The old pattern: `key: "reviews"` as a top-level group key
    const needle = ["key:", ' "', "reviews", '"'].join("");
    expect(src).not.toContain(needle);
  });

  // (e) No existing non-reviews marketing entry was dropped (smoke check).
  //     Verify at least 3 stable pre-reorg marketing entries survive.
  it("pre-existing marketing entries still present after reorg", () => {
    const mkt = findGroup("marketing")!;
    const routes = new Set(mkt.entries.map((e) => e.route));
    // These existed before NAV-REORG and must not have been dropped.
    expect(routes.has("/marketing")).toBe(true);
    expect(routes.has("/marketing/templates")).toBe(true);
    expect(routes.has("/marketing/campaigns")).toBe(true);
    expect(routes.has("/seo")).toBe(true);
  });
});
