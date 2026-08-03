/**
 * Phase 30.3-diag2 · Feb-2026 — mobile customer portal sign-out
 * DIAGNOSTIC MODE (dual-location visual-state probe).
 *
 * The Phase 30.3-diag single-button MVP (yellow box + console.log +
 * Alert.alert) proved bundle-freshness but the tap still fired
 * nothing on device — even though the adjacent NotificationBell
 * (same parent, same Pressable API from `react-native`) works.
 *
 * Because Alert can silently no-op in some Expo Go builds AND
 * console.log requires a live Metro tail, this diag now drives a
 * `useState` from onPress so the buttons themselves flip colour
 * on tap. Visual proof of tap arrival, independent of Metro/Alert.
 *
 * Two probes are mounted:
 *   1. HEADER probe · `testID="portal-sign-out-button"`
 *      44×44 yellow → lime on `tapCount > 0`, red border,
 *      Ionicons log-out-outline glyph. Lives inside the
 *      Header's `right` slot alongside `<NotificationBell />`.
 *   2. SCROLL probe · `testID="portal-scroll-test-button"`
 *      height 60 orange → lime on `scrollTapCount > 0`, red
 *      border, "TAP HERE — count: N" label. Lives in the
 *      ScrollView body, just above the Next Service Day card.
 *
 * Interpretation matrix (documented for the next fork):
 *   ┌──────────────┬──────────────┬─────────────────────────────────┐
 *   │ HEADER lime? │ SCROLL lime? │ Diagnosis                       │
 *   ├──────────────┼──────────────┼─────────────────────────────────┤
 *   │  YES         │  YES         │ Touch works — P0 is downstream  │
 *   │              │              │ (Alert / handler chain)         │
 *   │  NO          │  YES         │ Header context uniquely broken  │
 *   │              │              │ (move sign-out outside Header)  │
 *   │  YES         │  NO          │ Scroll context broken — cache?  │
 *   │  NO          │  NO          │ Global Pressable failure —      │
 *   │              │              │ Expo Go / RN version mismatch   │
 *   └──────────────┴──────────────┴─────────────────────────────────┘
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const M_HOME    = R("../../../mobile/app/portal/home.tsx");
const M_PROFILE = R("../../../mobile/app/portal/profile.tsx");

describe("Phase 30.3-diag2 · dual visual-state tap probes", () => {
  it("still destructures `logout` from useAuth() (kept for restoration)", () => {
    expect(M_HOME).toMatch(
      /const\s+\{\s*user\s*,\s*logout\s*\}\s*=\s*useAuth\(\)/,
    );
  });

  it("declares tapCount + scrollTapCount useState hooks", () => {
    expect(M_HOME).toMatch(
      /const\s+\[\s*tapCount\s*,\s*setTapCount\s*\]\s*=\s*useState\(\s*0\s*\)/,
    );
    expect(M_HOME).toMatch(
      /const\s+\[\s*scrollTapCount\s*,\s*setScrollTapCount\s*\]\s*=\s*useState\(\s*0\s*\)/,
    );
  });

  // ── HEADER probe ───────────────────────────────────────────
  it("HEADER probe: exactly one Pressable with testID='portal-sign-out-button'", () => {
    const matches = M_HOME.match(/testID=["']portal-sign-out-button["']/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBe(1);
  });

  it("HEADER probe: onPress logs [SIGN_OUT_DEBUG] HEADER and increments tapCount", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block).not.toBeNull();
    const b = block[0];
    expect(b).toMatch(/console\.log\(\s*["']\[SIGN_OUT_DEBUG\] HEADER tap fired at["']/);
    expect(b).toMatch(/setTapCount\(\s*\(c\)\s*=>\s*c\s*\+\s*1\s*\)/);
    // Alert.alert removed — Alert may be silently no-op on device.
    expect(b).not.toMatch(/Alert\.alert/);
    // No downstream logout / router.replace — pure touch probe.
    expect(b).not.toMatch(/logout\(\)/);
    expect(b).not.toMatch(/router\.replace/);
  });

  it("HEADER probe: yellow → lime on tap (visual state), 44×44 with red border", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    const b = block[0];
    expect(b).toMatch(/width:\s*44/);
    expect(b).toMatch(/height:\s*44/);
    expect(b).toMatch(/borderWidth:\s*2/);
    expect(b).toMatch(/borderColor:\s*["']red["']/);
    expect(b).toMatch(/backgroundColor:\s*tapCount\s*>\s*0\s*\?\s*["']lime["']\s*:\s*["']yellow["']/);
  });

  it("HEADER probe: still sits alongside <NotificationBell /> in headerActions", () => {
    expect(M_HOME).toMatch(
      /<View\s+style=\{s\.headerActions\}>[\s\S]*?<NotificationBell[\s\S]*?<Pressable[\s\S]*?testID=["']portal-sign-out-button["']/,
    );
  });

  // ── SCROLL probe ───────────────────────────────────────────
  it("SCROLL probe: exactly one Pressable with testID='portal-scroll-test-button'", () => {
    const matches = M_HOME.match(/testID=["']portal-scroll-test-button["']/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBe(1);
  });

  it("SCROLL probe: onPress logs [SIGN_OUT_DEBUG] SCROLL and increments scrollTapCount", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-scroll-test-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block).not.toBeNull();
    const b = block[0];
    expect(b).toMatch(/console\.log\(\s*["']\[SIGN_OUT_DEBUG\] SCROLL test tap fired at["']/);
    expect(b).toMatch(/setScrollTapCount\(\s*\(c\)\s*=>\s*c\s*\+\s*1\s*\)/);
    expect(b).not.toMatch(/Alert\.alert/);
    expect(b).not.toMatch(/logout\(\)/);
    expect(b).not.toMatch(/router\.replace/);
  });

  it("SCROLL probe: orange → lime, 60 high, red border, label with count", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-scroll-test-button["'][\s\S]*?<\/Pressable>/,
    );
    const b = block[0];
    expect(b).toMatch(/height:\s*60/);
    expect(b).toMatch(/borderWidth:\s*3/);
    expect(b).toMatch(/borderColor:\s*["']red["']/);
    expect(b).toMatch(/backgroundColor:\s*scrollTapCount\s*>\s*0\s*\?\s*["']lime["']\s*:\s*["']orange["']/);
    expect(b).toMatch(/TAP HERE\s*—\s*count:\s*\{scrollTapCount\}/);
  });

  it("SCROLL probe: mounted OUTSIDE the Header (inside ScrollView body)", () => {
    // The scroll probe must sit AFTER the Header's closing bracket
    // and BEFORE the Next Service Day card.
    const scrollIdx = M_HOME.indexOf('testID="portal-scroll-test-button"');
    const headerCloseIdx = M_HOME.indexOf("</Header>");
    // Some codebases self-close the Header. Fall back to `/>` after
    // the Header opener if `</Header>` isn't present.
    const headerFallbackIdx = M_HOME.indexOf("<Header");
    const nextServiceIdx = M_HOME.indexOf('testID="portal-next-service-day"');
    expect(scrollIdx).toBeGreaterThan(-1);
    expect(headerFallbackIdx).toBeGreaterThan(-1);
    expect(scrollIdx).toBeGreaterThan(headerFallbackIdx);
    // If </Header> exists it must precede; otherwise the fallback
    // still gives us a valid ordering check.
    if (headerCloseIdx > -1) {
      expect(scrollIdx).toBeGreaterThan(headerCloseIdx);
    }
    // Placed above Next Service Day per the diagnostic brief.
    expect(nextServiceIdx).toBeGreaterThan(-1);
    expect(scrollIdx).toBeLessThan(nextServiceIdx);
  });

  // ── Regression / guardrails ────────────────────────────────
  it("regression · Profile subpage sign-out (testID='portal-logout') still exists", () => {
    expect(M_PROFILE).toMatch(/testID=["']portal-logout["']/);
  });

  it("Header render still emits the [SIGN_OUT_DEBUG] render trace", () => {
    expect(M_HOME).toMatch(
      /console\.log\(\s*["']\[SIGN_OUT_DEBUG\] Header render, right slot present:["']/,
    );
  });
});
