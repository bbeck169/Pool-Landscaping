/**
 * SO-A · Feb-2026 — Best-Fit sparkle tests.
 *
 * Locks:
 *   1. Green sparkle renders next to the top-ranked tech.
 *   2. Sparkle title (tooltip) shows the detour info.
 *   3. Sparkle DOES NOT render for non-top techs.
 *   4. Sparkle DOES NOT render when the recommendation is null /
 *      empty (recommendation cleared).
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { BestFitSpark } from
  "@/components/schedule/BestFitSpark";

const REC = {
  job_id: "job-x", target_date: "2026-02-16",
  apply_mode: "one_click",
  provider_used: "google",
  suggestions: [
    { technician_id: "tech_top", technician_name: "David",
      insertion_index: 1, detour_minutes: 2.3, detour_miles: 0.8,
      rank: 1, provider_used: "google", route_len: 3,
      plain_english: "…" },
    { technician_id: "tech_mid", technician_name: "Sara",
      insertion_index: 0, detour_minutes: 5.6, detour_miles: 2.1,
      rank: 2, provider_used: "osrm", route_len: 4,
      plain_english: "…" },
  ],
  unavailable_technicians: [],
};

describe("SO-A · CalendarSchedule best-fit spark", () => {
  it("renders sparkle next to top-ranked tech's row", () => {
    render(
      <BestFitSpark recommendation={REC} technicianId="tech_top" />,
    );
    expect(
      screen.getByTestId("best-fit-spark-tech_top"),
    ).toBeInTheDocument();
    // Detour is visible inside the pill.
    expect(
      screen.getByTestId("best-fit-spark-detour-tech_top").textContent,
    ).toMatch(/\+2\.3m/);
  });

  it("title/tooltip carries the detour text", () => {
    render(
      <BestFitSpark recommendation={REC} technicianId="tech_top" />,
    );
    const spark = screen.getByTestId("best-fit-spark-tech_top");
    expect(spark.title).toMatch(/Best fit per MARCO/);
    expect(spark.title).toMatch(/\+2\.3 min detour/);
  });

  it("non-top tech does NOT get a sparkle", () => {
    render(
      <BestFitSpark recommendation={REC} technicianId="tech_mid" />,
    );
    expect(
      screen.queryByTestId("best-fit-spark-tech_mid"),
    ).not.toBeInTheDocument();
  });

  it("null recommendation → no sparkle", () => {
    render(
      <BestFitSpark recommendation={null} technicianId="tech_top" />,
    );
    expect(
      screen.queryByTestId("best-fit-spark-tech_top"),
    ).not.toBeInTheDocument();
  });

  it("empty suggestions[] → no sparkle", () => {
    render(
      <BestFitSpark
        recommendation={{ ...REC, suggestions: [] }}
        technicianId="tech_top"
      />,
    );
    expect(
      screen.queryByTestId("best-fit-spark-tech_top"),
    ).not.toBeInTheDocument();
  });

  it("sparkle disappears when the top tech changes", () => {
    const { rerender } = render(
      <BestFitSpark recommendation={REC} technicianId="tech_top" />,
    );
    expect(
      screen.getByTestId("best-fit-spark-tech_top"),
    ).toBeInTheDocument();
    // Replace the recommendation so tech_top is no longer #1.
    const flipped = {
      ...REC,
      suggestions: [
        REC.suggestions[1], REC.suggestions[0],
      ],
    };
    rerender(
      <BestFitSpark recommendation={flipped} technicianId="tech_top" />,
    );
    expect(
      screen.queryByTestId("best-fit-spark-tech_top"),
    ).not.toBeInTheDocument();
  });
});
