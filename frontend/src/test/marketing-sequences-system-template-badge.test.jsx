/**
 * Feb 2026 · Task B — SYSTEM TEMPLATE badge on the marketing
 * sequences list.
 *
 * Source-parse coverage — asserts the sequence-row renderer:
 *   1. Reads ``r.system_template`` and gates a distinct badge on it.
 *   2. Uses a violet palette (background ``#EDE9FE``, text
 *      ``#5B21B6``) so it's visually distinct from the existing
 *      blue "SEED" badge.
 *   3. Attaches a stable ``data-testid`` so downstream Playwright
 *      / testing_agent can grip the badge without brittle CSS
 *      selectors.
 *   4. Keeps the pre-existing SEED badge (``r.system``) rendering
 *      unchanged — regression guard against accidental removal.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/marketing/MarketingSequencesPage.jsx"),
  "utf8",
);

describe("Task B · Marketing Sequences · SYSTEM TEMPLATE badge", () => {
  it("renders a badge gated on r.system_template", () => {
    // Badge only renders when the flag is truthy — matches the
    // pattern used by the existing SEED badge for r.system.
    expect(SRC).toMatch(/\{r\.system_template\s*\?/);
    // The gated JSX branch contains the badge text.
    const gateIdx = SRC.search(/\{r\.system_template\s*\?/);
    const badgeIdx = SRC.indexOf("SYSTEM TEMPLATE", gateIdx);
    expect(badgeIdx).toBeGreaterThan(gateIdx);
    // Falsy fallback is `: null` (regression guard — no accidental
    // rendering when the flag is off).
    expect(SRC).toMatch(/\{r\.system_template\s*\?[\s\S]{0,900}\)\s*:\s*null\}/);
  });

  it("uses the violet palette to differentiate from the blue SEED badge", () => {
    // Background + text color chosen from the design guidelines'
    // violet accent family. Any change to these hex values needs
    // a design review — that's why we assert the exact colors.
    expect(SRC).toMatch(/backgroundColor:\s*["']#EDE9FE["']/);
    expect(SRC).toMatch(/color:\s*["']#5B21B6["']/);
  });

  it("attaches a stable data-testid for downstream selectors", () => {
    // The testid embeds the sequence id so multiple badges on the
    // same list don't collide.
    expect(SRC).toMatch(/data-testid=\{`sequence-system-template-badge-\$\{r\.id\}`\}/);
  });

  it("preserves the pre-existing SEED badge (regression guard)", () => {
    // The older SEED badge (r.system) must still render — the two
    // are additive, not mutually exclusive.
    expect(SRC).toMatch(/\{r\.system\s*\?\s*\(?\s*[\s\S]{0,400}SEED/);
    expect(SRC).toMatch(/backgroundColor:\s*["']#DBEAFE["']/);
    expect(SRC).toMatch(/color:\s*["']#1E3A8A["']/);
  });

  it("the SYSTEM TEMPLATE badge is rendered INSIDE the sequence row (not stray)", () => {
    // Positional guard — badge must sit between the row's opening
    // ``<td className="py-3 px-3"`` cell and its closing ``</td>``
    // so it renders next to the sequence name.
    const badgeIdx = SRC.indexOf("SYSTEM TEMPLATE");
    const nameCellIdx = SRC.indexOf(`{r.name}`);
    // Badge sits AFTER the name (name-first, badge inline after).
    expect(badgeIdx).toBeGreaterThan(nameCellIdx);
    // And BEFORE the next column ``TriggerBadge``.
    const nextColIdx = SRC.indexOf(
      "<TriggerBadge type={r.trigger_type} />",
      nameCellIdx,
    );
    expect(badgeIdx).toBeLessThan(nextColIdx);
  });
});
