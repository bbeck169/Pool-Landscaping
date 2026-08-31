/**
 * Phase F1 · Feb-2026 — Bulk "Navigate route" tests.
 */
import { describe, it, expect, vi } from "vitest";
import { buildMapsRouteUrl, runBulkNavigateRoute, _sortForRoute, _resolveStop } from "../lib/googleMapsRoute";

const J = (o) => ({ id: "j", ...o });

describe("googleMapsRoute", () => {
  it("returns null url for 0 valid stops", () => {
    const r = buildMapsRouteUrl([]);
    expect(r.url).toBe(null);
    expect(r.usedCount).toBe(0);
  });

  it("returns single-destination URL for 1 stop", () => {
    const r = buildMapsRouteUrl([J({ address: "1 A St" })]);
    expect(r.url).toContain("destination=1+A+St");
    expect(r.url).not.toContain("waypoints=");
    expect(r.usedCount).toBe(1);
    expect(r.capped).toBe(false);
  });

  it("orders by date then route_index then tech", () => {
    const jobs = [
      J({ id: "a", scheduled_date: "2026-02-06", route_index: 1, address: "A" }),
      J({ id: "b", scheduled_date: "2026-02-05", route_index: 2, tech_user_id: "t2", address: "B" }),
      J({ id: "c", scheduled_date: "2026-02-05", route_index: 2, tech_user_id: "t1", address: "C" }),
    ];
    const ordered = _sortForRoute(jobs).map((j) => j.id);
    expect(ordered).toEqual(["c", "b", "a"]);
  });

  it("caps at 10 stops and reports capped=true", () => {
    const jobs = Array.from({ length: 15 }, (_, i) =>
      J({ id: `j${i}`, scheduled_date: "2026-02-05", route_index: i, address: `A${i}` }),
    );
    const r = buildMapsRouteUrl(jobs);
    expect(r.capped).toBe(true);
    expect(r.usedCount).toBe(10);
    expect(r.originalCount).toBe(15);
    expect(r.droppedNoAddress).toBe(0);
  });

  it("skips stops with no lat/lng and no address", () => {
    const jobs = [
      J({ address: "1 A St" }),
      J({ address: "" }),
      J({ latitude: 33, longitude: -112 }),
    ];
    const r = buildMapsRouteUrl(jobs);
    expect(r.usedCount).toBe(2);
    expect(r.droppedNoAddress).toBe(1);
  });

  it("prefers lat/lng over address when both present", () => {
    expect(_resolveStop(J({ latitude: 33.5, longitude: -112.1, address: "X" }))).toBe("33.5,-112.1");
    expect(_resolveStop(J({ latitude: 0, longitude: 0, address: "X" }))).toBe("X");
    expect(_resolveStop(J({ address: "" }))).toBe(null);
  });

  it("mixes address-only + lat/lng jobs into a single URL", () => {
    const jobs = [
      J({ id: "a", scheduled_date: "2026-02-05", route_index: 1, address: "1 Palm Rd" }),
      J({ id: "b", scheduled_date: "2026-02-05", route_index: 2, latitude: 33.5, longitude: -112.1 }),
      J({ id: "c", scheduled_date: "2026-02-05", route_index: 3, address: "5 Oak Ave" }),
    ];
    const r = buildMapsRouteUrl(jobs);
    expect(r.url).toContain("destination=5+Oak+Ave");
    expect(r.url).toContain("waypoints=1+Palm+Rd%7C33.5%2C-112.1");
  });

  it("cross-day + cross-tech selection is sorted schedule-first", () => {
    const jobs = [
      J({ id: "d", scheduled_date: "2026-02-07", route_index: 1, address: "D" }),
      J({ id: "a", scheduled_date: "2026-02-05", route_index: 1, tech_user_id: "t1", address: "A" }),
      J({ id: "c", scheduled_date: "2026-02-06", route_index: 1, address: "C" }),
      J({ id: "b", scheduled_date: "2026-02-05", route_index: 1, tech_user_id: "t2", address: "B" }),
    ];
    const r = buildMapsRouteUrl(jobs);
    // destination = last, waypoints in-order
    expect(r.url).toContain("destination=D");
    expect(r.url).toContain("waypoints=A%7CB%7CC");
  });
});

describe("runBulkNavigateRoute · orchestration", () => {
  const P = (n = 5) =>
    Array.from({ length: n }, (_, i) => ({
      id: `j${i}`,
      scheduled_date: "2026-02-06",
      route_index: i,
      address: `${i} Palm`,
    }));

  it("no-ops when fewer than 2 jobs are selected", () => {
    const onToast = vi.fn();
    const onOpen = vi.fn();
    const r = runBulkNavigateRoute({
      jobs: P(3),
      selectedIds: new Set(["j0"]),
      onToast,
      onOpen,
    });
    expect(r.opened).toBe(false);
    expect(onToast).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("opens Google Maps URL for 2+ picked jobs", () => {
    const onToast = vi.fn();
    const onOpen = vi.fn();
    const r = runBulkNavigateRoute({
      jobs: P(3),
      selectedIds: new Set(["j0", "j2"]),
      onToast,
      onOpen,
    });
    expect(r.opened).toBe(true);
    expect(r.usedCount).toBe(2);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0]).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\/\?/);
  });

  it("fires a warning toast when the selection exceeds 10 stops", () => {
    const onToast = vi.fn();
    const onOpen = vi.fn();
    const ids = new Set(P(15).map((j) => j.id));
    const r = runBulkNavigateRoute({
      jobs: P(15),
      selectedIds: ids,
      onToast,
      onOpen,
    });
    expect(r.capped).toBe(true);
    expect(r.usedCount).toBe(10);
    expect(r.originalCount).toBe(15);
    const info = onToast.mock.calls.find((c) => c[0].kind === "info");
    expect(info[0].text).toContain("up to 10 stops");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("fires a skipped toast when some jobs have no address", () => {
    const pool = [
      { id: "a", address: "1 Palm", scheduled_date: "2026-02-06", route_index: 1 },
      { id: "b", address: "",       scheduled_date: "2026-02-06", route_index: 2 },
      { id: "c", address: "3 Palm", scheduled_date: "2026-02-06", route_index: 3 },
    ];
    const onToast = vi.fn();
    const onOpen = vi.fn();
    const r = runBulkNavigateRoute({
      jobs: pool,
      selectedIds: new Set(["a", "b", "c"]),
      onToast,
      onOpen,
    });
    expect(r.opened).toBe(true);
    expect(r.usedCount).toBe(2);
    expect(r.droppedNoAddress).toBe(1);
    const info = onToast.mock.calls.find((c) => c[0].kind === "info");
    expect(info[0].text.toLowerCase()).toContain("skipped 1 job");
  });

  it("shows an error toast when no picked job has a routable stop", () => {
    const pool = [{ id: "a", address: "" }, { id: "b", address: "" }];
    const onToast = vi.fn();
    const onOpen = vi.fn();
    const r = runBulkNavigateRoute({
      jobs: pool,
      selectedIds: new Set(["a", "b"]),
      onToast,
      onOpen,
    });
    expect(r.opened).toBe(false);
    expect(onOpen).not.toHaveBeenCalled();
    const err = onToast.mock.calls.find((c) => c[0].kind === "err");
    expect(err[0].text.toLowerCase()).toContain("address or gps");
  });
});
