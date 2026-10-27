/**
 * Ticket XX · Feb-2026 — ``jobMatchesLane`` widens to crew-membership.
 *
 * BE sibling (``routers/jobs.py::scope_jobs_query`` admin elif) landed
 * in commit 6fec5af2c.  This FE sibling closes the matching lane
 * predicate on the Schedule page so crew-only jobs (``crew_id`` set,
 * ``technician_id`` null — written by UU's ``new_crew_id`` flow)
 * render on EVERY crew-member tech's lane.
 *
 * Plural semantics: a tech who is a member of multiple crews sees
 * jobs from every crew they belong to.
 */
import { describe, it, expect } from "vitest";
import { jobMatchesLane } from "@/pages/schedule/CalendarSchedule";


describe("XX · jobMatchesLane crew-membership widening", () => {

  // ── (a) THE FIX ────────────────────────────────────────────────
  it("(a) crew-only job (technician_id null, crew_id set) matches "
     + "a member's lane when techCrewIds includes the job's crew_id",
    () => {
      const job = {
        id: "j-1", technician_id: null, assigned_technician_id: null,
        assigned_to: null, tech_user_id: null,
        crew_id: "crew-landscape",
      };
      const techCrewIds = new Set(["crew-landscape"]);
      expect(jobMatchesLane(job, "t-wiley", techCrewIds)).toBe(true);
    });

  // ── (b) regression lock on backward-compat shape ──────────────
  it("(b) crew-only job with NO techCrewIds arg → false "
     + "(pre-XX call-sites behave identically; no throw)", () => {
    const job = {
      id: "j-2", technician_id: null, assigned_technician_id: null,
      assigned_to: null, tech_user_id: null,
      crew_id: "crew-landscape",
    };
    // Explicit undefined
    expect(jobMatchesLane(job, "t-wiley")).toBe(false);
    // Explicit null
    expect(jobMatchesLane(job, "t-wiley", null)).toBe(false);
  });

  // ── (c) direct-field regression lock ──────────────────────────
  it("(c) direct tech-id match on any of the four fields still "
     + "returns true (pre-XX four-field disjunction preserved)", () => {
    const noCrewSet = new Set();
    expect(jobMatchesLane(
      { technician_id: "t-wiley" }, "t-wiley", noCrewSet)).toBe(true);
    expect(jobMatchesLane(
      { assigned_technician_id: "t-wiley" }, "t-wiley", noCrewSet)).toBe(true);
    expect(jobMatchesLane(
      { assigned_to: "t-wiley" }, "t-wiley", noCrewSet)).toBe(true);
    expect(jobMatchesLane(
      { tech_user_id: "t-wiley" }, "t-wiley", noCrewSet)).toBe(true);
    expect(jobMatchesLane(
      { crew_id: "t-wiley" }, "t-wiley", noCrewSet)).toBe(true);
  });

  // ── (d) negative lock ─────────────────────────────────────────
  it("(d) crew-only job does NOT match a non-member tech's lane "
     + "(empty techCrewIds)", () => {
    const job = { crew_id: "crew-landscape", technician_id: null };
    // Non-member: techCrewIds is an empty Set (built from crews
    // array that doesn't contain this crew for this tech).
    expect(jobMatchesLane(job, "t-sam", new Set())).toBe(false);
  });

  // ── (e) plural semantics ──────────────────────────────────────
  it("(e) multi-crew tech: techCrewIds has 2+ entries → crew-only "
     + "job matches when its crew_id is ANY one of them",
    () => {
      const techCrewIds = new Set(
        ["crew-landscape", "crew-pool-ab", "crew-chem"]);
      // Match #1 — first crew.
      expect(jobMatchesLane(
        { crew_id: "crew-landscape", technician_id: null },
        "t-wiley", techCrewIds)).toBe(true);
      // Match #2 — second crew.
      expect(jobMatchesLane(
        { crew_id: "crew-pool-ab", technician_id: null },
        "t-wiley", techCrewIds)).toBe(true);
      // Match #3 — third crew.
      expect(jobMatchesLane(
        { crew_id: "crew-chem", technician_id: null },
        "t-wiley", techCrewIds)).toBe(true);
      // Non-match — crew the tech is not in.
      expect(jobMatchesLane(
        { crew_id: "crew-other", technician_id: null },
        "t-wiley", techCrewIds)).toBe(false);
    });

  // ── sanity checks ─────────────────────────────────────────────
  it("(sanity) all-pass pseudo-value: laneId falsy → true", () => {
    expect(jobMatchesLane({ crew_id: "crew-x" }, "", null)).toBe(true);
    expect(jobMatchesLane({ crew_id: "crew-x" }, null, null)).toBe(true);
  });

  it("(sanity) null job → false", () => {
    expect(jobMatchesLane(null, "t-wiley", new Set(["crew-x"]))).toBe(false);
  });
});
