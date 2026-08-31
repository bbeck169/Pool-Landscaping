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
    expect(SRC).toMatch(/import ArmToDelete from "@\/components\/ui\/ArmToDelete"/);
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
  const forbidden = [
    "src/pages/tenants/TenantsAdminPage.jsx",
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
