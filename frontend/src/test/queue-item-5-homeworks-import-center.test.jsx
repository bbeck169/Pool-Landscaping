// Queue Item 5 · Feb-2026 — source-inspection vitest for the
// Homeworks Import Center (web + backend delta-sync + income-items
// stub). Locks in:
//   • Delta-sync importer module exists with the wrapper contract.
//   • Delta-sync router registers all six endpoints under the
//     expected prefix.
//   • Income-items router registers the URL surface but returns
//     501 on /run per the stub design.
//   • Frontend component renders the four importer rows with
//     dry-run → confirm-modal → queue lifecycle.
//   • Import Center mounted on IntegrationsHub behind a super_admin
//     gate.
//   • Server.py wires both new routers into api_router.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const BACKEND = "/app/backend";
const FRONTEND = resolve(__dirname, "..");

const delta_importer = `${BACKEND}/services/homeworks_mcp/delta_sync_importer.py`;
const delta_router = `${BACKEND}/routers/integrations_homeworks_delta_sync.py`;
const income_router = `${BACKEND}/routers/integrations_homeworks_income_items.py`;
const delta_launcher = `${BACKEND}/scripts/homeworks_run_delta_sync.py`;
const server_py = `${BACKEND}/server.py`;
const import_center = `${FRONTEND}/components/settings/HomeworksImportCenter.jsx`;
const integrations_page = `${FRONTEND}/pages/settings/IntegrationsPages.jsx`;

const read = (p) => readFileSync(p, "utf8");

describe("Queue Item 5 · Homeworks Import Center", () => {
  it("all new backend files exist", () => {
    expect(existsSync(delta_importer)).toBe(true);
    expect(existsSync(delta_router)).toBe(true);
    expect(existsSync(income_router)).toBe(true);
    expect(existsSync(delta_launcher)).toBe(true);
  });

  describe("delta_sync_importer module", () => {
    const src = read(delta_importer);
    it("exposes the standard importer contract", () => {
      expect(src).toMatch(/async def dry_run/);
      expect(src).toMatch(/async def create_run/);
      expect(src).toMatch(/async def run_full/);
      expect(src).toContain('"kind": "delta_sync"');
    });
    it("reuses the existing active + inactive importers rather than duplicating logic", () => {
      expect(src).toContain("active_customers_importer as _active");
      expect(src).toContain("inactive_customers_importer as _inactive");
    });
    it("aggregates counters and reports last successful sync", () => {
      expect(src).toContain("since_last_sync");
      expect(src).toContain("customers_scanned");
      expect(src).toContain("customers_imported");
    });
  });

  describe("delta_sync router", () => {
    const src = read(delta_router);
    const prefix = "/integrations/homeworks/imports/delta-sync";
    it(`mounts under ${prefix}`, () => {
      expect(src).toContain(`prefix="${prefix}"`);
    });
    it("guards every endpoint with super_admin", () => {
      // At least one _require_super check per file.
      expect(src).toContain("_require_super(user)");
      const guards = src.match(/_require_super\(user\)/g) || [];
      expect(guards.length).toBeGreaterThanOrEqual(6);
    });
    it("registers all six polling endpoints", () => {
      expect(src).toMatch(/@router\.post\("\/dry-run"/);
      expect(src).toMatch(/@router\.post\("\/run"/);
      expect(src).toMatch(/@router\.post\("\/\{run_id\}\/cancel"/);
      expect(src).toMatch(/@router\.get\("\/\{run_id\}\/status"/);
      expect(src).toMatch(/@router\.get\("\/active"/);
      expect(src).toMatch(/@router\.get\("\/history"/);
    });
    it("enforces the 15-minute dry-run gate on /run", () => {
      expect(src).toContain("dry_run_required_within_15_minutes_before_run");
    });
  });

  describe("income_items router (stub)", () => {
    const src = read(income_router);
    const prefix = "/integrations/homeworks/imports/income-items";
    it(`mounts under ${prefix}`, () => {
      expect(src).toContain(`prefix="${prefix}"`);
    });
    it("returns 501 on POST /run so the FE can render a Coming soon badge", () => {
      expect(src).toContain("HTTPException(501");
      expect(src).toContain("pricebook_importer_not_yet_implemented");
    });
    it("dry-run responds truthfully (not_implemented + zeros)", () => {
      expect(src).toContain('"not_implemented": True');
      expect(src).toContain('"total_item_count"');
    });
  });

  describe("server.py wiring", () => {
    const src = read(server_py);
    it("includes both new routers", () => {
      expect(src).toContain("integrations_homeworks_delta_sync");
      expect(src).toContain("integrations_homeworks_income_items");
      expect(src).toContain("api_router.include_router(_hw_delta_sync.router)");
      expect(src).toContain("api_router.include_router(_hw_income_items.router)");
    });
  });

  describe("HomeworksImportCenter frontend component", () => {
    const src = read(import_center);
    it("exists at the expected path", () => {
      expect(existsSync(import_center)).toBe(true);
    });
    it("renders all four importer buttons (matched by testID)", () => {
      expect(src).toContain('data-testid={`homeworks-import-launch-${importer.key}`}');
      expect(src).toContain('key: "inactive-customers"');
      expect(src).toContain('key: "active-customers"');
      expect(src).toContain('key: "delta-sync"');
      expect(src).toContain('key: "income-items"');
    });
    it("flags pricebook as Coming soon (comingSoon:true + disabled button)", () => {
      expect(src).toMatch(/comingSoon:\s*true/);
      expect(src).toContain('data-testid={`homeworks-import-badge-comingsoon-${importer.key}`}');
    });
    it("uses dry-run → confirm modal → POST /run sequence", () => {
      expect(src).toContain('api.post(\n        `/integrations/homeworks/imports/${importer.slug}/dry-run`');
      expect(src).toContain("homeworks-import-confirm-modal");
      expect(src).toContain('api.post(\n        `/integrations/homeworks/imports/${modal.importer.slug}/run`');
    });
    it("polls the active-run endpoint for in-place progress", () => {
      expect(src).toContain('/active`,');
      expect(src).toContain("POLL_INTERVAL_MS");
    });
  });

  describe("IntegrationsHub wiring", () => {
    const src = read(integrations_page);
    it("imports and mounts the Import Center behind a super_admin gate", () => {
      expect(src).toContain(
        'import HomeworksImportCenter from "@/components/settings/HomeworksImportCenter"',
      );
      expect(src).toMatch(/user\?\.role === "super_admin"\s*\?\s*<HomeworksImportCenter/);
    });
  });
});
