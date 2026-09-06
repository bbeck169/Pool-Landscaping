/**
 * Phase F5 · Feb-2026 — TenantsAdminPage widget-key rotate is
 * gated by ArmToDelete (catastrophic — breaks every live external
 * embed). Source-body contract check.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/tenants/TenantsAdminPage.jsx"),
  "utf-8",
);

describe("TenantsAdminPage · F5 widget-key rotate retrofit", () => {
  it("imports ArmToDelete", () => {
    expect(SRC).toMatch(/import\s+ArmToDelete\s+from\s+"@\/components\/ui\/ArmToDelete"/);
  });

  it("no longer uses window.confirm for the rotate action", () => {
    // regenerate() body may not include window.confirm anymore.
    const idx = SRC.indexOf("const regenerate = async");
    expect(idx).toBeGreaterThan(-1);
    const slice = SRC.slice(idx, idx + 800);
    expect(slice).not.toMatch(/window\.confirm/);
  });

  it("renders ArmToDelete on the Regenerate affordance", () => {
    expect(SRC).toMatch(
      /<ArmToDelete[\s\S]{0,400}testIdPrefix="tenant-widget-key-regenerate"/,
    );
    expect(SRC).toMatch(
      /onConfirm=\{regenerate\}/,
    );
  });
});

describe("F5 · destructive-copy sweep (regression guard)", () => {
  // Files that must be totally free of ``window.confirm(``.
  const forbidden = [
    "src/pages/tenants/TenantsAdminPage.jsx",
    // Phase H2 · Feb-2026 (F5 Wave 2) — two more catastrophic sites.
    "src/pages/marketing/M2Campaigns.jsx",
    // Phase H3 · Feb-2026 — QB revoke migrated to useConfirmDelete
    // with typedKeyword="REVOKE". No raw window.confirm remains.
    "src/pages/admin/integrations/QuickBooksIntegrationPage.jsx",
  ];

  it("catastrophic files no longer contain window.confirm", () => {
    for (const rel of forbidden) {
      const src = fs.readFileSync(
        path.resolve(process.cwd(), rel), "utf-8",
      );
      expect(src, `${rel} must not contain window.confirm`)
        .not.toMatch(/window\.confirm\(/);
    }
  });
});


// ─── Phase H2 · Feb-2026 (F5 Wave 2) — per-file retrofit contracts ─────
describe("H2 · Deactivate tenant retrofit (TenantsAdminPage)", () => {
  const src = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/tenants/TenantsAdminPage.jsx"),
    "utf-8",
  );
  it("imports TypedConfirmModal", () => {
    expect(src).toMatch(/import\s+TypedConfirmModal\s+from\s+"@\/components\/ui\/TypedConfirmModal"/);
  });
  it("gates deactivate through requestToggleActive → typed slug confirm", () => {
    expect(src).toMatch(/requestToggleActive/);
    expect(src).toMatch(/setH2DeactivateTarget/);
    expect(src).toMatch(/testIdPrefix="h2-tenant-deactivate"/);
    expect(src).toMatch(/keyword=\{h2DeactivateTarget\?\.slug \|\| ""\}/);
  });
  it("copy calls out the tenant slug", () => {
    expect(src).toMatch(/tenant slug \(\$\{h2DeactivateTarget\.slug\}\)/);
  });
});

describe("H2 · QB force-sync retrofit (QuickBooksIntegrationPage)", () => {
  const src = fs.readFileSync(
    path.resolve(process.cwd(),
        "src/pages/admin/integrations/QuickBooksIntegrationPage.jsx"),
    "utf-8",
  );
  it("imports TypedConfirmModal", () => {
    expect(src).toMatch(/import\s+TypedConfirmModal\s+from\s+".*TypedConfirmModal"/);
  });
  it("gates the force-full path behind h2ForceOpen state", () => {
    expect(src).toMatch(/setH2ForceOpen\(true\)/);
    expect(src).toMatch(/testIdPrefix="h2-qb-force-sync"/);
  });
  it("keyword is exactly 'FORCE SYNC' and copy warns about API budget", () => {
    expect(src).toMatch(/keyword="FORCE SYNC"/);
    expect(src).toMatch(/consumes API budget/);
  });
});

describe("H2 · Campaign cancel retrofit (M2Campaigns)", () => {
  const src = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/marketing/M2Campaigns.jsx"),
    "utf-8",
  );
  it("imports TypedConfirmModal", () => {
    expect(src).toMatch(/import\s+TypedConfirmModal\s+from\s+"@\/components\/ui\/TypedConfirmModal"/);
  });
  it("gates the cancel POST behind h2CancelTarget state", () => {
    expect(src).toMatch(/setH2CancelTarget/);
    expect(src).toMatch(/testIdPrefix="h2-campaign-cancel"/);
    expect(src).toMatch(/keyword=\{h2CancelTarget\?\.name \|\| ""\}/);
  });
  it("cancel POST hits the campaign cancel endpoint only from _doCancel", () => {
    // The old ``cancel(cid)`` no longer posts directly; it opens the
    // modal.  The POST lives inside ``_doCancel`` which the modal's
    // onConfirm fires.
    expect(src).toMatch(
      /_doCancel[\s\S]{0,400}api\.post\(`\/marketing\/campaigns\/\$\{h2CancelTarget\.id\}\/cancel`/,
    );
  });
});

