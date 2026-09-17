/**
 * Feb-2026 · Ticket A · DispatchBoardPage pin-numbering wiring.
 *
 * Tests only the small pure helper: the ``stopLabelByCustomerId``
 * memo shape. Full DispatchBoardPage rendering pulls in Google Maps
 * SDK + auth context which is out of scope for a unit test — instead
 * we assert the shape ``useMemo`` produces from ``route_stops``.
 */
import { describe, it, expect } from "vitest";


/**
 * Mirror of the DispatchBoardPage useMemo body — kept in sync with
 * the ``stopLabelByCustomerId`` definition so this test guards the
 * lookup shape without dragging the whole page into jsdom.
 */
function buildStopLabelMap(activeStops) {
  const out = {};
  (activeStops || []).forEach((s, idx) => {
    if (s && s.customer_id) out[s.customer_id] = idx + 1;
  });
  return out;
}


describe("DispatchBoardPage stopLabelByCustomerId", () => {
  it("builds 1-indexed lookup from route_stops in order", () => {
    const route_stops = [
      { customer_id: "cust-A" },
      { customer_id: "cust-B" },
      { customer_id: "cust-C" },
    ];
    const map = buildStopLabelMap(route_stops);
    expect(map).toEqual({ "cust-A": 1, "cust-B": 2, "cust-C": 3 });
  });

  it("handles empty route_stops", () => {
    expect(buildStopLabelMap([])).toEqual({});
    expect(buildStopLabelMap(null)).toEqual({});
    expect(buildStopLabelMap(undefined)).toEqual({});
  });

  it("skips rows without customer_id", () => {
    const route_stops = [
      { customer_id: "cust-A" },
      { note: "no customer_id here" },
      { customer_id: "cust-C" },
    ];
    const map = buildStopLabelMap(route_stops);
    // ``cust-C`` still gets index 3 (its physical position in the
    // input array) so numbered pins match the visual ordering the
    // user sees in the right-column stop list.
    expect(map).toEqual({ "cust-A": 1, "cust-C": 3 });
  });

  it("later duplicate customer_ids overwrite earlier ones", () => {
    const route_stops = [
      { customer_id: "cust-A" },
      { customer_id: "cust-A" },
    ];
    const map = buildStopLabelMap(route_stops);
    // Idempotent-ish — customer_id should be unique in route_stops
    // but the reducer is deterministic if it isn't.
    expect(map["cust-A"]).toBe(2);
  });
});


describe("DispatchBoardPage label formatting integration", () => {
  it("labels 1-9 zero-pad to 2 digits via formatPinLabel", async () => {
    const { formatPinLabel } = await import(
      "../components/maps/TeardropPin"
    );
    const route_stops = [
      { customer_id: "cust-A" },
      { customer_id: "cust-B" },
      { customer_id: "cust-C" },
    ];
    const map = buildStopLabelMap(route_stops);
    expect(formatPinLabel(map["cust-A"])).toBe("01");
    expect(formatPinLabel(map["cust-B"])).toBe("02");
    expect(formatPinLabel(map["cust-C"])).toBe("03");
  });
});
