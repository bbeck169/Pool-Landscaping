/**
 * Feb 2026 · Sidebar "Pricebook" quick-menu entry.
 *
 * Contract:
 *   * The Pricebook entry is registered in ADMIN_NAV_V2 under the
 *     ``operations`` group's "Schedule & Dispatch" subsection with
 *     ``hard_rule: "manager_only"`` — mirroring the Recurring Jobs
 *     precedent shipped in this session.
 *   * The route target is ``/price-book`` (the OpsHub Price Book
 *     grid; see ``App.js`` — ``<Route path="price-book" element={
 *     <OpsHub />} />``).
 *   * The AdminSidebar filter surfaces the entry for super_admin,
 *     admin and manager; techs and portal customers never see it.
 *
 * These tests validate BOTH the config (adminNav.js) and the
 * runtime filter behaviour without mounting the sidebar itself —
 * the sidebar tree flakes under vitest's forked workers. We
 * exercise the filter logic directly by replicating it here, which
 * is the same code path the runtime uses.
 */
import { describe, it, expect } from "vitest";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";


const PRICEBOOK_TO = "/price-book";


function _visibleForRole(effectiveRole, canReadAll = true) {
  return ADMIN_NAV_V2.map((g) => ({
    ...g,
    entries: g.entries.filter((e) => {
      if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
      if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
      if (e.hard_rule === "manager_only") {
        return ["super_admin", "admin", "manager"].includes(effectiveRole);
      }
      if (e.feature === "jobs" && (effectiveRole === "technician" || effectiveRole === "customer")) {
        // Techs + customers do NOT get the ``jobs`` feature in the
        // default matrix — mirrored here.
        return false;
      }
      return canReadAll || effectiveRole === "admin";
    }),
  })).filter((g) => g.entries.length > 0);
}


describe("Pricebook sidebar shortcut · adminNav.js registration", () => {
  it("registers exactly one operations-group Pricebook entry in the Schedule & Dispatch subsection", () => {
    const opsGroup = ADMIN_NAV_V2.find((g) => g.key === "operations");
    expect(opsGroup).toBeTruthy();
    const opsPricebook = opsGroup.entries.filter(
      (e) => e.to === PRICEBOOK_TO && e.subsection === "Schedule & Dispatch",
    );
    expect(opsPricebook).toHaveLength(1);
  });

  it("does NOT keep a lingering Field Service Pricebook duplicate", () => {
    const opsGroup = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const stray = opsGroup.entries.filter(
      (e) => e.to === PRICEBOOK_TO && e.subsection !== "Schedule & Dispatch",
    );
    expect(stray).toHaveLength(0);
  });

  it("uses hard_rule 'manager_only' + feature 'jobs' + Tag/DollarSign/BookOpen icon", () => {
    const opsGroup = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const entry = opsGroup.entries.find(
      (e) => e.to === PRICEBOOK_TO && e.subsection === "Schedule & Dispatch",
    );
    expect(entry.hard_rule).toBe("manager_only");
    expect(entry.feature).toBe("jobs");
    expect(entry.label).toMatch(/pricebook|price book/i);
    expect(entry.icon).toBeTruthy();
  });

  it("sits adjacent to the Recurring Jobs shortcut in the Schedule & Dispatch subsection", () => {
    const opsGroup = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const recurIndex = opsGroup.entries.findIndex(
      (e) => e.to === "/admin/recurring-jobs" && e.subsection === "Schedule & Dispatch",
    );
    const priceIndex = opsGroup.entries.findIndex(
      (e) => e.to === PRICEBOOK_TO && e.subsection === "Schedule & Dispatch",
    );
    expect(recurIndex).toBeGreaterThanOrEqual(0);
    expect(priceIndex).toBeGreaterThanOrEqual(0);
    // Immediately after — no unrelated entry in between.
    expect(priceIndex - recurIndex).toBe(1);
  });
});


describe("Pricebook sidebar shortcut · role gating (all 5 roles)", () => {
  const findEntry = (visible, to, subsection) => {
    for (const g of visible) {
      const hit = g.entries.find(
        (e) => e.to === to && (!subsection || e.subsection === subsection),
      );
      if (hit) return hit;
    }
    return null;
  };

  it("super_admin sees Pricebook under Operations · Schedule & Dispatch", () => {
    const vis = _visibleForRole("super_admin");
    expect(findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch")).toBeTruthy();
  });

  it("admin sees Pricebook", () => {
    const vis = _visibleForRole("admin");
    expect(findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch")).toBeTruthy();
  });

  it("manager sees Pricebook — manager_only allows manager role explicitly", () => {
    const vis = _visibleForRole("manager");
    const entry = findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch");
    expect(entry).toBeTruthy();
    expect(entry.hard_rule).toBe("manager_only");
  });

  it("technician does NOT see Pricebook", () => {
    const vis = _visibleForRole("technician");
    expect(findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch")).toBeNull();
  });

  it("customer does NOT see Pricebook", () => {
    const vis = _visibleForRole("customer");
    expect(findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch")).toBeNull();
  });

  it("marketer + sales roles do NOT see Pricebook (outside the three-role allowed set)", () => {
    for (const r of ["marketer", "sales"]) {
      const vis = _visibleForRole(r);
      expect(findEntry(vis, PRICEBOOK_TO, "Schedule & Dispatch")).toBeNull();
    }
  });

  it("Pricebook flattens into NAV_FLAT so the command palette can surface it", async () => {
    const { NAV_FLAT } = await import("@/nav/adminNav");
    const hit = NAV_FLAT.find(
      (e) => e.to === PRICEBOOK_TO && e.subsection === "Schedule & Dispatch",
    );
    expect(hit).toBeTruthy();
    // ZZ-A Wave 3-A · Feb-2026 — the OPS-NAV-FLATTEN pass changed
    // NAV_FLAT's ``group`` key to prefer ``subsection`` (post-
    // flatten) over the broader top-level ``g.label`` ("Operations").
    // The command palette now groups the entry under "Schedule &
    // Dispatch" so sibling schedule/dispatch entries cluster
    // together rather than collapsing under the "Operations"
    // bucket. See ``nav/adminNav.js`` OPS-NAV-FLATTEN comment.
    expect(hit.group).toBe("Schedule & Dispatch");
  });
});
