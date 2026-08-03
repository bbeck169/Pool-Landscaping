#!/usr/bin/env node
/**
 * Phase 28 · Feb-2026 — offline EAS Update config sanity check.
 *
 * Reads /app/mobile/{app.json, eas.json, package.json} and asserts
 * that everything required for a first ``eas update --branch …``
 * call is in place. Deliberately makes ZERO network calls — this
 * is a pure config validator that can be wired into CI or run
 * pre-flight from the runbook.
 *
 * Exit codes:
 *   0 → all green.
 *   1 → one or more checks failed. Human-readable diagnostics
 *       print to stderr.
 *
 * Usage:
 *   node mobile/scripts/validate_eas_update_config.mjs
 */
import fs from "node:fs";
import path from "node:path";

const MOBILE_DIR = path.resolve(
  path.dirname(new URL(import.meta.url).pathname), "..",
);

const APP_JSON      = path.join(MOBILE_DIR, "app.json");
const EAS_JSON      = path.join(MOBILE_DIR, "eas.json");
const PACKAGE_JSON  = path.join(MOBILE_DIR, "package.json");

const errors = [];
const warnings = [];

/** Read + parse a JSON file. Push a fatal error on any failure. */
function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (e) {
    errors.push(`Cannot read ${file}: ${e.message}`);
    return null;
  }
}

const appJson     = readJson(APP_JSON);
const easJson     = readJson(EAS_JSON);
const packageJson = readJson(PACKAGE_JSON);

// ── app.json checks ───────────────────────────────────────────
if (appJson) {
  const expo = appJson.expo || {};
  const updates = expo.updates || {};
  const runtimeVersion = expo.runtimeVersion;

  if (typeof updates.url !== "string" || updates.url.length === 0) {
    errors.push(
      "app.json → expo.updates.url is missing. Expected " +
      "'https://u.expo.dev/<PROJECT_ID>'.",
    );
  } else if (!updates.url.startsWith("https://u.expo.dev/")) {
    errors.push(
      `app.json → expo.updates.url does not start with ` +
      `'https://u.expo.dev/'. Got: ${updates.url}`,
    );
  } else if (updates.url.includes("PLACEHOLDER_EXPO_PROJECT_ID")) {
    // Phase 28 · Feb-2026 hotfix — while the placeholder is in
    // the URL, ``expo-updates`` MUST be inert at runtime.
    // Otherwise the app hits the placeholder host on boot and
    // surfaces an uncaught 404 to the user (the exact regression
    // that shipped in Phase 28's first pass). We enforce a hard
    // invariant here: placeholder present ⇔ enabled:false AND
    // checkAutomatically:"NEVER".
    warnings.push(
      "app.json → expo.updates.url still contains " +
      "PLACEHOLDER_EXPO_PROJECT_ID. Swap for the real project " +
      "UUID (from `eas init`) before publishing. See §1d of " +
      "EAS_UPDATE_RUNBOOK.md.",
    );
    if (updates.enabled !== false) {
      errors.push(
        "app.json → expo.updates.enabled MUST be `false` while " +
        "PLACEHOLDER_EXPO_PROJECT_ID is in the URL. Otherwise " +
        "the runtime fetches from a non-existent host on boot " +
        "and surfaces a 404 to the user. Set " +
        "`\"enabled\": false` OR swap the placeholder for a " +
        "real project UUID first.",
      );
    }
    if (updates.checkAutomatically !== "NEVER") {
      errors.push(
        "app.json → expo.updates.checkAutomatically MUST be " +
        "\"NEVER\" while PLACEHOLDER_EXPO_PROJECT_ID is in the " +
        "URL. Got: " +
        JSON.stringify(updates.checkAutomatically) +
        ". Set `\"checkAutomatically\": \"NEVER\"` OR swap " +
        "the placeholder for a real project UUID first.",
      );
    }
  } else {
    // URL contains a real (non-placeholder) UUID. The runtime
    // should be active — warn (not fail) if enabled/check are
    // still in the disabled hotfix state, so the operator
    // remembers to flip them after the swap.
    if (updates.enabled === false) {
      warnings.push(
        "app.json → expo.updates.enabled is `false` even though " +
        "the placeholder has been swapped. Flip to `true` to " +
        "actually consume OTA updates.",
      );
    }
    if (updates.checkAutomatically === "NEVER") {
      warnings.push(
        "app.json → expo.updates.checkAutomatically is \"NEVER\" " +
        "even though the placeholder has been swapped. Flip to " +
        "\"ON_LOAD\" (or \"ON_ERROR_RECOVERY\") to enable " +
        "update checks on foreground.",
      );
    }
  }

  if (!runtimeVersion) {
    errors.push(
      "app.json → expo.runtimeVersion is missing. Expected " +
      "{ policy: 'appVersion' }.",
    );
  } else if (typeof runtimeVersion === "string") {
    // A literal string (e.g. "1.0.0") is technically valid for
    // EAS but breaks the "bump-version-to-force-rebuild" flow
    // this project relies on. Fail loudly.
    errors.push(
      "app.json → expo.runtimeVersion is a literal string. " +
      "Phase 28 requires { policy: 'appVersion' } so JS-only " +
      "OTA updates auto-scope to the current expo.version.",
    );
  } else if (runtimeVersion.policy !== "appVersion") {
    errors.push(
      "app.json → expo.runtimeVersion.policy is " +
      `'${runtimeVersion.policy}', expected 'appVersion'.`,
    );
  }
}

