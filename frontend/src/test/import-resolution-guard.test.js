// Feb 2026 · Import Resolution Guard
// ==================================
//
// Ships as a follow-up to the ``AdminMigrationsPage.jsx`` invented-
// import compile blocker (``../../lib/api-client`` — pointed at a
// non-existent module). That specifier compiled cleanly under
// vitest (which never bundles the full graph, mocks resolve
// anything) but nuked ``yarn build`` in prod. A broken bundle
// blank-screens the entire app.
//
// This test walks every ``.js`` / ``.jsx`` under ``src/`` and asserts
// that every *local* import specifier (starts with ``.`` or ``@/``)
// resolves to a real file. Bare specifiers (npm packages) are
// skipped — they'd already fail vitest's own module registry.
//
// Zero new dependencies — pure ``node:fs`` + ``node:path`` walk.
// Runs in <500ms across ~1k source files. Deterministic — same
// input → same failure list.
//
// See also: ``eslint.config.js`` — ``eslint-plugin-import`` is
// installed but ``import/no-unresolved`` is NOT configured because
// it requires an ``eslint-import-resolver-alias`` (or similar) dep
// to teach ESLint about the ``@/`` alias. This test covers the
// same guarantee without the extra dep.
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SRC_ROOT = path.resolve(__dirname, "..");

// JS/TS module extensions we can resolve. Order matters — vite/craco
// try ``.js`` first, then ``.jsx``. TS files present in ``src/`` too.
const JS_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"];

// Extensions webpack/craco loads via loaders — considered resolved
// iff the exact file path exists on disk (no ``index`` fallback).
const ASSET_EXTS = new Set([
  ".css", ".scss", ".sass", ".less",
  ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp",
  ".mp3", ".mp4", ".webm", ".ogg", ".wav",
  ".woff", ".woff2", ".ttf", ".eot", ".otf",
  ".json", ".md", ".txt", ".pdf", ".html", ".xml", ".yaml", ".yml",
]);

// Dirs to skip. Widgets/embed are vendored 3P bundles — already
// excluded from ESLint (``eslint.config.js`` lines 96-97).
const EXCLUDE_DIRS = new Set([
  "node_modules", "widgets", "embed", "__mocks__", "coverage",
  "dist", "build", "public",
]);

// The guard test itself — skip so it doesn't fail on ``import.meta.url``
// or any self-reference.
const SELF_BASENAME = "import-resolution-guard.test.js";

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    if (EXCLUDE_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walk(full));
      continue;
    }
    if (entry.name === SELF_BASENAME) continue;
    if (/\.(js|jsx|mjs|cjs|ts|tsx)$/.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

// Strip block comments + line comments to avoid matching commented-
// out imports. Also strip template-literal contents (Radix + tailwind
// snippets sometimes embed "import" as a string).
function stripCommentsAndStrings(src) {
  return src
    // block comments
    .replace(/\/\*[\s\S]*?\*\//g, "")
    // line comments — leading whitespace only so we don't mangle
    // ``foo // note`` where ``foo`` is meaningful (rare in imports).
    .replace(/(^|\s)\/\/[^\n]*/g, "$1")
    // template literals — replace contents with placeholder. Nested
    // ${} interpolations aren't perfect but for import detection
    // it's enough.
    .replace(/`[^`]*`/g, "``");
}

// Regex catalog. Each captures the specifier in group 1.
const SPEC_REGEXES = [
  // ``import Foo from 'x'``, ``import { A } from 'x'``,
  // ``import 'x'`` (side-effect), ``import * as Foo from 'x'``.
  /\bimport\s+(?:[\s\S]+?\s+from\s+)?["']([^"']+)["']/g,
  // ``export * from 'x'``, ``export { A } from 'x'``.
  /\bexport\s+(?:\*|\{[^}]*\})\s+from\s+["']([^"']+)["']/g,
  // ``import('x')`` — dynamic import.
  /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
  // ``require('x')`` — CommonJS.
  /\brequire\s*\(\s*["']([^"']+)["']\s*\)/g,
];

function extractSpecifiers(src) {
  const cleaned = stripCommentsAndStrings(src);
  const specs = new Set();
  for (const re of SPEC_REGEXES) {
    // ``exec`` mutates ``lastIndex`` on the shared regex — re-use is
    // fine within one call, but reset between calls belts and
    // suspenders.
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(cleaned)) !== null) {
      specs.add(m[1]);
    }
  }
  return [...specs];
}

function isLocalSpecifier(spec) {
  return spec.startsWith(".") || spec.startsWith("@/");
}

function resolveSpecifier(fromFile, spec) {
  // Vite/webpack allow query suffixes (``?raw`` for text imports,
  // ``?url`` for asset URLs, ``?worker`` for web workers) and hash
  // fragments. Strip both before touching the filesystem.
  const cleaned = spec.replace(/[?#].*$/, "");
  if (!cleaned) return true; // pure query like ``?worker&inline``
  let base;
  if (cleaned.startsWith("@/")) {
    base = path.join(SRC_ROOT, cleaned.slice(2));
  } else {
    base = path.resolve(path.dirname(fromFile), cleaned);
  }
  const ext = path.extname(base).toLowerCase();
  // Asset with explicit extension — only accept an exact match.
  if (ASSET_EXTS.has(ext)) {
    return fs.existsSync(base);
  }
  // Explicit JS/TS extension — accept exact match.
  if (JS_EXTS.includes(ext)) {
    return fs.existsSync(base);
  }
  // Bare specifier (no extension) — try each JS extension + index.
  const candidates = [];
  for (const e of JS_EXTS) candidates.push(base + e);
  for (const e of JS_EXTS) candidates.push(path.join(base, "index" + e));
  return candidates.some((c) => fs.existsSync(c));
}

describe("import resolution guard", () => {
  it(
    "every local import in src/**/*.{js,jsx,ts,tsx} resolves to a real file",
    () => {
      const files = walk(SRC_ROOT);
      expect(files.length).toBeGreaterThan(100); // Sanity — scan happened.
      const failures = [];
      for (const file of files) {
        let src;
        try {
          src = fs.readFileSync(file, "utf8");
        } catch (_e) {
          continue;
        }
        for (const spec of extractSpecifiers(src)) {
          if (!isLocalSpecifier(spec)) continue;
          if (!resolveSpecifier(file, spec)) {
            failures.push(
              `${path.relative(SRC_ROOT, file)}  →  '${spec}'`,
            );
          }
        }
      }
      // Format failures for readable pytest-style output.
      const msg =
        failures.length === 0
          ? "ok"
          : `Unresolved local imports (${failures.length}):\n  ` +
              failures.join("\n  ");
      expect(msg, msg).toBe("ok");
    },
    { timeout: 5000 },
  );
});
