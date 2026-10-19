/**
 * TD-86 · Feb-2026 — OpsHub Crews tab tenant-scope + orphan-prune
 * regression suite.
 *
 * Three contract rails locked here:
 *
 *   1. Picker only renders techs whose ``tenant_id`` matches the
 *      current tenant (defensive filter — belt + braces over the
 *      BE's own ``/api/technicians`` scope).
 *   2. ``openEdit(c)`` prunes orphan / foreign-tenant ids from the
 *      incoming ``c.tech_ids`` so the save payload never carries
 *      ids that would trip the ``td86-be-guard`` 400.
 *   3. The inline warning banner surfaces only when ids were
 *      pruned — new-crew flow never shows it.
 *
 * JSX is sourced via grep against the compiled render path
 * (same style as the ``JobDetail.photo-src-fallback`` suite);
 * the full OpsHub.jsx is a 3.7-kloc multi-tab page component
 * where rendering it under JSDOM would require stubbing >20
 * providers.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
  "utf8",
);

describe("TD-86 · Crew member picker tenant-scope + orphan prune", () => {
  it("picker iterates ``scopedTechs`` (tenant-filtered), not raw ``techs``", () => {
    // The TD-86 ship swapped ``(techs || []).map`` for
    // ``scopedTechs.map`` on the picker tile loop.
    expect(SRC).toMatch(/\{scopedTechs\.map\(\(t\) => \{/);
    // Legacy raw-techs iteration must not reappear on the picker.
    const legacy = /\{\(techs \|\| \[\]\)\.map\(\(t\) => \{\s*\n\s*const on = form\.tech_ids/;
    expect(SRC).not.toMatch(legacy);
  });

  it("``scopedTechs`` filters by current tenant_id (missing OR matching passes)", () => {
    // Defensive filter — tolerant on missing ``tenant_id`` so a
    // synthesized-from-users row (BE emits those too) still
    // renders.
    expect(SRC).toMatch(
      /list\.filter\(\s*\n?\s*\(t\) => !t\.tenant_id \|\| t\.tenant_id === currentTenantId,?\s*\n?\s*\)/,
    );
  });

  it("``currentTenantId`` is resolved from GET /tenants/current", () => {
    expect(SRC).toMatch(/api\.get\("\/tenants\/current"\)/);
    expect(SRC).toMatch(/setCurrentTenantId\(t\?\.id \|\| null\)/);
  });

  it("``openEdit`` prunes orphan / cross-tenant ids before form seed", () => {
    // Lock the pruned-filter shape so a regression that reverts
    // to ``c.tech_ids || []`` fails here.
    expect(SRC).toMatch(/const incoming = Array\.isArray\(c\.tech_ids\) \? c\.tech_ids : \[\];/);
    expect(SRC).toMatch(/const pruned = incoming\.filter\(\(x\) => validTechIds\.has\(x\)\);/);
    // Legacy direct-seed must not reappear.
    const legacySeed = /setForm\(\{ name: c\.name, color: c\.color \|\| "#3B82F6", tech_ids: c\.tech_ids \|\| \[\] \}\)/;
    expect(SRC).not.toMatch(legacySeed);
  });

  it("``openNew`` resets prunedCount to 0 (banner never shows on new-crew flow)", () => {
    expect(SRC).toMatch(
      /const openNew = \(\) => \{\s*\n\s*setEditing\(null\);\s*\n\s*setForm\(\{ name: "", color: "#3B82F6", tech_ids: \[\] \}\);\s*\n\s*setPrunedCount\(0\);/,
    );
  });

  it("``openEdit`` stamps prunedCount = incoming.length − pruned.length", () => {
    expect(SRC).toMatch(
      /setPrunedCount\(incoming\.length - pruned\.length\);/,
    );
  });

  it("inline banner renders only when prunedCount > 0", () => {
    expect(SRC).toMatch(/prunedCount > 0 \? \(/);
    expect(SRC).toMatch(/data-testid="crew-pruned-banner"/);
  });

  it("banner copy clearly explains the prune + instructs to Save", () => {
    expect(SRC).toMatch(
      /\{prunedCount\} member\{prunedCount === 1 \? "" : "s"\} removed/,
    );
    expect(SRC).toMatch(
      /because they are no longer available in this tenant\.\s*\n?\s*Click Save to apply\./,
    );
  });

  it("``validTechIds`` membership is sourced from scoped (tenant-filtered) list", () => {
    // The prune set must come from ``scopedTechs``, not from the
    // raw ``techs`` wire payload — otherwise a cross-tenant row
    // leaking into the BE response would re-enter the prune set.
    expect(SRC).toMatch(
      /new Set\(scopedTechs\.map\(\(t\) => t\.id\)\)/,
    );
  });

  it("TD-86 audit reference is linked in the Crews-component source", () => {
    // Catches a refactor that strips the TD-86 helper comments —
    // the audit cross-link is the only trail future auditors have
    // to find the ``/app/memory/td86_crew_tenant_audit.md`` doc.
    expect(SRC).toMatch(/TD-86 · Feb-2026/);
    expect(SRC).toMatch(/td86_crew_tenant_audit\.md/);
  });
});
