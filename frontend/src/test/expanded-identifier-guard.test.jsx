/**
 * Feb-2026 · Defensive sweep · `/schedule` ``expanded is not
 * defined`` regression guard.
 *
 * Background:  a persistent production ``ReferenceError:
 * expanded is not defined`` was reported on ``/schedule`` from a
 * stale CDN chunk (``5979.aad12649.chunk.js``).  Multiple
 * historical fixes concluded HEAD was clean and the crash was a
 * downstream cache artefact.  This test is the Feb-2026
 * defensive guard — it fails CI the moment anyone commits a bare
 * ``expanded`` identifier reference in a file that does NOT
 * declare one (useState tuple, destructured prop, const / let /
 * var, or function parameter).
 *
 * Design:
 *   1. Walk every ``frontend/src/**``*.{js,jsx,ts,tsx}``.
 *   2. Strip strings + line / block comments + template literal
 *      content (preserving ``${...}`` expression bodies so a bare
 *      ``expanded`` inside a template interpolation DOES get
 *      flagged).
 *   3. Match bare-word ``expanded`` with word boundaries + a
 *      lookbehind that rejects ``-`` so JSX attribute names like
 *      ``aria-expanded`` / ``data-expanded`` DO NOT match.
 *   4. Match every ``expanded`` DECLARATION pattern across the
 *      file: useState tuple, destructure assignment, const / let /
 *      var, function parameter, arrow-destructure parameter.
 *   5. For each file: if there is at least one bare READ and
 *      zero DECLARATIONS → that file is an orphan — fail.
 *
 * Allowlist:
 *   None.  Every orphan read is a crash risk; file-level
 *   whitelisting defeats the purpose of this guard.  If a new
 *   file genuinely needs ``expanded`` referenced from a module-
 *   level import, declare it as ``import { expanded } from ...``
 *   or rename the local reference.
 *
 * Scope:
 *   Scope matches the production ``frontend/src`` tree only.
 *   ``/app/mobile`` lives on the Expo specialist's shift and is
 *   covered by its own guards.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


const SRC_ROOT = path.resolve(__dirname, "..");


function walk(dir) {
  const out = [];
  const stack = [dir];
  while (stack.length) {
    const cur = stack.pop();
    for (const name of fs.readdirSync(cur)) {
      const full = path.join(cur, name);
      const st = fs.statSync(full);
      if (st.isDirectory()) stack.push(full);
      else if (/\.(jsx?|tsx?)$/.test(name)) out.push(full);
    }
  }
  return out;
}


function stripStringsAndComments(src) {
  // Preserve newlines so line counts stay aligned on failures.
  const out = [];
  let i = 0;
  let inBlock = false;
  while (i < src.length) {
    if (inBlock) {
      if (src.slice(i, i + 2) === "*/") {
        inBlock = false;
        i += 2;
        continue;
      }
      if (src[i] === "\n") out.push("\n");
      i += 1;
      continue;
    }
    if (src.slice(i, i + 2) === "/*") {
      inBlock = true;
      i += 2;
      continue;
    }
    if (src.slice(i, i + 2) === "//") {
      const nl = src.indexOf("\n", i);
      if (nl >= 0) {
        out.push("\n");
        i = nl + 1;
      } else {
        i = src.length;
      }
      continue;
    }
    const ch = src[i];
    if (ch === '"' || ch === "'") {
      const q = ch;
      out.push(" ");
      i += 1;
      while (i < src.length && src[i] !== q) {
        if (src[i] === "\\") { i += 2; continue; }
        if (src[i] === "\n") out.push("\n");
        i += 1;
      }
      if (i < src.length) i += 1;
      continue;
    }
    if (ch === "`") {
      // Template literal — preserve ${...} expression bodies so a
      // bare `expanded` inside interpolation IS flagged, but
      // elide the surrounding plain-text segments.
      out.push(" ");
      i += 1;
      while (i < src.length && src[i] !== "`") {
        if (src[i] === "\\") { i += 2; continue; }
        if (src.slice(i, i + 2) === "${") {
          out.push("  ");
          i += 2;
          let depth = 1;
          while (i < src.length && depth > 0) {
            if (src[i] === "{") depth += 1;
            else if (src[i] === "}") depth -= 1;
            if (depth > 0) {
              out.push(src[i]);
              i += 1;
            } else {
              out.push(" ");
              i += 1;
            }
          }
          continue;
        }
        if (src[i] === "\n") out.push("\n");
        i += 1;
      }
      if (i < src.length) i += 1;
      continue;
    }
    out.push(ch);
    i += 1;
  }
  return out.join("");
}


const DECL = new RegExp(
  "\\[\\s*expanded\\s*,|" +                                     // useState tuple
  "\\{[^}]*\\bexpanded\\b[^}]*\\}\\s*=|" +                      // destructure assign
  "\\bconst\\s+expanded\\b|" +
  "\\blet\\s+expanded\\b|" +
  "\\bvar\\s+expanded\\b|" +
  "function\\s*\\w*\\s*\\([^)]*\\bexpanded\\b[^)]*\\)|" +       // fn param
  "\\(\\s*\\{[^}]*\\bexpanded\\b[^}]*\\}\\s*\\)\\s*=>|" +       // arrow destructure
  "\\(\\s*[^)]*\\bexpanded\\b[^)]*\\)\\s*=>",                   // arrow unmarked
  "g",
);

