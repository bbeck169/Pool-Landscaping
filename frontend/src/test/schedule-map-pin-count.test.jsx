/**
 * Feb-2026 · Batch #4 · Item 4 — ScheduleMap pin-count fixture.
 *
 * The user reported "17 jobs but only 8 pins". Root cause: multiple
 * jobs at the same customer address collapsing to identical
 * ``(lat, lng)`` and rendering pin-on-pin. The fix (spider-offset
 * dedupe) is verified here plus:
 *   • The 40-job fixture the human explicitly asked for (well above
 *     the single-tech ceiling of 40 to stress-test).
 *   • Missing-coords branch (badge + count).
 *   • Dedupe branch (spider-offset produces distinct positions for
 *     jobs at the same address).
 *
 * Note: ``_buildDedupedPins`` is exported from ScheduleMap.jsx for
 * direct unit assertion — we don't need to mount the full ``<Map>``
 * to prove the pipeline math.
 */
import { describe, it, expect } from "vitest";
import { _buildDedupedPins } from "@/pages/schedule/ScheduleMap";


function _makeJob(id, opts = {}) {
  return {
    id,
    customer_id: `c-${id}`,
    customer_name: `Customer ${id}`,
    address: opts.address ?? `${id} Main St`,
    location_lat: opts.lat ?? null,
    location_lng: opts.lng ?? null,
    technician_id: opts.tech || "tech-A",
    scheduled_time: "09:00",
  };
}


describe("ScheduleMap · _buildDedupedPins", () => {
  it("keeps solo pins at their exact coord", () => {
    const jobs = [_makeJob(1, { lat: 33.5, lng: -112.1 })];
    const { pins, missing } = _buildDedupedPins(jobs);
    expect(pins).toHaveLength(1);
    expect(pins[0].lat).toBeCloseTo(33.5, 5);
    expect(pins[0].lng).toBeCloseTo(-112.1, 5);
    expect(missing).toHaveLength(0);
  });

  it("spider-offsets duplicates to distinct positions", () => {
    const jobs = [
      _makeJob(1, { lat: 33.5, lng: -112.1 }),
      _makeJob(2, { lat: 33.5, lng: -112.1 }),
      _makeJob(3, { lat: 33.5, lng: -112.1 }),
    ];
    const { pins } = _buildDedupedPins(jobs);
    expect(pins).toHaveLength(3);
    // All three positions distinct after spider-offset.
    const positions = new Set(pins.map((p) => `${p.lat.toFixed(6)}:${p.lng.toFixed(6)}`));
    expect(positions.size).toBe(3);
    // Every offset stays within a ~30m tolerance of the centroid.
    for (const p of pins) {
      expect(Math.abs(p.lat - 33.5)).toBeLessThan(0.0005);
      expect(Math.abs(p.lng - -112.1)).toBeLessThan(0.0005);
      expect(p.spidered).toBe(true);
    }
  });

  it("counts jobs missing coords and excludes them from pins", () => {
    const jobs = [
      _makeJob(1, { lat: 33.5, lng: -112.1 }),
      _makeJob(2), // no coords
      _makeJob(3, { lat: 0, lng: 0 }), // 0/0 legacy placeholder
    ];
    const { pins, missing } = _buildDedupedPins(jobs);
    expect(pins).toHaveLength(1);
    expect(missing).toHaveLength(2);
    expect(missing.map((j) => j.id).sort()).toEqual([2, 3]);
  });

  it("40-job fixture · 30 valid distinct + 5 dedupe-same-address + 5 missing", () => {
    const jobs = [];
    // 30 jobs at distinct addresses (Phoenix metro grid).
    for (let i = 0; i < 30; i += 1) {
      jobs.push(_makeJob(`ok-${i}`, {
        lat: 33.4 + i * 0.005,
        lng: -112.2 + i * 0.004,
      }));
    }
    // 5 jobs all at the same customer address (recurring weekly).
    for (let i = 0; i < 5; i += 1) {
      jobs.push(_makeJob(`dupe-${i}`, {
        lat: 33.65, lng: -112.05,
        address: "1234 Recurring Ln",
      }));
    }
    // 5 jobs missing coords.
    for (let i = 0; i < 5; i += 1) {
      jobs.push(_makeJob(`miss-${i}`));
    }

    const { pins, missing } = _buildDedupedPins(jobs);

    // 35 renderable pins total (30 solo + 5 spider-offset).
    expect(pins).toHaveLength(35);
    // 5 missing counted separately.
    expect(missing).toHaveLength(5);
    // All 35 positions distinct after spider-offset.
    const positions = new Set(pins.map((p) => `${p.lat.toFixed(6)}:${p.lng.toFixed(6)}`));
    expect(positions.size).toBe(35);
    // The 5 spidered members share a common centroid area.
    const spidered = pins.filter((p) => p.spidered);
    expect(spidered).toHaveLength(5);
    for (const p of spidered) {
      expect(Math.abs(p.lat - 33.65)).toBeLessThan(0.0005);
      expect(Math.abs(p.lng - -112.05)).toBeLessThan(0.0005);
    }
  });
});
