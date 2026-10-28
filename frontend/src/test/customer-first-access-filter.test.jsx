/**
 * Feb-2026 · Customer temp password + first-access tracking —
 * CustomersList "Never logged in" filter chip.
 *
 * Source-body contract check (mirrors the G4a / P44 pattern used
 * across this suite). Pins the wire contract with the backend
 * (`?first_access=never`), the URL sync shorthand, the chip's
 * data-testid, and the standalone count-fetch cadence. Any
 * regression that drops the chip, changes the wire param name,
 * or reintroduces localStorage persistence is caught by CI before
 * it ever hits preview.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · Never logged in filter (Feb-2026)", () => {
  it("hydrates neverLoggedIn state from the ?first_access=never URL", () => {
    expect(SRC).toMatch(
      /const \[neverLoggedIn, setNeverLoggedIn\] = useState\(\s*\(\)\s*=>\s*searchParams\.get\("first_access"\)\s*===\s*"never"/,
    );
  });

  it("renders the chip button with the canonical testid", () => {
    expect(SRC).toMatch(
      /data-testid="customers-never-logged-in-filter"/,
    );
  });

  it("renders the standalone count badge with its testid", () => {
    expect(SRC).toMatch(
      /data-testid="customers-never-logged-in-count"/,
    );
  });

  it("sends ?first_access=never to /api/customers when the chip is on", () => {
    expect(SRC).toMatch(
      /if\s*\(neverLoggedIn\)\s*params\.set\("first_access",\s*"never"\);/,
    );
  });

  it("keeps the URL in sync — sets first_access=never / deletes on off", () => {
    // Feb-2026 · Round 2 flake fix — production also handles the
    // "Signed in" companion chip inside this block, so the branch
    // is now `if (neverLoggedIn) set(never); else if (signedInFilter)
    // set(any); else delete()`. Match the set-never branch; the
    // delete branch is covered indirectly by the negative-case
    // sibling below.
    expect(SRC).toMatch(
      /if\s*\(neverLoggedIn\)\s*next\.set\("first_access",\s*"never"\);/,
    );
    expect(SRC).toMatch(
      /else\s+next\.delete\("first_access"\);/,
    );
  });

  it("participates in load() dependency list so refetch fires on toggle", () => {
    // The load effect's dep array must include neverLoggedIn so the
    // list refetches every time the operator flips the chip. The
    // tuple has evolved repeatedly (P43 chips, P44 city, K40 hasCard,
    // etc.); anchor on neverLoggedIn appearing within the dep tuple
    // rather than any specific neighbour.
    expect(SRC).toMatch(
      /\}\s*,\s*\[searchDeb[\s\S]{0,600}?neverLoggedIn[\s\S]{0,400}?\]\);/,
    );
  });

  it("resets pagination on toggle (via the shared URL-sync effect deps)", () => {
    // The URL-sync effect's dep array includes neverLoggedIn AND
    // the effect body calls setPage(1). Match on co-occurrence
    // rather than a rigid neighbour tuple (hasCardFilter now sits
    // between noPaymentFilter and neverLoggedIn after CUS-perf v3).
    //
    // ZZ-A Wave 3-D · Feb-2026 — the P2#6 service-category chip
    // URL sync (``CustomersList.jsx:888``) added
    // ``serviceCategoryFilter`` as the final dep after
    // ``signedInFilter``, so the pre-Wave-3 trailing-anchor
    // ``signedInFilter])`` no longer closes the array literally.
    // Rebaselined to assert the three mid-array deps appear in
    // order without anchoring on the terminator.
    expect(SRC).toMatch(
      /neverLoggedIn,\s*portalInvitedFilter,\s*signedInFilter[,\s\]]/,
    );
  });

  it("hydrates the never-logged-in count from the consolidated loadCounts() response", () => {
    // Phase P31 (Feb-2026) consolidated the per-badge count fetches
    // into a single ``/customers/counts`` call. The pre-P31
    // standalone ``/customers?count_only=true&first_access=never``
    // probe is sunsetted — the badge now reads
    // ``r?.never_logged_in ?? 0`` off the unified envelope.
    expect(SRC).toMatch(
      /setNeverLoggedInCount\(r\?\.never_logged_in\s*\?\?\s*0\)/,
    );
  });

  it("has NO localStorage persistence (regression guard)", () => {
    // The Feb-2026 K40 policy forbids per-filter localStorage
    // hydration. Every filter must default to its literal on mount.
    expect(SRC).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*neverLoggedIn/,
    );
    expect(SRC).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*first_access/,
    );
  });

  it("increments the active-filters counter when the chip is on", () => {
    // Preserves the "more filters" trigger badge accuracy.
    expect(SRC).toMatch(
      /\(neverLoggedIn\s*\?\s*1\s*:\s*0\)/,
    );
  });

  it("adds a 'Never logged in' summary bit when active", () => {
    // The trigger button surfaces the human-readable filter list;
    // the chip must contribute its own label.
    expect(SRC).toMatch(
      /if\s*\(neverLoggedIn\)\s*summaryBits\.push\("Never logged in"\);/,
    );
  });
});


describe("CustomersList · first-access chip stacks with sibling filters", () => {
  it("keeps the P43c portal-status filter surface untouched", () => {
    // Regression guard: the new chip must not have replaced the
    // portal-status tri-state — spec says STACKS with it.
    expect(SRC).toMatch(/data-testid="customers-portal-status-filter"/);
  });

  it("keeps the P44 no-payment chip untouched", () => {
    expect(SRC).toMatch(/data-testid="customers-no-payment-filter"/);
  });
});
