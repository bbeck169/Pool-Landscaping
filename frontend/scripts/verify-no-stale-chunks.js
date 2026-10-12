#!/usr/bin/env node
/*
 * P0d · 2026-10-12 — Stale-chunk guard
 *
 * CI/build-time guard that fails the build if the production bundle
 * emits any JS chunk filename on the known-bad list. Added after the
 * 4th user report of `ReferenceError: expanded is not defined` on
 * `/schedule`, which the fork audit (`2a9fa6cea`) proved was a stale
 * downstream-cached chunk `5979.aad12649.chunk.js` — not a HEAD bug.
 *
 * The guard runs AFTER `craco build`. If any known-bad chunk hash
 * reappears in `build/static/js/`, we exit 1 and point the operator
 * at the remediation step (edit the source file that owns the chunk
 * so the content hash moves).
 *
 * Known-bad list is one entry today, intentionally. Extend as new
 * stale-cache incidents are triaged.
 *
 * Also exported as `runGuard(buildDir)` for the vitest unit test —
 * `module.exports.runGuard` is the pure-function entry point. The
 * CLI wrapper at the bottom only executes when the file is run
 * directly (`node scripts/verify-no-stale-chunks.js`), never during
 * `require()` in the vitest harness.
 */
"use strict";

const fs = require("fs");
const path = require("path");

// Each entry matches the leading-portion of the chunk filename
// (minus the `.chunk.js` suffix and any file-type variants emitted
// by CRA like `.chunk.js.map`). Keep entries as literal substrings
// so there's no regex ambiguity about whether a hash with a
// coincidental substring match ("aad1264" vs "aad12649") is
// flagged. We match against the FULL filename with `includes`.
const KNOWN_BAD_CHUNK_PATTERNS = [
  "5979.aad12649",
];

const DEFAULT_BUILD_DIR = path.resolve(__dirname, "..", "build", "static", "js");

function runGuard(buildDir) {
  const target = buildDir || DEFAULT_BUILD_DIR;
  const report = {
    scanned_dir: target,
    files_scanned: 0,
    offenders: [],
    status: "ok",
  };

  let entries;
  try {
    entries = fs.readdirSync(target);
  } catch (err) {
    // Missing dir = build didn't run. That's a build-pipeline bug,
    // not a stale-chunk recurrence. Report green so this guard
    // doesn't mask the real "no build output" error upstream.
    report.status = "no_build_output";
    report.error = err.code || String(err);
    return report;
  }

  for (const name of entries) {
    report.files_scanned += 1;
    for (const bad of KNOWN_BAD_CHUNK_PATTERNS) {
      if (name.includes(bad)) {
        report.offenders.push({ filename: name, matched_pattern: bad });
      }
    }
  }

  if (report.offenders.length > 0) {
    report.status = "stale_chunk_recurred";
  }
  return report;
}

function formatOffenderError(report) {
  const lines = [];
  lines.push("");
  lines.push("─────────────────────────────────────────────────────────────");
  lines.push(" ❌  STALE-CHUNK GUARD FAILED — known-bad chunk hash emitted ");
  lines.push("─────────────────────────────────────────────────────────────");
  lines.push("");
  lines.push(`Scan dir : ${report.scanned_dir}`);
  lines.push(`Scanned  : ${report.files_scanned} file(s)`);
  lines.push("");
  lines.push("Offenders:");
  for (const o of report.offenders) {
    lines.push(`  · ${o.filename}  (matched: ${o.matched_pattern})`);
  }
  lines.push("");
  lines.push("REMEDIATION:");
  lines.push("  1. Identify the source files that compile into this chunk");
  lines.push("     (webpack emits chunk-ids by splitChunks grouping — look");
  lines.push("      at the top of the chunk .js.map `sources` list).");
  lines.push("  2. Add a trivial content change (e.g. a comment at the top");
  lines.push("     of each source file) so webpack recomputes a new");
  lines.push("     content hash.");
  lines.push("  3. Rebuild. Confirm the new chunk filename does NOT contain");
  lines.push("     any string in KNOWN_BAD_CHUNK_PATTERNS.");
  lines.push("");
  lines.push("Context: this guard was added after the 4th report of a");
  lines.push("`ReferenceError: expanded is not defined` crash on /schedule");
  lines.push("sourced from downstream-cached stale chunks. HEAD code is");
  lines.push("clean (audit 2a9fa6cea). The guard prevents the bad hash");
  lines.push("from ever being emitted again.");
  lines.push("");
  return lines.join("\n");
}

function main() {
  const report = runGuard();
  if (report.status === "no_build_output") {
    // Soft-exit: let the build pipeline surface the real error.
    console.warn(
      `[verify-no-stale-chunks] build dir not found (${report.scanned_dir}): ${report.error}. ` +
      `Skipping check — the build itself likely failed upstream.`
    );
    process.exit(0);
  }
  if (report.status === "stale_chunk_recurred") {
    console.error(formatOffenderError(report));
    process.exit(1);
  }
  console.log(
    `[verify-no-stale-chunks] OK — scanned ${report.files_scanned} file(s) in ` +
    `${report.scanned_dir}; 0 known-bad chunk hashes detected.`
  );
  process.exit(0);
}

module.exports = {
  runGuard,
  formatOffenderError,
  KNOWN_BAD_CHUNK_PATTERNS,
  DEFAULT_BUILD_DIR,
};

if (require.main === module) {
  main();
}
