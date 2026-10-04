/**
 * CP-1-B · Feb-2026 — Gate code promoted to the top stat-tile row on
 * the Customer Overview tab.
 *
 * Contract checks live at the source-body level (mirroring the K41 /
 * K48 / A2 pattern used across this repo) so the suite runs without
 * mounting the 2990-line CustomerDetail graph.  The four assertion
 * groups below map 1:1 to the four behavioural criteria from the
 * CP-1-B brief:
 *
 *   a. Tile with data-testid="cd-stat-gate-code" is present in the DOM
 *      for an admin user.
 *      → source proof: the tile is a static array entry inside the
 *      stat-tile array literal with ``testid: "cd-stat-gate-code"``
 *      wired to the shared ``data-testid={c.testid}`` renderer below.
 *   b. Shows the stored value when ``customer.gate_code`` is non-empty.
 *      → source proof: ``value: customer.gate_code`` (direct binding,
 *      no masking / transform) and the shared loop renders
 *      ``{c.value || "—"}`` → non-empty strings pass through verbatim.
 *   c. Shows "—" when ``customer.gate_code`` is null / undefined /
 *      empty string.  → source proof: the shared loop fallback
 *      ``{c.value || "—"}`` is the SAME expression every other tile
 *      uses, so null/undefined/"" all coerce to the em-dash.
 *   d. Tile renders for every role — no role conditional.
 *      → source proof: the tile object is inside the base array
 *      literal (not wrapped in a role-gated ``? :`` or ``.filter()``),
 *      and the whole array is iterated unconditionally via
 *      ``.map((c) => <div ...>)``.  No ``authUser.role`` / ``isAdmin``
 *      / ``user.role`` symbol appears inside the stat-tile array
 *      literal scope.
 *
 * GCR · Feb-2026 (follow-up to CP-1-B) — the lower ``<Info label=
 * "Gate code" value={customer.gate_code} />`` render inside
 * ``cd-address-block`` was DELETED.  Gate code now lives ONLY on
 * the top stat-tile grid.  The regression lock below is INVERTED:
 * assertions (e)+(f) prove the lower <Info> is absent and the
 * ``cd-address-block`` scope carries no residual "Gate code" text.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const SRC = read("src/pages/customers/CustomerDetail.jsx");

/* Slice the stat-tile array literal.  The array sits between the
 * grid wrapper ``<div className="grid grid-cols-1 sm:grid-cols-2
 * lg:grid-cols-4 gap-3 mt-4">`` opening and the ``.map((c) => (``
 * iterator that renders each tile.  Capturing just the array literal
 * (not the renderer) keeps per-test regex scans focused on the tile
 * declarations themselves and prevents false-positive matches on the
 * shared fallback expression. */
const STAT_TILE_ARRAY = SRC.split(
  'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">',
)[1].split("].map((c) => (")[0];

/* The renderer immediately below the array — the shared loop that
 * iterates EVERY entry unconditionally.  Used to prove criterion (c)
 * and (d): the loop has no role gate and the null-fallback is a
 * single, shared ``{c.value || "—"}`` expression. */
const STAT_TILE_RENDERER = SRC.split("].map((c) => (")[1].split(
  "))}",
)[0];


