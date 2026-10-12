// P0d · 2026-10-12 — Unit test for the stale-chunk guard.
//
// Covers both branches of ``runGuard``:
//   · clean build dir  → status "ok", exit 0
//   · build dir has a known-bad filename → status "stale_chunk_recurred",
//     offender captured with the matched pattern
//   · missing build dir → status "no_build_output" (soft-pass so the
//     real build-pipeline error surfaces upstream)
//
// Uses a scratch tmpdir to simulate the dist layout — no dependency
// on the live ``build/static/js/`` output.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";

// eslint-disable-next-line @typescript-eslint/no-var-requires
const guard = require("../../scripts/verify-no-stale-chunks.js");

describe("verify-no-stale-chunks guard", () => {
  let tmp;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "stale-chunk-guard-"));
  });
  afterEach(() => {
    try {
      fs.rmSync(tmp, { recursive: true, force: true });
    } catch (_err) {
      /* best effort */
    }
  });

  it("reports status=ok on a clean build directory", () => {
    fs.writeFileSync(path.join(tmp, "main.aaaaaaaa.chunk.js"), "// ok");
    fs.writeFileSync(path.join(tmp, "5979.deadbeef.chunk.js"), "// ok");
    fs.writeFileSync(path.join(tmp, "runtime.11112222.js"), "// ok");

    const report = guard.runGuard(tmp);
    expect(report.status).toBe("ok");
    expect(report.offenders).toEqual([]);
    expect(report.files_scanned).toBe(3);
  });

  it("flags the known-bad 5979.aad12649 chunk filename", () => {
    fs.writeFileSync(
      path.join(tmp, "5979.aad12649.chunk.js"),
      "// stale cached chunk",
    );
    fs.writeFileSync(path.join(tmp, "main.aaaaaaaa.chunk.js"), "// ok");

    const report = guard.runGuard(tmp);
    expect(report.status).toBe("stale_chunk_recurred");
    expect(report.offenders).toHaveLength(1);
    expect(report.offenders[0]).toMatchObject({
      filename: "5979.aad12649.chunk.js",
      matched_pattern: "5979.aad12649",
    });
  });

  it("also flags the .map sibling of the bad chunk (same content hash)", () => {
    fs.writeFileSync(
      path.join(tmp, "5979.aad12649.chunk.js.map"),
      "{}",
    );

    const report = guard.runGuard(tmp);
    expect(report.status).toBe("stale_chunk_recurred");
    expect(report.offenders).toHaveLength(1);
    expect(report.offenders[0].filename).toBe(
      "5979.aad12649.chunk.js.map",
    );
  });

  it("returns no_build_output when the build dir is missing", () => {
    const missing = path.join(tmp, "does-not-exist");
    const report = guard.runGuard(missing);
    expect(report.status).toBe("no_build_output");
    expect(report.error).toBeDefined();
  });

  it("formatOffenderError produces an actionable message", () => {
    const report = {
      scanned_dir: "/x/build/static/js",
      files_scanned: 42,
      offenders: [
        { filename: "5979.aad12649.chunk.js", matched_pattern: "5979.aad12649" },
      ],
      status: "stale_chunk_recurred",
    };
    const msg = guard.formatOffenderError(report);
    expect(msg).toContain("STALE-CHUNK GUARD FAILED");
    expect(msg).toContain("5979.aad12649.chunk.js");
    expect(msg).toContain("REMEDIATION");
    expect(msg).toContain("content hash");
  });

  it("exports a non-empty KNOWN_BAD_CHUNK_PATTERNS list including the historical offender", () => {
    expect(guard.KNOWN_BAD_CHUNK_PATTERNS).toContain("5979.aad12649");
    expect(guard.KNOWN_BAD_CHUNK_PATTERNS.length).toBeGreaterThan(0);
  });
});
