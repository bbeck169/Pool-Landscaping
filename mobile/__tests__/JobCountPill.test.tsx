/**
 * Feb-2026 · Mobile unit tests for the shared job classifier and the
 * ``<JobCountPill>`` component that consumes it. Mirrors the web
 * suite at ``frontend/src/test/job-count-pill.test.jsx`` — both
 * files exercise the SAME regex + priority rules to guarantee the
 * two surfaces never drift.
 */
import React from "react";
import { render } from "@testing-library/react-native";

import { classifyJob, computePillCounts } from "@/lib/jobCategory";
import JobCountPill from "@/components/JobCountPill";


describe("classifyJob (mobile)", () => {
  test("clear-service service_types map to 'service'", () => {
    expect(classifyJob({ service_type: "Weekly Pool Service" })).toBe("service");
    expect(classifyJob({ service_type: "landscape maintenance" })).toBe("service");
    expect(classifyJob({ service_type: "Cleaning" })).toBe("service");
  });

  test("clear-repair service_types map to 'repair'", () => {
    expect(classifyJob({ service_type: "Pump Repair" })).toBe("repair");
    expect(classifyJob({ service_type: "Fix Leak" })).toBe("repair");
    expect(classifyJob({ service_type: "install filter" })).toBe("repair");
    expect(classifyJob({ service_type: "Replace Heater" })).toBe("repair");
  });

  test("repair wins on ambiguous multi-pattern matches", () => {
    expect(classifyJob({ service_type: "Pool Repair" })).toBe("repair");
    expect(classifyJob({ service_type: "landscape install" })).toBe("repair");
  });

  test("unclassifiable / empty → null", () => {
    expect(classifyJob({ service_type: "" })).toBeNull();
    expect(classifyJob({ service_type: null })).toBeNull();
    expect(classifyJob({})).toBeNull();
    expect(classifyJob({ service_type: "Consultation" })).toBeNull();
    expect(classifyJob(null)).toBeNull();
    expect(classifyJob(undefined)).toBeNull();
  });
});


describe("computePillCounts (mobile)", () => {
  test("aggregates services / repairs and their remaining counts", () => {
    const jobs = [
      { service_type: "Weekly Pool Service", status: "completed" },
      { service_type: "Weekly Pool Service", status: "in_progress" },
      { service_type: "landscape maintenance", status: "pending" },
      { service_type: "Pump Repair", status: "completed" },
      { service_type: "Fix Leak", status: "pending" },
      // Unclassifiable → does NOT bump either bucket.
      { service_type: "Consultation", status: "pending" },
      { service_type: "", status: "completed" },
    ];
    const c = computePillCounts(jobs);
    expect(c.services.total).toBe(3);
    expect(c.services.remaining).toBe(2);
    expect(c.repairs.total).toBe(2);
    expect(c.repairs.remaining).toBe(1);
  });

  test("empty / null input → zero'd counts", () => {
    expect(computePillCounts([])).toEqual({
      services: { total: 0, remaining: 0 },
      repairs: { total: 0, remaining: 0 },
    });
    expect(computePillCounts(null)).toEqual({
      services: { total: 0, remaining: 0 },
      repairs: { total: 0, remaining: 0 },
    });
  });

  test("cancelled counts as remaining (matches schedule ring semantics)", () => {
    const c = computePillCounts([
      { service_type: "Weekly Service", status: "cancelled" },
      { service_type: "Repair Pump", status: "cancelled" },
    ]);
    expect(c.services.remaining).toBe(1);
    expect(c.repairs.remaining).toBe(1);
  });
});


describe("<JobCountPill /> (mobile)", () => {
  test("renders the SERVICES pill with remaining/total and label", () => {
    const { getByTestId } = render(
      <JobCountPill category="services" total={5} remaining={3} testID="pill-svc" />
    );
    expect(getByTestId("pill-svc")).toBeTruthy();
    expect(getByTestId("pill-svc-remaining").children.join("")).toBe("3");
    expect(getByTestId("pill-svc-total").children.join("")).toBe("5");
    expect(getByTestId("pill-svc-label").children.join("")).toBe("SERVICES");
  });

  test("renders the REPAIRS pill with correct label", () => {
    const { getByTestId } = render(
      <JobCountPill category="repairs" total={2} remaining={1} testID="pill-rep" />
    );
    expect(getByTestId("pill-rep-remaining").children.join("")).toBe("1");
    expect(getByTestId("pill-rep-total").children.join("")).toBe("2");
    expect(getByTestId("pill-rep-label").children.join("")).toBe("REPAIRS");
  });

  test("clamps remaining to [0, total]", () => {
    const { getByTestId, rerender } = render(
      <JobCountPill category="services" total={3} remaining={-2} testID="pill-lo" />
    );
    expect(getByTestId("pill-lo-remaining").children.join("")).toBe("0");
    rerender(
      <JobCountPill category="services" total={3} remaining={99} testID="pill-hi" />
    );
    expect(getByTestId("pill-hi-remaining").children.join("")).toBe("3");
  });
});
