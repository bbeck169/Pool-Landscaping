/**
 * Phase 30.3 · Feb-2026 — mobile customer portal sign-out.
 *
 * Source-inspection asserts:
 *   1. Portal home imports `useAuth` and destructures `logout` from it.
 *   2. A pressable Sign out affordance exists at
 *      ``testID="portal-sign-out-button"``.
 *   3. Tap is wrapped in a native ``Alert.alert(...)`` confirmation
 *      before calling `logout()` — no bare `onPress={logout}`
 *      handler that could silently sign the user out.
 *   4. The Sign out button lives in the header right-slot cluster
 *      alongside `<NotificationBell />` (Placement A).
 *   5. Regression: no other sign-out affordance was removed from
 *      `mobile/app/portal/profile.tsx` (it kept its
 *      `testID="portal-logout"` button — customers can still sign
 *      out from Profile too).
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const M_HOME    = R("../../../mobile/app/portal/home.tsx");
const M_PROFILE = R("../../../mobile/app/portal/profile.tsx");

describe("Phase 30.3 · Portal home sign-out affordance", () => {
  it("destructures `logout` from useAuth()", () => {
    expect(M_HOME).toMatch(
      /const\s+\{\s*user\s*,\s*logout\s*\}\s*=\s*useAuth\(\)/,
    );
  });

  it("renders a <Pressable> with testID='portal-sign-out-button'", () => {
    expect(M_HOME).toMatch(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["']/,
    );
  });

  it("wraps the sign-out call in a native Alert.alert confirmation", () => {
    // The Alert MUST include a destructive Sign out action that
    // calls logout(). A bare `onPress={logout}` would violate the
    // "confirm before sign-out" spec.
    expect(M_HOME).toMatch(/Alert\.alert\(\s*["']Sign out\?["']/);
    expect(M_HOME).toMatch(
      /style:\s*["']destructive["'][\s\S]*?onPress:[\s\S]*?logout\(\)/,
    );
    // Regression — no bare `onPress={logout}` handler on the
    // button (would bypass the confirmation).
    expect(M_HOME).not.toMatch(
      /testID=["']portal-sign-out-button["'][\s\S]{0,400}onPress=\{logout\}/,
    );
  });

  it("sits alongside <NotificationBell /> in the header right slot (Placement A)", () => {
    // Both must be rendered inside the same header actions row,
    // AND the sign-out <Pressable> must come immediately AFTER
    // the <NotificationBell /> — the user's clarification is
    // "to the right of the notification bell", which in a
    // left-to-right flex row means the sign-out is the second
    // sibling.
    expect(M_HOME).toMatch(
      /<View\s+style=\{s\.headerActions\}>[\s\S]*?<NotificationBell[\s\S]*?<Pressable[\s\S]*?testID=["']portal-sign-out-button["']/,
    );
    expect(M_HOME).toMatch(/headerActions\s*:\s*\{/);
    // Adjacency guard — nothing else can render between the
    // bell and the sign-out button. The character gap between
    // </NotificationBell*/> and the sign-out <Pressable>'s
    // opening tag must not contain another JSX element.
    const bellIdx = M_HOME.indexOf("<NotificationBell");
    const signOutIdx = M_HOME.indexOf('testID="portal-sign-out-button"');
    expect(bellIdx).toBeGreaterThan(-1);
    expect(signOutIdx).toBeGreaterThan(bellIdx);
    const between = M_HOME.slice(bellIdx, signOutIdx);
    // Only the NotificationBell open+close and the sign-out
    // <Pressable> opening tag should appear in `between`. No
    // other JSX elements (i.e., no `<AnyOtherComponent` other
    // than the sign-out Pressable itself).
    const stray = between.match(
      /<(?!\/|NotificationBell|Pressable\b|Ionicons\b|View\b|Text\b\/>)[A-Z][A-Za-z]*/g,
    );
    expect(stray).toBeNull();
  });

  it("uses the project's mobile icon family for the glyph (Ionicons log-out-outline)", () => {
    // Mobile stack uses @expo/vector-icons (Ionicons); no
    // `lucide-react-native` dep. `log-out-outline` is the
    // semantic equivalent of lucide's `LogOut`.
    expect(M_HOME).toMatch(
      /testID=["']portal-sign-out-button["'][\s\S]{0,300}<Ionicons\s+name=["']log-out-outline["']/,
    );
  });

  it("no duplicate bottom-of-page sign-out affordance exists", () => {
    // The user's clarification says the button lives at the
    // top-right ONLY — a second copy at the bottom would violate
    // the "so we don't have two sign-out affordances" rule.
    const matches = M_HOME.match(/testID=["']portal-sign-out-button["']/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBe(1);
  });

  it("regression · Profile subpage sign-out button (testID='portal-logout') still exists", () => {
    // The pre-Phase-30.3 sign-out affordance on the Profile page
    // is not removed — customers can still sign out from either
    // surface.
    expect(M_PROFILE).toMatch(/testID=["']portal-logout["']/);
  });
});
