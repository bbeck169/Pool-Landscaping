/**
 * Phase 23 · Feb-2026 — Portal home dark-card restyle.
 *
 * Three attention-blocks on PortalHome used to render with
 * distinct gradient hero cards:
 *
 *   * Ask a Concierge     — teal → sky → emerald gradient
 *   * Refer a Friend      — purple → pink gradient
 *   * NFC-Ready card hero — sky → green gradient
 *
 * Phase 23 restyles all three to the Balance Due / Past Due /
 * Credit tile chassis (deep-navy ``colors.surface`` background +
 * ``colors.border`` slate border + ``rounded-2xl`` + hover-
 * brighten) so the three blocks + the three Balance tiles read
 * as a single visual language on PortalHome.
 *
 * Each section keeps a DISTINCT accent to stay recognisable:
 *   * Ask a Concierge     — BLUE   (``colors.brand``   #3B82F6)
 *   * Refer a Friend      — GREEN  (``colors.success`` #4ADE80)
 *   * NFC-Ready card hero — NAVY   (``brandTertiary``  #1E3A8A)
 *
 * Source-inspection pattern — fast, deterministic, no React
 * render, no provider mount.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PH_SRC = readFileSync(
  resolve(__dirname, "../pages/portal/PortalHome.jsx"), "utf8");
const RS_SRC = readFileSync(
  resolve(__dirname, "../pages/portal/ReferralSection.jsx"), "utf8");
const BC_SRC = readFileSync(
  resolve(__dirname,
    "../components/business-card/BusinessCard.jsx"), "utf8");


// ─── Pixel-match reference ─ Balance-tile chassis ─────────────────
//
// Grep-sourced from PortalHome.jsx's ``Tile`` component (lines
// ~787-823 at ship time) — the Balance Due / Past Due / Credit
// chrome contract:
//
//   className="text-left rounded-2xl p-3 transition hover:brightness-95"
//   style={{
//     backgroundColor: colors.surface,
//     border: `1px solid ${colors.border}`,
//   }}
//
// Phase 23 reuses the SAME chassis contract on the three target
// sections (padding scales up to p-5/p-6 for the larger
// section-level cards — proportional to Balance tiles' p-3 for
// stat tiles).  The className and style primitives match
// byte-for-byte.


describe("Phase 23 · Balance tile chassis survives on the reference tiles", () => {
  it("the Tile component still ships the dark-navy chassis contract", () => {
    // Lock the Balance-tile chrome so a future palette tweak that
    // breaks the chassis is caught here before Phase 23's
    // "pixel-identical" claim rots.
    const tileIdx = PH_SRC.indexOf("function Tile(");
    expect(tileIdx).toBeGreaterThan(-1);
    const tileEnd = PH_SRC.indexOf("\n}", tileIdx);
    const tileBody = PH_SRC.slice(tileIdx, tileEnd);
    expect(tileBody).toMatch(
      /className="text-left rounded-2xl p-3 transition hover:brightness-95"/,
    );
    expect(tileBody).toMatch(/backgroundColor:\s*colors\.surface/);
    expect(tileBody).toMatch(
      /border:\s*`1px solid \$\{borderColor\}`/,
    );
  });
});


describe("Phase 23 · Ask a Concierge · dark chassis + BLUE accent", () => {
  it("gradient retired — ``portal-ai-section`` carries NO teal gradient any more", () => {
    const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
    expect(idx).toBeGreaterThan(-1);
    const openIdx = PH_SRC.lastIndexOf("<div", idx);
    const closeIdx = PH_SRC.indexOf(">", idx);
    const openTag = PH_SRC.slice(openIdx, closeIdx);
    // No gradient hex stops from the pre-Phase-23 teal→sky→emerald
    // palette (``#0891B2`` / ``#0EA5E9`` / ``#10B981``).
    expect(openTag).not.toMatch(/0891B2/);
    expect(openTag).not.toMatch(/0EA5E9/);
    expect(openTag).not.toMatch(/10B981/);
    // And no literal ``linear-gradient`` on the section wrapper.
    expect(openTag).not.toMatch(/linear-gradient/);
  });

  it("adopts the Balance-tile dark chassis (bg colors.surface + border colors.border + rounded-2xl)", () => {
    const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
    const openIdx = PH_SRC.lastIndexOf("<div", idx);
    const closeIdx = PH_SRC.indexOf(">", idx);
    const openTag = PH_SRC.slice(openIdx, closeIdx);
    // Chassis class + style match the Balance-tile contract
    // (padding scales up to p-5 for a section-level card).
    expect(openTag).toMatch(/rounded-2xl/);
    expect(openTag).toMatch(/transition hover:brightness-95/);
    expect(openTag).toMatch(/backgroundColor:\s*colors\.surface/);
    expect(openTag).toMatch(/border:\s*`1px solid \$\{colors\.border\}`/);
  });

  it("Sparkles icon carries the BLUE accent (``colors.brand``)", () => {
    // The accent flip is the one visual that disambiguates the
    // three dark cards.  The icon + the heading colors are the
    // most prominent accent surfaces.
    const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
    // Scope the slice forward to the ``Ask a Concierge`` heading
    // + ~400 chars of its surrounding JSX.
    const askIdx = PH_SRC.indexOf("Ask a Concierge", idx);
    expect(askIdx).toBeGreaterThan(idx);
    const slice = PH_SRC.slice(idx, askIdx + 100);
    expect(slice).toMatch(/<Sparkles[\s\S]{0,80}color:\s*colors\.brand/);
  });

  it("heading + body text flipped from white to onSurface / muted palette", () => {
    const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
    const chatIdx = PH_SRC.indexOf("Chat with one of our AI concierges", idx);
    expect(chatIdx).toBeGreaterThan(idx);
    const slice = PH_SRC.slice(idx, chatIdx + 300);
    // Heading uses ``colors.onSurface`` (slate-100).
    expect(slice).toMatch(/color:\s*colors\.onSurface/);
    // Body uses ``colors.muted`` (slate-400).
    expect(slice).toMatch(/color:\s*colors\.muted/);
    // No more hard-coded ``#FFFFFF`` on the section's own text.
    const sectionEnd = PH_SRC.indexOf("portal-referral-section", idx);
    const sectionSlice = PH_SRC.slice(idx, sectionEnd > 0 ? sectionEnd : idx + 3000);
    // One ``#FFFFFF`` is permitted (the inner avatar circle's
    // fallback gradient family) but the heading / body MUST NOT
    // reference the pre-Phase-23 ``color: "#FFFFFF"`` style.
    expect(sectionSlice).not.toMatch(
      /style=\{\{ color: "#FFFFFF" \}\}\s*>\s*Ask a Concierge/,
    );
  });

  it("inner AI-employee buttons swap glass bg for the surfaceSecondary dark card", () => {
    const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
    const sectionEnd = PH_SRC.indexOf("portal-referral-section", idx);
    const section = PH_SRC.slice(idx, sectionEnd > 0 ? sectionEnd : idx + 3000);
    // The inner cards use ``colors.surfaceSecondary`` (raised
    // card bg) + ``colors.border`` — matches the dark chassis.
    expect(section).toMatch(/backgroundColor:\s*colors\.surfaceSecondary/);
    // The pre-Phase-23 ``rgba(255,255,255,0.16)`` glass bg +
    // ``rgba(255,255,255,0.28)`` border + ``backdropFilter`` are
    // retired.
    expect(section).not.toMatch(/rgba\(255,255,255,0\.16\)/);
    expect(section).not.toMatch(/rgba\(255,255,255,0\.28\)/);
    expect(section).not.toMatch(/backdropFilter:\s*"blur\(6px\)"/);
  });
});


describe("Phase 23 · Refer a Friend · dark chassis + GREEN accent", () => {
  it("gradient retired — ``portal-referral-section`` carries NO purple→pink gradient", () => {
    const idx = RS_SRC.indexOf('data-testid="portal-referral-section"');
    expect(idx).toBeGreaterThan(-1);
    const openIdx = RS_SRC.lastIndexOf("<div", idx);
    const closeIdx = RS_SRC.indexOf(">", idx);
    const openTag = RS_SRC.slice(openIdx, closeIdx);
    expect(openTag).not.toMatch(/7C3AED/);
    expect(openTag).not.toMatch(/A855F7/);
    expect(openTag).not.toMatch(/EC4899/);
    expect(openTag).not.toMatch(/linear-gradient/);
  });

  it("adopts the Balance-tile dark chassis + hover brighten", () => {
    const idx = RS_SRC.indexOf('data-testid="portal-referral-section"');
    const openIdx = RS_SRC.lastIndexOf("<div", idx);
    const closeIdx = RS_SRC.indexOf(">", idx);
    const openTag = RS_SRC.slice(openIdx, closeIdx);
    expect(openTag).toMatch(/rounded-2xl/);
    expect(openTag).toMatch(/transition hover:brightness-95/);
    expect(openTag).toMatch(/backgroundColor:\s*colors\.surface/);
    expect(openTag).toMatch(/border:\s*`1px solid \$\{colors\.border\}`/);
  });

  it("UserPlus icon + ``$55 credit`` highlight both carry the GREEN accent (``colors.success``)", () => {
    const headingIdx = RS_SRC.indexOf("Refer a Friend — earn");
    expect(headingIdx).toBeGreaterThan(-1);
    const slice = RS_SRC.slice(headingIdx - 300, headingIdx + 300);
    // UserPlus icon flipped to ``colors.success``.
    expect(slice).toMatch(/<UserPlus[\s\S]{0,80}color=\{colors\.success\}/);
    // ``$55 credit`` wrapped in a span that highlights with
    // ``colors.success``.
    expect(slice).toMatch(/color:\s*colors\.success[\s\S]{0,80}\$55 credit/);
  });

  it("submit button background flipped from ``colors.brand`` (blue) to ``colors.success`` (green)", () => {
    const btnIdx = RS_SRC.indexOf('data-testid="portal-referral-submit-btn"');
    expect(btnIdx).toBeGreaterThan(-1);
    const slice = RS_SRC.slice(btnIdx - 300, btnIdx + 60);
    expect(slice).toMatch(/background:\s*colors\.success/);
  });

  it("retired every ``text-white`` / ``color: #FFFFFF`` label on the dark card", () => {
    // Grep the full file.  The six form labels used to carry
    // ``className="text-[11px] font-bold uppercase text-white"``
    // + inline ``color: "#FFFFFF"``.  Phase 23 flips both to the
    // palette-wrapped ``colors.onSurface``.
    expect(RS_SRC).not.toMatch(/text-\[11px\] font-bold uppercase text-white/);
    const whiteHits = (RS_SRC.match(/color:\s*"#FFFFFF"/g) || []);
    // Only legitimate ``color: "#FFFFFF"`` surfaces remain on the
    // submit button's ``text-white`` className (which stays
    // because the green button needs white text).
    expect(whiteHits.length).toBe(0);
  });

  it("thank-you screen also adopts the dark chassis + GREEN accent", () => {
    const idx = RS_SRC.indexOf('data-testid="portal-referral-thankyou"');
    expect(idx).toBeGreaterThan(-1);
    const openIdx = RS_SRC.lastIndexOf("<div", idx);
    const closeIdx = RS_SRC.indexOf(">", idx);
    const openTag = RS_SRC.slice(openIdx, closeIdx);
    expect(openTag).toMatch(/backgroundColor:\s*colors\.surface/);
    expect(openTag).toMatch(/border:\s*`1px solid \$\{colors\.border\}`/);
    expect(openTag).not.toMatch(/F0FDF4/);     // retired light-green gradient start
    expect(openTag).not.toMatch(/DCFCE7/);     // retired light-green gradient end
    expect(openTag).not.toMatch(/linear-gradient/);
    // Thank-you Sparkles still uses the GREEN accent.
    const sparkIdx = RS_SRC.indexOf("<Sparkles", idx);
    const sparkSlice = RS_SRC.slice(sparkIdx, sparkIdx + 120);
    expect(sparkSlice).toMatch(/color=\{colors\.success\}/);
  });
});


describe("Phase 23 · NFC-Ready card hero · dark chassis + NAVY-variant accent", () => {
  it("compact-variant hero bypasses the branded gradient and adopts the dark chassis", () => {
    // Phase 23 gates the hero style on ``variant === \"compact\"``
    // (used by PortalHome).  Full-variant (admin / tech card)
    // keeps the branded gradient — regression lock below.
    expect(BC_SRC).toMatch(
      /const heroStyle = compact[\s\S]{0,400}backgroundColor:\s*PORTAL_HERO_BG/,
    );
    // Dark-chassis palette hardcoded = portalColors.surface / border.
    expect(BC_SRC).toMatch(/PORTAL_HERO_BG = "#03002e"/);
    expect(BC_SRC).toMatch(/PORTAL_HERO_BORDER = "#1E293B"/);
  });

  it("full-variant hero STILL uses the branded gradient (regression lock on admin + tech preview)", () => {
    // The ``variant=\"full\"`` branch must stay on the branded
    // gradient so BusinessCardSettings preview + the tech card
    // page don't suddenly flip dark too.
    expect(BC_SRC).toMatch(
      /heroStyle = compact[\s\S]{0,400}: \{ background: gradient \}/,
    );
    expect(BC_SRC).toMatch(/const gradient = `linear-gradient/);
  });

  it("NFC-ready badge flips to the NAVY-variant accent on the compact dark hero", () => {
    const badgeIdx = BC_SRC.indexOf(
      'data-testid="business-card-nfc-badge"');
    expect(badgeIdx).toBeGreaterThan(-1);
    const slice = BC_SRC.slice(badgeIdx - 500, badgeIdx + 60);
    // Compact branch uses PORTAL_HERO_ACCENT (navy variant).
    expect(slice).toMatch(/PORTAL_HERO_ACCENT/);
    expect(BC_SRC).toMatch(/PORTAL_HERO_ACCENT = "#1E3A8A"/);
    // Full branch stays on the pre-Phase-23 glass style.
    expect(slice).toMatch(/rgba\(255,255,255,0\.22\)/);
  });
});


describe("Phase 23 · wiring + content preserved · no handler / copy / testid altered", () => {
  it("every section's business-logic handler stays intact (regression lock)", () => {
    // Ask Concierge — chat trigger (``setAiChat({ employee: emp })``).
    expect(PH_SRC).toMatch(/onClick=\{\(\) => setAiChat\(\{\s*employee:\s*emp\s*\}\)\}/);
    // Refer a Friend — form submit + referral POST.
    expect(RS_SRC).toMatch(
      /await api\.post\("\/customer-portal\/referrals",\s*form\)/,
    );
    // NFC-Ready — vCard download / share / copy actions.
    expect(BC_SRC).toMatch(/fetchVcfText/);
    expect(BC_SRC).toMatch(/saveVcfBlob/);
    expect(BC_SRC).toMatch(/navigator\.clipboard\.writeText/);
  });

  it("every pre-Phase-23 testid preserved byte-for-byte", () => {
    const TESTIDS = [
      ["PortalHome.jsx", PH_SRC, "portal-ai-section"],
      // Billy / Charlie card testids are template-literal, so
      // match the ``portal-ai-${emp.key}-card`` pattern.
      ["ReferralSection.jsx", RS_SRC, "portal-referral-section"],
      ["ReferralSection.jsx", RS_SRC, "portal-referral-friend-name"],
      ["ReferralSection.jsx", RS_SRC, "portal-referral-friend-email"],
      ["ReferralSection.jsx", RS_SRC, "portal-referral-submit-btn"],
      ["ReferralSection.jsx", RS_SRC, "portal-referral-thankyou"],
      ["BusinessCard.jsx", BC_SRC, "business-card-hero"],
      ["BusinessCard.jsx", BC_SRC, "business-card-nfc-badge"],
    ];
    for (const [file, src, tid] of TESTIDS) {
      expect(src, `${file} missing ${tid}`).toContain(
        `data-testid="${tid}"`,
      );
    }
    // Billy + Charlie AI-card testids are template-literal.
    expect(PH_SRC).toMatch(
      /data-testid=\{`portal-ai-\$\{emp\.key\}-card`\}/,
    );
  });

  it("content strings preserved byte-for-byte (no copy drift)", () => {
    expect(PH_SRC).toContain("Ask a Concierge");
    expect(PH_SRC).toContain("Chat with one of our AI concierges");
    expect(RS_SRC).toContain("Refer a Friend — earn");
    expect(RS_SRC).toContain("$55 credit");
    expect(RS_SRC).toContain(
      "Know someone who could use pool or landscape care?",
    );
    expect(BC_SRC).toContain("NFC-ready");
  });

  it("tenant / role gates preserved — Ask Concierge still conditional on aiEmployees.length", () => {
    // Gate stays as ``{aiEmployees.length > 0 ? (<div …
    // data-testid="portal-ai-section" …`` — but there is a
    // multi-line comment block between the gate and the testid,
    // so widen the regex window.
    expect(PH_SRC).toMatch(
      /\{aiEmployees\.length > 0 \? \([\s\S]{0,2000}data-testid="portal-ai-section"/,
    );
  });

  it("Refer-a-Friend white input chrome preserved (locks ``ReferralSection.whiteInputs.test.jsx``)", () => {
    // The 6 form inputs keep their white backgrounds + slate
    // border + near-black text.  Phase 23 only flipped the OUTER
    // card chassis + the LABELS.
    const whiteBgHits = (RS_SRC.match(/background:\s*"#FFFFFF"/g) || []);
    expect(whiteBgHits.length).toBeGreaterThanOrEqual(6);
  });
});
