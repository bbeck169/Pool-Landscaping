/**
 * Phase G4a · Feb-2026 — CustomersList portal-status filter.
 * Phase K40 · Feb-2026 — persistence REMOVED (site-wide "no
 *   persistence across page loads" rule). This suite pins the
 *   post-K40 shape:
 *     • dropdown still ships with 3 options (all / activated /
 *       not_activated),
 *     • defaults to ``"all"`` on every mount,
 *     • wire param ``portal_status`` is only sent when non-default,
 *     • NO localStorage read/write (regression guard).
 *
 * Source-body contract check (mirrors the F5 / F6c pattern used
 * across this test suite). Runs against the actual JSX file so any
 * regression that drops the filter or reintroduces persistence is
 * caught by CI before it ever hits preview.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · G4a portal-status filter (K40-updated)", () => {
  it("defines exactly three portal-status options", () => {
    expect(SRC).toMatch(
      /_PORTAL_STATUS_OPTIONS\s*=\s*\[[\s\S]{0,600}"all"[\s\S]{0,600}"activated"[\s\S]{0,600}"not_activated"[\s\S]{0,80}\]/,
    );
  });

  it("K40 · initial value is the literal 'all' — no localStorage read", () => {
    // The old ``useState(() => localStorage.getItem(...))`` hydration
    // was stripped by K40. The initializer must now be a stable
    // literal so every mount lands on the "All" bucket.
    expect(SRC).toMatch(
      /const \[portalStatus, setPortalStatus\] = useState\("all"\);/,
    );
  });

  it("K40 · NO localStorage plumbing for the portal filter (regression guard)", () => {
    expect(SRC).not.toMatch(/_PORTAL_STORAGE_KEY/);
    expect(SRC).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*customerListFilter\.portalStatus/,
    );
  });

  it("resets pagination to page 1 on filter change (not on mount)", () => {
    // Mount-skip guard preserved — same F6c-shaped invariant even
    // though the persistence layer is gone.
    expect(SRC).toMatch(/_portalStatusInitRef/);
    expect(SRC).toMatch(
      /_portalStatusInitRef\.current\s*=\s*false;[\s\S]{0,60}return;\s*\}\s*setPage\(1\);/,
    );
  });

  it("sends ?portal_status=<value> to /api/customers only when non-default", () => {
    // The load() body should skip the param when portalStatus === "all"
    // so the wire log stays clean.
    expect(SRC).toMatch(
      /if\s*\(portalStatus\s*&&\s*portalStatus\s*!==\s*"all"\)\s*\{\s*params\.set\("portal_status",\s*portalStatus\);/,
    );
  });

  it("renders the dropdown with the G4a testid + all three options", () => {
    expect(SRC).toMatch(
      /data-testid="customers-filter-portal-status"/,
    );
    expect(SRC).toMatch(
      /data-testid={`portal-status-option-\$\{o\.value\}`}/,
    );
  });
});


describe("G4a · segmented cohort tabs still ship (no accidental removal)", () => {
  it("preserves the F6c segmented cohort tab shell so the two filters stack", () => {
    // Regression guard: the portal filter must NOT have replaced
    // the segmented tabs — spec says STACKS with them.
    expect(SRC).toMatch(/data-testid="customers-cohort-tabs"/);
    expect(SRC).toMatch(/testid:\s*"tab-active"/);
    expect(SRC).toMatch(/testid:\s*"tab-inactive"/);
    expect(SRC).toMatch(/testid:\s*"tab-muted"/);
    expect(SRC).toMatch(/testid:\s*"tab-all"/);
  });
});
