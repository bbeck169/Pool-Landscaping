/**
 * Phase 54f · Feb-2026 — Pricebook supplier column + filter + Sync-all button.
 *
 * Web-side coverage. Mobile parity lives in
 * ``__tests__/phase54f-mobile-supplier-parity.test.tsx``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

// SupplierBadge is exposed via the OpsHub module. To avoid rendering
// the entire OpsHub page (heavy) we import the component structure
// through a lightweight source-inspection instead. That still catches
// the regressions we care about — wiring, testids, filter presence —
// with far less setup churn.

describe("Phase 54f — pricebook supplier column source wiring", () => {
  it("PriceBook function imports SUPPLIER_METADATA and defines SupplierBadge", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/ops/OpsHub.jsx"), "utf8");
    expect(src).toContain('from "@/pages/settings/supplier_metadata"');
    expect(src).toMatch(/function SupplierBadge\(\{ slug, testid \}\)/);
    expect(src).toMatch(/data-testid="pb-supplier-filter"/);
    expect(src).toMatch(/pb-supplier-badge-\$\{r\.id\}/);
  });

  it("PriceBook applies the filter via filteredRows (client-side, additive)", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/ops/OpsHub.jsx"), "utf8");
    // The filter is a client-side useMemo — do NOT change the /items
    // endpoint contract.
    expect(src).toMatch(/const filteredRows = useMemo/);
    expect(src).toMatch(/supplier_slug\s*\|\|\s*""/);
    // The badge palette carries all five wired slugs.
    for (const slug of ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(src).toContain(slug);
    }
  });
});


describe("Phase 54f — SupplierSettings sync-all button", () => {
  it("Sync all button + progress state wired via source", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/settings/SupplierSettings.jsx"), "utf8");
    expect(src).toMatch(/data-testid="supplier-settings-sync-all-btn"/);
    expect(src).toMatch(/syncAllProgress/);
    // Super-admin only — admin doesn't get the button.
    expect(src).toMatch(/isSuperAdmin\s*=\s*role === "super_admin"/);
    // Sequential fire — no Promise.all around the sync calls.
    const bodyBetween = src.split("const syncAll")[1]?.split("finally")[0] || "";
    expect(bodyBetween).not.toMatch(/Promise\.all/);
    // no_credentials-friendly — the loop catches that error class.
    expect(bodyBetween).toMatch(/no_credentials/);
  });
});


describe("Phase 54f — parity guardrails", () => {
  it("web + mobile pricebook both render a supplier badge testid", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const web = fs.readFileSync(
      path.resolve(__dirname, "../pages/ops/OpsHub.jsx"), "utf8");
    const mobile = fs.readFileSync(
      path.resolve(__dirname, "../../../mobile/app/price-book.tsx"), "utf8");
    expect(web).toContain("pb-supplier-badge-");
    expect(mobile).toContain("item-supplier-badge-");
  });

  it("web + mobile share the same wired supplier slug set (source-level)", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const meta = fs.readFileSync(
      path.resolve(__dirname, "../pages/settings/supplier_metadata.js"), "utf8");
    const mobile = fs.readFileSync(
      path.resolve(__dirname, "../../../mobile/app/price-book.tsx"), "utf8");
    for (const slug of ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(meta).toContain(slug);
      expect(mobile).toContain(slug);
    }
  });
});

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());
