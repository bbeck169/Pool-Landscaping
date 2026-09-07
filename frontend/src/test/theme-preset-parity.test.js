/**
 * Phase I1.5.c · Feb-2026 — Backend / frontend preset registry parity.
 *
 * Reads the backend preset registry directly from
 * ``services/theme/presets.py`` (via ``fs.readFileSync`` + a
 * lightweight JSON extract) and diffs it against the client-side
 * mirror in ``src/theme/presets.js``. Any structural drift —
 * missing key, extra key, different slot topology, different hex —
 * fails the suite with a diff-friendly message.
 *
 * Why not fetch ``GET /api/theme-presets``? The parity check must
 * run in the same in-process vitest sandbox as the rest of the FE
 * suite; hitting an external backend during unit tests would be a
 * regression against the Hygiene B "no network in vitest" rule.
 * The backend pytest suite already locks the API's payload shape.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

import { CLIENT_PRESETS } from "@/theme/presets";


// ── Load the backend registry via a Python subprocess ──────────
// The backend registry is expressed in Python. To get a
// structurally comparable JSON view without hand-parsing the
// source file (which would miss ``_p`` parameter defaults for
// ``rail_bg``, ``tile_bg``, etc.), shell out to a one-liner that
// imports the registry and prints JSON. Fails hard if the backend
// venv isn't set up — that's the right signal.
const BACKEND_DIR = path.resolve(
  __dirname, "..", "..", "..", "backend"
);


let BACKEND_PRESETS;
try {
  const out = execSync(
    `python -c "import json, sys; sys.path.insert(0, '.'); ` +
    `from services.theme.presets import PRESETS; ` +
    `print(json.dumps(PRESETS))"`,
    { cwd: BACKEND_DIR, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  BACKEND_PRESETS = JSON.parse(out);
} catch (e) {
  // Surface a clean error at describe-time instead of leaving
  // BACKEND_PRESETS as ``undefined`` and confusing every downstream
  // assertion.
  throw new Error(
    "theme-preset-parity: unable to load backend registry via " +
    `python subprocess (${e.message}). Ensure the backend venv is ` +
    "available on PATH so vitest can shell out."
  );
}


// ── Parity contract ─────────────────────────────────────────────
describe("Phase I1.5.c · theme preset parity (backend ↔ client)", () => {
  it("client mirror lists exactly the backend's preset keys", () => {
    const backendKeys = Object.keys(BACKEND_PRESETS).sort();
    const clientKeys = Object.keys(CLIENT_PRESETS).sort();
    expect(clientKeys).toEqual(backendKeys);
  });

  it("client mirror declares exactly 31 presets", () => {
    expect(Object.keys(CLIENT_PRESETS)).toHaveLength(31);
  });

  it("every client preset structurally equals the backend preset", () => {
    // Deep-equal per-preset so the failure message names the
    // offending key + slot on drift.
    for (const key of Object.keys(BACKEND_PRESETS)) {
      expect(CLIENT_PRESETS[key], `preset '${key}' drift`)
        .toEqual(BACKEND_PRESETS[key]);
    }
  });
});
