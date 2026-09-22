/**
 * Phase CHEM1 · Feb-2026 — Required Four chemistry gate (web).
 *
 * Locks in:
 *   * The web gate mirror surfaces exactly the Required Four
 *     (free_chlorine, ph, alkalinity, cyanuric_acid) — Total
 *     Chlorine is not a required key any more.
 *   * PoolChecklistForm does NOT render a `Total Chlorine` input.
 *   * The chemistry-bands map no longer classifies Total Chlorine.
 *   * The water-bodies allow-list drops ``total_chlorine`` from
 *     ``pool`` / ``other`` allow-lists AND from the required set.
 *   * Optional readings (calcium_hardness, salt, tds, phosphates)
 *     accept blank / null / undefined without a "Required" flag.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import {
  CORE_KEYS,
  DISPLAY_LABELS,
  CANONICAL_SHORT_LABELS,
  missingCoreReadings,
  isChemistryGateSatisfied,
} from "@/utils/chemistryGate";
import { CANONICAL_BAND_THRESHOLDS, bandForReading } from "@/utils/chemistryBands";
import {
  READING_ALLOWLIST,
  READING_REQUIRED,
  READING_LABELS,
  missingRequiredReadings,
} from "@/lib/waterBodies";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";

describe("Phase CHEM1 · Required Four contract (web mirror)", () => {
  it("CORE_KEYS + label maps expose exactly the Required Four", () => {
    // Phase P17.1 · Feb-2026 — canonical rename: ``free_chlorine`` →
    // ``chlorine`` end-to-end. Legacy ``free_chlorine`` remains a
    // source alias in ALIAS_MAP; CORE_KEYS emits the new canonical.
    expect(CORE_KEYS).toEqual([
      "chlorine", "alkalinity", "ph", "cyanuric_acid",
    ]);
    expect(CORE_KEYS.includes("total_chlorine")).toBe(false);
    expect(DISPLAY_LABELS.total_chlorine).toBeUndefined();
    expect(CANONICAL_SHORT_LABELS.total_chlorine).toBeUndefined();
  });

  it("gate passes when the Required Four are filled and optionals blank", () => {
    expect(isChemistryGateSatisfied([
      { key: "free_chlorine",   value: 2.5 },
      { key: "ph",              value: 7.4 },
      { key: "alkalinity",      value: 100 },
      { key: "cyanuric_acid",   value: 40 },
      { key: "calcium_hardness", value: null },
      { key: "salt",             value: "" },
      { key: "phosphates",       value: null },
    ])).toBe(true);
  });

  it("gate 400 payload names the missing Required Four fields", () => {
    const missing = missingCoreReadings([
      // Chlorine missing (P17.1 · Feb-2026 canonical rename — was
      // ``Free Cl`` under P17).
      { key: "ph",             value: 7.4 },
      { key: "alkalinity",     value: 100 },
      { key: "cyanuric_acid",  value: 40 },
    ]);
    expect(missing).toEqual(["Chlorine"]);
  });

  it("gate silently tolerates total_chlorine in the payload", () => {
    expect(isChemistryGateSatisfied([
      { key: "free_chlorine",  value: 2.5 },
      { key: "total_chlorine", value: 3.0 },   // extra — dropped
      { key: "ph",             value: 7.4 },
      { key: "alkalinity",     value: 100 },
      { key: "cyanuric_acid",  value: 40 },
    ])).toBe(true);
  });

  it("chemistry bands map no longer classifies total_chlorine", () => {
    expect(CANONICAL_BAND_THRESHOLDS.total_chlorine).toBeUndefined();
    expect(bandForReading("total_chlorine", 3.0)).toBeNull();
    // Sanity — chlorine still bands correctly. Phase P17.1 · Feb-2026
    // — canonical rename: bands module keys on ``chlorine``.
    expect(bandForReading("chlorine", 3.0)).toBe("Average");
  });

  it("water-bodies allow-list drops total_chlorine from pool/other", () => {
    expect(READING_ALLOWLIST.pool.includes("total_chlorine")).toBe(false);
    expect(READING_ALLOWLIST.other.includes("total_chlorine")).toBe(false);
    // Phase P17.1 · Feb-2026 — canonical rename: READING_REQUIRED.pool
    // emits ``chlorine`` (was ``free_chlorine`` under P17).
    expect(READING_REQUIRED.pool).toEqual([
      "chlorine", "ph", "alkalinity", "cyanuric_acid",
    ]);
    expect(READING_LABELS.total_chlorine).toBeUndefined();
  });

  it("multi-body: pool body missing pH is flagged as required", () => {
    const kidsBody = {
      id: "wb-kids",
      type: "pool",
      label: "Kids Pool",
      readings: [
        // Phase P17.1 · Feb-2026 — canonical rename: use ``chlorine``
        // key (was ``free_chlorine`` under P17).
        { key: "chlorine",      value: 2.0 },
        // pH deliberately missing
        { key: "alkalinity",    value: 90 },
        { key: "cyanuric_acid", value: 35 },
      ],
    };
    expect(missingRequiredReadings(kidsBody)).toEqual(["ph"]);
  });
});

describe("Phase CHEM1 · PoolChecklistForm renders no Total Chlorine input", () => {
  it("renders only the Required Four with the red required star", () => {
    const readingFields = [
      { key: "combined_chlorine", name: "Combined Chlorine", unit: "ppm" },
      { key: "free_chlorine",     name: "Free Chlorine",     unit: "ppm" },
      { key: "ph",                name: "pH",                unit: "" },
      { key: "alkalinity",        name: "Total Alkalinity",  unit: "ppm" },
      { key: "cyanuric_acid",     name: "Cyanuric Acid",     unit: "ppm" },
      { key: "calcium_hardness",  name: "Calcium Hardness",  unit: "ppm" },
    ];
    const readings = readingFields.map((f) => ({ ...f, value: null }));
    render(
      <PoolChecklistForm
        jobId="job-1"
        customerId="cust-1"
        locked={false}
        readings={readings}
        readingFields={readingFields}
        checklistItems={[]}
        onChange={() => {}}
        template="pool"
      />
    );
    // No Total Chlorine input rendered anywhere.
    expect(screen.queryByTestId("pool-reading-total_chlorine-input")).toBeNull();
    expect(screen.queryByTestId("pool-reading-total_chlorine-required")).toBeNull();
    // Required Four each carry a red required-star marker.
    // ``PoolChecklistForm`` folds ``alkalinity`` onto
    // ``total_alkalinity`` via ``canonicalReadingKey``, so we
    // assert on the resolved test-id.
    // Phase P17.1 · Feb-2026 — canonical rename: the chlorine test-id
    // resolves to ``chlorine`` (was ``free_chlorine`` under P17).
    const _REQUIRED_TESTID_KEYS = [
      "chlorine",
      "total_alkalinity",
      "ph",
      "cyanuric_acid",
    ];
    for (const k of _REQUIRED_TESTID_KEYS) {
      const star = screen.getByTestId(`pool-reading-${k}-required`);
      expect(star).toBeTruthy();
      expect(star.getAttribute("aria-label")).toBe("required");
    }
    // Optional fields never render the required star.
    expect(screen.queryByTestId("pool-reading-calcium_hardness-required")).toBeNull();
    expect(screen.queryByTestId("pool-reading-combined_chlorine-required")).toBeNull();
  });
});
