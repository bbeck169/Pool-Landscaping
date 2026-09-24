/**
 * Phase P53 tail · Feb-2026 — Fix B · Home breadcrumb 404.
 *
 * Locks the routeMeta invariants that prevent the Home crumb from
 * being a dead ``/dashboard`` link:
 *
 *   1. Home entry keyed by ``"/"`` (was ``"/dashboard"`` — a route
 *      that is NOT mounted in App.js).
 *   2. Every admin route's ``parent`` points at ``"/"`` (never at
 *      ``"/dashboard"``), so the breadcrumb chain always builds
 *      back to the real admin landing.
 *   3. Legacy ``/dashboard`` path stays in ``CRUMB_SKIP`` so a
 *      stale bookmark to that dead route doesn't render a
 *      misleading "Dashboard > ..." trail on the 404 shell.
 *   4. Deep-page ``buildCrumbs()`` walk produces a valid Home link
 *      pointing at ``/`` (not a broken ``/dashboard``).
 */
import { describe, it, expect } from "vitest";
import {
  CRUMB_SKIP,
  ROUTE_META,
  buildCrumbs,
  matchRouteKey,
} from "../components/breadcrumbs/routeMeta";


describe("P53 · Home breadcrumb route metadata", () => {
  it("Home entry is keyed by '/' (never '/dashboard')", () => {
    expect(ROUTE_META["/"]).toBeDefined();
    expect(ROUTE_META["/"].label).toBe("Home");
    expect(ROUTE_META["/"].parent).toBeNull();
    // The pre-P53 dead key must be gone.
    expect(ROUTE_META["/dashboard"]).toBeUndefined();
  });

  it("no route's parent is the dead '/dashboard' path", () => {
    const badParents = Object.entries(ROUTE_META).filter(
      ([, meta]) => meta && meta.parent === "/dashboard",
    );
    expect(badParents).toEqual([]);
  });

  it("every admin root's parent points at '/'", () => {
    const adminRoots = [
      "/workstream", "/schedule", "/customers", "/jobs",
      "/leads", "/quotes", "/estimates", "/invoices",
      "/payments", "/analytics", "/reports", "/reviews",
      "/marketing", "/admin", "/settings",
    ];
    for (const key of adminRoots) {
      expect(ROUTE_META[key]).toBeDefined();
      expect(ROUTE_META[key].parent).toBe("/");
    }
  });

  it("legacy '/dashboard' remains in CRUMB_SKIP for stale-bookmark safety", () => {
    // The route is NOT mounted, but a legacy bookmark shouldn't
    // trigger a misleading breadcrumb trail on the 404 shell.
    expect(CRUMB_SKIP.has("/dashboard")).toBe(true);
    // ``/`` (real admin home) is also skipped.
    expect(CRUMB_SKIP.has("/")).toBe(true);
  });

  it("buildCrumbs('/customers') → Home link resolves to '/'", () => {
    const crumbs = buildCrumbs("/customers");
    expect(crumbs.length).toBeGreaterThanOrEqual(2);
    // First crumb is Home, points at '/' (not '/dashboard').
    expect(crumbs[0].label).toBe("Home");
    expect(crumbs[0].path).toBe("/");
    // Last crumb is the current page (no link).
    expect(crumbs[crumbs.length - 1].label).toBe("Customers");
    expect(crumbs[crumbs.length - 1].path).toBeNull();
  });

  it("buildCrumbs('/customers/:id') → Home link resolves to '/'", () => {
    const crumbs = buildCrumbs("/customers/cust_abc",
      { customer: "Jennifer" });
    expect(crumbs.length).toBe(3);
    expect(crumbs[0].label).toBe("Home");
    expect(crumbs[0].path).toBe("/");
    expect(crumbs[1].label).toBe("Customers");
    expect(crumbs[1].path).toBe("/customers");
    expect(crumbs[2].label).toBe("Jennifer");
    expect(crumbs[2].path).toBeNull();
  });

  it("buildCrumbs('/settings/tenant/hq') → Home link resolves to '/'", () => {
    const crumbs = buildCrumbs("/settings/tenant/hq");
    expect(crumbs[0].label).toBe("Home");
    expect(crumbs[0].path).toBe("/");
    // No crumb in the chain points at the dead '/dashboard'.
    for (const c of crumbs) {
      expect(c.path).not.toBe("/dashboard");
    }
  });

  it("buildCrumbs('/admin/queue') → Home link resolves to '/'", () => {
    const crumbs = buildCrumbs("/admin/queue");
    expect(crumbs[0].label).toBe("Home");
    expect(crumbs[0].path).toBe("/");
    for (const c of crumbs) {
      expect(c.path).not.toBe("/dashboard");
    }
  });

  it("no crumb path anywhere in the map is '/dashboard'", () => {
    // Exhaustive scan — build crumbs for every static ROUTE_META
    // key + verify no rendered path is the dead route.
    for (const key of Object.keys(ROUTE_META)) {
      if (key.includes(":")) continue;  // dynamic — resolved elsewhere
      const crumbs = buildCrumbs(key);
      for (const c of crumbs) {
        expect(c.path).not.toBe("/dashboard");
      }
    }
  });

  it("matchRouteKey('/') → '/' (admin landing) and Home renders skip", () => {
    expect(matchRouteKey("/")).toBe("/");
    // '/' is in CRUMB_SKIP so buildCrumbs returns [] on the landing.
    expect(buildCrumbs("/")).toEqual([]);
  });

  it("tech routes still parent at '/tech/dashboard' (unchanged)", () => {
    // The tech shell has its own dashboard route — unrelated to
    // the admin fix. Regression bumper.
    expect(ROUTE_META["/tech/schedule"].parent).toBe("/tech/dashboard");
    expect(ROUTE_META["/tech/jobs"].parent).toBe("/tech/dashboard");
    expect(ROUTE_META["/tech/dashboard"].parent).toBeNull();
  });
});
