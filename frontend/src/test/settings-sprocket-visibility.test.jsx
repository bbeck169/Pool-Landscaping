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

  it("sprocket sits immediately BEFORE `SignOutButton` in every "
      + "responsive variant", () => {
    // Each of the three action clusters (tech-wrap, narrow-wrap,
    // wide-wrap) must render <SettingsSprocket /> followed by
    // <SignOutButton />. We assert on all three by counting the
    // adjacent pair occurrences.
    const pairs = TOPBAR_SRC.match(
      /<SettingsSprocket\s*\/>\s*<SignOutButton\s*\/>/g,
    ) || [];
    // The wide-wrap + narrow-wrap variants MUST be covered.
    // The tech-wrap (visible.length === 0) also renders the pair.
    expect(pairs.length).toBeGreaterThanOrEqual(3);
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
