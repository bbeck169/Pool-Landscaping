// Follow-up bundle (Items 5, 2, 4, 3) · Feb-2026 —
// source-inspection vitest.
//
// Locks in:
//   Item 5 — "Run now" dispatcher trigger endpoint + FE button.
//   Item 2 — Confirm-modal delta headline.
//   Item 4 — Suppression Log deep-link from DemoAccountToggle +
//              backend recipient_id filter.
//   Item 3 — Shared importer_base module + pricebook migration.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const BACKEND = "/app/backend";
const FRONTEND = resolve(__dirname, "..");

const dispatcher_router = `${BACKEND}/routers/integrations_homeworks_dispatcher.py`;
const comms_admin       = `${BACKEND}/routers/comms_admin.py`;
const importer_base     = `${BACKEND}/services/homeworks_mcp/importer_base.py`;
const pricebook_imp     = `${BACKEND}/services/homeworks_mcp/pricebook_importer.py`;
const server_py         = `${BACKEND}/server.py`;

const import_center      = `${FRONTEND}/components/settings/HomeworksImportCenter.jsx`;
const demo_toggle        = `${FRONTEND}/components/comms/DemoAccountToggle.jsx`;
const suppression_log    = `${FRONTEND}/pages/admin/AdminCommsSuppressionLog.jsx`;

const read = (p) => readFileSync(p, "utf8");

describe("Item 5 · Run-now dispatcher trigger", () => {
  it("dispatcher router file exists", () => {
    expect(existsSync(dispatcher_router)).toBe(true);
  });
  const src = read(dispatcher_router);
  it("mounts POST /tick under the dispatcher prefix", () => {
    expect(src).toContain(
      'prefix="/integrations/homeworks/imports/dispatcher"',
    );
    expect(src).toMatch(/@router\.post\("\/tick"/);
  });
  it("gates on super_admin only", () => {
    expect(src).toContain('super_admin_only');
  });
  it("enforces a 5-second cooldown so mashing can't stampede the scheduler", () => {
    expect(src).toContain("_COOLDOWN_S = 5.0");
    expect(src).toContain('"cooldown": True');
  });
  it("delegates to dispatcher_tick when hot", () => {
    expect(src).toContain("await dispatcher_tick()");
  });
  it("server.py wires the router", () => {
    const s = read(server_py);
    expect(s).toContain("integrations_homeworks_dispatcher");
    expect(s).toContain("api_router.include_router(_hw_dispatcher_router.router)");
  });
  it("Import Center renders the Run-now button conditionally", () => {
    const s = read(import_center);
    expect(s).toContain('data-testid="homeworks-import-run-now-btn"');
    expect(s).toContain("queuedCount > 0");
    expect(s).toContain('/integrations/homeworks/imports/dispatcher/tick');
  });
});

describe("Item 2 · Confirm-modal delta headline", () => {
  const src = read(import_center);
  it("renders a delta headline with data-testid + numeric count", () => {
    expect(src).toContain('data-testid="homeworks-import-delta-headline"');
    expect(src).toContain('data-testid="homeworks-import-delta-count"');
  });
  it("computes newCount from total - existing and flags 0-new re-runs", () => {
    expect(src).toContain("Math.max(0, knownCount - knownExisting)");
    expect(src).toContain("isNoop");
    expect(src).toMatch(/No new records/);
  });
  it("visually differentiates no-op vs. new-work state", () => {
    // Yellow scheme for no-op, green for new work.
    expect(src).toContain('"#FEF3C7"');
    expect(src).toContain('"#DCFCE7"');
  });
});

describe("Item 4 · Suppression Log deep-link from Demo toggle", () => {
  it("backend filter accepts recipient_id", () => {
    const src = read(comms_admin);
    expect(src).toContain('recipient_id: Optional[str] = Query(None)');
    expect(src).toContain('q["recipient_id"] = recipient_id');
  });
  it("DemoAccountToggle renders the deep-link", () => {
    const src = read(demo_toggle);
    expect(src).toContain('import { Link } from "react-router-dom"');
    expect(src).toContain("/admin/comms/suppression-log?recipient_id=");
    expect(src).toContain(
      'data-testid={`demo-flag-suppression-link-${recordType}-${recordId}`}',
    );
    // The prop is opt-out with a default of true.
    expect(src).toContain("showSuppressionLink = true");
  });
  it("Suppression Log page honours recipient_id from the query string", () => {
    const src = read(suppression_log);
    expect(src).toContain('import { useSearchParams } from "react-router-dom"');
    expect(src).toContain('searchParams.get("recipient_id")');
    expect(src).toContain(
      'data-testid="admin-suppression-log-recipient-filter-chip"',
    );
    expect(src).toContain(
      'data-testid="admin-suppression-log-recipient-filter-clear"',
    );
  });
});

describe("Item 3 · Config-driven importer_base refactor", () => {
  it("importer_base module exists", () => {
    expect(existsSync(importer_base)).toBe(true);
  });
  const base = read(importer_base);
  it("exposes the shared primitives", () => {
    expect(base).toContain("class RateLimiter");
    expect(base).toContain("async def load_run");
    expect(base).toContain("async def checkpoint");
    expect(base).toContain("async def cancel_flag_set");
    expect(base).toContain("class PagedDriverConfig");
    expect(base).toContain("async def run_paged_driver");
  });
  it("supports the driver contract used by the pricebook importer", () => {
    expect(base).toContain("import_one_fn");
    expect(base).toContain("counter_scanned");
    expect(base).toContain("counter_failed");
    expect(base).toContain("cascade_stop_after");
    expect(base).toContain("page_retries");
  });
  it("pricebook importer migrated to run_paged_driver", () => {
    const src = read(pricebook_imp);
    expect(src).toContain("from services.homeworks_mcp import importer_base");
    expect(src).toContain("_PRICEBOOK_DRIVER_CONFIG");
    expect(src).toContain("importer_base.PagedDriverConfig(");
    expect(src).toContain("importer_base.run_paged_driver(");
    // The old inline run driver — no longer expected in run_full.
    expect(src).not.toMatch(/while True:\s*if await _cancel_flag_set/);
  });
});
