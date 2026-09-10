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
    expect(SRC).toMatch(
      /if\s*\(neverLoggedIn\)\s*next\.set\("first_access",\s*"never"\);\s*else\s*next\.delete\("first_access"\);/,
    );
  });

  it("participates in load() dependency list so refetch fires on toggle", () => {
    // The load effect's dep array must include neverLoggedIn so the
    // list refetches every time the operator flips the chip.
    expect(SRC).toMatch(
      /noPaymentFilter,\s*neverLoggedIn,\s*includeDeleted/,
    );
  });

  it("resets pagination on toggle (via the shared URL-sync effect deps)", () => {
    // The URL-sync effect's dep array includes neverLoggedIn AND
    // the effect body calls setPage(1). This keeps the chip's page-
    // reset invariant identical to the P43/P44 chips.
    expect(SRC).toMatch(
      /noPaymentFilter,\s*neverLoggedIn\]\);/,
    );
  });

  it("fetches the standalone count without composing with other filters", () => {
    // Badge stability contract: never compose. Match the exact
    // count_only + first_access-only URL.
    expect(SRC).toMatch(
      /api\.get\(\s*"\/customers\?count_only=true&first_access=never"/,
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
