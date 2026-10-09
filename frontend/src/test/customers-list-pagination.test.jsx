/**
 * Phase 9c · Feb-2026 — Customers list pagination + slim-param FE
 * contract tests. Static source-body checks against
 * ``CustomersList.jsx`` (matching the ``customers-list-*`` suite
 * convention — full-page mount is too heavy for the vitest harness,
 * see vitest.config.js Phase 41.5 note).
 *
 * Locks:
 *   1. Default ``_K62_DEFAULT_PAGE_SIZE`` is now 50 (bumped from
 *      25 as part of Phase 9cd).
 *   2. ``_K62_PAGE_SIZE_OPTIONS`` still ships 25 / 50 / 100 so
 *      operators can override the default.
 *   3. ``load()`` passes ``slim=1`` to the ``/customers`` list
 *      request (opt-in into the Phase 9c slim projection).
 *   4. ``load()`` still passes ``page`` + ``page_size`` so the
 *      backend returns the paginated envelope (regression lock on
 *      Phase 9b's URL-driven filter wiring).
 *   5. ``load()`` still consumes the ``counts_by_status`` block
 *      from the paginated envelope (K68 tab-badge wiring must not
 *      regress under slim).
 *   6. The three Phase 9b tile URL params still map through to the
 *      list request without a rename (``portal_activated`` /
 *      ``first_access`` / ``has_payment_method``).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("Phase 9cd · CustomersList pagination + slim-param FE contract", () => {
  it("1. Default page size is 50 (bumped from 25 per Phase 9cd)", () => {
    expect(SRC).toMatch(
      /const\s+_K62_DEFAULT_PAGE_SIZE\s*=\s*50\s*;/,
    );
    // Old default must be gone — regression guard.
    expect(SRC).not.toMatch(
      /const\s+_K62_DEFAULT_PAGE_SIZE\s*=\s*25\s*;/,
    );
  });

  it("2. Page-size options still include 25 / 50 / 100", () => {
    expect(SRC).toMatch(
      /_K62_PAGE_SIZE_OPTIONS\s*=\s*\[\s*25\s*,\s*50\s*,\s*100\s*\]/,
    );
  });

  it("3. load() passes slim=1 on the /customers list request", () => {
    // The exact line is ``params.set("slim", "1");`` — static grep
    // keeps the opt-in locked. Removing it would silently revert
    // the perf win (per-row properties_count + next_scheduled_at
    // hydration would come back) without any user-visible break.
    expect(SRC).toMatch(/params\.set\(\s*"slim"\s*,\s*"1"\s*\)/);
  });

  it("4. load() still passes page + page_size (envelope regression lock)", () => {
    expect(SRC).toMatch(/params\.set\(\s*"page"\s*,\s*String\(page\)\s*\)/);
    expect(SRC).toMatch(
      /params\.set\(\s*"page_size"\s*,\s*String\(pageSize\)\s*\)/,
    );
  });

  it("5. load() still consumes counts_by_status from the paginated envelope", () => {
    // K68 tab-badge wiring — the Phase 9c slim projection must not
    // strip this block out of the response envelope on the server
    // side (regression lock mirrored on the backend by
    // test_9c_slim_counts_by_status_still_present).
    expect(SRC).toMatch(/const\s+cbs\s*=\s*data\?\.counts_by_status/);
    expect(SRC).toMatch(/setCounts\(\{[\s\S]{0,300}active:\s*/);
  });

  it("6. Phase 9b tile URL params still map through to the request verbatim", () => {
    // The three tile-filter URL params must still be plumbed into
    // the ``/customers`` list request so clicking a Phase 9b tile
    // produces the same server-filtered list under slim.
    expect(SRC).toMatch(/params\.set\(\s*"portal_activated"/);
    expect(SRC).toMatch(/params\.set\(\s*"first_access"/);
    expect(SRC).toMatch(/params\.set\(\s*"has_payment_method"/);
  });

  it("7. Semantic alignment · slim does not touch the tile → URL mapping", () => {
    // Phase 9b semantic alignment lock — the tile's URL params map
    // 1:1 to server params. Phase 9cd must not have changed the
    // param names on the client side.
    //
    //   Activated       → ?portal_activated=1 | true
    //   Signed in       → ?first_access=any
    //   Cards on file   → ?has_payment_method=true (+ is_active=true)
    //
    // The exact string ``portal_activated`` must appear with the
    // ``true`` value in the load() body — this guards against a
    // rename to ``activated``, which would silently decouple the
    // tile from the list.
    expect(SRC).toMatch(/params\.set\(\s*"portal_activated"\s*,\s*"true"\s*\)/);
  });
});
