/**
 * Feb-2026 · WorkstreamPage — status ReferenceError cleanup.
 *
 * The ``ActiveFilterChips`` shorthand at ``<page>:686`` used to
 * read ``status,`` (bare identifier) in the ``filters`` object.
 * WorkstreamPage has no local ``status`` state, so under strict
 * lint / SSR / any bundler that doesn't fall through to the
 * ``window.status`` global, this raised a ``ReferenceError``.
 *
 * Fix removed the phantom ``status`` reference entirely; the page
 * is scoped to ``status=completed`` server-side. This test locks
 * the fix by asserting the phantom identifier is gone from the
 * source AND that the ActiveFilterChips call site no longer
 * references it.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/workstream/WorkstreamPage.jsx"),
  "utf8",
);

describe("WorkstreamPage — status ReferenceError cleanup", () => {
  it("no bare ``status,`` shorthand in the ActiveFilterChips call", () => {
    const chipsIdx = SRC.indexOf("<ActiveFilterChips");
    expect(chipsIdx).toBeGreaterThan(-1);
    // Scan the JSX block up to the closing ``/>``.
    const closeIdx = SRC.indexOf("/>", chipsIdx);
    const block = SRC.slice(chipsIdx, closeIdx);
    // The bug looked like:  status,\n  }}
    expect(block).not.toMatch(/\bstatus,\s*\n\s*\}\}/);
    // Guard against reintroduction as ``status:`` too.
    expect(block).not.toMatch(/\bstatus\s*:\s*status\b/);
  });

  it("page has no local ``status`` state (guard vs. regression)", () => {
    // The fix rests on the assumption that WorkstreamPage doesn't
    // own a status filter (server-side scope). If someone later
    // adds ``const [status, setStatus] = useState(...)``, the chip
    // shorthand SHOULD come back — this guard catches that so we
    // don't silently leave the chip empty.
    expect(SRC).not.toMatch(/const\s*\[\s*status\s*,\s*setStatus\s*\]\s*=/);
  });
});
