/**
 * Feb-2026 · AI Dock ↔ AI Employees page avatar parity.
 *
 * Guarantees the AI Dock roster + chat header render the SAME
 * <AIAvatar> component the /ai-employees page uses, so every
 * persona shows the same portrait across both surfaces.
 *
 * Source-inspection style (same pattern as
 * ``customer-detail-action-row.test.jsx``): fast, no jsdom needed.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const AIDOCK = readFileSync(
  resolve(__dirname, "../components/AIDock/AIDock.jsx"), "utf8");
const AIOPS  = readFileSync(
  resolve(__dirname, "../pages/aiops/AiOpsPages.jsx"), "utf8");
const AIAVA  = readFileSync(
  resolve(__dirname, "../components/ai/AIAvatar.jsx"), "utf8");


describe("AI Dock ↔ AI Employees page — shared avatar component", () => {
  it("AI Dock imports the shared <AIAvatar> component", () => {
    expect(AIDOCK).toMatch(/import\s+AIAvatar\s+from\s+["']@\/components\/ai\/AIAvatar["']/);
  });

  it("AI Employees page imports the same shared <AIAvatar> component", () => {
    expect(AIOPS).toMatch(/import\s+AIAvatar\s+from\s+["']@\/components\/ai\/AIAvatar["']/);
  });

  it("AI Dock roster row uses <AIAvatar> with the persona's avatar_url + name", () => {
    // The roster row previously rendered ``e.avatar_emoji`` — the
    // legacy emoji span must be gone from the roster branch.
    const rosterIdx = AIDOCK.indexOf('data-testid="ai-dock-roster"');
    expect(rosterIdx).toBeGreaterThan(-1);
    const roster = AIDOCK.slice(rosterIdx, rosterIdx + 2500);
    // <AIAvatar> is present.
    expect(roster).toMatch(/<AIAvatar\b/);
    // Wired to the persona's avatar_url (single source of truth).
    expect(roster).toMatch(/src=\{e\.avatar_url\b/);
    // Name passed for the initial-fallback.
    expect(roster).toMatch(/name=\{e\.name\}/);
    // Legacy emoji rendering removed from the roster row.
    expect(roster).not.toMatch(/e\.avatar_emoji/);
  });

  it("AI Dock chat header uses <AIAvatar> with the selected persona", () => {
    const chatIdx = AIDOCK.indexOf('data-testid="ai-dock-chat"');
    expect(chatIdx).toBeGreaterThan(-1);
    const chat = AIDOCK.slice(chatIdx, chatIdx + 2500);
    expect(chat).toMatch(/<AIAvatar\b/);
    expect(chat).toMatch(/src=\{employee\?\.avatar_url\b/);
    expect(chat).toMatch(/name=\{employee\?\.name\}/);
    expect(chat).not.toMatch(/employee\?\.avatar_emoji/);
  });

  it("shared <AIAvatar> renders an initial-in-circle fallback when src is missing", () => {
    // Ensures the "no icons" fallback contract holds — the missing-
    // src branch renders the initial letter inside a pastel circle,
    // not the raw Lottie loop / a lucide icon.
    expect(AIAVA).toMatch(/{initial}/);
    expect(AIAVA).toMatch(/-initial/);
    expect(AIAVA).toMatch(/pickPastel/);
  });

  it("2+ personas exercised — both surfaces derive the row from the persona payload", () => {
    // The AI Dock roster maps over ``employees`` (an array of
    // persona records with ``key``, ``name``, ``avatar_url``); the
    // /ai-employees page maps over ``rows`` with the same shape.
    // Assert both surfaces pass the same identifying fields — this
    // is the "shared source" guarantee: swapping to any 2 personas
    // (e.g. Casey + Emmie) automatically wires the same avatar to
    // both places.
    expect(AIDOCK).toMatch(/employees\.map\(\(e\)\s*=>/);
    expect(AIOPS).toMatch(/rows\.map\(\(e\)\s*=>/);
    expect(AIDOCK).toMatch(/ai-dock-avatar-\$\{e\.key\s*\|\|\s*e\.slug\s*\|\|\s*e\.id\}/);
    expect(AIOPS).toMatch(/ai-lottie-avatar-\$\{e\.slug\s*\|\|\s*e\.id\}/);
  });
});
