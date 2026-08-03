/**
 * Phase 30.3 (final) · Feb-2026 — mobile customer portal sign-out.
 *
 * ROOT CAUSE (locked in by these tests): the previous three hotfix
 * attempts all wrapped ``logout()`` in ``Alert.alert(...destructive)``.
 * On the user's Android/Expo Go build ``Alert.alert`` renders nothing
 * and silently drops the destructive callback → tap looked dead. The
 * dual-probe diagnostic (Phase 30.3-diag2) proved Pressable + touch
 * are fine — Alert.alert was the single silent link.
 *
 * The production fix mirrors the two proven-working sign-outs in this
 * repo: ``mobile/app/(app)/more.tsx`` (tech drawer) and
 * ``mobile/app/portal/profile.tsx`` (portal Profile). Both call
 * ``onPress={logout}`` directly, no confirmation. We layer:
 *   * try/catch with ``if (__DEV__) console.log/error(...)`` traces
 *     so any future silent-drop mode is surfaced immediately.
 *   * ``router.replace("/login")`` after ``logout()`` — belt-and-
 *     suspenders navigation independent of the ``portal/_layout``
 *     ``<Redirect>`` gate.
 *   * Touch-region guardrails from the earlier hotfix:
 *     ``flexShrink:0``, ``padding:8``, ``hitSlop`` on all four sides.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const M_HOME    = R("../../../mobile/app/portal/home.tsx");
const M_PROFILE = R("../../../mobile/app/portal/profile.tsx");

describe("Phase 30.3 (final) · Portal home sign-out", () => {
  it("destructures `logout` from useAuth()", () => {
    expect(M_HOME).toMatch(
      /const\s+\{\s*user\s*,\s*logout\s*\}\s*=\s*useAuth\(\)/,
    );
  });

  it("declares a `handleSignOut` useCallback that awaits logout() and navigates", () => {
    const block = M_HOME.match(
      /const\s+handleSignOut\s*=\s*React\.useCallback\(\s*async[\s\S]*?\},\s*\[[^\]]*\]\s*\)/,
    );
    expect(block).not.toBeNull();
    const body = block[0];
    // Must actually call logout() (awaited).
    expect(body).toMatch(/await\s+logout\(\)/);
    // Must navigate via router.replace to /login.
    expect(body).toMatch(/router\.replace\(\s*["']\/login["']\s*\)/);
    // Must be wrapped in try/catch so a rejected logout doesn't
    // silently drop like the Alert.alert primitive did.
    expect(body).toMatch(/try\s*\{/);
    expect(body).toMatch(/catch\s*\(/);
    // Dev-only logging around the pressed / ok / failed transitions.
    expect(body).toMatch(/__DEV__/);
    expect(body).toMatch(/console\.log\(\s*["']\[portal sign-out\] pressed["']/);
    expect(body).toMatch(/console\.error\(\s*["']\[portal sign-out\] failed["']/);
  });

  it("Pressable uses `handleSignOut` as its onPress (no Alert.alert wrap)", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block).not.toBeNull();
    const b = block[0];
    expect(b).toMatch(/onPress=\{handleSignOut\}/);
    // ROOT-CAUSE REGRESSION GUARD — the button MUST NOT reintroduce
    // Alert.alert in any form. That primitive is silently broken
    // on the user's Android/Expo Go build; using it here again
    // would reproduce the P0.
    expect(b).not.toMatch(/Alert\.alert/);
    expect(b).not.toMatch(/onPress=\{onSignOutPress\}/);
  });

  it("handler module NO LONGER references Alert.alert anywhere", () => {
    // Belt-and-suspenders regression guard: even if a future edit
    // moves the handler out of the JSX block, the file as a whole
    // must not depend on ``Alert.alert`` for sign-out (or anything
    // else) — the import itself was removed to make this impossible.
    //
    // Strip line comments before matching so the breadcrumb
    // paragraph above the handler (which intentionally *mentions*
    // ``Alert.alert(...)`` as a historical note) does not
    // falsely trip the guard.
    const codeOnly = M_HOME
      .split("\n")
      .filter((ln) => !/^\s*(?:\/\/|\*)/.test(ln))
      .join("\n");
    expect(codeOnly).not.toMatch(/Alert\.alert\(/);
    // Import guard — Alert removed from the react-native named
    // imports to prevent accidental reintroduction.
    expect(M_HOME).not.toMatch(
      /from\s+["']react-native["'][\s\S]{0,200}\bAlert\b[\s\S]{0,20}[},]/,
    );
  });

  it("exactly one Pressable with testID='portal-sign-out-button'", () => {
    const matches = M_HOME.match(/testID=["']portal-sign-out-button["']/g);
    expect(matches).not.toBeNull();
    expect(matches.length).toBe(1);
  });

  it("Pressable has hitSlop on all four sides", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block[0]).toMatch(
      /hitSlop=\{\{\s*top:\s*\d+,\s*bottom:\s*\d+,\s*left:\s*\d+,\s*right:\s*\d+\s*\}\}/,
    );
  });

  it("Pressable style prop references s.signOutBtn (not the diagnostic inline style)", () => {
    const block = M_HOME.match(
      /<Pressable[\s\S]*?testID=["']portal-sign-out-button["'][\s\S]*?<\/Pressable>/,
    );
    expect(block[0]).toMatch(/s\.signOutBtn/);
    // Diagnostic-only visual state was yellow / red-border / fixed
    // 44×44. Production styling must not carry any of that debris.
    expect(block[0]).not.toMatch(/backgroundColor:\s*["']yellow["']/);
    expect(block[0]).not.toMatch(/backgroundColor:\s*["']orange["']/);
    expect(block[0]).not.toMatch(/borderColor:\s*["']red["']/);
    expect(block[0]).not.toMatch(/tapCount/);
  });

  it("Pressable renders Ionicons `log-out-outline` size 24", () => {
    expect(M_HOME).toMatch(
      /testID=["']portal-sign-out-button["'][\s\S]{0,1200}<Ionicons\s+name=["']log-out-outline["']\s+size=\{24\}/,
    );
  });

  it("sits alongside <NotificationBell /> in the header right slot", () => {
    expect(M_HOME).toMatch(
      /<View\s+style=\{s\.headerActions\}>[\s\S]*?<NotificationBell[\s\S]*?<Pressable[\s\S]*?testID=["']portal-sign-out-button["']/,
    );
  });

  it("headerActions has flexDirection:row + flexShrink:0 + gap", () => {
    const body = M_HOME.match(/headerActions\s*:\s*\{([\s\S]*?)\}/)[1];
    expect(body).toMatch(/flexDirection\s*:\s*["']row["']/);
    expect(body).toMatch(/flexShrink\s*:\s*0/);
    expect(body).toMatch(/gap\s*:/);
    // No pointer/overflow blockers on the wrapper.
    expect(body).not.toMatch(/pointerEvents\s*:\s*["']none["']/);
    expect(body).not.toMatch(/overflow\s*:\s*["']hidden["']/);
  });

  it("signOutBtn has flexShrink:0 + padding:8 for a safe touch region", () => {
    const body = M_HOME.match(/signOutBtn\s*:\s*\{([\s\S]*?)\}/)[1];
    expect(body).toMatch(/flexShrink\s*:\s*0/);
    expect(body).toMatch(/padding\s*:\s*8/);
    expect(body).toMatch(/borderRadius\s*:\s*\d+/);
  });

  // ── Diagnostic cleanup guardrails ─────────────────────────
  it("diagnostic tap-count state has been removed", () => {
    expect(M_HOME).not.toMatch(/\btapCount\b/);
    expect(M_HOME).not.toMatch(/setTapCount/);
    expect(M_HOME).not.toMatch(/scrollTapCount/);
    expect(M_HOME).not.toMatch(/setScrollTapCount/);
  });

  it("diagnostic scroll-area test button has been removed", () => {
    expect(M_HOME).not.toMatch(/testID=["']portal-scroll-test-button["']/);
    expect(M_HOME).not.toMatch(/TAP HERE\s*—\s*count/);
    expect(M_HOME).not.toMatch(/\[SIGN_OUT_DEBUG\]/);
  });

  it("legacy `doSignOut` / `onSignOutPress` callbacks have been retired", () => {
    // Those were the Alert.alert-wrapped helpers. If they come
    // back, someone's re-introduced the broken pattern.
    expect(M_HOME).not.toMatch(/const\s+doSignOut\s*=/);
    expect(M_HOME).not.toMatch(/const\s+onSignOutPress\s*=/);
  });

  it("regression · Profile subpage sign-out (testID='portal-logout') still exists", () => {
    expect(M_PROFILE).toMatch(/testID=["']portal-logout["']/);
  });
});
