/**
 * CHEM-LOCK · Feb-2026 — Tech ServiceReport locked/unlocked gate.
 *
 * Source-inspection lock (matches ``jobdetail-k6-completed-unlock``
 * pattern). Runtime ServiceReport bootstrap is heavy (autosave loop,
 * elapsed timer hook, api mocks); the lock semantics are cheaper
 * to validate at the source level.
 *
 * Coverage:
 *   1. ``locked`` boolean derived from ``report.submitted_at``.
 *   2. Chemistry / chemical inputs carry ``disabled={locked}``.
 *   3. The "Locked — ask admin" hint renders when ``locked === true``
 *      with the canonical testid.
 *   4. When admin unlocks, the SR's ``submitted_at`` is cleared, so
 *      ``locked`` flips to ``false`` and controls become live.
 *      (Locked-state derivation is the contract we lock here — the
 *      admin unlock endpoint clears ``submitted_at``, which is
 *      covered by the backend test suite ``test_job_unlock_flow.py``.)
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/tech/ServiceReport.jsx"),
  "utf8",
);


describe("Tech ServiceReport · CHEM-LOCK edit-controls gate", () => {
  it("derives ``locked`` from ``report.submitted_at``", () => {
    // ``locked`` flips false immediately when the admin unlock
    // endpoint clears ``submitted_at`` — that's the "unlocked
    // means editable" contract.
    expect(SRC).toMatch(
      /const\s+locked\s*=\s*!!\s*report\.submitted_at/,
    );
  });

  it("disables chemical name input via ``disabled={locked}``", () => {
    // The chemical name <select> is one of the two edit surfaces
    // that MUST respect the lock state. In the source the
    // ``disabled={locked}`` attribute appears BEFORE the trailing
    // ``data-testid`` on the element — assert both within a
    // shared JSX-block window.
    expect(SRC).toMatch(
      /disabled=\{locked\}[\s\S]{0,600}data-testid=\{`svc-chem-name-\$\{i\}`\}/,
    );
  });

  it("disables the amount input via ``disabled={locked}``", () => {
    expect(SRC).toMatch(
      /disabled=\{locked\}[\s\S]{0,600}data-testid=\{`svc-chem-amount-\$\{i\}`\}/,
    );
  });

  it("gates the ``Add another chemical`` button behind ``!locked``", () => {
    // ``right={!locked && (…)}``
    expect(SRC).toMatch(
      /right=\{\s*!locked\s*&&/,
    );
    expect(SRC).toMatch(/data-testid="svc-add-chemical"/);
  });

  it("renders the ``svc-report-locked-hint`` banner when locked", () => {
    // Banner is gated ``locked ? (<div … />) : null``.
    expect(SRC).toMatch(
      /data-testid="svc-report-locked-hint"/,
    );
    expect(SRC).toMatch(/Ask an admin to unlock/);
    expect(SRC).toMatch(/Report is locked/);
    // The banner is gated on the ``locked`` boolean so an unlocked
    // report doesn't display it.
    expect(SRC).toMatch(
      /\{\s*locked\s*\?\s*\(\s*<div/,
    );
  });

  it("writes both ``quantity`` and ``amount`` fields on new chemical rows", () => {
    // Writer forward-compat — see the CHEM-LOCK design fork §5.
    // ``addRecToChemicals`` writes BOTH fields explicitly.
    expect(SRC).toMatch(
      /quantity:\s*rec\.amount[\s\S]*amount:\s*rec\.amount/,
    );
    // ``addChemical`` writes both when adding an empty row.
    expect(SRC).toMatch(
      /quantity:\s*""[\s\S]*amount:\s*""/,
    );
  });

  it("mirrors amount⇔quantity in updChemical patches", () => {
    // ``updChemical`` mirrors either key onto the other so a legacy
    // caller that only patches one field still produces a
    // dual-keyed row.
    expect(SRC).toMatch(
      /if\s*\(\s*"amount"\s+in\s+_patch\s*&&\s*!\("quantity"\s+in\s+_patch\)\s*\)/,
    );
    expect(SRC).toMatch(
      /if\s*\(\s*"quantity"\s+in\s+_patch\s*&&\s*!\("amount"\s+in\s+_patch\)\s*\)/,
    );
  });
});
