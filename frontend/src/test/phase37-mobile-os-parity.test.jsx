// Phase 37 · Feb-2026 — Mobile Business OS Parity (P1.3) source-inspection.
//
// Locks in the 7 new OS surfaces + the hub tile links + a new
// Business OS drawer group. Huddle is a hub link only (mobile
// already has a technician-focused `mobile/app/huddle.tsx` — no dup).

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const NAV_PATH = resolve(MOBILE, "src/nav/adminNav.ts");
const HUB_PATH = resolve(MOBILE, "app/os/index.tsx");
const HUDDLE_PATH = resolve(MOBILE, "app/huddle.tsx");

const SURFACES = [
  {
    name: "OS Hub",
    file: "app/os/index.tsx",
    title: "Business OS",
    endpoints: ['api.get("/os/overview")'],
    testId: "os-hub-page",
  },
  {
    name: "OS · SOPs",
    file: "app/os/sops.tsx",
    title: "SOPs",
    endpoints: ['api.get("/sops")', 'api.post("/sops"', 'api.post("/sops/generate"'],
    testId: "os-sops-page",
    usesPrimitive: true,
  },
  {
    name: "OS · Roles",
    file: "app/os/roles.tsx",
    title: "Roles",
    endpoints: ['api.get("/role-definitions")', 'api.post("/role-definitions"'],
    testId: "os-roles-page",
    usesPrimitive: true,
  },
  {
    name: "OS · Scorecards",
    file: "app/os/scorecards.tsx",
    title: "Scorecards",
    endpoints: ['api.get("/kpi-scorecards")', 'api.post("/kpi-scorecards"'],
    testId: "os-scorecards-page",
    usesPrimitive: true,
  },
  {
    name: "OS · Lean Boards",
    file: "app/os/leanboards.tsx",
    title: "Lean Boards",
    endpoints: ['api.get("/leanboards")', "/leanboards/${boardId}/cards", "/move`"],
    testId: "os-leanboards-page",
  },
  {
    name: "OS · Sprints",
    file: "app/os/sprints.tsx",
    title: "Sprints",
    endpoints: ['api.get("/sprints")', 'api.post("/sprints"', "/retro-ai`"],
    testId: "os-sprints-page",
  },
  {
    name: "OS · Lana AI",
    file: "app/os/lana.tsx",
    title: "Lana AI",
    endpoints: ['api.post("/business-os/lana/chat"'],
    testId: "os-lana-page",
    // Phase 49 · Feb-2026 — Lana AI voice permissions legitimately use
    // ``Alert.alert`` for OS-native mic-permission prompts (mirroring
    // the Mapbox permission pattern from Phase 38b). Also gates at
    // ``admin_plus`` instead of ``strict_admin`` because it's the
    // only OS page that carries a manager-visible surface.
    roleLevel: "admin_plus",
    allowAlertAlert: true,
  },
];

