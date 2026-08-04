// Phase 38 · Feb-2026 — Mobile Dispatch Parity (P1.4) source-inspection.
//
// Locks in the 4 new mobile dispatch pieces + the Phase 30.4
// completeness patch on `huddle.tsx`:
//
//   1. OptimizeRoute page      mobile/app/dispatch/optimize.tsx
//   2. ShiftRoute page         mobile/app/dispatch/shift-route.tsx
//   3. TechLoadStrip component mobile/src/components/dispatch/TechLoadStrip.tsx
//   4. UnroutedPanel component mobile/src/components/dispatch/UnroutedPanel.tsx
//   +  Board wiring            mobile/app/(app)/dispatch/board.tsx
//   +  Alert.alert removal     mobile/app/huddle.tsx
//
// Live pin layer explicitly deferred to Phase 38b — no new mapping
// dep introduced.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");

const F = (rel) => resolve(MOBILE, rel);
const R = (rel) => existsSync(F(rel)) ? readFileSync(F(rel), "utf8") : "";

describe("Phase 38 · Optimize Route page", () => {
  const src = R("app/dispatch/optimize.tsx");
  it("file exists", () => expect(existsSync(F("app/dispatch/optimize.tsx"))).toBe(true));
  it("mounts <Header> titled 'Optimize Route'", () => {
    expect(src).toMatch(/<Header\b/); expect(src).toContain("Optimize Route");
  });
  it("hits POST /dispatch/route/optimize for the preview", () => {
    expect(src).toMatch(/api\.post\(["']\/dispatch\/route\/optimize["']/);
  });
  it("hits POST /dispatch/route/apply for the persist action", () => {
    expect(src).toMatch(/api\.post\(["']\/dispatch\/route\/apply["']/);
  });
  it("wraps the destructive apply in showConfirm (never Alert.alert)", () => {
    expect(src).toMatch(/showConfirm\(/);
    expect(src).not.toMatch(/Alert\.alert\(/);
  });
  it("role-gates to strict_admin", () => {
    expect(src).toMatch(/<RoleGate\s+level=["']strict_admin["']/);
  });
  it("carries root testID dispatch-optimize-page", () => {
    expect(src).toContain("dispatch-optimize-page");
  });
});

describe("Phase 38 · Shift Route page", () => {
  const src = R("app/dispatch/shift-route.tsx");
  it("file exists", () => expect(existsSync(F("app/dispatch/shift-route.tsx"))).toBe(true));
  it("mounts <Header> titled 'Shift Route'", () => {
    expect(src).toMatch(/<Header\b/); expect(src).toContain("Shift Route");
  });
  it("hits POST /dispatch/reassign", () => {
    expect(src).toMatch(/api\.post\(["']\/dispatch\/reassign["']/);
  });
  it("permanent duration confirms via showConfirm (never Alert.alert)", () => {
    expect(src).toMatch(/showConfirm\(/);
    expect(src).not.toMatch(/Alert\.alert\(/);
    expect(src).toContain("PERMANENT");
  });
  it("handles existing_override_conflict via a second showConfirm", () => {
    expect(src).toContain("existing_override_conflict");
    expect(src).toContain("shift-route-conflict-confirm");
  });
  it("carries root testID dispatch-shift-route-page", () => {
    expect(src).toContain("dispatch-shift-route-page");
  });
});

describe("Phase 38 · TechLoadStrip component", () => {
  const src = R("src/components/dispatch/TechLoadStrip.tsx");
  it("file exists", () => expect(existsSync(F("src/components/dispatch/TechLoadStrip.tsx"))).toBe(true));
  it("exports a TechLoadStrip named component", () => {
    expect(src).toMatch(/export function TechLoadStrip/);
    expect(src).toMatch(/export type TechLoad/);
  });
  it("renders the dispatch-tech-load-list testID", () => {
    expect(src).toContain("dispatch-tech-load-list");
    expect(src).toContain("dispatch-tech-load-empty");
  });
});

describe("Phase 38 · UnroutedPanel component", () => {
  const src = R("src/components/dispatch/UnroutedPanel.tsx");
  it("file exists", () => expect(existsSync(F("src/components/dispatch/UnroutedPanel.tsx"))).toBe(true));
  it("exports an UnroutedPanel named component", () => {
    expect(src).toMatch(/export function UnroutedPanel/);
    expect(src).toMatch(/export type UnroutedPin/);
  });
  it("renders the dispatch-unrouted-panel testID", () => {
    expect(src).toContain("dispatch-unrouted-panel");
    expect(src).toContain("dispatch-unrouted-empty");
  });
});

describe("Phase 38 · Board wiring", () => {
  const src = R("app/(app)/dispatch/board.tsx");
  it("board.tsx exists", () => expect(existsSync(F("app/(app)/dispatch/board.tsx"))).toBe(true));
  it("imports the two new sub-components", () => {
    expect(src).toContain('from "@/src/components/dispatch/TechLoadStrip"');
    expect(src).toContain('from "@/src/components/dispatch/UnroutedPanel"');
  });
  it("hits /dispatch/board to hydrate the new panels", () => {
    expect(src).toMatch(/api\.get\(["']\/dispatch\/board/);
  });
  it("renders a tools row with Optimize + Shift buttons", () => {
    expect(src).toContain("dispatch-tools-row");
    expect(src).toContain("dispatch-open-optimize");
    expect(src).toContain("dispatch-open-shift-route");
  });
  it("navigates to the two new sub-pages via router.push", () => {
    expect(src).toContain("/dispatch/optimize");
    expect(src).toContain("/dispatch/shift-route");
  });
  it("regression: pre-existing auto-assign flow still present", () => {
    expect(src).toMatch(/api\.post\(["']\/dispatch\/auto-assign["']/);
    expect(src).toContain("dispatch-autoassign-toggle");
  });
});

describe("Phase 38 · Phase 30.4 completeness patch on huddle.tsx", () => {
  const src = R("app/huddle.tsx");
  it("no longer imports Alert from react-native", () => {
    expect(src).not.toMatch(/import\s*\{[^}]*\bAlert\b[^}]*\}\s*from\s*["']react-native["']/);
  });
  it("no Alert.alert() calls remain", () => {
    expect(src).not.toMatch(/Alert\.alert\(/);
  });
  it("uses an inline status banner instead", () => {
    expect(src).toContain("huddle-status-banner");
  });
  it("regression: still posts to /huddles + /huddles/{id}/action-items", () => {
    expect(src).toMatch(/api\.post\(["']\/huddles["']/);
    expect(src).toMatch(/\/huddles\/\$\{[^}]+\}\/action-items/);
  });
});

describe("Phase 38 · Live-pin layer explicitly deferred (38b)", () => {
  it("no react-native-mapbox / new mapping dep was added", () => {
    const pkg = readFileSync(resolve(MOBILE, "package.json"), "utf8");
    expect(pkg).not.toMatch(/@rnmapbox\/maps/);
    expect(pkg).not.toMatch(/react-native-mapbox/);
    // The pre-existing dep (react-native-maps) is unchanged — its
    // presence is fine; a new one would fail this test.
    expect(pkg).toContain('"react-native-maps"');
  });
  it("no new LivePins component landed in the board file", () => {
    const src = R("app/(app)/dispatch/board.tsx");
    expect(src).not.toMatch(/LiveTechPinsLayer/);
    expect(src).not.toMatch(/LivePins/);
  });
});
