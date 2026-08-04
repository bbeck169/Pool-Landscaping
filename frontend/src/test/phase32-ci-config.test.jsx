// Phase 32 · Feb-2026 — Locks the minimal CI pipeline shape.
// Source-inspection test: reads .github/workflows/ci.yml as text and asserts
// its key invariants without pulling js-yaml (not a repo dep).

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const CI_PATH = resolve(__dirname, "../../../.github/workflows/ci.yml");
const README_PATH = resolve(__dirname, "../../../.github/workflows/README.md");

describe("Phase 32 · CI pipeline configuration", () => {
  it("exposes .github/workflows/ci.yml", () => {
    expect(existsSync(CI_PATH)).toBe(true);
  });

  it("exposes .github/workflows/README.md documenting the workflow", () => {
    expect(existsSync(README_PATH)).toBe(true);
  });

  const yml = existsSync(CI_PATH) ? readFileSync(CI_PATH, "utf8") : "";

  it("declares three named jobs: backend, frontend-web, mobile", () => {
    // Each job key sits at 2-space indent under `jobs:`.
    expect(yml).toMatch(/^\s{2}backend:\s*$/m);
    expect(yml).toMatch(/^\s{2}frontend-web:\s*$/m);
    expect(yml).toMatch(/^\s{2}mobile:\s*$/m);
  });

  it("runs the backend job with pytest and the excluded markers", () => {
    expect(yml).toMatch(/pytest/);
    // All three legacy markers must be excluded in the same run command.
    expect(yml).toMatch(/not live/);
    expect(yml).toMatch(/not destructive/);
    expect(yml).toMatch(/not legacy_iteration/);
  });

  it("runs the frontend-web job via yarn vitest / yarn test:coverage", () => {
    // Phase 41.4 · Feb-2026 — CI was upgraded from
    // ``yarn vitest run`` to ``yarn test:coverage`` (which fronts
    // vitest with the ``--coverage`` flag + threshold gate). Either
    // form is accepted here to stay compatible with any future rename.
    expect(yml).toMatch(/yarn (vitest run|test:coverage)/);
  });

  it("runs the mobile job via yarn test --ci --forceExit", () => {
    expect(yml).toMatch(/yarn test --ci --forceExit/);
  });

  it("triggers on both pull_request and push to main", () => {
    expect(yml).toMatch(/^on:\s*$/m);
    expect(yml).toMatch(/pull_request/);
    expect(yml).toMatch(/push:/);
    // The `main` branch must be listed under push.branches.
    expect(yml).toMatch(/branches:\s*\n\s*-\s*main/);
  });

  it("declares a concurrency stanza that cancels superseded runs", () => {
    expect(yml).toMatch(/^concurrency:/m);
    expect(yml).toMatch(/group:\s*ci-\$\{\{\s*github\.ref\s*\}\}/);
    expect(yml).toMatch(/cancel-in-progress:\s*true/);
  });

  it("pins Node 20.19 for both Node jobs", () => {
    // Two occurrences: frontend-web and mobile.
    const matches = yml.match(/node-version:\s*"?20\.19"?/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("pins Python 3.11 for the backend job", () => {
    expect(yml).toMatch(/python-version:\s*"?3\.11"?/);
  });

  it("uses actions/cache or setup-node cache for both pip and yarn", () => {
    expect(yml).toMatch(/actions\/cache@/);
    expect(yml).toMatch(/cache:\s*"yarn"/);
    expect(yml).toMatch(/cache-dependency-path:\s*frontend\/yarn\.lock/);
    expect(yml).toMatch(/cache-dependency-path:\s*mobile\/yarn\.lock/);
  });

  it("does NOT include a deploy or publish step (out of scope for Phase 32)", () => {
    // Guardrail — future phases might add these, but not this one.
    expect(yml).not.toMatch(/^\s{2}deploy:\s*$/m);
    expect(yml).not.toMatch(/^\s{2}publish:\s*$/m);
    expect(yml).not.toMatch(/eas build/i);
    expect(yml).not.toMatch(/eas update/i);
    expect(yml).not.toMatch(/expo publish/i);
  });
});
