/**
 * TD-78b · Feb-2026 — "Closed job — edits logged" banner on
 * ``JobDetail.jsx``.
 *
 * Operator-spec contract:
 *   * Visible ONLY when the viewer has K6 unlock AND the job is
 *     closed/completed.
 *   * Hidden for in-progress jobs (any role).
 *   * Hidden for non-K6 roles on closed jobs (viewer, marketer,
 *     etc.).
 *   * Hidden for customers (already read-only).
 *   * Non-dismissible — once visible it stays.
 *
 * Source-grep locks (no DOM render required — the banner lives
 * inside a gate that's already fully covered by
 * ``jobdetail-k6-completed-unlock.test.jsx``). This suite pins
 * the structural contract.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf-8",
);


describe("TD-78b · closed-job 'edits logged' banner — structural locks", () => {
  it("banner element with the canonical testid exists", () => {
    expect(SRC).toMatch(/data-testid="jd-closed-job-edits-logged-banner"/);
  });

  it("banner is gated by `canEditCompleted` — same K6 + completed-status gate as the edit controls", () => {
    // The gate expression ``canEditCompleted ? ( ... ) : null``
    // must contain the banner testid INSIDE the truthy branch.
    const gateIdx = SRC.indexOf("canEditCompleted ? (");
    expect(gateIdx).toBeGreaterThan(-1);
    const close = SRC.indexOf(") : null}", gateIdx);
    expect(close).toBeGreaterThan(gateIdx);
    // Walk every ``canEditCompleted ? (`` block and find the one
    // whose body contains the banner testid.
    const haystack = SRC;
    let i = 0;
    let found = false;
    while (true) {
      const start = haystack.indexOf("canEditCompleted ? (", i);
      if (start < 0) break;
      const stop = haystack.indexOf(") : null}", start);
      if (stop > start) {
        const slice = haystack.slice(start, stop);
        if (slice.includes("jd-closed-job-edits-logged-banner")) {
          found = true;
          break;
        }
      }
      i = (stop > start ? stop : start) + 1;
    }
    expect(found).toBe(true);
  });

  it("banner copy mentions both 'Closed job' and 'edits are logged'", () => {
    expect(SRC).toMatch(/Closed job/);
    expect(SRC).toMatch(/edits are logged/);
  });

  it("banner is NOT inside a dismissal-state gate — operator-spec non-dismissible", () => {
    // Negative lock — no ``setBannerDismissed`` / ``bannerDismissed``
    // state hooks on this file (would indicate a dismiss toggle).
    expect(SRC).not.toMatch(/\bbannerDismissed\b/);
    expect(SRC).not.toMatch(/\bsetBannerDismissed\b/);
  });

  it("`canEditCompleted` gate still requires both `!isCustomer` AND K6_UNLOCK_ROLES — regression lock", () => {
    // Pre-existing contract from ``jobdetail-k6-completed-unlock``
    // suite. Re-pinned here so a future refactor touching the
    // banner cannot accidentally loosen the gate.
    expect(SRC).toMatch(
      /const\s+canEditCompleted\s*=\s*\n?\s*!isCustomer\s*\n?\s*&&\s*K6_UNLOCK_ROLES\.has\(\s*user\?\.role\s*\|\|\s*""\s*\)\s*\n?\s*&&\s*\(job\?\.status\s*===\s*"completed"\)/
    );
  });
});
