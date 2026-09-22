/**
 * Phase P18 · Feb-2026 · Recurring Jobs Active / Paused tab switcher
 * + Pause toast surfaces ``cancelled_visit_count``.
 *
 * Locks in the source-shape invariants (RecurringJobs.jsx is a
 * ~1900 LOC surface; a full JSDOM mount pulls in every customer /
 * crew / category / orphan-preview fetch and is brittle — the P14
 * suite settled on a source-scan pattern for exactly this reason).
 *
 * Invariants:
 *   1. The tab strip renders with ``data-testid="recurring-status-tabs"``
 *      and one button per tab keyed on the tab id.
 *   2. Both tabs (``active`` / ``paused``) render labels + a count
 *      pulled from ``tabCounts`` (which the load() reader populates
 *      from the backend ``counts`` field).
 *   3. Selected tab is initialised from ``?status=`` URL param and
 *      the ``setStatusTab``-triggered effect keeps the URL param in
 *      sync (single source of truth).
 *   4. ``load()`` sends ``?status=<statusTab>`` on the
 *      ``/recurring-jobs`` GET so the backend narrows the row set.
 *   5. ``load()`` sets tabCounts from the backend ``counts`` field.
 *   6. ``togglePause`` sends BOTH ``is_active`` (canonical) AND
 *      ``active`` (legacy mirror) in the PATCH body so the backend
 *      detects the True→False transition.
 *   7. On a Pause success (``!nextActive``), the toast surfaces
 *      ``cancelled_visit_count`` from the PATCH response, singular /
 *      plural aware.
 *   8. Refetch effect is keyed on ``statusTab`` — flipping tabs
 *      triggers a new ``load()``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC_PATH = path.resolve(
  __dirname, "../pages/admin/RecurringJobs.jsx",
);
const src = fs.readFileSync(SRC_PATH, "utf8");


describe("Phase P18 · Recurring Jobs Active / Paused tab strip", () => {
  it("renders the tab strip container with the canonical data-testid", () => {
    expect(src).toMatch(/data-testid="recurring-status-tabs"/);
  });

  it("has both tabs keyed by the ``active`` / ``paused`` status ids", () => {
    // The two tab keys drive the button IDs — the backend takes the
    // string verbatim as the ``?status=`` query param.
    expect(src).toMatch(
      /\{[^}]*key:\s*"active",\s*label:\s*"Active"[^}]*\}/,
    );
    expect(src).toMatch(
      /\{[^}]*key:\s*"paused",\s*label:\s*"Paused"[^}]*\}/,
    );
  });

  it("renders per-tab data-testids that testing agents can drive", () => {
    // ``data-testid="recurring-status-tab-active"`` +
    // ``data-testid="recurring-status-tab-paused"`` — spec.
    expect(src).toMatch(
      /data-testid=\{`recurring-status-tab-\$\{tab\.key\}`\}/,
    );
  });

  it("renders the label alongside the tabCounts badge in parentheses", () => {
    // The template literal ``{tab.label} ({badge})`` is the
    // rendered contract — flipping this without also updating the
    // testing-agent flows would silently mismatch the visible copy.
    expect(src).toMatch(/\{tab\.label\} \(\{badge\}\)/);
    // ``badge`` is Number(tabCounts[tab.key] || 0).
    expect(src).toMatch(
      /const badge\s*=\s*Number\(tabCounts\[tab\.key\]\s*\|\|\s*0\)/,
    );
  });
});


describe("Phase P18 · URL query is the source of truth for the tab", () => {
  it("initialises statusTab from ``?status=`` with an ``active`` default", () => {
    // The initial state reads the URL param and coerces anything
    // non-"paused" back to "active" (never trust untyped strings).
    expect(src).toMatch(
      /const raw = \(searchParams\.get\("status"\) \|\| ""\)\.toLowerCase\(\);/,
    );
    expect(src).toMatch(/return raw === "paused" \? "paused" : "active";/);
  });

  it("effect syncs the URL query back when statusTab changes", () => {
    // Effect body must update ``?status=<statusTab>`` via
    // ``setSearchParams`` with ``replace: true`` (so the tab flip
    // doesn't grow the browser history stack).
    expect(src).toMatch(/next\.set\("status", statusTab\);/);
    expect(src).toMatch(/setSearchParams\(next, \{ replace: true \}\);/);
    // Effect dependency array carries statusTab (guarded ESLint
    // disable is fine — verified above).
    expect(src).toMatch(/\}, \[statusTab\]\);/);
  });
});


describe("Phase P18 · load() wires the status filter + counts contract", () => {
  it("passes the current statusTab to the backend as ``?status=``", () => {
    // Encoded so a future rename to a value containing ``&``
    // (unlikely but defensive) doesn't corrupt the URL.
    expect(src).toMatch(
      /api\.get\(`\/recurring-jobs\?status=\$\{encodeURIComponent\(statusTab\)\}`\)/,
    );
  });

  it("populates tabCounts from the backend ``counts`` field", () => {
    // The reader tolerates missing / malformed counts (falls back
    // to 0) so a legacy backend that hasn't shipped the aggregate
    // yet still renders the tab strip with zero badges.
    expect(src).toMatch(
      /if \(tpls\?\.counts && typeof tpls\.counts === "object"\)/,
    );
    expect(src).toMatch(/setTabCounts\(\{/);
    expect(src).toMatch(/active: Number\(tpls\.counts\.active \|\| 0\)/);
    expect(src).toMatch(/paused: Number\(tpls\.counts\.paused \|\| 0\)/);
    expect(src).toMatch(/total:  ?Number\(tpls\.counts\.total \|\| 0\)/);
  });
});


describe("Phase P18 · togglePause sends both keys + surfaces cancelled_visit_count", () => {
  it("PATCH body carries BOTH is_active and active", () => {
    // Backend detects the True→False transition on the canonical
    // ``is_active`` field, but the legacy mirror keeps any code
    // path still reading ``active`` in sync.
    expect(src).toMatch(
      /api\.patch\(`\/recurring-jobs\/\$\{row\.id\}`,\s*\{\s*is_active:\s*nextActive,\s*active:\s*nextActive,\s*\}\)/,
    );
  });

  it("computes nextActive off the effective active flag (is_active > active)", () => {
    expect(src).toMatch(
      /const effectiveActive = row\.is_active !== undefined\s*\?\s*!!row\.is_active\s*:\s*!!row\.active;/,
    );
    expect(src).toMatch(/const nextActive = !effectiveActive;/);
  });

  it("on Pause success surfaces cancelled_visit_count in a singular/plural toast", () => {
    // ``noun`` flips singular for 1, plural otherwise — no ternary
    // repeat, just one clean template literal.
    expect(src).toMatch(
      /const n = Number\(res\?\.cancelled_visit_count \|\| 0\);/,
    );
    expect(src).toMatch(/const noun = n === 1 \? "visit" : "visits";/);
    expect(src).toMatch(
      /toast\.success\(`Paused\. \$\{n\} future \$\{noun\} cancelled\.`\);/,
    );
  });

  it("on Resume success surfaces a plain ``Resumed.`` toast", () => {
    // Resume path is symmetric with Pause but does NOT surface a
    // count — the Auto-Activate generation is best-effort and its
    // count is already surfaced via ``generated_count`` on the
    // response body (P17-era).
    expect(src).toMatch(/toast\.success\("Resumed\."\)/);
  });
});


describe("Phase P18 · refetch effect drives on statusTab change", () => {
  it("effect calls load() so a tab flip requeries the backend", () => {
    // The effect body must invoke ``load()`` after syncing the URL
    // param — the two operations MUST live in the same effect so
    // there's no race between URL sync + re-fetch.
    const idx = src.indexOf(/setSearchParams\(next, \{ replace: true \}\);/);
    // The literal ``load();`` call sits below the URL sync.
    const eff = src.match(
      /setSearchParams\(next, \{ replace: true \}\);\s*\}\s*load\(\);/s,
    );
    expect(eff).not.toBeNull();
  });
});
