/**
 * Phase 51.5 · Feb 2026 — Walkie pin action role gate.
 *
 * Mirrors the server-side ``PIN_ROLES`` set (super_admin / admin /
 * manager). Non-leadership roles never see the pin icon, and never
 * see the unpin icon on the currently-pinned row.
 *
 * The gate lives in ``pages/walkie/walkie-helpers.js#canPinInChannel``.
 * We exercise the predicate directly here — the full render is
 * covered by ``walkie-pin-timeline-order.test.jsx``.
 */
import { describe, it, expect } from "vitest";
import { PIN_ROLES, canPinInChannel } from "@/pages/walkie/walkie-helpers";

const CH_AH = { id: "ch_ah", kind: "all_hands" };

describe("Phase 51.5 · walkie pin role gate", () => {
  it("PIN_ROLES matches the server-side set", () => {
    expect(Array.from(PIN_ROLES).sort()).toEqual(["admin", "manager", "super_admin"]);
  });

  it("admin / super_admin / manager can pin", () => {
    for (const role of ["admin", "super_admin", "manager"]) {
      expect(canPinInChannel({ id: "u", role }, CH_AH)).toBe(true);
    }
  });

  it("technician / dispatcher / owner CANNOT pin", () => {
    for (const role of ["technician", "dispatcher", "owner"]) {
      expect(canPinInChannel({ id: "u", role }, CH_AH)).toBe(false);
    }
  });

  it("customer CANNOT pin (no walkie access at all)", () => {
    expect(canPinInChannel({ id: "u", role: "customer" }, CH_AH)).toBe(false);
  });

  it("no-user is a safe false; channel arg is optional (server also enforces membership)", () => {
    expect(canPinInChannel(null, CH_AH)).toBe(false);
    // The channel arg is presently unused on the client (server
    // enforces membership on the pin endpoint). Locking the safe
    // behaviour when it's undefined so the button never renders
    // without a signed-in leadership user.
    expect(canPinInChannel(undefined, undefined)).toBe(false);
  });

  it("role match is case-insensitive (defensive vs. backend shape drift)", () => {
    expect(canPinInChannel({ id: "u", role: "ADMIN" }, CH_AH)).toBe(true);
    expect(canPinInChannel({ id: "u", role: "Super_Admin" }, CH_AH)).toBe(true);
  });
});
