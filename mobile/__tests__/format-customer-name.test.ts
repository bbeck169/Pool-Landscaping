/**
 * Ship 3 · formatCustomerName — pure-function unit tests.
 *
 * Port of /frontend/src/test/format-customer-name.test.js
 */
import { formatCustomerName, UNKNOWN_CUSTOMER_LABEL } from "@/src/utils/formatCustomerName";

describe("formatCustomerName", () => {
  it('object with customer_name: "Jane Doe" → "Jane Doe"', () => {
    expect(formatCustomerName({ customer_name: "Jane Doe" })).toBe("Jane Doe");
  });

  it('object with customer_name: "" → "Unknown Customer"', () => {
    expect(formatCustomerName({ customer_name: "" })).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it('object with customer_name: null → "Unknown Customer"', () => {
    expect(formatCustomerName({ customer_name: null as any })).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it('string input "Bob" → "Bob"', () => {
    expect(formatCustomerName("Bob")).toBe("Bob");
  });

  it('null input → "Unknown Customer"', () => {
    expect(formatCustomerName(null)).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it('undefined input → "Unknown Customer"', () => {
    expect(formatCustomerName(undefined)).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it('whitespace-only "   " → "Unknown Customer"', () => {
    expect(formatCustomerName("   ")).toBe(UNKNOWN_CUSTOMER_LABEL);
  });

  it("trims surrounding whitespace", () => {
    expect(formatCustomerName("  Alice  ")).toBe("Alice");
  });

  it("UNKNOWN_CUSTOMER_LABEL constant equals 'Unknown Customer'", () => {
    expect(UNKNOWN_CUSTOMER_LABEL).toBe("Unknown Customer");
  });
});
