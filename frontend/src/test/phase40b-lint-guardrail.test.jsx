// Phase 40b hotfix guardrail (Feb 2026) — locks in the ESLint rule that
// would have caught the `@/lib/api` regression at lint stage.
//
// Source-inspection test: reads `frontend/eslint.config.js` as text and
// asserts the `no-restricted-imports` rule + its `@/lib/*` pattern are
// present. Also verifies the CI frontend-web job wires up `yarn eslint`.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const CONFIG_PATH = resolve(__dirname, "../../eslint.config.js");
const CI_PATH = resolve(__dirname, "../../../.github/workflows/ci.yml");

describe("Phase 40b · Lint guardrail (no-restricted-imports for @/lib/*)", () => {
  it("exposes frontend/eslint.config.js at the workspace root", () => {
    expect(existsSync(CONFIG_PATH)).toBe(true);
  });

  const cfg = existsSync(CONFIG_PATH) ? readFileSync(CONFIG_PATH, "utf8") : "";

  it("declares the no-restricted-imports rule as an ESLint error", () => {
    expect(cfg).toMatch(/"no-restricted-imports":\s*\[\s*"error"/);
  });

  it("targets the `@/lib/*` group in the restricted-imports pattern", () => {
    expect(cfg).toMatch(/"@\/lib\/\*"/);
  });

  it("allow-lists the three real @/lib modules via negation", () => {
    // These three actually exist under src/lib/ and must NOT be flagged.
    expect(cfg).toMatch(/"!@\/lib\/utils"/);
    expect(cfg).toMatch(/"!@\/lib\/stripeConfig"/);
    expect(cfg).toMatch(/"!@\/lib\/checklistType"/);
  });

  it("carries a message pointing users to the correct alias (`@/api`)", () => {
    // Error message must mention @/api so devs know the canonical fix.
    expect(cfg).toMatch(/@\/api/);
    // And reference the CHANGELOG entry for context.
    expect(cfg).toMatch(/Phase 40b hotfix/i);
  });

  it("scopes the rule to src/**/*.{js,jsx} only (no backend / mobile bleed)", () => {
    expect(cfg).toMatch(/src\/\*\*\/\*\.\{js,jsx\}/);
  });

  it("wires the ESLint guardrail into the CI frontend-web job", () => {
    // The Phase 32 CI file lives in .github/workflows/ci.yml.
    expect(existsSync(CI_PATH)).toBe(true);
    const yml = readFileSync(CI_PATH, "utf8");
    // Step name mentions the guardrail so future readers understand why.
    expect(yml).toMatch(/Run ESLint.*guardrail/);
    // Phase 41.3 · Feb-2026 — accept either the old ``yarn eslint src``
    // or the new ``yarn lint`` (which fronts eslint with
    // ``--max-warnings=0``).
    expect(yml).toMatch(/yarn (lint|eslint src)/);
  });
});
