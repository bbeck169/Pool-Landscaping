// Task A + B · Feb-2026 — source-inspection vitest.
//
// Locks in the real pricebook importer, the auto-launcher scheduler
// job, and the Import Center's promotion of the pricebook row from
// "coming soon" to a live-runnable button.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const BACKEND = "/app/backend";
const FRONTEND = resolve(__dirname, "..");

const importer     = `${BACKEND}/services/homeworks_mcp/pricebook_importer.py`;
const dispatcher   = `${BACKEND}/services/homeworks_mcp/import_dispatcher.py`;
const router       = `${BACKEND}/routers/integrations_homeworks_income_items.py`;
const server_py    = `${BACKEND}/server.py`;
const launcher     = `${BACKEND}/scripts/homeworks_run_pricebook.py`;
const queries_py   = `${BACKEND}/services/homeworks_mcp/queries.py`;
const import_center = `${FRONTEND}/components/settings/HomeworksImportCenter.jsx`;

const read = (p) => readFileSync(p, "utf8");

describe("Task A · Pricebook importer (real, replaces the 501 stub)", () => {
  it("all new backend files exist", () => {
    expect(existsSync(importer)).toBe(true);
    expect(existsSync(launcher)).toBe(true);
  });

  describe("queries.py — items GraphQL", () => {
    const src = read(queries_py);
    it("exports ITEM_PAGE_QUERY + ITEM_COUNT_PAGE_QUERY with isDeleted:false", () => {
      expect(src).toContain("ITEM_PAGE_QUERY");
      expect(src).toContain("ITEM_COUNT_PAGE_QUERY");
      expect(src).toMatch(/isDeleted:\s*false/);
    });
    it("enumerates the four ItemType enum values", () => {
      expect(src).toContain("ITEM_TYPE_VALUES");
      expect(src).toContain('"SERVICE"');
      expect(src).toContain('"ITEM"');
      expect(src).toContain('"LABOR"');
      expect(src).toContain('"OTHER"');
    });
  });

  describe("pricebook_importer module", () => {
    const src = read(importer);
    it("exposes the standard importer contract", () => {
      expect(src).toMatch(/async def dry_run/);
      expect(src).toMatch(/async def create_run/);
      expect(src).toMatch(/async def run_full/);
      expect(src).toContain('"kind": "pricebook"');
    });
    it("carries the five sanity-gate constants", () => {
      expect(src).toContain("GATE_MIN_COUNT");
      expect(src).toContain("GATE_MAX_COUNT");
      expect(src).toContain("GATE_MAX_SAMPLE_LATENCY_MS");
      expect(src).toContain("GATE_MAX_NAME_COLLISION_PCT");
      expect(src).toContain("20_000");
    });
    it("skips on both original_id AND name collision", () => {
      expect(src).toContain("items_skipped_by_original_id");
      expect(src).toContain("items_skipped_by_name_collision");
      expect(src).toContain("name_collision_with_existing_item");
    });
    it("auto-creates the catch-all service category", () => {
      expect(src).toContain("CATCH_ALL_CATEGORY_NAME");
      expect(src).toContain("Homeworks (unmapped)");
      expect(src).toMatch(/_ensure_catch_all_category/);
    });
    it("maps costs into a homeworks_costs blob (nothing lost)", () => {
      expect(src).toContain("homeworks_costs");
      expect(src).toContain("materialCost");
      expect(src).toContain("equipmentCost");
      expect(src).toContain("subcontractCost");
      expect(src).toContain("markupType");
    });
    it("leaves supplier_prices empty by design", () => {
      // We do NOT populate supplier_prices at import time because
      // the existing validator requires a pricebook_supplier row +
      // income_category_id, both tenant-configured.
      expect(src).toContain('"supplier_prices": []');
    });
  });

  describe("router replaces the 501 stub", () => {
    const src = read(router);
    it("imports the real pricebook_importer", () => {
      expect(src).toContain("from services.homeworks_mcp import pricebook_importer");
    });
    it("no longer returns 501 not_implemented", () => {
      expect(src).not.toContain("HTTPException(501");
      expect(src).not.toContain("pricebook_importer_not_yet_implemented");
    });
    it("enforces the five sanity gates", () => {
      expect(src).toContain("_apply_sanity_gates");
      expect(src).toContain("gate_min_count");
      expect(src).toContain("gate_max_count");
      expect(src).toContain("gate_latency");
      expect(src).toContain("gate_collisions");
      expect(src).toContain("dry_run_fatal");
    });
  });
});

describe("Task B · Homeworks import dispatcher", () => {
  it("dispatcher module exists", () => {
    expect(existsSync(dispatcher)).toBe(true);
  });

  describe("dispatcher module", () => {
    const src = read(dispatcher);
    it("polls every 30s via a scheduler interval job", () => {
      expect(src).toContain("DISPATCHER_INTERVAL_S = 30");
      expect(src).toContain('"interval"');
      expect(src).toContain('id="homeworks_import_dispatcher"');
    });
    it("routes all four importer kinds", () => {
      expect(src).toContain("_IMPORTER_KIND_MAP");
      expect(src).toContain('"inactive_customers"');
      expect(src).toContain('"active_customers"');
      expect(src).toContain('"delta_sync"');
      expect(src).toContain('"pricebook"');
    });
    it("uses an atomic queued → running flip", () => {
      // The atomic guarantee is the whole point — the update_one
      // filter must include ``status: "queued"`` so a lost race
      // returns modified_count == 0.
      expect(src).toMatch(/"status":\s*"queued"/);
      expect(src).toMatch(/"\$set":\s*\{"status":\s*"running"/);
    });
    it("enforces per-tenant concurrency (one live run per tenant)", () => {
      expect(src).toContain("_tenant_has_running");
      expect(src).toContain("skipped_concurrency");
    });
    it("handles unhandled crashes by flipping the doc to failed", () => {
      expect(src).toContain("dispatcher_crash");
      expect(src).toContain('"status": "failed"');
    });
    it("marks unknown kinds failed so a poison doc doesn't retrip", () => {
      expect(src).toContain("unknown_kind:");
    });
    it("exposes register_dispatcher(scheduler) for server.py", () => {
      expect(src).toContain("def register_dispatcher(scheduler)");
      expect(src).toContain("max_instances=1");
      expect(src).toContain("coalesce=True");
    });
  });

  describe("server.py wiring", () => {
    const src = read(server_py);
    it("registers the dispatcher alongside the lumino reconciler", () => {
      expect(src).toContain(
        "from services.homeworks_mcp.import_dispatcher import register_dispatcher",
      );
      expect(src).toContain("register_dispatcher(scheduler)");
    });
  });
});

describe("Import Center: pricebook button no longer coming-soon", () => {
  const src = read(import_center);
  it("kind field for the income-items row is 'pricebook'", () => {
    // The row previously had comingSoon:true; now it should be a
    // fully-live button whose kind matches the backend run doc.
    expect(src).toContain('kind: "pricebook"');
  });
  it("does not carry comingSoon:true anywhere", () => {
    expect(src).not.toMatch(/comingSoon:\s*true/);
  });
});
