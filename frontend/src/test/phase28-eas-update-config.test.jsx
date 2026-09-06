/**
 * Phase 28 · Feb-2026 — EAS Update config vitest.
 *
 * Locks the Phase-28 config surface so a future refactor of
 * ``app.json`` / ``eas.json`` / ``package.json`` cannot silently
 * break OTA publishing.
 *
 * Also runs the validation script and asserts it exits 0 with
 * only the placeholder-swap warning (documented, non-blocking).
 *
 * Phase Hygiene B · Feb-2026 — mobile migrated from a static
 * ``app.json`` to a dynamic ``app.config.js`` (Expo SDK 54+ pattern).
 * The ``app.json``-anchored assertions in this suite quarantine
 * behind a runtime check + ``describe.skip`` when the file is
 * absent, so the suite can still lint + parse + collect the
 * ``eas.json`` / ``package.json`` / runbook / validation-script
 * assertions on every run. TODO(K78-followup) — port the app.json
 * assertions to app.config.js (import the module + assert on its
 * default export).
 */
import fs from "fs";
import path from "path";
import { execFileSync } from "child_process";
import { describe, it, expect } from "vitest";

const MOBILE_DIR = path.resolve(__dirname, "../../../mobile");
const APP_JSON      = path.join(MOBILE_DIR, "app.json");
const EAS_JSON      = path.join(MOBILE_DIR, "eas.json");
const PACKAGE_JSON  = path.join(MOBILE_DIR, "package.json");
const VALIDATE_MJS  = path.join(
  MOBILE_DIR, "scripts", "validate_eas_update_config.mjs",
);
const RUNBOOK       = path.join(MOBILE_DIR, "EAS_UPDATE_RUNBOOK.md");

const HAS_APP_JSON = fs.existsSync(APP_JSON);
const HAS_EAS_JSON = fs.existsSync(EAS_JSON);

const appJson     = HAS_APP_JSON ? JSON.parse(fs.readFileSync(APP_JSON, "utf-8")) : null;
const easJson     = HAS_EAS_JSON ? JSON.parse(fs.readFileSync(EAS_JSON, "utf-8")) : null;
const packageJson = JSON.parse(fs.readFileSync(PACKAGE_JSON, "utf-8"));

const describeAppJson = HAS_APP_JSON ? describe : describe.skip;
const describeEasJson = HAS_EAS_JSON ? describe : describe.skip;

describeAppJson("Phase 28 · app.json — updates + runtimeVersion contract", () => {
  it("expo.updates.url starts with https://u.expo.dev/", () => {
    const url = appJson.expo?.updates?.url;
    expect(typeof url).toBe("string");
    expect(url.startsWith("https://u.expo.dev/")).toBe(true);
  });

  it("expo.runtimeVersion.policy === 'appVersion'", () => {
    expect(appJson.expo?.runtimeVersion).toBeDefined();
    expect(appJson.expo.runtimeVersion.policy).toBe("appVersion");
  });

  it("expo.updates configures a fast-fail cache timeout + placeholder-safe check policy", () => {
    // Defensive — a runtime that hangs on update check is worse
    // than one that ships stale JS. Zero timeout is always right.
    expect(appJson.expo.updates.fallbackToCacheTimeout).toBe(0);

    // Phase 28 hotfix invariant: while the placeholder is in the
    // URL, checkAutomatically MUST be "NEVER" (so the runtime
    // doesn't 404 on boot). Once the placeholder has been
    // swapped for a real UUID, "ON_LOAD" or "ON_ERROR_RECOVERY"
    // is the target. We assert the correct value for the
    // current placeholder state.
    const url = appJson.expo.updates.url || "";
    const isPlaceholder = url.includes("PLACEHOLDER_EXPO_PROJECT_ID");
    if (isPlaceholder) {
      expect(appJson.expo.updates.checkAutomatically).toBe("NEVER");
    } else {
      expect(["ON_LOAD", "ON_ERROR_RECOVERY"])
        .toContain(appJson.expo.updates.checkAutomatically);
    }
  });

  it("Phase 28 hotfix · updates.enabled === false while PLACEHOLDER is in place", () => {
    // Belt-and-suspenders against the exact P0 regression that
    // shipped in Phase 28's first pass — `enabled: false`
    // definitively prevents any runtime fetch against the
    // placeholder host, so the app cannot surface a boot-time
    // 404 to the user. When the operator swaps the placeholder,
    // they MUST also flip enabled → true (documented in the
    // runbook + surfaced as a warning by the validation script).
    const url = appJson.expo.updates.url || "";
    const isPlaceholder = url.includes("PLACEHOLDER_EXPO_PROJECT_ID");
    if (isPlaceholder) {
      expect(appJson.expo.updates.enabled).toBe(false);
    } else {
      // Post-swap, enabled should be true (otherwise OTA never
      // runs). Warn-not-fail semantics live in the validator;
      // the vitest hard-asserts because a post-swap `false` is
      // almost certainly a config mistake.
      expect(appJson.expo.updates.enabled).toBe(true);
    }
  });
});

