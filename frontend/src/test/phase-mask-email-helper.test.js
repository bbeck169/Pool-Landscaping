/**
 * Sep-2026 · maskEmail helper coverage.
 */
import { describe, it, expect } from "vitest";
import { maskEmail } from "../lib/maskEmail";


describe("maskEmail (SP3-DFS)", () => {
  it("masks a typical email keeping first 3 chars + @domain", () => {
    expect(maskEmail("brian@plofv.com")).toBe("bri***@plofv.com");
    expect(maskEmail("user@example.com")).toBe("use***@example.com");
  });

  it("fully masks short local part (<=3 chars)", () => {
    expect(maskEmail("bo@x.com")).toBe("***@x.com");
    expect(maskEmail("a@example.com")).toBe("***@example.com");
    expect(maskEmail("bob@example.com")).toBe("***@example.com");
  });

  it("returns *** for non-email input", () => {
    expect(maskEmail("not-an-email")).toBe("***");
    expect(maskEmail("")).toBe("***");
    expect(maskEmail(null)).toBe("***");
    expect(maskEmail(undefined)).toBe("***");
  });

  it("preserves multi-part domains verbatim", () => {
    expect(maskEmail("user@sub.corp-domain.co.uk"))
      .toBe("use***@sub.corp-domain.co.uk");
  });

  it("handles leading/trailing whitespace", () => {
    expect(maskEmail("  brian@plofv.com  ")).toBe("bri***@plofv.com");
  });
});
