/**
 * Phase K68 · Feb-2026 — CustomersList tab count wiring against the
 * new ``counts_by_status`` envelope block.
 *
 * Source-shape assertions (following the K49 pattern) — the runtime
 * mount graph for CustomersList is heavy (tags dropdown, pagination,
 * merge candidates, bulk toolbars) so a source-body test is the
 * durable + fast surface. Verified behaviours:
 *
 *   1. ``counts`` state initializer carries all 5 buckets (active,
 *      inactive, muted, waitlist, all).
 *   2. ``load()`` consumes the envelope's ``counts_by_status`` block
 *      and pushes it into the counts state.
 *   3. The ``ALL`` tab is wired to ``counts.all`` (was hardcoded
 *      null before K68).
 *   4. The useEffect that fires on filter/tab/page changes no
 *      longer invokes the legacy 3-4-request ``loadCounts()`` fan
 *      out — envelope path is the primary.
 *   5. Legacy ``loadCounts()`` fallback still exists for defensive
 *      use and now also computes the ``all`` bucket for the
 *      envelope-missing edge case.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const LIST = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);

describe("Phase K68 · CustomersList counts_by_status wiring", () => {
  it("initializes the counts state with all 5 buckets", () => {
    expect(LIST).toMatch(
      /useState\(\{\s*active:\s*null,\s*inactive:\s*null,\s*muted:\s*null,\s*waitlist:\s*null,\s*all:\s*null\s*\}\)/,
    );
  });

  it("load() consumes counts_by_status from the envelope", () => {
    expect(LIST).toMatch(/const cbs = data\?\.counts_by_status/);
    expect(LIST).toMatch(/setCounts\(\{[\s\S]{0,600}?cbs\.active[\s\S]{0,600}?cbs\.all[\s\S]{0,200}?\}\)/);
  });

  it("ALL tab now uses counts.all instead of hardcoded null", () => {
    expect(LIST).toMatch(
      /\{\s*k:\s*"all",\s*label:\s*"All",\s*count:\s*counts\.all/,
    );
  });

  it("filter/tab change effect dispatches load() + loadCounts() in parallel", () => {
    // Phase K68 originally removed the legacy fanout; CUS-perf v3
    // (R3=B ruling, Feb-2026) reversed that by firing both load()
    // and loadCounts() concurrently inside a Promise.all() so the
    // tab counts stay fresh for the admin "all" bucket without a
    // round-trip serialization cost. Lock the current contract so
    // a future revert doesn't silently drop loadCounts() from the
    // filter-change effect again.
    const effectMatch = LIST.match(
      /useEffect\(\(\)\s*=>\s*\{[\s\S]{0,2000}?Promise\.all\(\s*\[\s*load\(\)\s*,\s*loadCounts\(\)\s*\]\s*\)[\s\S]{0,1200}?\},\s*\[searchDeb, tag, scope, tab/,
    );
    expect(effectMatch, "CUS-perf v3 filter-change effect must dispatch Promise.all([load(), loadCounts()])").toBeTruthy();
  });

  it("loadCounts() fallback still computes an all bucket", () => {
    // The fallback branch should now assign ``all: isAdmin ? ...``
    // so the tab isn't stuck on null when the envelope is missing.
    // Feb-2026 · Round 2 flake fix — the P43/P44/P46/K68 filter
    // suffix additions pushed the fallback slightly past the
    // original 2500-char slice; widen to 4000 to keep the assertion
    // stable.
    const loadCountsFn = LIST.split(
      "const loadCounts = async () =>",
    )[1];
    expect(loadCountsFn).toBeDefined();
    const fnBody = loadCountsFn.slice(0, 4000);
    expect(fnBody).toMatch(/all:\s*isAdmin/);
  });
});
