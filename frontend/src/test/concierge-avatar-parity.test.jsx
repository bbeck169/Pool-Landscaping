/**
 * Feb-2026 · AI Concierge avatar parity with AI Employee Hub.
 *
 * Source-inspection tests — same pattern as
 * ``customer-portal-invite-relocation.test.jsx``. Locks the contract
 * that the customer-facing Concierge (in PortalHome.jsx) renders
 * through the SAME shared ``<AIAvatar>`` component the AI Employee
 * Hub uses (``pages/aiops/AiOpsPages.jsx``), NOT through the older
 * ``<PersonaAvatar>`` primitive.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PORTAL_HOME = resolve(__dirname, "../pages/portal/PortalHome.jsx");
const HUB_PAGE    = resolve(__dirname, "../pages/aiops/AiOpsPages.jsx");
const portalSrc = readFileSync(PORTAL_HOME, "utf8");
const hubSrc    = readFileSync(HUB_PAGE, "utf8");


describe("Concierge · avatar parity with AI Employee Hub", () => {
  it("Hub uses AIAvatar (source of truth)", () => {
    // Sanity — Hub imports and renders <AIAvatar>.  If someone
    // rewires the Hub, this test surfaces the breakage first.
    expect(hubSrc).toMatch(/from "@\/components\/ai\/AIAvatar"/);
    expect(hubSrc).toMatch(/<AIAvatar\b/);
  });

  it("Concierge (PortalHome) imports the SAME shared AIAvatar", () => {
    expect(portalSrc).toMatch(/from "@\/components\/ai\/AIAvatar"/);
  });

  it("Concierge chat + picker both render via <AIAvatar>", () => {
    // Both surfaces on PortalHome now render through <AIAvatar>.
    // The old inline uses were flagged with the ``portal-ai-…``
    // testId prefix — every one of those must be an <AIAvatar>.
    const picker = portalSrc.match(
      /<AIAvatar[^>]+testId=\{`portal-ai-\$\{emp\.key\}-avatar`\}/,
    );
    const chat   = portalSrc.match(
      /<AIAvatar[^>]+testId=\{`portal-ai-chat-avatar-\$\{employee\.key\}`\}/,
    );
    expect(picker).not.toBeNull();
    expect(chat).not.toBeNull();
  });

  it("Concierge no longer renders PersonaAvatar for AI employees", () => {
    // Regression guard: no <PersonaAvatar> call inside the Concierge
    // sections should carry the ``portal-ai-…`` testid anymore.
    expect(portalSrc).not.toMatch(
      /<PersonaAvatar[^>]+testid=`portal-ai-\$\{emp\.key\}-avatar`/,
    );
    expect(portalSrc).not.toMatch(
      /<PersonaAvatar[^>]+testid=`portal-ai-chat-avatar-\$\{employee\.key\}`/,
    );
  });

  it("Fallback contract matches — both surfaces pass `name` for initial fallback", () => {
    // The shared <AIAvatar> renders a pastel initial-badge when
    // ``src`` is missing; the fallback is the SAME across every
    // surface because both call sites feed the ``name`` prop.
    const picker = portalSrc.match(
      /<AIAvatar[\s\S]*?name=\{emp\.name\}[\s\S]*?portal-ai-\$\{emp\.key\}/,
    );
    const chat = portalSrc.match(
      /<AIAvatar[\s\S]*?name=\{employee\.name\}[\s\S]*?portal-ai-chat-avatar-\$\{employee\.key\}/,
    );
    expect(picker).not.toBeNull();
    expect(chat).not.toBeNull();
    // The Hub itself feeds ``name`` too — same fallback rendered
    // when ``avatar_url`` is null. Phase C.web residual · Feb-2026 —
    // the Hub's prop now reads ``name={e.human_name || e.name}``
    // (per `AiOpsPages.jsx` display-name fallback). Widen the
    // regex to accept any expression body as long as it contains
    // ``e.name`` — the semantic intent (Hub passes an ``e.name``
    // reference into AIAvatar's name prop) is preserved.
    expect(hubSrc).toMatch(/<AIAvatar[\s\S]*?name=\{[^}]*e\.name[^}]*\}/);
  });
});
