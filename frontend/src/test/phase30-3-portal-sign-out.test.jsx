/**
 * Phase 30.3 · Feb-2026 — mobile customer portal sign-out.
 *
 * ⚠ DIAGNOSTIC MODE (Phase 30.3-diag).
 *
 * Three hypothesis-based hotfixes (Alert wrap, router.replace race,
 * flexShrink/hitSlop geometry) all failed on device — user confirms the
 * button is visible top-right, notification bell (adjacent sibling)
 * works, and the sign-out tap fires nothing at all.
 *
 * To separate "tap doesn't fire" from "handler crashes silently" we
 * temporarily replaced the styled Pressable with a bright-yellow /
 * red-border 44×44 minimum-viable button that only console.log's and
 * Alert.alert's on tap. These vitests lock that diagnostic shape so a
 * future edit can't quietly re-introduce the failing styled version
 * without re-doing the diagnostic first.
 *
 * The original invariants (headerActions flexShrink:0, hitSlop, styled
 * confirmation flow, doSignOut router.replace) will be restored in a
 * follow-up test once the tap firing is proven on device.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const M_HOME    = R("../../../mobile/app/portal/home.tsx");
const M_PROFILE = R("../../../mobile/app/portal/profile.tsx");

describe("Phase 30.3-diag · Portal home sign-out MVP button", () => {
  it("still destructures `logout` from useAuth() (kept for restoration)", () => {
    expect(M_HOME).toMatch(
      /const\s+\{\s*user\s*,\s*logout\s*\}\s*=\s*useAuth\(\)/,
    );
  });

  it("renders exactly ONE <Pressable> with testID='portal-sign-out-button'", () => {
    const matches = M_HOME.match(/testID=["']portal-sign-out-button["']/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBe(1);
  });

  it("MVP button on-press logs [SIGN_OUT_DEBUG] and fires an Alert", () => {
    // The diagnostic MUST:
    //   (a) console.log the tap with a timestamp so Metro shows it,
    //   (b) show an Alert so the user has visual proof on device,
    //   (c) NOT call logout() / doSignOut / router.replace — we're
    //       explicitly isolating the touch layer from the downstream
    //       auth/nav layer.
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block).not.toBeNull();
    const b = block[0];
    expect(b).toMatch(/console\.log\(\s*["']\[SIGN_OUT_DEBUG\] tap fired at["']/);
    expect(b).toMatch(/Alert\.alert\(\s*["']Sign out debug["']/);
    expect(b).not.toMatch(/onPress=\{onSignOutPress\}/);
    expect(b).not.toMatch(/logout\(\)/);
    expect(b).not.toMatch(/router\.replace/);
  });

  it("MVP button styled with the diagnostic 44×44 yellow / red-border shape", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    const b = block[0];
    expect(b).toMatch(/width:\s*44/);
    expect(b).toMatch(/height:\s*44/);
    expect(b).toMatch(/borderWidth:\s*2/);
    expect(b).toMatch(/borderColor:\s*["']red["']/);
    expect(b).toMatch(/backgroundColor:\s*["']yellow["']/);
  });

  it("still uses Ionicons `log-out-outline` at size 24 (black glyph on yellow)", () => {
    expect(M_HOME).toMatch(
      /testID=["']portal-sign-out-button["'][\s\S]{0,1200}<Ionicons\s+name=["']log-out-outline["']\s+size=\{24\}\s+color=["']black["']/,
    );
  });

  it("sits alongside <NotificationBell /> inside the headerActions wrapper", () => {
    expect(M_HOME).toMatch(
      /<View\s+style=\{s\.headerActions\}>[\s\S]*?<NotificationBell[\s\S]*?<Pressable[\s\S]*?testID=["']portal-sign-out-button["']/,
    );
  });

  it("Header right slot emits a render-time [SIGN_OUT_DEBUG] log", () => {
    // Second console.log lives *inside* the right-slot render so we
    // can prove the JSX is actually being mounted (as opposed to the
    // Header stripping it or a stale bundle showing an older layout).
    expect(M_HOME).toMatch(
      /console\.log\(\s*["']\[SIGN_OUT_DEBUG\] Header render, right slot present:["']/,
    );
  });

  it("regression · Profile subpage sign-out (testID='portal-logout') still exists", () => {
    expect(M_PROFILE).toMatch(/testID=["']portal-logout["']/);
  });
});
