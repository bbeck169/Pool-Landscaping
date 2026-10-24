/**
 * TD-crew-edit-no-auto-remove-and-save-full-roster · Feb-2026.
 *
 * Ticket G FE contract rails.  Supersedes TD-86 rails #2 + #3 (the
 * ``openEdit`` auto-prune and the "N members removed" banner).
 *
 * What this suite locks in ``OpsHub.jsx::Crews``:
 *
 *   1. ``openEdit(c)`` seeds ``form.tech_ids`` with the FULL
 *      ``c.tech_ids`` array — no filter, no prune.
 *   2. ``openEdit(c)`` also stashes ``c.members`` into
 *      ``incomingMembers`` so unavailable chips can resolve
 *      display names from the BE join.
 *   3. ``openNew`` resets ``incomingMembers`` + ``beErrors``.
 *   4. The banner wording was swapped from the TD-86
 *      "N members removed" (which implied the FE had already
 *      pruned them) to the Ticket-G "flagged as unavailable ...
 *      remain assigned to the crew" (which tells the operator
 *      the roster is still intact and they must decide).
 *   5. Unavailable chips render with:
 *        * warning styling (``colors.warning100`` background),
 *        * a resolved display name (from ``incomingMembers``) or
 *          a short-id stub for truly orphan ids,
 *        * an explicit "×" remove button so the operator can
 *          drop just the ones they want to lose.
 *   6. ``save()`` sends ``form`` as-is (no FE pre-filter) and on
 *      BE 400 parses the categorised ``errors`` array off
 *      ``e.data.detail.errors``, routing orphan vs
 *      foreign_tenant into separate banner buckets.
 *
 * JSX is sourced via grep against the compiled render path (same
 * style as the TD-86 companion suite); the full OpsHub.jsx is a
 * 3.8-kloc multi-tab page component where rendering it under
 * JSDOM would require stubbing >20 providers.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
  "utf8",
);

describe("Ticket G · Crew edit — no auto-remove, save full roster", () => {
  it("``openEdit`` seeds form.tech_ids with the FULL incoming array", () => {
    // The replacement for the TD-86 ``pruned = incoming.filter(...)``
    // seed. Legacy prune must NOT reappear.
    expect(SRC).toMatch(
      /tech_ids: incoming,/,
    );
    const legacyPrune = /const pruned = incoming\.filter\(\(x\) => validTechIds\.has\(x\)\);/;
    expect(SRC).not.toMatch(legacyPrune);
    const legacyPrunedCount = /setPrunedCount\(incoming\.length - pruned\.length\);/;
    expect(SRC).not.toMatch(legacyPrunedCount);
  });

  it("``openEdit`` stashes c.members into incomingMembers for name resolution", () => {
    expect(SRC).toMatch(
      /setIncomingMembers\(Array\.isArray\(c\.members\) \? c\.members : \[\]\)/,
    );
  });

  it("``openEdit`` resets beErrors so a prior save's 400 state doesn't leak", () => {
    // Belt-and-braces — the save handler clears beErrors on save
    // attempt too, but a user who hits Cancel after a 400 and
    // re-opens Edit shouldn't see the stale banner.
    expect(SRC).toMatch(/setBeErrors\(\[\]\);\s*\n\s*setOpen\(true\);/);
  });

  it("``openNew`` resets incomingMembers + beErrors (not prunedCount)", () => {
    expect(SRC).toMatch(
      /const openNew = \(\) => \{\s*\n\s*setEditing\(null\);\s*\n\s*setForm\(\{ name: "", color: "#3B82F6", tech_ids: \[\] \}\);\s*\n\s*setIncomingMembers\(\[\]\);\s*\n\s*setBeErrors\(\[\]\);/,
    );
    // TD-86's prunedCount state is gone.
    expect(SRC).not.toMatch(/setPrunedCount\(0\);/);
  });

  it("banner wording tells operator members 'remain assigned' (not 'removed')", () => {
    // The TD-86 banner implied the FE had already pruned ("removed
    // because they are no longer available"); the Ticket-G banner
    // must make clear the roster is intact and the operator must
    // decide.
    expect(SRC).toMatch(/flagged as unavailable/);
    expect(SRC).toMatch(/remain assigned to the crew/);
    // Old banner JSX must not reappear (comment-only historical
    // mentions in ``openEdit`` are not JSX output — guard the
    // actual render path).
    expect(SRC).not.toMatch(
      /\{prunedCount\} member\{prunedCount === 1 \? "" : "s"\} removed/,
    );
    expect(SRC).not.toMatch(/crew-pruned-banner/);
  });

  it("unavailable chips render with warning styling + × remove button", () => {
    // One per form.tech_ids id missing from validTechIds.
    expect(SRC).toMatch(/data-testid=\{\`crew-tech-unavailable-\$\{uid\}\`\}/);
    expect(SRC).toMatch(
      /data-testid=\{\`crew-tech-unavailable-remove-\$\{uid\}\`\}/,
    );
    // Warning styling.
    expect(SRC).toMatch(/colors\.warning100/);
    // Short-id fallback for truly orphan ids.
    expect(SRC).toMatch(/Unknown user \(\$\{String\(uid\)\.slice\(0, 8\)\}/);
  });

  it("save() sends form as-is (no FE pre-filter on tech_ids)", () => {
    // The patch body is the raw ``form`` object — a pre-filter
    // would show up here as ``{ ...form, tech_ids: form.tech_ids.filter(...) }``.
    expect(SRC).toMatch(/api\.patch\(`\/crews\/\$\{editing\.id\}`, form\)/);
    // Negative guard — no filter wrapping the save payload.
    expect(SRC).not.toMatch(
      /api\.patch\(`\/crews\/\$\{editing\.id\}`, \{[^}]*tech_ids:[^}]*\.filter\(/,
    );
  });

  it("save() parses BE 400 categorised errors off e.data.detail.errors", () => {
    // The api client stashes the parsed response body on ``e.data``
    // (see api.js L265).  The categorised crew errors live at
    // ``e.data.detail.errors`` per routers/ops.py.
    expect(SRC).toMatch(/e\?\.data\?\.detail/);
    expect(SRC).toMatch(/Array\.isArray\(_detail\.errors\)/);
    expect(SRC).toMatch(/setBeErrors\(_errs\)/);
  });

  it("post-save banner partitions errors into orphan vs foreign_tenant buckets", () => {
    expect(SRC).toMatch(/beErrors\.filter\(\(e\) => e\?\.reason === "orphan"\)/);
    expect(SRC).toMatch(
      /beErrors\.filter\(\(e\) => e\?\.reason === "foreign_tenant"\)/,
    );
    expect(SRC).toMatch(/data-testid="crew-unavailable-orphan"/);
    expect(SRC).toMatch(/data-testid="crew-unavailable-foreign"/);
  });

  it("TD-crew-edit audit reference is linked in the Crews-component source", () => {
    expect(SRC).toMatch(/TD-crew-edit-no-auto-remove-and-save-full-roster/);
  });
});