const BARE = /(?<![\w\-])expanded(?!\w)/g;


describe("Defensive sweep · bare `expanded` identifier guard", () => {
  const files = walk(SRC_ROOT);

  it("every `expanded` identifier read lives in a file that also " +
     "declares `expanded` (useState / destructure / prop / const)", () => {
    const orphans = [];
    for (const p of files) {
      // Skip this guard file itself — it contains the word
      // ``expanded`` inside regex literals that the string /
      // comment stripper cannot elide, which would make the
      // guard spuriously flag itself.
      if (p.endsWith(path.join("test", "expanded-identifier-guard.test.jsx"))) continue;
      const src = fs.readFileSync(p, "utf8");
      if (!src.includes("expanded")) continue;
      const clean = stripStringsAndComments(src);
      BARE.lastIndex = 0;
      DECL.lastIndex = 0;
      const bareHits = [...clean.matchAll(BARE)];
      if (bareHits.length === 0) continue;
      const decls = [...clean.matchAll(DECL)];
      if (decls.length === 0) {
        // Every bare read in this file is an orphan.
        const lines = bareHits.map(
          (m) => clean.slice(0, m.index).split("\n").length,
        );
        orphans.push({ file: path.relative(SRC_ROOT, p), lines });
      }
    }
    expect(
      orphans,
      "orphan `expanded` reads found (no declaration in same file):\n" +
      orphans
        .map((o) => `  ${o.file} @ lines ${o.lines.join(", ")}`)
        .join("\n"),
    ).toEqual([]);
  });

  it("scope sanity — the walker scanned ≥500 source files " +
     "(regression guard against an accidentally scoped-down " +
     "sweep)", () => {
    expect(files.length).toBeGreaterThan(500);
  });

  it("schedule / calendar surface specifically — zero orphans in " +
     "`pages/schedule/**` and `components/schedule/**` (the two " +
     "surfaces that produced the historical ``5979.aad12649.chunk`` " +
     "ReferenceError)", () => {
    const SCOPE = (p) => (
      p.includes(`${path.sep}pages${path.sep}schedule${path.sep}`) ||
      p.includes(`${path.sep}components${path.sep}schedule${path.sep}`)
    );
    const scoped = files.filter(SCOPE);
    // Sanity probe — the two historical crash surfaces must be in
    // the scoped list, otherwise the test is matching nothing.
    expect(
      scoped.find((p) => p.endsWith("CalendarSchedule.jsx")),
      "CalendarSchedule.jsx not in scope — path matcher regressed?",
    ).toBeTruthy();
    expect(
      scoped.find((p) => p.endsWith("JobNotesCallout.jsx")),
      "JobNotesCallout.jsx not in scope — path matcher regressed?",
    ).toBeTruthy();
    const orphans = [];
    for (const p of scoped) {
      const src = fs.readFileSync(p, "utf8");
      if (!src.includes("expanded")) continue;
      const clean = stripStringsAndComments(src);
      BARE.lastIndex = 0;
      DECL.lastIndex = 0;
      const bareHits = [...clean.matchAll(BARE)];
      if (bareHits.length === 0) continue;
      const decls = [...clean.matchAll(DECL)];
      if (decls.length === 0) {
        orphans.push(path.relative(SRC_ROOT, p));
      }
    }
    expect(orphans).toEqual([]);
  });
});


describe("Defensive sweep · schedule-surface isolation renders " +
         "do not throw `ReferenceError`", () => {
  // The guard above locks the source-level invariant.  These
  // isolation smoke tests belt-and-brace the three
  // ``components/schedule`` surfaces that historically wired
  // ``expanded`` state so that any future refactor that drops a
  // ``useState`` call or an ``expanded`` prop surfaces as a
  // runtime failure HERE instead of in production.
  it("JobNotesCallout renders without a `ReferenceError`", async () => {
    const React = (await import("react")).default;
    const { render } = await import("@testing-library/react");
    const mod = await import(
      "../components/schedule/JobNotesCallout.jsx"
    );
    const JobNotesCallout = mod.default;
    expect(() => render(
      React.createElement(JobNotesCallout, {
        jobId: "job-1",
        note: "Short note",
        customerNote: "Cust",
        poolNote: "Pool",
        landscapeNote: "Land",
      }),
    )).not.toThrow();
  });

  it("ServiceNotePill renders in both collapsed + expanded " +
     "state without a `ReferenceError`", async () => {
    const React = (await import("react")).default;
    const { render, screen, fireEvent } = await import(
      "@testing-library/react"
    );
    const { MemoryRouter } = await import("react-router-dom");
    const mod = await import(
      "../components/schedule/ServiceNotePill.jsx"
    );
    const ServiceNotePill = mod.ServiceNotePill;
    expect(() => render(
      React.createElement(
        MemoryRouter,
        null,
        React.createElement(ServiceNotePill, {
          note: "A".repeat(200),
          serviceType: "pool_service",
          jobId: "job-1",
        }),
      ),
    )).not.toThrow();
    // Toggle expanded state via the pill click.
    const pill = screen.getByTestId("service-note-pill-job-1");
    expect(() => fireEvent.click(pill)).not.toThrow();
    // Preview region now visible — confirms the expanded branch
    // of the component mounted without a ReferenceError.
    expect(
      screen.getByTestId("service-note-pill-job-1-preview"),
    ).toBeTruthy();
  });
});
