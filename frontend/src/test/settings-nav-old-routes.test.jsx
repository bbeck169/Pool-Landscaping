/**
 * Feb-2026 · Consolidated Settings Hub — router wiring guard.
 *
 * Locks in the routing choices made in the Feb-2026 hub migration:
 *   1. `<Route path="settings">` mounts `<AdminOnly><SettingsHub />
 *      </AdminOnly>` with an index route + `general` / `branding` /
 *      `integrations` / `social` NESTED child routes.
 *   2. The pre-hub sibling routes for `settings/branding` and
 *      `settings/integrations` are GONE — clicking a hub sidebar
 *      link must keep the hub shell visible.
 *   3. `settings/integrations/supercool` still lives as a top-
 *      level route (bare OAuth flow needs the full viewport, so
 *      it intentionally does NOT nest under the hub).
 *   4. `/settings/migration` and `/settings/users` (team) were
 *      removed from the sidebar per user brief — no dead entries.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const APP_SRC = readFileSync(
  resolve(__dirname, "../App.js"),
  "utf8",
);

const HUB_SRC = readFileSync(
  resolve(__dirname, "../layouts/SettingsHub.jsx"),
  "utf8",
);

describe("App.js · Settings hub route wiring", () => {
  it("mounts `<SettingsHub>` under `<AdminOnly>` at `/settings`", () => {
    // The hub route MUST be gated. Match the actual shipped shape
    // with whitespace flexibility.
    expect(APP_SRC).toMatch(
      /<Route\s+path="settings"\s+element=\{\s*<AdminOnly>\s*<SettingsHub\s*\/>\s*<\/AdminOnly>\s*\}\s*>/,
    );
  });

  it("has an index route rendering `<SettingsGeneral />`", () => {
    expect(APP_SRC).toMatch(
      /<Route\s+index\s+element=\{\s*<SettingsGeneral\s*\/>\s*\}\s*\/>/,
    );
  });

  it.each([
    ["general", /<SettingsGeneral/],
    ["branding", /<BrandLogoSettings/],
    ["integrations", /<IntegrationsHub/],
    ["social", /<SettingsSocial/],
  ])(
    "nests `settings/%s` as a CHILD route under the hub",
    (path, element) => {
      const re = new RegExp(
        `<Route\\s+path="${path}"\\s+element=\\{\\s*${element.source.replace("<", "<")}[^}]*\\}\\s*/>`,
      );
      expect(APP_SRC).toMatch(re);
    },
  );

  it("no sibling `Route path=\"settings/branding\"` route exists", () => {
    // The sibling route was removed when branding moved inside
    // the hub. Any resurrection would defeat the hub shell.
    expect(APP_SRC).not.toMatch(
      /<Route\s+path="settings\/branding"\s+element=\{\s*<AdminOnly>/,
    );
  });

  it("no sibling `Route path=\"settings/integrations\"` route exists", () => {
    // Feb-2026 · K55.a — the deeper ``settings/integrations/supercool``
    // sub-route was removed as part of the SuperCool + HomeWorks
    // sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md).  The literal
    // ``settings/integrations`` sibling should also be gone because
    // the hub route is now nested inside the SettingsHub above.
    expect(APP_SRC).not.toMatch(
      /<Route\s+path="settings\/integrations"\s+element=\{\s*<AdminOnly>\s*<IntegrationsHub\s*\/>\s*<\/AdminOnly>/,
    );
    // K55.a — no separate top-level supercool sub-route anymore.
    expect(APP_SRC).not.toMatch(
      /<Route\s+path="settings\/integrations\/supercool"\s+element/,
    );
  });
});

describe("SettingsHub · sidebar entries stay in sync with the router", () => {
  it("SECTIONS array contains exactly the canonical keys", () => {
    // Extract the SECTIONS declaration and count `key:` entries.
    // Phase I1.5.b · Feb-2026 — added ``theme`` (tenant palette
    // editor + live preview). Bumped from 4 → 5 canonical keys.
    // Feb-2026 · Business Settings feature — added ``business``
    // (brand identity, logo upload, primary/secondary hex).
    // Bumped from 5 → 6 canonical keys.
    // Feb-2026 · Multi-industry Phase B — added ``industries``
    // (25-checkbox multi-select tenant vertical picker).
    // Bumped from 6 → 7 → 9 canonical keys (Feb-2026: added
    // ``org-notifications`` for Ticket #3 + ``ai-configuration``
    // for Ticket #4).
    // Feb-2026 · Sprint 3b — added ``chemistry-configuration``
    // (per-tenant chemistry targets + dosing formulas).
    // Feb-2026 · Sprint 3c — added ``feature-marketplace``
    // (four premium add-ons: Zillow, SEO Heatmap, AI Analytics,
    // AI Copilot).
    // Feb-2026 · Phase P16 — added ``master-services`` (catalog
    // of services with name, category, default price).
    // Feb-2026 · Proposal Analytics feature — added
    // ``proposal-analytics``.
    // LDM-D · Feb-2026 — added ``automations`` (Manage Automations
    // tab with sliders for the four settings.automation_rules
    // fields; AI Live Dispatcher + Predictive Maintenance
    // thresholds).
    // Any future addition MUST update this list AND wire the
    // route in ``App.js``.
    const start = HUB_SRC.indexOf("const SECTIONS = [");
    const end = HUB_SRC.indexOf("];", start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const block = HUB_SRC.slice(start, end);
    const keys = (block.match(/key:\s*"([^"]+)"/g) || [])
      .map((s) => s.match(/"([^"]+)"/)[1]);
    expect(keys.sort()).toEqual(
      ["ai-configuration", "automations", "branding", "business",
        "chemistry-configuration", "feature-marketplace",
        "general", "industries", "integrations",
        "master-services", "org-notifications",
        "proposal-analytics", "social", "theme"],
    );
  });

  it("no `key: \"migration\"` or `key: \"team\"` entries remain", () => {
    // Regression guard — if either is re-added without a real
    // route, the sidebar link would 404.
    expect(HUB_SRC).not.toMatch(/key:\s*"migration"/);
    expect(HUB_SRC).not.toMatch(/key:\s*"team"/);
  });
});
