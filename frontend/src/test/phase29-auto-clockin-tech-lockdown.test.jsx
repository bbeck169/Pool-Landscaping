/**
 * Phase 29 · Feb-2026 — Auto Clock-In tech lockdown vitest.
 *
 * Locks the enforcement contract at three surfaces:
 *
 *   1. Mobile settings screen (`mobile/app/(app)/settings/auto-clockin.tsx`)
 *      - reads role from auth store
 *      - <Switch> gets `disabled={true}` + `value={true}` for techs
 *      - enforcement copy ("Enforced by your organization") renders
 *   2. Mobile background hook (`mobile/src/background/autoClockin.ts`)
 *      - `isAutoClockinEnabled` short-circuits `return true` for
 *        `role === "technician"` regardless of stored value
 *   3. Web mirror — none. `frontend/src/pages/ops/OpsHub.jsx` has an
 *      admin-only per-tech toggle on the Team roster; it is NOT a
 *      self-service surface (a tech viewing their own row already
 *      lacks the `editable` permission). Deliberately skipped per
 *      the Phase 29 brief.
 *
 * Backend enforcement is asserted separately in
 * `backend/tests/test_phase29_auto_clockin_tech_lockdown.py`.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const SETTINGS_SRC = fs.readFileSync(
  path.resolve(
    __dirname, "../../../mobile/app/(app)/settings/auto-clockin.tsx",
  ),
  "utf-8",
);
const HOOK_SRC = fs.readFileSync(
  path.resolve(__dirname, "../../../mobile/src/background/autoClockin.ts"),
  "utf-8",
);

describe("Phase 29 · Mobile settings screen — tech lockdown", () => {
  it("reads user role from the auth store", () => {
    // `useAuth()` from `@/src/auth` is the canonical role source
    // across the mobile codebase.
    expect(SETTINGS_SRC).toMatch(
      /import\s*\{[^}]*useAuth[^}]*\}\s*from\s*["']@\/src\/auth["']/,
    );
    expect(SETTINGS_SRC).toMatch(/const\s+\{\s*user\s*\}\s*=\s*useAuth\(\)/);
    // The screen must compute a tech-role flag off the auth user
    // to drive the enforcement.
    expect(SETTINGS_SRC).toMatch(/role\s*===\s*["']technician["']/);
  });

  it("<Switch> receives disabled={true} AND value={true} — no flip possible", () => {
    // Extract the label-row <Switch> block.
    const switchBlock = SETTINGS_SRC.match(
      /<Switch[\s\S]*?testID=["']auto-clockin-toggle["'][\s\S]*?\/>/,
    );
    expect(switchBlock).not.toBeNull();
    // Both props must be present with their literal true value.
    expect(switchBlock[0]).toMatch(/value=\{true\}/);
    expect(switchBlock[0]).toMatch(/disabled=\{true\}/);
    // And it MUST NOT re-render the pre-Phase-29 dynamic bindings
    // (`value={enabled}` / `disabled={busy}`).
    expect(switchBlock[0]).not.toMatch(/value=\{enabled\}/);
    expect(switchBlock[0]).not.toMatch(/disabled=\{busy\}/);
  });

  it("locked-state subtext renders the enforcement copy", () => {
    // Exact copy per the Phase 29 brief. Split match so
    // whitespace / line-wrap in the source (the subtext is
    // wrapped onto two lines inside the JSX literal) doesn't
    // break the assertion.
    expect(SETTINGS_SRC).toMatch(/Enforced by your organization/);
    expect(SETTINGS_SRC).toMatch(/Contact your\s+manager to change this setting/);
    // Testid must exist so the QA suite can select the copy.
    expect(SETTINGS_SRC).toMatch(
      /testID=["']auto-clockin-tech-locked-subtext["']/,
    );
  });

  it("onToggle short-circuits when isTech (defence in depth)", () => {
    // The onToggle handler MUST bail before touching storage or
    // the background hook so no code path (deep link, race, etc.)
    // can flip the flag for a tech.
    expect(SETTINGS_SRC).toMatch(
      /const\s+onToggle\s*=[\s\S]*?if\s*\(\s*isTech\s*\)\s*return/,
    );
  });

  it("mounts a heal-storage side-effect for techs", () => {
    // A tech opening the screen should silently overwrite the
    // storage key to ``true`` (via ``setAutoClockinEnabled(true,
    // "technician")``) so any legacy ``false`` value from a
    // pre-Phase-29 debug build gets healed.
    expect(SETTINGS_SRC).toMatch(
      /setAutoClockinEnabled\(\s*true\s*,\s*["']technician["']\s*\)/,
    );
  });

  it("non-tech role still sees the pre-existing gate (behaviour unchanged)", () => {
    // The screen must still render the "available to technicians"
    // gate for non-tech roles — Phase 29 only tightens the tech
    // branch.
    expect(SETTINGS_SRC).toMatch(/if\s*\(\s*!isTech\s*\)/);
    expect(SETTINGS_SRC).toMatch(/auto-clockin-role-gate/);
  });
});

describe("Phase 29 · Background hook — getter short-circuit", () => {
  it("isAutoClockinEnabled returns true immediately when role === 'technician'", () => {
    // Extract the exported function body.
    const fnBody = HOOK_SRC.match(
      /export\s+async\s+function\s+isAutoClockinEnabled[\s\S]*?\n\}/,
    );
    expect(fnBody).not.toBeNull();
    // The short-circuit MUST appear BEFORE the storage reads —
    // otherwise a bad storage value could still leak through on
    // some code path. We assert the return-true line precedes
    // the ``storage.getItem`` calls in source order.
    const body = fnBody[0];
    const returnTrueIdx = body.search(
      /if\s*\(\s*role\s*===\s*["']technician["']\s*\)\s*return\s+true/,
    );
    const storageIdx = body.search(/storage\.getItem/);
    expect(returnTrueIdx).toBeGreaterThan(-1);
    expect(storageIdx).toBeGreaterThan(-1);
    expect(returnTrueIdx).toBeLessThan(storageIdx);
  });

  it("setAutoClockinEnabled coerces to true when role === 'technician'", () => {
    // Second layer of defence — even if some caller passes
    // ``false``, the setter itself refuses to persist it for
    // tech-role callers.
    const fnBody = HOOK_SRC.match(
      /export\s+async\s+function\s+setAutoClockinEnabled[\s\S]*?\n\}/,
    );
    expect(fnBody).not.toBeNull();
    expect(fnBody[0]).toMatch(
      /role\s*===\s*["']technician["']\s*\?\s*true\s*:\s*enabled/,
    );
  });
});

describe("Phase 29 · Web mirror — deliberately none", () => {
  it("web OpsHub Team toggle is admin-only, not a tech self-service surface", () => {
    // Documentation-only guard. The web toggle is on
    // ``frontend/src/pages/ops/OpsHub.jsx::TechAutoClockinToggle``
    // and is gated by an ``editable`` prop that is only true for
    // admin/super_admin. A technician viewing the Team page
    // (which they cannot navigate to in the first place) still
    // sees the row but the toggle is inert. No Phase 29 changes
    // needed on the web surface.
    const webSrc = fs.readFileSync(
      path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
      "utf-8",
    );
    expect(webSrc).toMatch(/TechAutoClockinToggle/);
    expect(webSrc).toMatch(/editable/);
  });
});
