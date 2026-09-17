/**
 * Phase SRL — sequential route lock helper tests.
 *
 *  1. First job always unlocked.
 *  2. Locked when any earlier job is "scheduled".
 *  3. Locked when any earlier job is "in_progress" / "active".
 *  4. Unlocked when all earlier jobs are "completed".
 *  5. Unlocked when all earlier jobs are "skipped".
 *  6. Unlocked with mix of completed + skipped.
 *  7. Locked when 3 completed but 4th is "scheduled".
 *  8. Empty array → false.
 *  9. Target not in array → false (with console.warn).
 * 10. TERMINAL_STATUSES includes all terminal values.
 */
import { isJobLockedByRoute, TERMINAL_STATUSES } from "../src/lib/sequentialRouteLock";

const mkJob = (id: string, status: string) => ({ id, status });

describe("isJobLockedByRoute", () => {
  it("first job in the route is always unlocked", () => {
    const jobs = [mkJob("a", "scheduled"), mkJob("b", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[0])).toBe(false);
  });

  it('locked when an earlier job is "scheduled"', () => {
    const jobs = [mkJob("a", "scheduled"), mkJob("b", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[1])).toBe(true);
  });

  it('locked when an earlier job is "active" / "in_progress"', () => {
    const jobs = [mkJob("a", "active"), mkJob("b", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[1])).toBe(true);

    const jobs2 = [mkJob("a", "in_progress"), mkJob("b", "scheduled")];
    expect(isJobLockedByRoute(jobs2, jobs2[1])).toBe(true);
  });

  it('unlocked when all earlier jobs are "completed"', () => {
    const jobs = [mkJob("a", "completed"), mkJob("b", "completed"), mkJob("c", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[2])).toBe(false);
  });

  it('unlocked when all earlier jobs are "skipped"', () => {
    const jobs = [mkJob("a", "skipped"), mkJob("b", "skipped"), mkJob("c", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[2])).toBe(false);
  });

  it("unlocked with mix of completed + skipped earlier jobs", () => {
    const jobs = [
      mkJob("a", "completed"), mkJob("b", "skipped"),
      mkJob("c", "could_not_service"), mkJob("d", "scheduled"),
    ];
    expect(isJobLockedByRoute(jobs, jobs[3])).toBe(false);
  });

  it('locked when 3 completed but 4th earlier job is "scheduled"', () => {
    const jobs = [
      mkJob("a", "completed"), mkJob("b", "completed"),
      mkJob("c", "completed"), mkJob("d", "scheduled"), mkJob("e", "scheduled"),
    ];
    expect(isJobLockedByRoute(jobs, jobs[4])).toBe(true);
  });

  it("empty jobs array → false", () => {
    expect(isJobLockedByRoute([], mkJob("x", "scheduled"))).toBe(false);
  });

  it("target not in array → false + console.warn", () => {
    const spy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const jobs = [mkJob("a", "scheduled")];
    expect(isJobLockedByRoute(jobs, mkJob("z", "scheduled"))).toBe(false);
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("[sequentialRouteLock]"),
      "z",
    );
    spy.mockRestore();
  });

  it("TERMINAL_STATUSES includes completed, canceled, cancelled, skipped, could_not_service", () => {
    expect(TERMINAL_STATUSES.has("completed")).toBe(true);
    expect(TERMINAL_STATUSES.has("canceled")).toBe(true);
    expect(TERMINAL_STATUSES.has("cancelled")).toBe(true);
    expect(TERMINAL_STATUSES.has("skipped")).toBe(true);
    expect(TERMINAL_STATUSES.has("could_not_service")).toBe(true);
    // Non-terminal
    expect(TERMINAL_STATUSES.has("scheduled")).toBe(false);
    expect(TERMINAL_STATUSES.has("active")).toBe(false);
  });

  it("cancelled (double-l) unlocks the next stop", () => {
    const jobs = [mkJob("a", "cancelled"), mkJob("b", "scheduled")];
    expect(isJobLockedByRoute(jobs, jobs[1])).toBe(false);
  });

  it("null/undefined target → false", () => {
    expect(isJobLockedByRoute([mkJob("a", "scheduled")], null as any)).toBe(false);
    expect(isJobLockedByRoute([mkJob("a", "scheduled")], undefined as any)).toBe(false);
  });
});
