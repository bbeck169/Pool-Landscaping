/**
 * Phase P0.5 · Feb-2026 · Leads UI polish — LeadDetail regressions.
 *
 * Locks three source-level acceptance checks on
 * ``frontend/src/pages/leads/LeadDetail.jsx``:
 *
 *   1. Empty-address rows render an explicit
 *      ``data-testid="lead-address-empty"`` "No address provided"
 *      line (visible when NEITHER ``service_address`` / ``address``
 *      NOR ``city`` / ``state`` / ``zip`` are set).
 *   2. lat/lng hint (``data-testid="lead-latlng"``) renders ONLY
 *      when BOTH ``lead.latitude`` AND ``lead.longitude`` are
 *      present.
 *   3. The city/state/zip block stays hidden when all three are
 *      empty (per Phase P0.5 direction — the outer empty-state
 *      line covers that case).
 *
 * We source-scan the JSX rather than mounting the full LeadDetail
 * page (which pulls in api-client, toaster, click-to-call, and a
 * live ``/api/leads/:id`` fetch). Fast + zero-mount signal on the
 * polish items — matches the pattern in
 * ``leads-list-and-raw-submission.test.jsx``.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/leads/LeadDetail.jsx"),
  "utf-8",
);


describe("LeadDetail · Phase P0.5 polish", () => {
  it("renders 'No address provided' empty-state under a testid", () => {
    expect(SRC).toMatch(/data-testid="lead-address-empty"/);
    expect(SRC).toMatch(/No address provided/);
  });

  it("empty-state gates on !hasAnyAddress (blob + csz both absent)", () => {
    // The empty-state branch fires when the row has NO street blob
    // (``service_address`` / ``address``) AND no discrete city /
    // state / zip. Locking the guard clause verbatim so a future
    // refactor can't loosen the gate and start rendering the
    // "No address provided" line on rows that DO have data.
    expect(SRC).toMatch(/hasAnyAddress\s*=\s*!!\(line1\s*\|\|\s*hasCSZ\)/);
    expect(SRC).toMatch(/!hasAnyAddress/);
  });

  it("renders the lat/lng hint under 'lead-latlng' testid", () => {
    expect(SRC).toMatch(/data-testid="lead-latlng"/);
    // The formatted output uses ``toFixed(4)`` for both coordinates.
    expect(SRC).toMatch(/Number\(_lat\)\.toFixed\(4\)/);
    expect(SRC).toMatch(/Number\(_lng\)\.toFixed\(4\)/);
  });

  it("lat/lng hint is gated on BOTH coordinates being present", () => {
    // Confirms the ``_lat !== undefined && _lat !== null && _lng !==
    // undefined && _lng !== null`` guard is intact — a single
    // coordinate must never trigger the render.
    expect(SRC).toMatch(
      /_lat\s*!==\s*undefined\s*&&\s*_lat\s*!==\s*null\s*&&\s*_lng\s*!==\s*undefined\s*&&\s*_lng\s*!==\s*null/,
    );
  });

  it("city/state/zip block stays hidden when all three are empty", () => {
    // The ``hasCSZ ? (...) : null`` ternary must remain in place —
    // otherwise the detail view would render an empty comma line
    // for rows without a discrete address (the outer empty-state
    // line covers that case).
    expect(SRC).toMatch(
      /hasCSZ\s*=\s*!!\(lead\.city\s*\|\|\s*lead\.state\s*\|\|\s*lead\.zip\)/,
    );
    expect(SRC).toMatch(/hasCSZ\s*\?[\s\S]{0,400}lead-city-state-zip/);
  });

  it("populated-address branch still renders the street blob", () => {
    // Regression guard — the ternary's non-empty branch must
    // continue to render ``lead.service_address || lead.address``
    // under the ``lead-address`` testid.
    expect(SRC).toMatch(/data-testid="lead-address"/);
    expect(SRC).toMatch(/line1\s*=\s*lead\.service_address\s*\|\|\s*lead\.address/);
  });
});
