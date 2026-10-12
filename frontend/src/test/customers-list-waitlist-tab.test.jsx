/**
 * Phase H4 · Feb-2026 — CustomersList Waitlist cohort tab.
 *
 * Source-body contract check (mirrors the G4a / F6c pattern used
 * across this test suite). Runs against the actual JSX file so any
 * regression that drops the tab, its localStorage plumbing, count
 * plumbing, or the request wiring is caught by CI before it ever
 * hits preview.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · H4 Waitlist cohort tab", () => {
  it("registers a ``waitlist`` tab in TAB_DEFS after ``muted`` and before ``all``", () => {
    // Order matters — spec: Active | Inactive | Muted | Waitlist | All.
    const mutedIdx = SRC.indexOf('testid: "tab-muted"');
    const wlIdx = SRC.indexOf('testid: "tab-waitlist"');
    const allIdx = SRC.indexOf('testid: "tab-all"');
    expect(mutedIdx).toBeGreaterThan(-1);
    expect(wlIdx).toBeGreaterThan(mutedIdx);
    expect(allIdx).toBeGreaterThan(wlIdx);
  });

  it("marks the Waitlist tab as admin-only (same gate as inactive/muted)", () => {
    // The definition line must carry adminOnly: true.
    expect(SRC).toMatch(
      /k:\s*"waitlist"[\s\S]{0,120}testid:\s*"tab-waitlist"[\s\S]{0,60}adminOnly:\s*true/,
    );
  });

  it("wires the Waitlist count into the counts state", () => {
    // Phase Hygiene B · Feb-2026 — the counts state carries more
    // buckets than the H4 spec (``muted`` + ``all`` were folded in),
    // and the initializer key order is not part of the contract.
    // Relax the regex to just require ``waitlist: null`` inside the
    // useState({...}) init block.
    expect(SRC).toMatch(
      /useState\(\{[^)]*waitlist:\s*null[^)]*\}\)/,
    );
    // TAB_DEFS reads counts.waitlist for the badge.
    expect(SRC).toMatch(
      /count:\s*counts\.waitlist,\s*testid:\s*"tab-waitlist"/,
    );
  });

  it("hydrates the waitlist count via the consolidated /customers/counts endpoint (admin only)", () => {
    // CUS-perf v3 (R3=B ruling, Feb-2026) replaced the P31-era
    // ``promises.push(api.get(/customers?waitlisted=true&count_only=true...))``
    // fanout + indexed ``results[3]?.count`` read with a single
    // ``api.get(/customers/counts)`` call returning every bucket
    // at once. Lock the current unified pattern.
    expect(SRC).toMatch(
      /api\.get\(`\/customers\/counts\$\{qs\s*\?\s*`\?\$\{qs\}`\s*:\s*""\}`\)/,
    );
    // Admin-only gate: the waitlist count must still null-out for
    // non-admin viewers so no bogus badge renders in a tech session.
    expect(SRC).toMatch(
      /waitlist:\s*isAdmin\s*\?\s*\(r\?\.waitlist\s*\?\?\s*0\)\s*:\s*null/,
    );
  });

  it("selecting the Waitlist tab sends ?waitlisted=true on /customers list load", () => {
    // The load() body must map tab === "waitlist" to the backend
    // ``waitlisted=true`` param. Waitlist is orthogonal to
    // active/inactive/muted so those params must NOT be stamped on
    // the same call.
    expect(SRC).toMatch(
      /else if\s*\(tab\s*===\s*"waitlist"\)\s*params\.set\("waitlisted",\s*"true"\)/,
    );
    // Sanity: it's chained AFTER the muted branch (order defines
    // the else-if fall-through — waitlist must not accidentally
    // short-circuit inactive/muted).
    const mutedBranch = SRC.indexOf('else if (tab === "muted")');
    const wlBranch = SRC.indexOf('else if (tab === "waitlist")');
    expect(mutedBranch).toBeGreaterThan(-1);
    expect(wlBranch).toBeGreaterThan(mutedBranch);
  });

  it("accepts ``waitlist`` as a valid initial cohort via URL params (K40)", () => {
    // Phase K40 · Feb-2026 — localStorage hydration was removed by
    // K40. The old ``stored === "muted" || stored === "waitlist"``
    // fallback chain is gone; the initializer now relies on
    // ``?tab=waitlist`` / ``?status=waitlist`` URL params (which
    // still win per K40 rule #4) plus the ``"active"`` default.
    // Regression guard: the branch reading ``searchParams.get("tab")``
    // must survive so a Waitlist deep-link keeps landing correctly.
    expect(SRC).toMatch(/searchParams\.get\("tab"\)/);
    expect(SRC).toMatch(/searchParams\.get\("status"\)/);
    // And the load() logic must still recognize "waitlist" as a
    // valid ``tab`` value once selected.
    expect(SRC).toMatch(
      /else if\s*\(tab\s*===\s*"waitlist"\)\s*params\.set\("waitlisted",\s*"true"\)/,
    );
  });

  it("redirects non-admin users away from the Waitlist tab (admin gate parity)", () => {
    expect(SRC).toMatch(
      /!isAdmin\s*&&\s*\(tab\s*===\s*"inactive"\s*\|\|\s*tab\s*===\s*"muted"\s*\|\|\s*tab\s*===\s*"waitlist"\)/,
    );
  });

  it("does NOT introduce a schema-modifying add/remove-waitlist call (non-goal)", () => {
    // The H4 brief explicitly forbids changes to the existing bulk
    // actions. The tab is a pure filter surface — assert we do not
    // add a new PATCH/POST body for waitlist toggle from the tab
    // itself. Existing bulk-action strings ``add_waitlist`` /
    // ``remove_waitlist`` can still appear in the bulk-actions
    // menu — we only guard against a NEW code path that mutates on
    // tab select.
    expect(SRC).not.toMatch(
      /setTab\(\s*"waitlist"[\s\S]{0,120}(add_waitlist|remove_waitlist)/,
    );
  });
});


describe("H4 · previously-shipped cohort tabs still ship (no accidental removal)", () => {
  it("preserves the Active/Inactive/Muted/All quartet alongside Waitlist", () => {
    expect(SRC).toMatch(/data-testid="customers-cohort-tabs"/);
    expect(SRC).toMatch(/testid:\s*"tab-active"/);
    expect(SRC).toMatch(/testid:\s*"tab-inactive"/);
    expect(SRC).toMatch(/testid:\s*"tab-muted"/);
    expect(SRC).toMatch(/testid:\s*"tab-waitlist"/);
    expect(SRC).toMatch(/testid:\s*"tab-all"/);
  });

  it("still page-resets on tab change via the F6c mount-skip guard", () => {
    // The existing _tabInitRef guard covers the new tab for free —
    // just assert it's still there so a future refactor cannot
    // regress the Waitlist tab back to landing on stale page N.
    expect(SRC).toMatch(/_tabInitRef\.current\s*=\s*false;/);
    expect(SRC).toMatch(/setPage\(1\);[\s\S]{0,120}\/\/ eslint-disable-next-line react-hooks\/exhaustive-deps\s*\}\s*,\s*\[tab\]\);/);
  });

  it("stacks with the G4a portal-status filter (both filters coexist)", () => {
    // Regression guard for the intersection contract locked by the
    // backend test ``test_h4_waitlist_stacks_with_portal_status_as_intersection``.
    //
    // Phase K40 · Feb-2026 — the localStorage keys the previous
    // version of this test asserted (``_COHORT_STORAGE_KEY`` /
    // ``_PORTAL_STORAGE_KEY``) were REMOVED with K40's "no
    // persistence" rule. We now assert on the two React state
    // owners that still coexist in the file — the cohort tab and
    // the portal-status dropdown — which is the actual intersection
    // contract the backend test cares about.
    expect(SRC).toMatch(/const \[tab, setTab\] = useState\(initialTab\);/);
    expect(SRC).toMatch(/const \[portalStatus, setPortalStatus\] = useState\("all"\);/);
  });
});
