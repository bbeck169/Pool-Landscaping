/**
 * TD-73 · Feb-2026 — Portal Edit Profile button + modal theme
 * parity with the Call Now CTA.
 *
 * Operator-reported symptom cluster:
 *   (A) The hero "Edit profile" button rendered in a muted
 *       translucent-white pill style while the "Call Now" CTA
 *       beside it was prominent green. The two CTAs on the same
 *       hero band read as different affordance families.
 *   (B) The Edit Profile modal's Save button was portal navy
 *       (``#1B1F5C``) beside a white Cancel — producing a dark-
 *       blue Save cluster that didn't match the operator-ruled
 *       "green matches Call Now" rule.
 *
 * Fix: both buttons now paint the Call Now green (``#16A34A``
 * from ``pages/portal/CallNowButton.jsx``) with bold white text
 * + ``brightness-95`` hover state. Pin via source-grep so a
 * future refactor can't drift the color.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");

const HOME_SRC   = R("../pages/portal/PortalHome.jsx");
const MODAL_SRC  = R("../components/portal/PortalEditProfileModal.jsx");
const CTA_SRC    = R("../pages/portal/CallNowButton.jsx");


describe("TD-73 · Portal Edit Profile theme parity with Call Now", () => {

  it("Call Now canonical green is #16A34A (source-of-truth lock)", () => {
    // If this ever flips, the parity contract is broken from the
    // OTHER side first and the hero/modal buttons need to follow.
    expect(CTA_SRC).toMatch(/background:\s*["']#16A34A["']/);
    expect(CTA_SRC).toMatch(/font-bold/);
    expect(CTA_SRC).toMatch(/text-white/);
  });

  it("(A) Hero Edit profile button matches Call Now green + bold white", () => {
    // Scope the match to the Edit-profile button block via its
    // addressable testid so we don't pattern-match stray
    // ``#16A34A`` occurrences elsewhere in PortalHome.
    const chunk = HOME_SRC.match(
      /data-testid=\{?["']portal-hero-edit-profile-btn["']\}?[\s\S]{0,500}/,
    );
    const prev = HOME_SRC.slice(0, HOME_SRC.indexOf("portal-hero-edit-profile-btn"));
    expect(chunk).not.toBeNull();
    // Walk BACKWARDS from the testid to grab the enclosing <button>
    // open-tag — the colour + font-weight live before the testid.
    const buttonStart = prev.lastIndexOf("<button");
    const buttonChunk = HOME_SRC.slice(buttonStart, HOME_SRC.indexOf(">", HOME_SRC.indexOf("portal-hero-edit-profile-btn")) + 1);
    expect(buttonChunk).toMatch(/background:\s*["']#16A34A["']/);
    expect(buttonChunk).toMatch(/font-bold/);
    expect(buttonChunk).toMatch(/text-white/);
    // Negative lock — pre-TD-73 translucent-white glass style gone.
    expect(buttonChunk).not.toMatch(/rgba\(255,255,255,0\.15\)/);
    expect(buttonChunk).not.toMatch(/backdrop-blur/);
  });

  it("(B) Edit Profile modal Save button matches Call Now green", () => {
    // Walk from the Save-btn testid back to the enclosing
    // <button> open tag.
    const idx = MODAL_SRC.indexOf("portal-edit-profile-save-btn");
    expect(idx).toBeGreaterThan(-1);
    const buttonStart = MODAL_SRC.lastIndexOf("<button", idx);
    const buttonEnd = MODAL_SRC.indexOf(">", idx) + 1;
    const buttonChunk = MODAL_SRC.slice(buttonStart, buttonEnd);
    expect(buttonChunk).toMatch(/background:\s*["']#16A34A["']/);
    expect(buttonChunk).toMatch(/text-white/);
    expect(buttonChunk).toMatch(/font-semibold/);
    // Negative lock — pre-TD-73 portal-navy fill gone.
    expect(buttonChunk).not.toMatch(/#1B1F5C/);
  });

  it("Modal Cancel button stays neutral (white bg + dark text + light border)", () => {
    const idx = MODAL_SRC.indexOf("portal-edit-profile-cancel-btn");
    const buttonStart = MODAL_SRC.lastIndexOf("<button", idx);
    const buttonEnd = MODAL_SRC.indexOf(">", idx) + 1;
    const buttonChunk = MODAL_SRC.slice(buttonStart, buttonEnd);
    expect(buttonChunk).toMatch(/background:\s*["']#FFFFFF["']/);
    expect(buttonChunk).toMatch(/color:\s*["']#334155["']/);
    expect(buttonChunk).toMatch(/borderColor:\s*["']#CBD5E1["']/);
  });

  it("Modal shell remains white-card chrome (operator spec unchanged)", () => {
    // The modal container stays bg-white + dark text — pre-TD-73
    // this part was already correct. Lock it so a future
    // refactor can't drift it accidentally.
    expect(MODAL_SRC).toMatch(/rounded-2xl\s+shadow-2xl\s+bg-white/);
    // Dark header title.
    expect(MODAL_SRC).toMatch(/color:\s*["']#0F172A["']/);
  });

});
