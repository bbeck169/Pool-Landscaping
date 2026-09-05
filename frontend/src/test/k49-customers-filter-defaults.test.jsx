/**
 * Phase K49 · Feb-2026 — Customers page filter defaults + Last-Name
 * sort default.
 *
 * Source-body contract checks (K41 pattern) — the runtime graph is
 * heavy for this page (tags dropdown, pagination, merge candidates,
 * multiple bulk toolbars) so a source-shape assertion is the
 * durable + fast test surface here. The behaviours covered:
 *
 *   1. Sort dropdown default is "Last Name A-Z" (value:
 *      ``last_name_asc``).
 *   2. localStorage persistence for ``customers.sortBy`` is removed
 *      (K40 rule alignment).
 *   3. Explicit ``?sort=`` URL param is honoured on mount (bookmark
 *      exception).
 *   4. All red-circle filters default to no-filter: chips ``scope``
 *      starts at ``"all"``, dropdown ``tag`` starts at ``""``,
 *      ``portalStatus`` at ``"all"``, ``missingCardOnly`` /
 *      ``includeDeleted`` / ``includeMerged`` all ``false``.
 *   5. Top-level tab still defaults to ``active`` — K40 exception
 *      preserved.
 *   6. Sort dropdown lists all 5 sort options in the expected
 *      order, with the K49 addition first.
 *   7. ``load()`` forwards ``sort=<value>`` on the wire so the
 *      backend receives the K49 sort key.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const LIST = read("src/pages/customers/CustomersList.jsx");


describe("K49 · CustomersList — sort dropdown", () => {
  it("defaults sortBy to ``last_name_asc``", () => {
    // Initializer literal falls through to the K49 default.
    expect(LIST).toMatch(/return "last_name_asc";/);
  });

  it("lists Last Name A-Z as the FIRST sort option so the menu opens on it", () => {
    // Options array must lead with the K49 addition; the label
    // string doubles as the ``<option>`` text.
    expect(LIST).toMatch(
      /_SORT_OPTIONS = \[\s*\n\s*\/\/ K49 default[\s\S]{0,200}?\{ value: "last_name_asc", label: "Last Name A-Z" \}/,
    );
  });

  it("removes the ``customers.sortBy`` localStorage read + write", () => {
    // The prior K46-era file wrote to localStorage on every sortBy
    // change; K49 drops that so the dropdown obeys the K40 reset-
    // on-every-mount rule. Neither read (``getItem``) nor write
    // (``setItem``) may reference the sort key any more; historical
    // mentions in comments are fine.
    expect(LIST).not.toMatch(/localStorage\.getItem\([^)]*sortBy/);
    expect(LIST).not.toMatch(/localStorage\.setItem\([^)]*sortBy/);
    expect(LIST).not.toMatch(/_SORT_STORAGE_KEY\s*=/);
  });

  it("honours an explicit ``?sort=`` URL param on mount", () => {
    // Bookmark exception — matches the ``?tab=`` / ``?status=``
    // behaviour on the tab initializer above.
    expect(LIST).toMatch(
      /new URLSearchParams\(window\.location\.search\)\s*\n?\s*\.get\("sort"\)/,
    );
    expect(LIST).toMatch(/if \(raw && _SORT_VALUES\.has\(raw\)\) return raw;/);
  });

  it("forwards the ``sort`` key to GET /customers", () => {
    // ``load()`` writes ``params.set("sort", sortBy)`` so the wire
    // request carries the K49 value.
    expect(LIST).toMatch(/params\.set\("sort", sortBy\)/);
  });

  it("keeps the four legacy sort options", () => {
    // Regression guard — Last Name shipped as an ADDITION, not a
    // replacement.
    expect(LIST).toMatch(/value: "created_desc"/);
    expect(LIST).toMatch(/value: "created_asc"/);
    expect(LIST).toMatch(/value: "name_asc"/);
    expect(LIST).toMatch(/value: "name_desc"/);
  });
});


describe("K49 · CustomersList — filter defaults (red-circle inventory)", () => {
  it("chip scope defaults to ``all`` (effective no-filter)", () => {
    expect(LIST).toMatch(/useState\("all"\); \/\/ all \| waitlist \| unscheduled/);
  });

  it("tag dropdown defaults to `` `` (renders as \"All tags\")", () => {
    expect(LIST).toMatch(/const \[tag, setTag\] = useState\(""\);/);
    // Option label kept — user brief said keep "All" wording where
    // it already reads correctly in context.
    expect(LIST).toMatch(/<option value="">All tags<\/option>/);
  });

  it("Portal filter defaults to ``all``", () => {
    expect(LIST).toMatch(
      /const \[portalStatus, setPortalStatus\] = useState\("all"\);/,
    );
    expect(LIST).toMatch(/label: "Portal: All"/);
  });

  it("Missing card / includeDeleted / includeMerged toggles are OFF on mount", () => {
    expect(LIST).toMatch(
      /const \[missingCardOnly, setMissingCardOnly\] = useState\(false\);/,
    );
    expect(LIST).toMatch(
      /const \[includeDeleted, setIncludeDeleted\] = useState\(false\);/,
    );
    expect(LIST).toMatch(
      /const \[includeMerged, setIncludeMerged\] = useState\(false\);/,
    );
  });

  it("No email / No phone chips hydrate from URL params (bookmark honour)", () => {
    // These two are the intentional K40 exception — URL params
    // ``?missing_email=1`` / ``?missing_phone=1`` still win on
    // mount so the Dashboard "missing contact" deep-links work.
    expect(LIST).toMatch(
      /useState\(\s*\n?\s*\(\) => searchParams\.get\("missing_email"\) === "1"\)/,
    );
    expect(LIST).toMatch(
      /useState\(\s*\n?\s*\(\) => searchParams\.get\("missing_phone"\) === "1"\)/,
    );
  });
});


describe("K49 · CustomersList — top-level tab default preserved (K40 exception)", () => {
  it("tab initializer falls through to \"active\" when no URL / route param is present", () => {
    // Explicit K40 exception — the tab bar defaults to ACTIVE while
    // every other filter in the red circle resets to no-filter.
    expect(LIST).toMatch(/return "active";/);
    expect(LIST).toMatch(/const \[tab, setTab\] = useState\(initialTab\);/);
  });
});
