// Queue Item 6 · Feb-2026 — Dashboard nav shortcut source-inspection.
//
// Locks in that both the web sidebar and the mobile drawer add a
// "Dashboard" link (Home icon) directly under the search input.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const WEB_SIDEBAR = resolve(__dirname, "../layouts/AdminSidebar.jsx");
const MOBILE_MENU = resolve(__dirname, "../../../mobile/src/components/tools/ToolsMenuBody.tsx");

const read = (p) => readFileSync(p, "utf8");

describe("Queue Item 6 · Dashboard nav shortcut", () => {
  describe("Web sidebar (AdminSidebar.jsx)", () => {
    const src = read(WEB_SIDEBAR);
    it("imports the Home icon from lucide-react", () => {
      expect(src).toMatch(/Home as HomeIcon.*from ["']lucide-react["']/);
    });
    it("renders the Dashboard NavLink with the Home icon and testID", () => {
      expect(src).toContain('data-testid="nav-dashboard-link"');
      expect(src).toContain("<HomeIcon size={14} />");
      // Route target is the root "/".
      expect(src).toMatch(/<NavLink[\s\S]*?to="\/"[\s\S]*?end/);
    });
    it("mounts the link between the palette trigger and the pinned block", () => {
      const paletteIdx = src.indexOf('data-testid="nav-palette-trigger"');
      const dashIdx = src.indexOf('data-testid="nav-dashboard-link"');
      const pinnedIdx = src.indexOf('data-testid="nav-pinned"');
      expect(paletteIdx).toBeGreaterThan(-1);
      expect(dashIdx).toBeGreaterThan(paletteIdx);
      // Only assert pinnedIdx ordering when pinned is present.
      if (pinnedIdx > -1) {
        expect(dashIdx).toBeLessThan(pinnedIdx);
      }
    });
  });

  describe("Mobile drawer (ToolsMenuBody.tsx)", () => {
    it("file exists", () => {
      expect(existsSync(MOBILE_MENU)).toBe(true);
    });
    const src = read(MOBILE_MENU);
    it("renders the Dashboard Pressable with the Home icon and testID", () => {
      expect(src).toContain('testID="mobile-menu-dashboard-link"');
      expect(src).toContain('name="home-outline"');
    });
    it("mounts the shortcut directly under the SearchBar", () => {
      const searchIdx = src.indexOf("<SearchBar");
      const dashIdx = src.indexOf('testID="mobile-menu-dashboard-link"');
      expect(searchIdx).toBeGreaterThan(-1);
      expect(dashIdx).toBeGreaterThan(searchIdx);
      // And appears before the QuickAccess strip (also above pins/recents).
      const quickAccessIdx = src.indexOf("<QuickAccessChips");
      expect(dashIdx).toBeLessThan(quickAccessIdx);
    });
    it("routes to the /(app) group index (the mobile dashboard)", () => {
      expect(src).toMatch(/const route = "\/\(app\)" as any/);
    });
    it("hides the shortcut once the user starts searching", () => {
      // Wrapped inside {!query ? ... : null}
      expect(src).toMatch(/\{!query \? \(\s*<Pressable/);
    });
  });
});
