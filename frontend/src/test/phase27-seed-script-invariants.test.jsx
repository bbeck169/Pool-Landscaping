/**
 * Phase 27 follow-up #2 · Feb-2026 — seed-script invariants.
 *
 * The Dispatch Board's `tech_load` derives from
 * `customers.assigned_tech_ids`. To keep the seed idempotent and
 * matching that data contract, the seed script MUST:
 *
 *   1. Upsert/update a customer document (not just the job).
 *   2. Use `$addToSet` for the tech array so re-runs never
 *      duplicate the entry.
 *   3. Point the job at the seeded customer via `customer_id` so
 *      the dispatch board's customer/job join lights up.
 *
 * This vitest source-inspects the seed script and locks the above
 * three invariants — cheaper than a live pytest, catches drift
 * fast on any future refactor of the seed helper.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const SEED_SRC = fs.readFileSync(
  path.resolve(
    __dirname, "../../../backend/scripts/seed_phase27_demo_job.py",
  ),
  "utf-8",
);

describe("Phase 27 follow-up #2 · seed script invariants", () => {
  it("upserts a customer document (not just the job)", () => {
    // Any mutation targeting db.customers is acceptable — the exact
    // shape is enforced by the next assertions.
    expect(SEED_SRC).toMatch(/db\.customers\.update_one\s*\(/);
  });

  it("adds the tech user_id to assigned_tech_ids with $addToSet (idempotent)", () => {
    // Regex is deliberately permissive on whitespace / quote style
    // so a cosmetic refactor of the payload dict doesn't break the
    // guard. The two anchors we lock are the operator name and the
    // target array name.
    expect(SEED_SRC).toMatch(
      /\$addToSet["'\s:]+\{[^}]*assigned_tech_ids[^}]*\}/,
    );
  });

  it("uses upsert=True on the customer update so first-run inserts the doc", () => {
    expect(SEED_SRC).toMatch(/upsert\s*=\s*True/);
  });

  it("points the job's customer_id at the seeded customer id", () => {
    // Job payload must reference the seeded id so the dispatch
    // board's customer/job join resolves.
    expect(SEED_SRC).toMatch(
      /customer_id["'\s:]+customer_id/,
    );
    // And the seeded id itself is the stable string the CHANGELOG
    // documents.
    expect(SEED_SRC).toMatch(/"seed-phase27-demo-customer"/);
  });

  it("preflight bails cleanly if the tenant or Luis user is missing", () => {
    // Regression guard so a future refactor doesn't accidentally
    // start writing orphan docs when the demo tenant drifts.
    expect(SEED_SRC).toMatch(/return None/);
    expect(SEED_SRC).toMatch(/bailing/);
  });

  // ── Phase 27 follow-up #3 · dispatch-board denormalized fields. ──
  it("Phase 27 follow-up #3 · writes service_lat / service_lng on the customer", () => {
    // The dispatch board query hard-filters on ``service_lat:
    // {$exists: true, $ne: null}`` — customer-form ``latitude``
    // alone is invisible to that surface. The seed MUST populate
    // both shapes.
    expect(SEED_SRC).toMatch(/["']service_lat["']\s*:/);
    expect(SEED_SRC).toMatch(/["']service_lng["']\s*:/);
  });

  it("Phase 27 follow-up #3 · writes service_address on the customer", () => {
    expect(SEED_SRC).toMatch(/["']service_address["']\s*:/);
  });

  it("Phase 27 follow-up #3 · writes service_days using the mon..sun convention", () => {
    // dispatch_board.py + customer_categories._DAY_NAMES both use
    // lowercase 3-letter names. The seed MUST match — a bare list
    // of integers would silently exclude the row from any
    // day-filtered dispatch query.
    expect(SEED_SRC).toMatch(/["']service_days["']\s*:/);
    expect(SEED_SRC).toMatch(
      /\[\s*["']mon["'][\s\S]*?["']tue["'][\s\S]*?["']wed["'][\s\S]*?["']thu["'][\s\S]*?["']fri["'][\s\S]*?["']sat["'][\s\S]*?["']sun["']\s*\]/,
    );
  });
});
