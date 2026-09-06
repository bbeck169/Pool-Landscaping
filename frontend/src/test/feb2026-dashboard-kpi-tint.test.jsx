/**
 * Feb 2026 · Color pass — KPI tile source-of-truth contract.
 *
 * The Dashboard's KpiCard now applies a tone-driven left border,
 * icon tint, and soft background. We source-lint the JSX so a
 * regression (someone stripping the ``tone`` prop off a KpiCard
 * or reverting the palette usage) surfaces at CI time — same
 * pattern the Stripe cards use.
 *
 * We deliberately don't full-mount Dashboard here because it
 * touches ~30 API endpoints on load. The regex checks lock in
 * the four spec-required assertions:
 *   1. KpiCard accepts a ``tone`` prop.
 *   2. Every dashboard KpiCard invocation ships a ``tone=`` value.
 *   3. KpiCard reads its palette via ``getAccentTone(tone)``.
 *   4. Colored left border (``4px solid``) uses the palette 500
 *      shade.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
  "utf8",
);


describe("Dashboard · KpiCard tone-driven palette", () => {
  it("KpiCard accepts a ``tone`` prop", () => {
    expect(SRC).toMatch(
      /function KpiCard\(\s*\{[^}]*\btone\b[^}]*\}\s*\)/,
    );
  });

  it("KpiCard resolves the palette via getAccentTone(tone)", () => {
    expect(SRC).toMatch(
      /const\s+palette\s*=\s*getAccentTone\(\s*tone\s*\)/,
    );
  });

  it("Left border reads ``4px solid ${palette[500]}``", () => {
    expect(SRC).toMatch(
      /borderLeft:\s*`4px solid \$\{palette\[500\]\}`/,
    );
  });

  it("Card background reads palette[50] (soft tint)", () => {
    expect(SRC).toMatch(/backgroundColor:\s*palette\[50\]/);
  });

  it("Icon wrapper reads palette[100] + palette[600]", () => {
    // Phase K70.a superseded the palette-driven icon chip: the
    // chip carried the shared K67 navy → green gradient.
    // Phase K74 superseded that with solid navy
    // (``colors.tile.solidNavy`` == #1B1F5C). The tone-driven
    // pastel BACKGROUND + colored left border are preserved
    // (checked above), only the icon-chip fill moved twice.
    // Assertion flipped so the K70 palette-driven shape is
    // explicitly forbidden; the K74 shape is asserted below.
    expect(SRC).not.toMatch(
      /backgroundColor:\s*palette\[100\][\s\S]{0,60}color:\s*palette\[600\]/,
    );
  });

  it("Phase K74 — icon chip carries solid colors.tile.solidNavy (#1B1F5C)", () => {
    // K74 · Feb-2026 — replaces the K70.a
    // ``gradients.navyToGreen.css`` icon-chip background with
    // the solid navy token ``colors.tile.solidNavy`` (== #1B1F5C).
    // The icon glyph stays white (AAA @ 12.8:1 on navy).
    //
    // Icon chip uses the canonical solid navy token.
    expect(SRC).toMatch(
      /backgroundColor:\s*colors\.tile\.solidNavy/,
    );
    // Icon color is white (reads at AAA 12.8:1 on #1B1F5C).
    expect(SRC).toMatch(
      /backgroundColor:\s*colors\.tile\.solidNavy[\s\S]{0,120}color:\s*["']#FFFFFF["']/,
    );
    // Every KpiCard tile exposes a K74 data attribute the
    // contract test can grep for without a full mount.
    expect(SRC).toMatch(/data-k74-solid-navy-chip="true"/);
    // Negative: the K70.a gradient chip attribute is retired
    // on Dashboard (the shared R0 KpiCard still uses gradient).
    expect(SRC).not.toMatch(/data-k70a-gradient-chip="true"/);
    // Negative: the icon chip inline style no longer reaches
    // for ``gradients.navyToGreen.css``. (``gradients`` is still
    // imported for the RevenueByService progress bar below.)
    const startIdx = SRC.indexOf("function KpiCard(");
    const endIdx = SRC.indexOf("function ReferralRevenueTile(");
    const kpiCardSlice = SRC.slice(startIdx, endIdx);
    expect(kpiCardSlice).not.toMatch(/background:\s*gradients\.navyToGreen\.css/);
  });

  it("All four dashboard KpiCard invocations declare a ``tone`` prop", () => {
    // Slice the KPI grid block so we don't count KpiCard's own
    // definition (which reads ``tone`` as a parameter, not a
    // prop). Anchor on the JSX comment markers surrounding the
    // grid so ``Referral Revenue`` earlier-in-file mentions
    // don't confuse the slice.
    const startIdx = SRC.indexOf("{/* KPI grid */}");
    const endIdx = SRC.indexOf(
      "{/* Referral Revenue tile — Phase 20B module B */}");
    expect(startIdx).toBeGreaterThan(-1);
    expect(endIdx).toBeGreaterThan(startIdx);
    const block = SRC.slice(startIdx, endIdx);
    const invocations = block.match(/<KpiCard\b[\s\S]*?\/>/g) || [];
    expect(invocations.length).toBeGreaterThanOrEqual(4);
    for (const inv of invocations) {
      expect(inv).toMatch(/\btone=\{?["']?[a-z]+["']?\}?/i);
    }
  });

  it("Revenue chart bar palette uses accent tokens (not the legacy brand only)", () => {
    // Any of the accent hues will do — the point is: no more
    // "if isLast → brand else brandTertiary" bi-tone stripe.
    expect(SRC).toMatch(/getAccentTone\(/);
    // And the "most recent bar" branch now uses the pool primary
    // (matches the "Pool = blue/cyan" contract from the color-pass
    // spec).
    expect(SRC).toMatch(/colors\.pool\[500\]/);
  });
});