describe("CP-1-B · Gate code stat tile · structural contract", () => {
  it("a. the tile with testid='cd-stat-gate-code' is declared inside the stat-tile array literal", () => {
    // Shared renderer wires ``data-testid={c.testid}`` on each tile — so
    // declaring ``testid: "cd-stat-gate-code"`` on an array entry is
    // sufficient to put the DOM node on the page.
    expect(STAT_TILE_ARRAY).toMatch(/testid: "cd-stat-gate-code"/);
    expect(STAT_TILE_ARRAY).toMatch(/icon: KeyRound/);
    expect(STAT_TILE_ARRAY).toMatch(/label: "Gate code"/);
    // Shared renderer confirms the testid lands on the rendered node.
    expect(STAT_TILE_RENDERER).toMatch(/data-testid=\{c\.testid\}/);
  });

  it("b. tile value binding is ``customer.gate_code`` (direct, no transform / mask)", () => {
    // The value binding passes the raw string through to the shared
    // renderer — no .slice(), no mask function, no conditional
    // suppression.  Non-empty strings reach the DOM verbatim.
    expect(STAT_TILE_ARRAY).toMatch(/value: customer\.gate_code,/);
    // The gate_code tile stays inside the base array — no .filter()
    // / role gate / conditional push that could strip it from the
    // iteration.
    expect(STAT_TILE_ARRAY).not.toMatch(/gate_code[^,\n]*\?/);
  });

  it("c. shared renderer coalesces null / undefined / empty-string to '—'", () => {
    // Every tile — including the new gate_code tile — uses the shared
    // ``{c.value || "—"}`` fallback.  The ``||`` coerces null,
    // undefined, and the empty string to the em-dash.  This is the
    // same contract every other tile in the row relies on, so no
    // tile-specific branch is needed.
    expect(STAT_TILE_RENDERER).toMatch(/\{c\.value \|\| "—"\}/);
    // Negative — no masking helper is called on the gate_code value.
    expect(STAT_TILE_ARRAY).not.toMatch(/maskGateCode|redactGateCode/);
  });

  it("d. tile renders for every role — no role-check symbol in the array scope", () => {
    // No concrete role-check symbol appears inside the stat-tile
    // array scope.  (Covers admin / super_admin / manager / owner /
    // tech / viewer / undefined all at once.)  The regexes target
    // *actual* role-adjacent patterns — not the English word "role"
    // in prose — so a comment that mentions roles doesn't false-positive.
    expect(STAT_TILE_ARRAY).not.toMatch(/authUser/);
    expect(STAT_TILE_ARRAY).not.toMatch(/useAuth\(/);
    expect(STAT_TILE_ARRAY).not.toMatch(/\.role\b/);               // .role property access
    expect(STAT_TILE_ARRAY).not.toMatch(/\brole\s*[=!]==?/);       // role === / role !==
    expect(STAT_TILE_ARRAY).not.toMatch(/isAdmin/);
    expect(STAT_TILE_ARRAY).not.toMatch(/isTech/);
    expect(STAT_TILE_ARRAY).not.toMatch(/isManager/);
    expect(STAT_TILE_ARRAY).not.toMatch(/isOwner/);
    // Renderer loop iterates every entry — no filter() or role-gated
    // short-circuit between the array literal and the .map().
    const spliceSlice = SRC.split("].map((c) => (")[0].split(
      "<div className=\"grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4\">",
    )[1];
    expect(spliceSlice).not.toMatch(/\.filter\(/);
  });
});


describe("GCR · lower <Info> render DELETED (replaces CP-1-B regression lock)", () => {
  /* Flipped by GCR (Feb 2026) — the CP-1-B belt-and-suspenders assertion
   * that the LOWER ``<Info label="Gate code" value={customer.gate_code} />``
   * stays in place inside ``cd-address-block`` is INVERTED now that the
   * user has approved removing the duplicate render.  Gate code lives
   * ONLY in the top stat-tile grid (``cd-stat-gate-code``). */
  it("e. no ``<Info label=\"Gate code\" …>`` remains anywhere in CustomerDetail.jsx", () => {
    // The lower address-block render is gone — zero <Info> occurrences
    // of the Gate code label survive.
    expect(SRC).not.toMatch(/<Info label="Gate code"/);
    const infoHits = (
      SRC.match(/<Info label="Gate code"/g) || []
    ).length;
    expect(infoHits).toBe(0);
    // The literal "Gate code" string appears exactly ONCE across the
    // file — on the ``label:`` key of the stat-tile array entry.  That
    // single occurrence proves the top-tile label is still wired AND
    // locks against a future diff that accidentally re-introduces the
    // duplicate render.
    const labelHits = (
      SRC.match(/"Gate code"/g) || []
    ).length;
    expect(labelHits).toBe(1);
  });

  it("f. the ``cd-address-block`` scope contains no gate_code JSX render or data binding", () => {
    // Slice the cd-address-block scope — from the opening ``<div
    // data-testid="cd-address-block" …>`` to the sibling
    // ``<MasterBillingCard`` tag that always follows the block.  The
    // assertions below check for JSX-renderable patterns (not the
    // English words "Gate code" in a comment) so an in-source
    // tombstone comment that happens to mention gate-code doesn't
    // trip the test.
    const addressScope = SRC.split(
      'data-testid="cd-address-block"',
    )[1]?.split('<MasterBillingCard')[0] || "";
    expect(addressScope.length).toBeGreaterThan(0);
    // No <Info> element rendering the Gate code label.
    expect(addressScope).not.toMatch(/<Info label="Gate code"/);
    // No data binding to the customer.gate_code field.
    expect(addressScope).not.toMatch(/customer\.gate_code/);
    // Belt-and-braces: Primary + Billing address siblings are still
    // in the scope (we removed the Gate code line only, not the
    // whole address block).
    expect(addressScope).toMatch(/label="Primary address"/);
    expect(addressScope).toMatch(/label="Billing address"/);
  });
});
