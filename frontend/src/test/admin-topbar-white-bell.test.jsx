/**
 * Feb-2026 · AdminTopBar bell cleanup — source-inspection guard.
 *
 * Contract locked by this file:
 *
 *   1. ``<AdminBellSlot />`` is no longer mounted anywhere in
 *      AdminTopBar's three wrap branches (tech / narrow / wide).
 *      The function definition survives (kept in the file for a
 *      future re-mount) but its JSX usages are gone.
 *
 *   2. Every ``<NotificationBell variant="inline" ... />`` mount in
 *      AdminTopBar carries the new ``tone="navy"`` prop so the Bell
 *      glyph flips to ``colors.nav.fg`` on the navy strip. Count is
 *      still exactly 3 (one per wrap branch).
 *
 *   3. ``NotificationBell`` accepts the ``tone`` prop, defaults to
 *      ``"surface"`` (preserves customer-portal ``colors.onSurface``
 *      glyph), and branches the glyph color on ``tone === "navy"``.
 *
 *   4. The red unread-count badge on ``NotificationBell`` is NOT
 *      themed by ``tone`` — it stays ``#DC2626`` / ``#FFFFFF`` in
 *      every mount so unread signalling is intact on any surface.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const TOPBAR = readFileSync(
  resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);
const BELL = readFileSync(
  resolve(__dirname, "../components/NotificationBell.jsx"),
  "utf8",
);


describe("AdminTopBar bell cleanup — AdminBellSlot mounts pulled", () => {
  it("no <AdminBellSlot /> JSX usage remains in any wrap branch", () => {
    // Definition stays; JSX usages are gone.  The definition still
    // uses <AlertBell /> internally so the AlertBell import survives.
    expect(TOPBAR).toMatch(/function AdminBellSlot\(\)/);
    const jsxUsages = TOPBAR.match(/<AdminBellSlot\s*\/>/g) || [];
    expect(jsxUsages.length).toBe(0);
  });
});


describe("AdminTopBar bell cleanup — tone='navy' on every inline mount", () => {
  it("all three inline NotificationBell mounts carry tone=\"navy\"", () => {
    // Every ``<NotificationBell variant="inline" ... />`` in the
    // three wrap branches must carry the new tone prop.  Bare
    // ``<NotificationBell variant="inline" />`` (without tone) would
    // regress the fix — the count of bare mounts must be 0.
    const withTone = TOPBAR.match(
      /<NotificationBell\s+variant="inline"\s+tone="navy"\s*\/>/g,
    ) || [];
    expect(withTone.length).toBe(3);

    const bareInline = TOPBAR.match(
      /<NotificationBell\s+variant="inline"\s*\/>/g,
    ) || [];
    expect(bareInline.length).toBe(0);
  });
});


describe("NotificationBell — tone prop wiring", () => {
  it("accepts a tone prop that defaults to 'surface'", () => {
    // Destructured default must be ``surface`` so every existing
    // consumer (customer portal header, UMENU inline / floating)
    // keeps the pre-cleanup ``colors.onSurface`` glyph.
    expect(BELL).toMatch(/tone\s*=\s*"surface"/);
    // Prop is on the exported component's parameter list.
    expect(BELL).toMatch(
      /export default function NotificationBell\(\s*\{\s*variant\s*=\s*"inline"\s*,\s*tone\s*=\s*"surface"\s*\}\s*\)/,
    );
  });

  it("Bell glyph color branches on tone === 'navy'", () => {
    // The Bell lucide-react element must carry the tone-branched
    // inline style so the glyph flips to ``colors.nav.fg`` when
    // rendered on the navy strip.
    expect(BELL).toMatch(
      /color:\s*tone\s*===\s*"navy"\s*\?\s*colors\.nav\.fg\s*:\s*colors\.onSurface/,
    );
  });

  it("red unread-count badge styling is NOT tone-themed", () => {
    // The badge span keeps its #DC2626 / #FFFFFF styling in every
    // mount — tone controls only the Bell glyph, not the counter.
    // Guard: the badge's backgroundColor / color pair still ships
    // as literal hex strings, not as a branch on ``tone``.
    expect(BELL).toMatch(
      /backgroundColor:\s*"#DC2626"\s*,\s*color:\s*"#FFFFFF"/,
    );
  });
});
