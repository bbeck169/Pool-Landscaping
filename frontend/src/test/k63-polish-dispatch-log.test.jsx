/**
 * Phase K63.polish · Feb-2026 — Lead Alerts chip + dispatch log modal.
 *
 * Two-layer contract:
 *   1. ``pickChip`` — pure-function state → { label, tone } mapping.
 *      Drives the row-level "last activity" chip. Covers all five
 *      states (none / success / neutral / warning / danger).
 *   2. Source-body contract on ``LeadAlertsSettings.jsx`` — the
 *      chip cell is rendered per row with the correct testid,
 *      opens a modal on click, and refreshes the log after save.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

import { pickChip } from "../pages/settings/LeadAlertsSettings.jsx";

const SETTINGS_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/settings/LeadAlertsSettings.jsx"),
  "utf-8",
);


describe("pickChip · K63.polish tone selection", () => {
  const now = Date.parse("2026-02-15T12:00:00Z");

  it("no dispatch rows → 'No sends yet' / muted", () => {
    const c = pickChip(null, now);
    expect(c.label).toMatch(/No sends yet/i);
    expect(c.tone).toBe("muted");
  });

  it("last row sent < 24h ago → success", () => {
    const c = pickChip({
      status: "sent",
      created_at: "2026-02-15T11:57:00Z",  // 3 min before
    }, now);
    expect(c.tone).toBe("success");
    expect(c.label).toMatch(/Last:/i);
    expect(c.label).toMatch(/min ago/i);
  });

  it("last row sent between 24h and 14d → neutral", () => {
    const c = pickChip({
      status: "sent",
      created_at: "2026-02-13T12:00:00Z",  // 2 days before
    }, now);
    expect(c.tone).toBe("neutral");
    expect(c.label).toMatch(/2 days ago/);
  });

  it("last row sent > 14d ago → warning", () => {
    const c = pickChip({
      status: "sent",
      created_at: "2026-01-20T12:00:00Z",  // 26 days before
    }, now);
    expect(c.tone).toBe("warning");
    expect(c.label).toMatch(/Silent 14\+ days/i);
  });

  it("last row failed → danger regardless of age", () => {
    const c = pickChip({
      status: "failed",
      created_at: "2026-02-15T11:55:00Z",  // 5 min before
    }, now);
    expect(c.tone).toBe("danger");
    expect(c.label).toMatch(/Last attempt failed/i);
    expect(c.label).toMatch(/5 min ago/i);
  });
});


describe("LeadAlertsSettings · K63.polish source-body contract", () => {
  it("fetches the dispatch log on mount + after save", () => {
    expect(SETTINGS_SRC).toMatch(
      /api\.get\(\s*"\/admin\/notification-dispatch-log\?limit=200"/,
    );
    // Save calls loadDispatchLog after a successful PUT.
    expect(SETTINGS_SRC).toMatch(/setTimeout\(\(\) => setToast\(""\), 2500\);\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*loadDispatchLog\(\);/);
  });

  it("renders a per-row chip button with testid + tone attr", () => {
    expect(SETTINGS_SRC).toMatch(/`lead-alerts-chip-\$\{idx\}`/);
    expect(SETTINGS_SRC).toMatch(/data-chip-tone=\{chip\.tone\}/);
  });

  it("chip clicks open the drill-down modal via the endpoint", () => {
    expect(SETTINGS_SRC).toMatch(
      /api\.get\(`\/admin\/notification-dispatch-log\?\$\{q\}`\)/,
    );
    expect(SETTINGS_SRC).toMatch(/data-testid="dispatch-log-modal"/);
    expect(SETTINGS_SRC).toMatch(/data-testid="dispatch-log-modal-close"/);
    expect(SETTINGS_SRC).toMatch(/data-testid="dispatch-log-modal-table"/);
    expect(SETTINGS_SRC).toMatch(/data-testid="dispatch-log-modal-empty"/);
    expect(SETTINGS_SRC).toMatch(/`dispatch-log-modal-row-\$\{i\}`/);
  });

  it("modal renders per-row status, channel, lead id, details", () => {
    // Failure rows must surface ``error`` (never the raw HTML body).
    expect(SETTINGS_SRC).toMatch(/failed\s*\?\s*\(row\.error \|\| "unknown error"\)/);
    // Success rows expose ``provider_message_id`` as the details cell.
    expect(SETTINGS_SRC).toMatch(/\(row\.provider_message_id \|\| ""\)/);
  });

  it("modal fetch uses limit=20 per the K63.polish contract", () => {
    expect(SETTINGS_SRC).toMatch(/limit:\s*"20"/);
  });
});
