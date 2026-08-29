/**
 * Feb-2026 · Customer Delete UX overhaul — orphan-safe display
 * name helper.
 *
 * Locks the "Unknown Customer" fallback contract so hard-deleted
 * customers never surface as blank / "—" in child-row reads.
 */
import { describe, it, expect } from "vitest";
import {
  formatCustomerName,
  UNKNOWN_CUSTOMER_LABEL,
} from "@/utils/formatCustomerName";


describe("formatCustomerName · orphan-safe reads", () => {
  it("returns the snapshotted name when present on a row object", () => {
    expect(formatCustomerName({ customer_name: "Grace Hopper" }))
      .toBe("Grace Hopper");
  });

  it("returns the string as-is when passed a string", () => {
    expect(formatCustomerName("Alan Turing")).toBe("Alan Turing");
  });

  it("returns 'Unknown Customer' for a row missing customer_name", () => {
    expect(formatCustomerName({ id: "j-1", title: "Weekly service" }))
      .toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it("returns 'Unknown Customer' for empty / whitespace-only snapshot", () => {
    expect(formatCustomerName({ customer_name: "" }))
      .toBe(UNKNOWN_CUSTOMER_LABEL);
    expect(formatCustomerName({ customer_name: "   " }))
      .toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it("returns 'Unknown Customer' for null / undefined input", () => {
    expect(formatCustomerName(null)).toBe(UNKNOWN_CUSTOMER_LABEL);
    expect(formatCustomerName(undefined)).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it("exports the label as a stable constant for other consumers", () => {
    // If we ever rename this string, the grep must find every call
    // site — hence exporting it separately. Locking the current
    // value here.
    expect(UNKNOWN_CUSTOMER_LABEL).toBe("Unknown Customer");
  });
});