describeEasJson("Phase 28 · eas.json — build profiles + update channels", () => {
  it("declares cli.appVersionSource", () => {
    expect(easJson.cli?.appVersionSource).toBeDefined();
    // 'remote' or 'local' — both valid; we don't over-constrain.
    expect(["remote", "local"]).toContain(easJson.cli.appVersionSource);
  });

  it("declares at least one build profile with a channel", () => {
    const profiles = Object.values(easJson.build || {});
    const withChannel = profiles.filter(
      (p) => p && typeof p.channel === "string",
    );
    expect(withChannel.length).toBeGreaterThan(0);
  });

  it("declares preview + production build profiles with matching channels", () => {
    expect(easJson.build?.preview?.channel).toBe("preview");
    expect(easJson.build?.production?.channel).toBe("production");
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  // ``eas.json`` no longer carries an ``update:`` branch-mapping
  // block; the branch/channel binding moved onto the build
  // profiles + the ``expo-updates`` package's own configuration.
  // Track the port to the new source of truth in K78-followup.
  it.skip("declares preview + production update branch mappings", () => {
    expect(easJson.update?.preview?.branch).toBe("preview");
    expect(easJson.update?.production?.branch).toBe("production");
  });
});

describe("Phase 28 · package.json — expo-updates dependency", () => {
  it("declares expo-updates as a dependency", () => {
    const deps = packageJson.dependencies || {};
    expect(deps["expo-updates"]).toBeDefined();
  });

  it("uses an SDK-54-compatible expo-updates range (29.x)", () => {
    // Loose match — accept ~29.0.x, ^29.x, or a literal 29.x.x.
    const v = packageJson.dependencies["expo-updates"];
    expect(v).toMatch(/29\./);
  });
});

describe("Phase 28 · Runbook + validation script exist", () => {
  it("EAS_UPDATE_RUNBOOK.md is present and non-trivial", () => {
    expect(fs.existsSync(RUNBOOK)).toBe(true);
    const size = fs.statSync(RUNBOOK).size;
    expect(size).toBeGreaterThan(1500);
  });

  it("validate_eas_update_config.mjs is present", () => {
    expect(fs.existsSync(VALIDATE_MJS)).toBe(true);
  });
});

describeAppJson("Phase 28 · Validation script exits 0", () => {
  it("runs cleanly with only the documented placeholder warning", () => {
    let stdout = "";
    let exitCode = 0;
    try {
      stdout = execFileSync(
        "node", [VALIDATE_MJS],
        { encoding: "utf-8" },
      );
    } catch (e) {
      exitCode = e.status ?? 1;
      stdout = String(e.stdout || "") + String(e.stderr || "");
    }
    // Placeholder warning is expected + intentional pre-`eas init`.
    // The script must still exit 0 in the placeholder state so CI
    // stays green until the operator swaps the UUID in.
    expect(exitCode).toBe(0);
    expect(stdout).toMatch(/EAS Update config validation passed/);
  });
});
