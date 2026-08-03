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
    // ultimately calls logout(). A bare `onPress={logout}` on the
    // header button would violate the "confirm before sign-out"
    // spec.
    expect(M_HOME).toMatch(/Alert\.alert\(\s*["']Sign out\?["']/);
    expect(M_HOME).toMatch(
      /style:\s*["']destructive["'][\s\S]*?onPress:\s*doSignOut/,
    );
    // Regression — no bare `onPress={logout}` handler on the
    // header button (would bypass the confirmation).
    expect(M_HOME).not.toMatch(
      /testID=["']portal-sign-out-button["'][\s\S]{0,400}onPress=\{logout\}/,
    );
  });

  it("Phase 30.3 hotfix · doSignOut awaits logout AND calls router.replace('/login')", () => {
    // Root cause of the P0 regression: relying solely on the
    // ``<Redirect href="/login" />`` layout gate raced Android's
    // Alert dismiss animation on some devices, leaving the
    // customer on a stale portal home after logout(). The
    // hotfix keeps the confirmation but adds an explicit
    // ``router.replace("/login")`` in a ``finally`` so
    // navigation happens regardless of layout-gate timing.
    const doSignOutBlock = M_HOME.match(
      /const\s+doSignOut\s*=\s*React\.useCallback\(\s*async[\s\S]*?\},\s*\[[^\]]*\]\s*\)/,
    );
    expect(doSignOutBlock).not.toBeNull();
    const body = doSignOutBlock[0];
    // Must await logout() and use router.replace to /login.
    expect(body).toMatch(/await\s+logout\(\)/);
    expect(body).toMatch(/router\.replace\(\s*["']\/login["']\s*\)/);
    // Belt-and-suspenders navigation MUST live in a `finally`
    // so a thrown/rejected logout still redirects the user
    // instead of stranding them.
    expect(body).toMatch(/finally\s*\{[\s\S]*?router\.replace/);
    // Regression guard against the pre-hotfix `void logout()`.
    expect(body).not.toMatch(/void\s+logout\(\)/);
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

  // ── Phase 30.3 hotfix · touch-target invariants ─────────────
  it("Phase 30.3 hotfix · sign-out is a <Pressable> (not a <View>) with an onPress prop", () => {
    // The tap-not-registering P0 was diagnosed as the Header's
    // flex:1 left block squeezing the right-slot child to
    // sub-pixel width. Guard: the element MUST still be a
    // Pressable, and its onPress prop MUST reference the
    // named handler (not be missing).
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block).not.toBeNull();
    expect(block[0]).toMatch(/onPress=\{onSignOutPress\}/);
  });

  it("Phase 30.3 hotfix · hitSlop present on all four sides", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    // hitSlop must specify top, right, bottom, left explicitly.
    // A number (`hitSlop={10}`) works too but the brief asked
    // for the object form so we lock that.
    expect(block[0]).toMatch(
      /hitSlop=\{\{\s*top:\s*\d+,\s*right:\s*\d+,\s*bottom:\s*\d+,\s*left:\s*\d+\s*\}\}/,
    );
  });

  it("Phase 30.3 hotfix · headerActions has flexDirection:row + flexShrink:0", () => {
    // Root cause of P0 — right-slot wrapper needs flexShrink:0
    // so the Header's flex:1 left block can't squeeze it.
    const body = M_HOME.match(/headerActions\s*:\s*\{([\s\S]*?)\}/)[1];
    expect(body).toMatch(/flexDirection\s*:\s*["']row["']/);
    expect(body).toMatch(/flexShrink\s*:\s*0/);
    // AND no ancestor-blocking pointerEvents:none / overflow:hidden.
    expect(body).not.toMatch(/pointerEvents\s*:\s*["']none["']/);
    expect(body).not.toMatch(/overflow\s*:\s*["']hidden["']/);
  });

  it("Phase 30.3 hotfix · signOutBtn has flexShrink:0 + padding for touch target", () => {
    const body = M_HOME.match(/signOutBtn\s*:\s*\{([\s\S]*?)\}/)[1];
    expect(body).toMatch(/flexShrink\s*:\s*0/);
    // Padding must be >= 6 dp so the tappable area is at least
    // (22 + 12) = 34 dp square before hitSlop expansion.
    const pad = parseInt((body.match(/padding\s*:\s*(\d+)/) || [0, "0"])[1], 10);
    expect(pad).toBeGreaterThanOrEqual(6);
  });

  it("regression · Profile subpage sign-out button (testID='portal-logout') still exists", () => {
    // The pre-Phase-30.3 sign-out affordance on the Profile page
    // is not removed — customers can still sign out from either
    // surface.
    expect(M_PROFILE).toMatch(/testID=["']portal-logout["']/);
  });
});
