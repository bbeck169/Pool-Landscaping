/**
 * jobCategory.ts — Jest tests mirroring the 6 new Vitest web cases
 * plus a bucket-leak guard.
 */
import { classifyJob, computePillCounts } from "@/lib/jobCategory";

describe("classifyJob — widened Service regex", () => {
  it('"Landscaping" and "Monthly Landscaping" classify as service (landscap stem)', () => {
    expect(classifyJob({ service_type: "Landscaping" })).toBe("service");
    expect(classifyJob({ service_type: "Monthly Landscaping" })).toBe("service");
  });

  it('regression: "landscape maintenance" still classifies as service', () => {
    expect(classifyJob({ service_type: "landscape maintenance" })).toBe("service");
  });

  it('"Weekly Cleanup", "Monthly Filter Check", "Annual Inspection" (+ case variants) → service', () => {
    expect(classifyJob({ service_type: "Weekly Cleanup" })).toBe("service");
    expect(classifyJob({ service_type: "Monthly Filter Check" })).toBe("service");
    expect(classifyJob({ service_type: "Annual Inspection" })).toBe("service");
    // lowercase
    expect(classifyJob({ service_type: "weekly cleanup" })).toBe("service");
    // ALL CAPS
    expect(classifyJob({ service_type: "MONTHLY FILTER CHECK" })).toBe("service");
    expect(classifyJob({ service_type: "ANNUAL INSPECTION" })).toBe("service");
  });
});

describe("classifyJob — completed fallback (rule #4)", () => {
  it("completed + unmatched service_type → service", () => {
    expect(
      classifyJob({ service_type: "Random unmatched string", status: "completed" }),
    ).toBe("service");
  });

  it("fallback does NOT fire for pending / in_progress / cancelled / missing status", () => {
    const st = "Random unmatched string";
    expect(classifyJob({ service_type: st, status: "pending" })).toBeNull();
    expect(classifyJob({ service_type: st, status: "in_progress" })).toBeNull();
    expect(classifyJob({ service_type: st, status: "cancelled" })).toBeNull();
    expect(classifyJob({ service_type: st })).toBeNull();
    expect(classifyJob({ service_type: st, status: "" })).toBeNull();
  });

  it("repair rule still wins on completed jobs (rule #3 > rule #4)", () => {
    expect(
      classifyJob({ service_type: "Emergency Repair", status: "completed" }),
    ).toBe("repair");
  });

  it('empty service_type stays null even when completed (bucket-leak guard)', () => {
    expect(classifyJob({ service_type: "", status: "completed" })).toBeNull();
    expect(classifyJob({ service_type: null, status: "completed" })).toBeNull();
    expect(classifyJob({ status: "completed" })).toBeNull();
  });
});
