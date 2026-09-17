/**
 * Phase SRL — Schedule-view rendering of route-locked jobs (source assertions).
 *
 *  1. Locked rows show the lock icon (lock-closed).
 *  2. Locked rows have reduced opacity (routeLockedCard style).
 *  3. Tap on locked row fires Alert.alert with the correct message.
 *  4. Tap on unlocked row calls onOpen (normal navigation).
 *  5. Alert text matches the spec.
 *  6. GridView computes lockedIds via isJobLockedByRoute.
 *  7. CalendarView also applies the route lock.
 *  8. isAdmin skips lock computation (lockedIds is empty set).
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf-8",
);

describe("Phase SRL — Schedule locked-row rendering (source assertions)", () => {
  it("locked rows show the lock-closed icon", () => {
    expect(SRC).toContain('name="lock-closed"');
    expect(SRC).toContain('testID={`grid-lock-${job.id}`}');
  });

  it("locked rows have reduced opacity via routeLockedCard style", () => {
    expect(SRC).toContain("routeLockedCard");
    expect(SRC).toContain("routeLocked && gStyles.routeLockedCard");
    expect(SRC).toContain("opacity: 0.55");
  });

  it('tap on locked row fires Alert.alert("Route lock", ...)', () => {
    expect(SRC).toContain(
      'Alert.alert("Route lock", "Please complete the previous job on your route before starting this one.")',
    );
  });

  it("tap on unlocked row calls onOpen (original handler)", () => {
    // The handlePress ternary: routeLocked ? alert : onOpen
    expect(SRC).toContain("routeLocked\n    ? () => Alert.alert");
    // Falls through to onOpen on the else branch
    expect(SRC).toContain(": onOpen;");
  });

  it("alert message exactly matches the spec", () => {
    const msg = "Please complete the previous job on your route before starting this one.";
    const matchCount = (SRC.match(new RegExp(msg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;
    // Should appear in both GridView (JobRow) and CalendarView
    expect(matchCount).toBeGreaterThanOrEqual(2);
  });

  it("GridView computes lockedIds via isJobLockedByRoute", () => {
    expect(SRC).toContain("isJobLockedByRoute(jobs, j)");
    expect(SRC).toContain("lockedIds.has(item.id)");
  });

  it("CalendarView also applies the route lock", () => {
    expect(SRC).toContain("isJobLockedByRoute(dayJ, j)");
    expect(SRC).toContain('testID={`calendar-lock-${j.id}`}');
  });

  it("isAdmin bypasses lock computation (empty set)", () => {
    expect(SRC).toContain("if (isAdmin) return new Set<string>()");
    // CalendarView uses !isAdmin gate
    expect(SRC).toContain("!isAdmin && isJobLockedByRoute");
  });

  it("JobRow accepts routeLocked prop", () => {
    expect(SRC).toContain("routeLocked }: any)");
    expect(SRC).toContain("routeLocked={lockedIds.has(item.id)}");
  });

  it("lock badge has the lockBadge style", () => {
    expect(SRC).toContain("gStyles.lockBadge");
    expect(SRC).toContain("lockBadge:");
  });
});
