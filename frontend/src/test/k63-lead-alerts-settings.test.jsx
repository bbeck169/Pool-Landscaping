/**
 * Phase K63 · Feb-2026 — LeadAlertsSettings source-body contract.
 *
 * Locks the invariants for the per-tenant Lead Alerts recipient
 * CRUD Settings UI:
 *   - Talks to the K63 endpoint pair.
 *   - Recipient cap of 10 with a counter + Add button gating.
 *   - E.164 phone hint + row-level validation errors.
 *   - Save button disabled until row validation passes + form is
 *     dirty.
 *   - NotificationPrefs mounts a link card to the new page.
 *   - App.js wires ``/settings/notifications/lead-alerts`` inside
 *     AdminOnly.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SETTINGS_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/settings/LeadAlertsSettings.jsx"),
  "utf-8",
);

const PREFS_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/settings/NotificationPrefs.jsx"),
  "utf-8",
);

const APP_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/App.js"),
  "utf-8",
);


describe("LeadAlertsSettings · K63 recipient CRUD", () => {
  it("hits the K63 tenant-scoped endpoint pair", () => {
    expect(SETTINGS_SRC).toMatch(
      /api\.get\(\s*`\/tenants\/\$\{t\.id\}\/settings\/lead-notifications`/,
    );
    expect(SETTINGS_SRC).toMatch(
      /api\.put\(\s*`\/tenants\/\$\{tenantId\}\/settings\/lead-notifications`/,
    );
  });

  it("caps recipients at 10 and disables the Add button when full", () => {
    expect(SETTINGS_SRC).toMatch(/rows\.length\s*>=\s*10/);
    expect(SETTINGS_SRC).toMatch(/data-testid="lead-alerts-add"/);
    expect(SETTINGS_SRC).toMatch(/disabled=\{rows\.length\s*>=\s*10\}/);
  });

  it("renders an X/10 recipient counter with a testid", () => {
    expect(SETTINGS_SRC).toMatch(/data-testid="lead-alerts-count"/);
    expect(SETTINGS_SRC).toMatch(/\{rows\.length\}\/10 recipients/);
  });

  it("shows the E.164 phone format hint in the row placeholder", () => {
    // The row-level phone input uses +16028874400 as its placeholder
    // — the format expected by the backend validator.
    expect(SETTINGS_SRC).toMatch(/placeholder="\+16028874400"/);
  });

  it("validates rows and gates Save on all rows passing", () => {
    // Save is disabled when ANY row has a non-empty errors array.
    expect(SETTINGS_SRC).toMatch(
      /const canSave = dirty && !saving && rowErrors\.every\(\(e\) => e\.length === 0\)/,
    );
    expect(SETTINGS_SRC).toMatch(/data-testid="lead-alerts-save"/);
    expect(SETTINGS_SRC).toMatch(/disabled=\{!canSave\}/);
  });

  it("validates E.164 phones and email formats per row", () => {
    expect(SETTINGS_SRC).toMatch(/const _E164 = \/\^\\\+\[1-9\]\\d\{9,14\}\$\//);
    expect(SETTINGS_SRC).toMatch(/const _EMAIL = \/\^\[\^@\\s\]\+@\[\^@\\s\]\+\\\.\[\^@\\s\]\+\$\//);
  });

  it("has row-level per-recipient testids for Playwright drives", () => {
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-name-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-email-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-phone-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-email-optin-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-sms-optin-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-remove-\$\{idx\}`/);
  });
});


describe("NotificationPrefs · K63 link-card wiring", () => {
  it("renders the Lead Alerts card + Manage recipients button", () => {
    expect(PREFS_SRC).toMatch(/data-testid="k63-lead-alerts-link-card"/);
    expect(PREFS_SRC).toMatch(/data-testid="k63-lead-alerts-open"/);
    expect(PREFS_SRC).toMatch(
      /nav\(\s*"\/settings\/notifications\/lead-alerts"\s*\)/,
    );
  });
});


describe("App.js · K63 route wiring", () => {
  it("mounts /settings/notifications/lead-alerts inside AdminOnly", () => {
    // Guards against the page shipping without a role gate.
    expect(APP_SRC).toMatch(
      /path="settings\/notifications\/lead-alerts"\s+element=\{<AdminOnly><LeadAlertsSettings\s*\/><\/AdminOnly>\}/,
    );
  });

  it("imports the LeadAlertsSettings page component", () => {
    expect(APP_SRC).toMatch(
      /import\s+LeadAlertsSettings\s+from\s+"@\/pages\/settings\/LeadAlertsSettings"/,
    );
  });
});
