/**
 * Phase K54 · Feb-2026 — solid destructive-red parity sweep.
 *
 * Locks the following contract app-wide:
 *
 *   • ``theme.js`` exposes a ``colors.destructive`` block with
 *     ``bg #DC2626`` (red-600), ``bgHover #B91C1C`` (red-700),
 *     ``fg #FFFFFF``, ``ring #EF4444`` (red-500) and
 *     ``disabledOpacity 0.55``.
 *   • ``components/ui/button.jsx`` ``destructive`` variant paints
 *     exactly those hexes via Tailwind arbitrary values.  ``theme.js``
 *     is the single source of truth — if a future palette shift
 *     changes the tokens, this test flags the ``button.jsx`` drift.
 *   • Every Sign-out entry point in the app renders a solid #DC2626
 *     surface with #B91C1C hover and the #EF4444 focus ring.
 *     Covered surfaces:
 *       - ``AdminTopBar``   (data-testid="header-signout")
 *       - ``UniversalMenu`` (data-testid="portal-signout" floating)
 *       - ``AppLayout``     (data-testid="shell-logout-button-mobile")
 *       - ``TenantPicker``  (data-testid="tenant-picker-logout")
 *   • ``DeleteAccountDangerCard`` — the canonical customer-facing
 *     destructive Delete flow — uses the same hex trio and the
 *     0.55 disabled opacity (was 0.40 pre-K54).
 *
 * If any consumer inlines a red hex that drifts from these tokens,
 * this suite fails so the deviation is caught before ship.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";

const READ = (p) => fs.readFileSync(p, "utf-8");
const REPO = path.resolve(__dirname, "..");

describe("K54 · destructive-red token block", () => {
  it("exposes colors.destructive with the spec hexes", () => {
    expect(colors.destructive).toBeDefined();
    expect(colors.destructive.bg).toBe("#DC2626");
    expect(colors.destructive.bgHover).toBe("#B91C1C");
    expect(colors.destructive.fg).toBe("#FFFFFF");
    expect(colors.destructive.ring).toBe("#EF4444");
    expect(colors.destructive.disabledOpacity).toBe(0.55);
  });
});

describe("K54 · shadcn Button variant='destructive' spec", () => {
  const src = READ(path.join(REPO, "components/ui/button.jsx"));

  it("uses the K54 red-600 surface + red-700 hover", () => {
    expect(src).toMatch(/destructive:\s*"[^"]*bg-\[#DC2626\][^"]*"/);
    expect(src).toMatch(/destructive:\s*"[^"]*hover:bg-\[#B91C1C\][^"]*"/);
  });

  it("uses white foreground on the destructive variant", () => {
    expect(src).toMatch(/destructive:\s*"[^"]*text-white[^"]*"/);
  });

  it("overrides the default ring to the red-500 focus ring", () => {
    expect(src).toMatch(
      /destructive:\s*"[^"]*focus-visible:ring-\[#EF4444\][^"]*"/,
    );
  });

  it("inherits disabled:opacity-55 from the shared cva base (single source)", () => {
    // The base cva string owns ``disabled:opacity-55`` so every
    // variant — including destructive — picks it up automatically.
    expect(src).toMatch(/disabled:opacity-55/);
  });

  it("does not silently drop the semantic ``bg-destructive`` class", () => {
    // Guardrail: if someone reverts button.jsx to the old
    // ``bg-destructive`` semantic-class flavor, the hex assertions
    // above already fail — this extra check just makes the failure
    // message clearer for the next reviewer.
    expect(src).not.toMatch(/destructive:\s*"[^"]*bg-destructive[^"]*"/);
  });
});

describe("K54 · Sign-out entry points sweep", () => {
  const files = {
    adminTopBar: READ(path.join(REPO, "layouts/AdminTopBar.jsx")),
    universalMenu: READ(path.join(REPO, "layouts/UniversalMenu.jsx")),
    appLayout: READ(path.join(REPO, "layouts/AppLayout.jsx")),
    tenantPicker: READ(path.join(REPO, "pages/TenantPicker.jsx")),
  };

  it.each([
    ["adminTopBar", "header-signout"],
    ["universalMenu", "portal-signout"],
    ["appLayout", "shell-logout-button-mobile"],
    ["tenantPicker", "tenant-picker-logout"],
  ])(
    "%s (data-testid=%s) paints the K54 red surface + hover + focus ring",
    (key, testid) => {
      const src = files[key];
      // Anchor to a narrow window around the testid so we don't
      // accidentally match some other red button on the page.
      const idx = src.indexOf(`data-testid="${testid}"`);
      expect(idx).toBeGreaterThan(-1);
      const window = src.slice(Math.max(0, idx - 800), idx + 200);
      expect(window).toMatch(/bg-\[#DC2626\]/);
      expect(window).toMatch(/hover:bg-\[#B91C1C\]/);
      expect(window).toMatch(/focus-visible:ring-\[#EF4444\]/);
      expect(window).toMatch(/text-white/);
    },
  );

  it("AdminTopBar Sign-out no longer uses the pre-K54 muted/gray surface", () => {
    // Old style was ``backgroundColor: colors.surfaceSecondary`` +
    // ``color: colors.error`` — a low-affordance gray pill with
    // red text.  Assert that inline style tuple is gone.
    const src = files.adminTopBar;
    const idx = src.indexOf('data-testid="header-signout"');
    const window = src.slice(Math.max(0, idx - 800), idx + 200);
    expect(window).not.toMatch(/backgroundColor:\s*colors\.surfaceSecondary/);
    expect(window).not.toMatch(/color:\s*colors\.error/);
  });

  it("AppLayout mobile Sign-out no longer uses the K50 semi-transparent red tint", () => {
    const src = files.appLayout;
    const idx = src.indexOf('data-testid="shell-logout-button-mobile"');
    const window = src.slice(Math.max(0, idx - 800), idx + 200);
    expect(window).not.toMatch(/rgba\(239,\s*68,\s*68,\s*0\.35\)/);
  });
});

describe("K54 · DeleteAccountDangerCard parity", () => {
  const src = READ(
    path.join(REPO, "components/portal/DeleteAccountDangerCard.jsx"),
  );

  it("primary Delete button uses the K54 red + hover + focus ring", () => {
    const idx = src.indexOf(
      'data-testid="portal-preferences-delete-account-open-btn"',
    );
    expect(idx).toBeGreaterThan(-1);
    const window = src.slice(Math.max(0, idx - 800), idx + 200);
    expect(window).toMatch(/bg-\[#DC2626\]/);
    expect(window).toMatch(/hover:bg-\[#B91C1C\]/);
    expect(window).toMatch(/focus-visible:ring-\[#EF4444\]/);
  });

  it("confirm Delete button uses opacity-55 (not the pre-K54 opacity-40)", () => {
    const idx = src.indexOf(
      'data-testid="portal-preferences-delete-account-confirm-btn"',
    );
    expect(idx).toBeGreaterThan(-1);
    const window = src.slice(Math.max(0, idx - 800), idx + 200);
    expect(window).toMatch(/disabled:opacity-55/);
    expect(window).not.toMatch(/disabled:opacity-40/);
  });
});
