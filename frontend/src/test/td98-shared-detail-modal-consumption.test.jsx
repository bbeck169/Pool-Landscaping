/**
 * TD-98/99 · Feb-2026 — Post-reap source-contract smoke.
 *
 * Scope-reality close-out ship `td98b-fe` reaped the orphan Wave A
 * `components/customers/CommunicationTimeline.jsx` + its two
 * companion vitest files + the dead import in
 * `pages/customers/CustomerDetail.jsx`.
 *
 * This smoke is source-contract only (file-text grep). It locks the
 * ACTUAL post-reap state corrected during the ship:
 *
 *   * `CommunicationDetailModal` IS consumed by lead-side (via the
 *     inline `CommTimelineItem` in `LeadDetail.jsx`). The TD-98/99
 *     audit §1 overclaimed that all three timelines consumed the
 *     modal — in reality `CustomerFullTimeline` uses its own
 *     row-click behavior without the shared modal. The modal
 *     remains a lead-side primitive post-reap; the shared BE
 *     endpoint `/communications-detail/{id}` stays available for
 *     any future surface.
 *   * Orphan Wave A `CommunicationTimeline.jsx` has been removed.
 *   * `CustomerDetail.jsx` no longer imports the reaped orphan.
 *   * `CustomerFullTimeline` (the canonical customer surface) still
 *     exists and still mounts in `CustomerDetail.jsx`.
 *   * `CommunicationDetailModal.jsx` (lead-side primitive) still
 *     exists.
 *
 * If this test fires:
 *   * Lead-side stopped consuming the shared modal → audit the
 *     ship against TD-98/99 close-out; either (a) re-wire the
 *     modal, or (b) raise a new TD documenting the split.
 *   * The reaped orphan reappeared → the reap was partially
 *     reverted; investigate the ship diff.
 *   * `CustomerFullTimeline` was removed → the canonical customer
 *     surface was reverted; a new TD must be raised to document.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const SRC_ROOT = path.resolve(__dirname, "..");

function _read(rel) {
  return fs.readFileSync(path.join(SRC_ROOT, rel), "utf8");
}


describe("TD-98/99 · post-reap source-contract", () => {
  it("LeadDetail imports the shared CommunicationDetailModal", () => {
    const src = _read("pages/leads/LeadDetail.jsx");
    expect(src).toMatch(
      /from\s+["']@\/components\/communications\/CommunicationDetailModal["']/,
    );
  });

  it("orphan Wave A CommunicationTimeline.jsx has been reaped", () => {
    const orphanPath = path.join(
      SRC_ROOT, "components/customers/CommunicationTimeline.jsx",
    );
    expect(fs.existsSync(orphanPath)).toBe(false);
  });

  it("CustomerDetail no longer imports the reaped orphan", () => {
    const src = _read("pages/customers/CustomerDetail.jsx");
    expect(src).not.toMatch(
      /from\s+["']@\/components\/customers\/CommunicationTimeline["']/,
    );
  });

  it("CustomerFullTimeline (canonical customer surface) still exists", () => {
    const canonicalPath = path.join(
      SRC_ROOT, "components/customers/CustomerFullTimeline.jsx",
    );
    expect(fs.existsSync(canonicalPath)).toBe(true);
  });

  it("CustomerDetail still mounts CustomerFullTimeline", () => {
    const src = _read("pages/customers/CustomerDetail.jsx");
    expect(src).toMatch(/<CustomerFullTimeline/);
  });

  it("CommunicationDetailModal (lead-side primitive) still exists", () => {
    const modalPath = path.join(
      SRC_ROOT, "components/communications/CommunicationDetailModal.jsx",
    );
    expect(fs.existsSync(modalPath)).toBe(true);
  });
});
