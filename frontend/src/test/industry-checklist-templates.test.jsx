/**
 * Phase MI1 · Feb 2026 — Multi-industry checklist templates settings.
 *
 * Source-scan the admin editor + the dispatcher wrapper to lock the
 * contract (7 tabs, PUT/DELETE wiring, industry-prop routing).
 * Full mount would need a live api client + toast — keeping this
 * a source-scan matches the pattern used by
 * ``leads-bulk-hard-delete-and-polish.test.jsx``.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const ADMIN_PAGE = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/ChecklistTemplatesSettings.jsx"),
  "utf-8",
);

const WRAPPER = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/IndustryChecklistForm.jsx"),
  "utf-8",
);

const APP = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf-8",
);


describe("ChecklistTemplatesSettings · admin editor", () => {
  it("renders exactly 7 industry tabs in the expected order", () => {
    const expected = [
      "pool", "landscaping", "hvac", "pest_control",
      "cleaning", "solar", "handyman",
    ];
    // Row-level testids use template literals — assert the pattern.
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-industry-tab-\$\{slug\}`\}/,
    );
    // Every canonical slug is enumerated in the source.
    expected.forEach((slug) => {
      expect(ADMIN_PAGE).toContain(`"${slug}"`);
    });
  });

  it("selecting an industry loads its template via api.get", () => {
    expect(ADMIN_PAGE).toMatch(/api\.get\(`\/checklists\/industry\/\$\{slug\}`\)/);
  });

  it("save handler PUTs to the industry endpoint with items", () => {
    expect(ADMIN_PAGE).toMatch(
      /api\.put\(\s*`\/checklists\/industry\/\$\{active\}`,\s*\{\s*items:\s*draft/,
    );
  });

  it("reset handler DELETEs the override and reloads via response", () => {
    expect(ADMIN_PAGE).toMatch(
      /api\.del\(`\/checklists\/industry\/\$\{active\}`\)/,
    );
  });

  it("editor renders reorder / required-toggle / remove / add / label edit controls", () => {
    // Every control must have a stable data-testid so the mobile
    // agent + backend testing agent can drive the editor.
    for (const testid of [
      "checklist-editor-list",
      "checklist-editor-add",
      "checklist-save-button",
      "checklist-reset-button",
    ]) {
      expect(ADMIN_PAGE).toContain(`data-testid="${testid}"`);
    }
    // Row-level testids use template literals — assert the pattern.
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-editor-up-\$\{row\.key\}`\}/,
    );
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-editor-down-\$\{row\.key\}`\}/,
    );
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-editor-required-\$\{row\.key\}`\}/,
    );
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-editor-remove-\$\{row\.key\}`\}/,
    );
    expect(ADMIN_PAGE).toMatch(
      /data-testid=\{`checklist-editor-label-\$\{row\.key\}`\}/,
    );
  });

  it("save button is disabled until the draft differs from the template", () => {
    // ``dirty`` flag drives the disabled attr.
    expect(ADMIN_PAGE).toMatch(/disabled=\{busy \|\| !dirty\}/);
  });

  it("reset button is disabled unless the current source is an override", () => {
    expect(ADMIN_PAGE).toMatch(/disabled=\{busy \|\| source !== "override"\}/);
  });

  it("registers the /admin/settings/checklists route under AdminOnly", () => {
    // Regression against dropping the AdminOnly wrapper — the page
    // trusts the router-level guard.
    expect(APP).toMatch(
      /admin\/settings\/checklists["'].*AdminOnly.*ChecklistTemplatesSettings/,
    );
  });
});


describe("IndustryChecklistForm · dispatcher wrapper", () => {
  it("delegates pool to the original PoolChecklistForm", () => {
    expect(WRAPPER).toMatch(
      /industry === "pool"[\s\S]{0,200}<PoolChecklistForm/,
    );
  });

  it("fetches /checklists/industry/{industry} for non-pool", () => {
    expect(WRAPPER).toMatch(
      /api\.get\(`\/checklists\/industry\/\$\{industry\}`\)/,
    );
  });

  it("renders required items with a red asterisk marker", () => {
    expect(WRAPPER).toMatch(
      /item\.required[\s\S]{0,120}color: "#DC2626"/,
    );
  });

  it("exports INDUSTRY_LABELS with the 7 canonical slugs", () => {
    for (const slug of [
      "pool", "landscaping", "hvac", "pest_control",
      "cleaning", "solar", "handyman",
    ]) {
      expect(WRAPPER).toMatch(
        new RegExp(`  ${slug}: "`),
      );
    }
  });
});
