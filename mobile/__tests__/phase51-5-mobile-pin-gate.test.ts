/**
 * Phase 51.5 · Feb-2026 — Mobile walkie pin role gate.
 *
 * Mirrors the vitest ``walkie-pin-action-gate.test.jsx`` on the
 * mobile side. Exercises the pure ``canPinInChannel`` predicate so
 * the same set of roles either sees or doesn't see the long-press
 * bottom-sheet pin option.
 */
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// eslint-disable-next-line import/first
import { PIN_ROLES, canPinInChannel } from "@/src/pages/walkie/walkie-helpers";

const CH_AH = { id: "ch_ah", kind: "all_hands" };

describe("Phase 51.5 · mobile pin role gate", () => {
  it("PIN_ROLES matches the server-side set exactly", () => {
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

  it("safely returns false with no user", () => {
    expect(canPinInChannel(null, CH_AH)).toBe(false);
    expect(canPinInChannel(undefined, undefined)).toBe(false);
  });

  it("role match is case-insensitive (defensive vs. backend shape drift)", () => {
    expect(canPinInChannel({ id: "u", role: "ADMIN" }, CH_AH)).toBe(true);
    expect(canPinInChannel({ id: "u", role: "Super_Admin" }, CH_AH)).toBe(true);
  });
});