// ── eas.json checks ───────────────────────────────────────────
if (easJson) {
  const cli = easJson.cli || {};
  if (!cli.appVersionSource) {
    errors.push(
      "eas.json → cli.appVersionSource is missing. Expected " +
      "'remote' (EAS-managed) or 'local'.",
    );
  }

  const buildProfiles = easJson.build || {};
  const declaredChannels = new Set();
  for (const [name, profile] of Object.entries(buildProfiles)) {
    if (profile && typeof profile.channel === "string") {
      declaredChannels.add(profile.channel);
    }
  }
  if (declaredChannels.size === 0) {
    errors.push(
      "eas.json → no build profile declares a `channel`. " +
      "Add channel: 'preview' / 'production' at minimum so the " +
      "store binary knows which update branch to consume.",
    );
  }

  // Sanity — the `update` block should mirror the channels so
  // `eas update --branch preview` reaches installs of the
  // 'preview' build profile.
  const updateBranches = new Set(
    Object.values(easJson.update || {})
      .map((u) => (u && typeof u.branch === "string") ? u.branch : null)
      .filter(Boolean),
  );
  if (updateBranches.size === 0) {
    warnings.push(
      "eas.json → no `update.<profile>.branch` mapping declared. " +
      "`eas update --branch <name>` still works, but the " +
      "profile→branch aliases are missing.",
    );
  }
}

// ── package.json checks ───────────────────────────────────────
if (packageJson) {
  const deps = packageJson.dependencies || {};
  if (!deps["expo-updates"]) {
    errors.push(
      "package.json → dependencies['expo-updates'] is missing. " +
      "Run `npx expo install expo-updates` in /app/mobile.",
    );
  }
}

// ── Report ────────────────────────────────────────────────────
if (warnings.length > 0) {
  for (const w of warnings) {
    process.stderr.write(`⚠  ${w}\n`);
  }
}
if (errors.length > 0) {
  process.stderr.write(`\n✗ EAS Update config validation FAILED with ${errors.length} error(s):\n\n`);
  for (const e of errors) {
    process.stderr.write(`  · ${e}\n`);
  }
  process.stderr.write("\nSee /app/mobile/EAS_UPDATE_RUNBOOK.md for guidance.\n");
  process.exit(1);
}

process.stdout.write("✓ EAS Update config validation passed.\n");
if (warnings.length > 0) {
  process.stdout.write(
    `  (${warnings.length} warning(s) — non-blocking. Address before first \`eas update\` call.)\n`,
  );
}
process.exit(0);
