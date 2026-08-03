/**
 * Phase 30 · Feb-2026 — Portal + Admin avatar coverage vitest.
 *
 * Scope: Option 3 + A + mobile persona correction (Phase 30.1) +
 * specialty subtitle.
 *
 *   Part A — web AI persona:  PortalHome uses PersonaAvatar at
 *                             card grid + chat header. Hand-rolled
 *                             <img src={emp.avatar_url}> is gone.
 *   Part B — web tech:        PortalHome + PortalPages + CopilotPage
 *                             each import TechAvatar, mount it, and
 *                             carry the correct testid pattern.
 *   Part C — mobile:          mobile/app/portal/{home,services,
 *                             service/[id]}.tsx each import mobile
 *                             TechAvatar and mount it. home.tsx
 *                             ALSO imports mobile PersonaAvatar and
 *                             renders the concierge specialty
 *                             subtitle from emp.role.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");

const PORTAL_HOME       = R("../pages/portal/PortalHome.jsx");
const PORTAL_PAGES      = R("../pages/portal/PortalPages.jsx");
const COPILOT           = R("../pages/admin/CopilotPage.jsx");
const M_HOME            = R("../../../mobile/app/portal/home.tsx");
const M_SERVICES        = R("../../../mobile/app/portal/services.tsx");
const M_SERVICE_DETAIL  = R("../../../mobile/app/portal/service/[id].tsx");

describe("Phase 30 · Part A · Web AI persona (PortalHome)", () => {
  it("imports PersonaAvatar", () => {
    expect(PORTAL_HOME).toMatch(
      /import\s+PersonaAvatar\s+from\s+["']@\/components\/personas\/PersonaAvatar["']/,
    );
  });
  it("mounts PersonaAvatar at concierge card grid (portal-ai-{key}-avatar)", () => {
    expect(PORTAL_HOME).toMatch(
      /<PersonaAvatar[\s\S]*?persona=\{emp\}[\s\S]*?testid=\{`portal-ai-\$\{emp\.key\}-avatar`\}/,
    );
  });
  it("mounts PersonaAvatar at chat header (portal-ai-chat-avatar-{key})", () => {
    expect(PORTAL_HOME).toMatch(
      /<PersonaAvatar[\s\S]*?persona=\{employee\}[\s\S]*?testid=\{`portal-ai-chat-avatar-\$\{employee\.key\}`\}/,
    );
  });
  it("regression · no hand-rolled <img src={emp.avatar_url}> block remains", () => {
    expect(PORTAL_HOME).not.toMatch(/<img[^>]*src=\{emp\.avatar_url\}/);
    expect(PORTAL_HOME).not.toMatch(/<img[^>]*src=\{employee\.avatar_url\}/);
  });
});

describe("Phase 30 · Part B · Web TechAvatar coverage", () => {
  it("PortalHome imports TechAvatar + mounts at next/last visit", () => {
    expect(PORTAL_HOME).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(PORTAL_HOME).toMatch(/testid=["']portal-tech-avatar-next["']/);
    expect(PORTAL_HOME).toMatch(/testid=["']portal-tech-avatar-last["']/);
  });
  it("PortalPages imports TechAvatar + mounts at list + detail", () => {
    expect(PORTAL_PAGES).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(PORTAL_PAGES).toMatch(
      /testid=\{`portal-tech-avatar-\$\{j\.id\}`\}/,
    );
  });
  it("CopilotPage imports TechAvatar + swaps <UserIcon> for the chat author avatar", () => {
    expect(COPILOT).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(COPILOT).toMatch(/testid=\{`admin-tech-avatar-copilot-/);
    // Regression — the old lucide UserIcon at the chat author spot is gone
    // from the JSX (comment mentions are allowed).
    const codeOnly = COPILOT
      .split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
    expect(codeOnly).not.toMatch(/<UserIcon\b/);
  });
});

describe("Phase 30 · Part C · Mobile portal avatars", () => {
  it("home.tsx imports TechAvatar + PersonaAvatar", () => {
    expect(M_HOME).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(M_HOME).toMatch(
      /import\s*\{\s*PersonaAvatar\s*\}\s*from\s*["']@\/src\/components\/personas\/PersonaAvatar["']/,
    );
  });
  it("home.tsx mounts PersonaAvatar with portal-ai-{key}-avatar testID", () => {
    expect(M_HOME).toMatch(
      /<PersonaAvatar[\s\S]*?testID=\{`portal-ai-\$\{emp\.key\}-avatar`\}/,
    );
  });
  it("home.tsx renders specialty subtitle from emp.role + conciergeSpecialty style", () => {
    expect(M_HOME).toMatch(
      /style=\{s\.conciergeSpecialty\}[\s\S]*?\{emp\.role/,
    );
    expect(M_HOME).toMatch(/conciergeSpecialty\s*:\s*\{/);
  });
  it("home.tsx has TechAvatar next-service chip with portal-tech-avatar-next testID", () => {
    expect(M_HOME).toMatch(
      /<TechAvatar[\s\S]*?testID=["']portal-tech-avatar-next["']/,
    );
  });
  it("services.tsx imports TechAvatar + mounts with portal-tech-avatar-{id} testID", () => {
    expect(M_SERVICES).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(M_SERVICES).toMatch(
      /<TechAvatar[\s\S]*?testID=\{`portal-tech-avatar-\$\{item\.id\}`\}/,
    );
  });
  it("service/[id].tsx imports TechAvatar + mounts with portal-tech-avatar-{id} testID", () => {
    expect(M_SERVICE_DETAIL).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
    expect(M_SERVICE_DETAIL).toMatch(
      /<TechAvatar[\s\S]*?testID=\{`portal-tech-avatar-\$\{job\.id\}`\}/,
    );
  });
  it("home.tsx no longer renders the hand-rolled conciergeEmoji <Text> block", () => {
    // Regression guard against the pre-Phase-30.1 emoji-only render.
    expect(M_HOME).not.toMatch(/<Text\s+style=\{s\.conciergeEmoji\}/);
  });
});