describe("Phase 37 · Mobile Business OS — surface files", () => {
  for (const s of SURFACES) {
    describe(s.name, () => {
      const p = resolve(MOBILE, s.file);
      const src = existsSync(p) ? readFileSync(p, "utf8") : "";

      it(`file exists at mobile/${s.file}`, () => {
        expect(existsSync(p)).toBe(true);
      });

      it(`mounts <Header> and includes the title text "${s.title}"`, () => {
        // Phase 41.2 · Feb-2026 — pages migrated onto the shared
        // ``<AdminListPage>`` primitive no longer mount ``<Header>``
        // inline. Accept the primitive shape as equivalent.
        if (s.usesPrimitive) {
          expect(src).toMatch(/<AdminListPage\b/);
        } else {
          expect(src).toMatch(/<Header\b/);
        }
        expect(src).toContain(s.title);
      });

      for (const ep of s.endpoints) {
        it(`hits the backend endpoint (${ep})`, () => {
          expect(src).toContain(ep);
        });
      }

      it(`carries the root testID (${s.testId})`, () => {
        expect(src).toMatch(new RegExp(`testID=["'\`]${s.testId}["'\`]`));
      });

      it("role-gates to strict_admin", () => {
        // Phase 41.2 · Feb-2026 — pages using ``<AdminListPage>`` inherit
        // the primitive's default ``roleLevel="strict_admin"`` (verified
        // by the primitive's own tests). Accept either shape:
        //   • inline ``<RoleGate level="strict_admin">`` (legacy)
        //   • ``<AdminListPage>`` (primitive supplies the gate)
        // Phase 49 · Feb-2026 — Lana AI legitimately gates at
        // ``admin_plus`` (manager-visible surface). ``roleLevel`` on
        // the surface entry overrides the default expectation.
        const expected = s.roleLevel || "strict_admin";
        const primitiveOk = s.usesPrimitive && /<AdminListPage\b/.test(src);
        const inlineOk = new RegExp(
          `<RoleGate\\s+level=["']${expected}["']`,
        ).test(src);
        expect(primitiveOk || inlineOk).toBe(true);
      });

      it("does NOT use Alert.alert (Phase 30.4 root cause)", () => {
        // Phase 49 · Feb-2026 — Lana AI voice input legitimately uses
        // ``Alert.alert`` for OS-native mic-permission prompts. The
        // ``allowAlertAlert`` flag on the surface entry opts out of
        // this specific check for that one file.
        if (s.allowAlertAlert) return;
        expect(src).not.toMatch(/Alert\.alert\(/);
      });
    });
  }
});

describe("Phase 37 · Hub tile links (all 7 deep-dives)", () => {
  const src = existsSync(HUB_PATH) ? readFileSync(HUB_PATH, "utf8") : "";

  const LINKS = [
    { to: "/os/sops",        testId: "os-link-sops" },
    { to: "/os/roles",       testId: "os-link-roles" },
    { to: "/os/scorecards",  testId: "os-link-scorecards" },
    { to: "/huddle",         testId: "os-link-huddle" },
    { to: "/os/leanboards",  testId: "os-link-leanboards" },
    { to: "/os/sprints",     testId: "os-link-sprints" },
    { to: "/os/lana",        testId: "os-link-lana" },
  ];

  for (const l of LINKS) {
    it(`links to ${l.to}`, () => {
      expect(src).toContain(l.to);
      expect(src).toContain(l.testId);
    });
  }

  it("renders the deep-dive tile row", () => {
    expect(src).toMatch(/testID=["']os-deep-dives["']/);
  });
});

describe("Phase 37 · Existing huddle screen unchanged (regression net)", () => {
  it("mobile/app/huddle.tsx still exists (technician submit form)", () => {
    expect(existsSync(HUDDLE_PATH)).toBe(true);
    const src = readFileSync(HUDDLE_PATH, "utf8");
    // Still uses the huddle endpoints (Phase 16B).
    expect(src).toMatch(/\/huddles/);
  });
});

describe("Phase 37 · Drawer nav — Business OS group", () => {
  const src = existsSync(NAV_PATH) ? readFileSync(NAV_PATH, "utf8") : "";

  it("adds a Business OS group with 8 T1 entries", () => {
    expect(src).toMatch(/key:\s*"business_os"/);
    for (const testId of [
      "drawer-nav-os-hub",
      "drawer-nav-os-sops",
      "drawer-nav-os-roles",
      "drawer-nav-os-scorecards",
      "drawer-nav-os-huddle",
      "drawer-nav-os-leanboards",
      "drawer-nav-os-sprints",
      "drawer-nav-os-lana",
    ]) {
      expect(src).toContain(testId);
    }
  });

  it("uses the real mobile routes (not desktop /admin/os/*) for all entries", () => {
    for (const route of [
      '"/os"',
      '"/os/sops"',
      '"/os/roles"',
      '"/os/scorecards"',
      '"/huddle"',
      '"/os/leanboards"',
      '"/os/sprints"',
      '"/os/lana"',
    ]) {
      expect(src).toContain(route);
    }
  });

  it("regression: prior nav groups intact", () => {
    // Phase 35/36 groups still present.
    expect(src).toContain('drawer-nav-recurring-jobs');
    expect(src).toContain('drawer-nav-cfo-forecast');
  });
});
