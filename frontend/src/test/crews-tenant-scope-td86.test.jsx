/**
 * TD-86 · Feb-2026 — OpsHub Crews tab tenant-scope regression suite.
 *
 * TD-crew-edit-no-auto-remove-and-save-full-roster · Feb-2026 — the
 * ``openEdit`` auto-prune (contract rails #2 + #3 in the original
 * TD-86 ship) is SUPERSEDED by Ticket G.  Operator-selected is now
 * the source of truth; unavailable members remain in the roster
 * and surface as warning chips with explicit remove buttons. The
 * replacement rails live in ``crew-edit-no-auto-remove-and-save-
 * full-roster.test.jsx``.  What stays locked here are the two
 * TD-86 rails that are STILL load-bearing after Ticket G:
 *
 *   1. Picker only renders techs whose ``tenant_id`` matches the
 *      current tenant (defensive filter — belt + braces over the
 *      BE's own ``/api/technicians`` scope).
 *   2. The current-tenant id is resolved from ``/tenants/current``.
 *
 * JSX is sourced via grep against the compiled render path (same
 * style as the ``JobDetail.photo-src-fallback`` suite); the full
 * OpsHub.jsx is a 3.7-kloc multi-tab page component where
 * rendering it under JSDOM would require stubbing >20 providers.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
  "utf8",
);

describe("TD-86 · Crew member picker tenant-scope (post-Ticket-G)", () => {
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

  it("``validTechIds`` membership is sourced from scoped (tenant-filtered) list", () => {
    // The flag set used by the Ticket-G unavailable-chip renderer
    // must still come from ``scopedTechs``, not from the raw
    // ``techs`` wire payload — otherwise a cross-tenant row
    // leaking into the BE response would re-enter the roster as
    // "available".
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
