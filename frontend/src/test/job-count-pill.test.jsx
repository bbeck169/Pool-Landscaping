/**
 * Feb-2026 · Web unit tests for the shared job classifier and the
 * ``<JobCountPill>`` component that consumes it.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { classifyJob, computePillCounts } from "../lib/jobCategory";
import JobCountPill from "@/components/JobCountPill";


describe("classifyJob", () => {
  it("classifies clear-service service_types as 'service'", () => {
    expect(classifyJob({ service_type: "Weekly Pool Service" })).toBe("service");
    expect(classifyJob({ service_type: "landscape maintenance" })).toBe("service");
    expect(classifyJob({ service_type: "Cleaning" })).toBe("service");
  });

  it("classifies clear-repair service_types as 'repair'", () => {
    expect(classifyJob({ service_type: "Pump Repair" })).toBe("repair");
    expect(classifyJob({ service_type: "Fix Leak" })).toBe("repair");
    expect(classifyJob({ service_type: "install filter" })).toBe("repair");
    expect(classifyJob({ service_type: "Replace Heater" })).toBe("repair");
  });

  it("gives repair priority when both regexes match", () => {
    // "pool repair" matches both /pool/ (services) and /repair/
    // (repairs); the pill dashboard's more actionable signal wins.
    expect(classifyJob({ service_type: "Pool Repair" })).toBe("repair");
    expect(classifyJob({ service_type: "landscape install" })).toBe("repair");
  });

  it("returns null for unclassifiable / empty service_type", () => {
    expect(classifyJob({ service_type: "" })).toBeNull();
    expect(classifyJob({ service_type: null })).toBeNull();
    expect(classifyJob({})).toBeNull();
    expect(classifyJob({ service_type: "Consultation" })).toBeNull();
    expect(classifyJob(null)).toBeNull();
    expect(classifyJob(undefined)).toBeNull();
  });

  // Feb-2026 · Classifier update — parity spec with mobile
  // ``mobile/lib/jobCategory.ts``. Any drift here MUST land on
  // mobile in the same PR window; the shared header comment locks
  // both surfaces to the same regex + priority + fallback rules.
  describe("Feb-2026 classifier update — parity with mobile", () => {
    it("landscape stem now matches both 'Landscaping' and 'Monthly Landscaping'", () => {
      // Typo hotfix: rule stem widened from ``landscape`` → ``landscap``.
      expect(classifyJob({ service_type: "Landscaping" })).toBe("service");
      expect(classifyJob({ service_type: "Monthly Landscaping" })).toBe("service");
      // Existing "landscape maintenance" call site still works
      // (regression guard for the old stem).
      expect(classifyJob({ service_type: "landscape maintenance" })).toBe("service");
    });

    it("new Service keywords classify as 'service' (Inspection, Weekly, Monthly)", () => {
      expect(classifyJob({ service_type: "Weekly Cleanup" })).toBe("service");
      expect(classifyJob({ service_type: "Monthly Filter Check" })).toBe("service");
      expect(classifyJob({ service_type: "Annual Inspection" })).toBe("service");
      // Case-insensitive — mirrors the ``/i`` flag on the SERVICES rx.
      expect(classifyJob({ service_type: "weekly cleanup" })).toBe("service");
      expect(classifyJob({ service_type: "INSPECTION" })).toBe("service");
    });

    it("completed fallback: unmatched completed jobs classify as 'service'", () => {
      // Rule #4 — completed jobs whose service_type didn't match
      // either regex fall through to the Services bucket so
      // finished work never leaks out of the pill totals.
      expect(
        classifyJob({ service_type: "Random unmatched string", status: "completed" }),
      ).toBe("service");
    });

    it("completed fallback does NOT fire for non-completed jobs", () => {
      expect(
        classifyJob({ service_type: "Random unmatched string", status: "pending" }),
      ).toBeNull();
      expect(
        classifyJob({ service_type: "Random unmatched string", status: "in_progress" }),
      ).toBeNull();
      expect(
        classifyJob({ service_type: "Random unmatched string", status: "cancelled" }),
      ).toBeNull();
      // No status field at all → still null.
      expect(classifyJob({ service_type: "Random unmatched string" })).toBeNull();
    });

    it("completed fallback does NOT override the Repair rule", () => {
      // Repair still wins on match, regardless of completion state.
      expect(
        classifyJob({ service_type: "Pump Repair", status: "completed" }),
      ).toBe("repair");
      expect(
        classifyJob({ service_type: "Fix Leak", status: "completed" }),
      ).toBe("repair");
      expect(
        classifyJob({ service_type: "install filter", status: "completed" }),
      ).toBe("repair");
    });

    it("empty / missing service_type is bucketed as 'service' when completed (Phase P27 fallback)", () => {
      // Phase P27 · Feb-2026 — commit ``b1fe56b39`` reversed the
      // pre-P27 ``if (!st) return null;`` short-circuit so a
      // completed job whose ``service_type`` was mistakenly left
      // blank (legacy CSV import, hand-created work order) still
      // lands in the Services bucket instead of silently
      // disappearing from the pill total. Non-completed empty
      // ``service_type`` still returns ``null`` (unchanged).
      expect(classifyJob({ service_type: "", status: "completed" })).toBe("service");
      expect(classifyJob({ status: "completed" })).toBe("service");
    });
  });
});


describe("computePillCounts", () => {
  it("aggregates services / repairs and their remaining counts", () => {
    const jobs = [
      { service_type: "Weekly Pool Service", status: "completed" },
      { service_type: "Weekly Pool Service", status: "in_progress" },
      { service_type: "landscape maintenance", status: "pending" },
      { service_type: "Pump Repair", status: "completed" },
      { service_type: "Fix Leak", status: "pending" },
      // Unclassifiable + non-completed → does NOT bump either bucket.
      { service_type: "Consultation", status: "pending" },
      // Phase P27 · Feb-2026 — empty + completed now falls through
      // to Services (see ``jobCategory.classifyJob`` comment).
      { service_type: "", status: "completed" },
    ];
    const c = computePillCounts(jobs);
    expect(c.services.total).toBe(4);
    expect(c.services.remaining).toBe(2);
    expect(c.repairs.total).toBe(2);
    expect(c.repairs.remaining).toBe(1);
  });

  it("handles empty / null input gracefully", () => {
    expect(computePillCounts([])).toEqual({
      services: { total: 0, remaining: 0 },
      repairs: { total: 0, remaining: 0 },
    });
    expect(computePillCounts(null)).toEqual({
      services: { total: 0, remaining: 0 },
      repairs: { total: 0, remaining: 0 },
    });
  });

  it("cancelled counts as remaining (parity with schedule ring)", () => {
    const c = computePillCounts([
      { service_type: "Weekly Service", status: "cancelled" },
      { service_type: "Repair Pump", status: "cancelled" },
    ]);
    expect(c.services.remaining).toBe(1);
    expect(c.repairs.remaining).toBe(1);
  });
});


describe("<JobCountPill />", () => {
  it("renders the SERVICES pill with remaining/total and label", () => {
    render(<JobCountPill category="services" total={5} remaining={3} testid="pill-svc" />);
    expect(screen.getByTestId("pill-svc")).toBeTruthy();
    expect(screen.getByTestId("pill-svc-remaining").textContent).toBe("3");
    expect(screen.getByTestId("pill-svc-total").textContent).toBe("5");
    expect(screen.getByTestId("pill-svc-label").textContent).toBe("SERVICES");
    // Blue tone (sky-500).
    expect(screen.getByTestId("pill-svc").className).toContain("bg-sky-500");
  });

  it("renders the REPAIRS pill with the correct dark navy tone", () => {
    render(<JobCountPill category="repairs" total={2} remaining={1} testid="pill-rep" />);
    expect(screen.getByTestId("pill-rep-remaining").textContent).toBe("1");
    expect(screen.getByTestId("pill-rep-total").textContent).toBe("2");
    expect(screen.getByTestId("pill-rep-label").textContent).toBe("REPAIRS");
    expect(screen.getByTestId("pill-rep").className).toContain("bg-slate-800");
  });

  it("clamps remaining to the [0, total] range", () => {
    render(<JobCountPill category="services" total={3} remaining={-2} testid="pill-lo" />);
    expect(screen.getByTestId("pill-lo-remaining").textContent).toBe("0");
    render(<JobCountPill category="services" total={3} remaining={99} testid="pill-hi" />);
    expect(screen.getByTestId("pill-hi-remaining").textContent).toBe("3");
  });

  it("returns null for an unknown category", () => {
    const { container } = render(
      // @ts-ignore intentional bad input
      <JobCountPill category="unknown" total={0} remaining={0} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
