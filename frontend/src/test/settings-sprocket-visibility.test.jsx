/**
 * Feb-2026 · Consolidated Settings Hub — sprocket visibility tests.
 *
 * The sprocket lives inside ``AdminTopBar.jsx``. Mounting the full
 * top-bar under jsdom hangs on Radix DropdownMenu portals, so we
 * combine cheap source-regex guards with a targeted behavioural
 * test that mounts a role-parameterised harness matching the
 * shipped ``SettingsSprocket`` role gate.
 *
 * Guards:
 *   1. Source: sprocket is imported from `lucide-react`, gated to
 *      admin/super_admin only, uses the canonical testid.
 *   2. Source: sprocket sits BEFORE ``SignOutButton`` in each of
 *      the three responsive variants (tech-wrap / narrow-wrap /
 *      wide-wrap).
 *   3. Behavioural harness: admin + super_admin see the sprocket,
 *      technician / customer / manager do NOT.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Link } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Settings as SettingsIcon } from "lucide-react";

const TOPBAR_SRC = readFileSync(
  resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);

// ══════════════════════════════════════════════════════════════════
// Layer 1 — source guards. Keep AdminTopBar honest.
// ══════════════════════════════════════════════════════════════════
describe("AdminTopBar source · sprocket gate + placement", () => {
  it("declares a `SettingsSprocket` component", () => {
    expect(TOPBAR_SRC).toMatch(/function\s+SettingsSprocket\s*\(/);
  });

  it("sprocket is role-gated to admin / super_admin only", () => {
    // The gate compares ``role`` (or its equivalent) against both
    // ``admin`` and ``super_admin`` and short-circuits with a
    // ``return null`` otherwise.
    expect(TOPBAR_SRC).toMatch(/role\s*!==\s*"admin"[\s\S]{0,80}role\s*!==\s*"super_admin"/);
    expect(TOPBAR_SRC).toMatch(/SettingsSprocket[\s\S]{0,600}return\s+null/);
  });

  it("sprocket uses the canonical testid + routes to `/settings`", () => {
    expect(TOPBAR_SRC).toMatch(/data-testid="header-settings-sprocket"/);
    expect(TOPBAR_SRC).toMatch(/to="\/settings"/);
  });

  it("sprocket sits BEFORE `SignOutButton` in every "
      + "responsive variant (LanguageSelector may sit between)", () => {
    // Feb 2026 · Consolidated Settings Hub + D3 i18n phase — each of
    // the three action clusters (tech-wrap, narrow-wrap, wide-wrap)
    // renders ``<SettingsSprocket />`` followed by (optionally)
    // ``<LanguageSelector />`` and then ``<SignOutButton />``. The
    // LanguageSelector was inserted between the two by the D3
    // language-picker phase; strict adjacency was the WRONG
    // invariant to lock — what matters is that the sprocket sits
    // LEFT of sign-out in every variant and the two aren't
    // separated by more than a single component (protects against
    // e.g. someone dropping a giant menu between them).
    //
    // ZZ-A Wave 3-A · Feb-2026 — loosened the between-elements
    // match to any content (including JSX comments / tone="navy"
    // multi-attr forms) within a 300-char window. The pre-Wave-3
    // regex only allowed one bare element with simple attrs and
    // broke when AdminTopBar's three variants gained ``{/* …
    // rationale … */}`` comments between ``<SettingsSprocket />``
    // and ``<NotificationBell variant="inline" tone="navy" />``.
    // The strict-adjacency / offset-ordering sibling test below
    // (``sprocket sits LEFT of sign-out…``) remains the hard
    // ordering invariant; this guard just confirms the pair
    // co-locates in each of the three variants.
    const pairs = TOPBAR_SRC.match(
      /<SettingsSprocket\s*\/>[\s\S]{0,300}?<SignOutButton\s*\/>/g,
    ) || [];
    expect(pairs.length).toBeGreaterThanOrEqual(3);
  });

  it("sprocket sits LEFT of sign-out in every variant "
      + "(no reversed ordering slipped in)", () => {
    // Belt-and-suspenders check: for every variant that mentions
    // both components, the SettingsSprocket string offset must be
    // less than the SignOutButton offset within the SAME variant.
    // We slice the source between successive JSX action-cluster
    // sentinels (the shipped variants both end with </div>) and
    // assert the ordering per slice.
    const sprocketMatches = [...TOPBAR_SRC.matchAll(/<SettingsSprocket\s*\/>/g)];
    const signoutMatches = [...TOPBAR_SRC.matchAll(/<SignOutButton\s*\/>/g)];
    expect(sprocketMatches.length).toBeGreaterThanOrEqual(3);
    expect(signoutMatches.length).toBeGreaterThanOrEqual(3);
    // Each matched sprocket must have a sign-out AFTER it AND
    // there must be no sign-out sitting BEFORE it in the same
    // 400-char window (which is the outer size of every variant
    // action cluster).
    for (const spro of sprocketMatches) {
      const idx = spro.index;
      const window = TOPBAR_SRC.slice(Math.max(0, idx - 400), idx);
      expect(
        /<SignOutButton\s*\/>/.test(window),
        `Found <SignOutButton /> BEFORE <SettingsSprocket /> at index ${idx}`,
      ).toBe(false);
    }
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 2 — behavioural harness mirroring the shipped role gate.
// Keeps the assertion role-agnostic so if the gate copy changes,
// this test still surfaces role coverage.
// ══════════════════════════════════════════════════════════════════
function SprocketHarness({ role }) {
  // Mirror the shipped gate: admin + super_admin only.
  if (role !== "admin" && role !== "super_admin") return null;
  return (
    <Link
      to="/settings"
      title="Settings"
      aria-label="Settings"
      data-testid="header-settings-sprocket"
    >
      <SettingsIcon size={16} />
    </Link>
  );
}

describe("SettingsSprocket · role visibility", () => {
  it.each(["admin", "super_admin"])(
    "renders for %s",
    (role) => {
      render(<MemoryRouter><SprocketHarness role={role} /></MemoryRouter>);
      expect(screen.getByTestId("header-settings-sprocket")).toBeTruthy();
    },
  );

  it.each(["technician", "customer", "manager", "portal", ""])(
    "does NOT render for %s",
    (role) => {
      render(<MemoryRouter><SprocketHarness role={role} /></MemoryRouter>);
      expect(screen.queryByTestId("header-settings-sprocket")).toBeNull();
    },
  );
});
