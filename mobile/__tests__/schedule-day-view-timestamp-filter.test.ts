/**
 * P2 #9 · MOBILE-SCHEDULE-DAY-VIEW-TIMESTAMP-FILTER-BUG
 *
 * Mobile Day view must bucket jobs exactly like web CalendarSchedule.jsx
 * P13 (scheduled_date prefix → else tenant-local scheduled_start) and key
 * the focus Date by device-local calendar fields, independent of the
 * device timezone.
 *
 *   1. happy path            — 2026-02-15 (bare + timestamp) on Feb 15 only
 *   2. DST-safe boundary     — 23:59 tenant-local = today, 00:00 = tomorrow
 *                              (normal day, fall-back Nov 1, spring-fwd Mar 8)
 *   3. tz-robust matrix      — identical Day view in 5 device TZs, incl. the
 *                              audit repro (NY 9 pm "Today", Sydney strip tap)
 *   4. screen contract       — calendar.tsx routes every day key through
 *                              the helpers (no UTC toISOString day keys left)
 */
import * as fs from "fs";
import * as path from "path";
import { execFile } from "child_process";
import { jobDayKey, localDateKey } from "@/src/utils/scheduleDayKey";

const TENANT_TZ = "America/New_York";
const DEVICE_TZS = ["UTC", "America/New_York", "America/Phoenix", "Australia/Sydney", "Asia/Kolkata"];
// Jest sandboxes ``process.env`` — assigning TZ at runtime does NOT move the
// worker's real timezone (verified: offset stayed 0). So each device TZ runs
// in its own child Jest process started with a real ``TZ`` env (see the
// "5-TZ matrix" block); a run tests the TZ it was actually launched with.
const IS_CHILD = process.env.P2_9_CHILD === "1";
const DEVICE_TZ = process.env.TZ || "UTC";
const JAN_OFFSET: Record<string, number> = {
  UTC: 0, "America/New_York": 300, "America/Phoenix": 420, "Australia/Sydney": -660, "Asia/Kolkata": -330,
};

type J = { id: string; scheduled_date?: string | null; scheduled_start?: string | null };

/** The screen's composition after the fix: dayJobs = filter(jobDayKey === iso(focus)). */
const dayView = (jobs: J[], focus: Date, tz = TENANT_TZ) =>
  jobs.filter((j) => jobDayKey(j, tz) === localDateKey(focus)).map((j) => j.id);
/** Pre-fix screen logic, verbatim (calendar.tsx L132 + L513 @ ac7f0ba00). */
const legacyDayView = (jobs: J[], focus: Date) =>
  jobs.filter((j) => j.scheduled_date === focus.toISOString().slice(0, 10)).map((j) => j.id);

const AUDIT_JOBS: J[] = [
  { id: "A-oct12", scheduled_date: "2026-10-12" },
  { id: "B-oct13", scheduled_date: "2026-10-13" },
  { id: "C-oct11", scheduled_date: "2026-10-11" },
  { id: "D-ts-oct12", scheduled_date: "2026-10-12T06:40:46+00:00" },
  { id: "E-start-only-oct12", scheduled_date: null, scheduled_start: "2026-10-12T16:00:00Z" },
];

describe(`device TZ=${DEVICE_TZ}`, () => {
  const deviceTz = DEVICE_TZ;

  it("device TZ is really in effect (guards the matrix itself)", () => {
    const off = new Date(2026, 0, 15).getTimezoneOffset();
    if (IS_CHILD) expect([deviceTz, off]).toEqual([deviceTz, JAN_OFFSET[deviceTz]]);
    else expect(typeof off).toBe("number");
  });

  it("1 · happy path — 2026-02-15 (bare + timestamp) appears on Feb 15 only", () => {
    const jobs: J[] = [
      { id: "bare", scheduled_date: "2026-02-15" },
      { id: "ts", scheduled_date: "2026-02-15T06:40:46+00:00" },
      { id: "other", scheduled_date: "2026-02-16" },
    ];
    expect(jobDayKey(jobs[0], TENANT_TZ)).toBe("2026-02-15");
    expect(jobDayKey(jobs[1], TENANT_TZ)).toBe("2026-02-15");
    expect(dayView(jobs, new Date(2026, 1, 15))).toEqual(["bare", "ts"]);
    expect(dayView(jobs, new Date(2026, 1, 14))).toEqual([]);
    expect(dayView(jobs, new Date(2026, 1, 16))).toEqual(["other"]);
    expect(jobDayKey({ id: "x" } as J, TENANT_TZ)).toBe("");
    expect(jobDayKey({ id: "x", scheduled_start: "not-a-date" } as J, TENANT_TZ)).toBe("");
  });

  it.each([
    ["normal day 23:59", "2026-10-12T23:59:00-04:00", "2026-10-12"],
    ["normal day 00:00 next", "2026-10-13T00:00:00-04:00", "2026-10-13"],
    ["fall-back eve 23:59 EDT", "2026-11-01T03:59:00Z", "2026-10-31"],
    ["fall-back day 00:00 EDT", "2026-11-01T04:00:00Z", "2026-11-01"],
    ["fall-back day 23:59 EST (25h day)", "2026-11-02T04:59:00Z", "2026-11-01"],
    ["after fall-back 00:00 EST", "2026-11-02T05:00:00Z", "2026-11-02"],
    ["spring-fwd eve 23:59 EST", "2026-03-08T04:59:00Z", "2026-03-07"],
    ["spring-fwd day 00:00 EST", "2026-03-08T05:00:00Z", "2026-03-08"],
    ["spring-fwd day 23:59 EDT (23h day)", "2026-03-09T03:59:00Z", "2026-03-08"],
    ["after spring-fwd 00:00 EDT", "2026-03-09T04:00:00Z", "2026-03-09"],
  ])("2 · DST-safe boundary (tenant NY) — %s → %s", (_label, start, expectedDay) => {
    expect(jobDayKey({ id: "s", scheduled_date: null, scheduled_start: start }, TENANT_TZ)).toBe(expectedDay);
  });

  it("2b · localDateKey walks every calendar day of 2026 exactly once (device DST can't skip/dup)", () => {
    const keys: string[] = [];
    for (let d = new Date(2026, 0, 1); d.getFullYear() === 2026; d.setDate(d.getDate() + 1)) keys.push(localDateKey(new Date(d)));
    expect(keys.length).toBe(365);
    expect(new Set(keys).size).toBe(365);
    expect([keys[0], keys[66], keys[67], keys[303], keys[304], keys[364]])
      .toEqual(["2026-01-01", "2026-03-08", "2026-03-09", "2026-10-31", "2026-11-01", "2026-12-31"]);
  });

  it("3 · tz-robust — same Day view for 9 pm 'Today' and a strip tap, in every device TZ", () => {
    const todayAt9pm = new Date(2026, 9, 12, 21, 0, 0);
    const stripTap = new Date(2026, 9, 12);
    const expected = ["A-oct12", "D-ts-oct12", "E-start-only-oct12"];
    expect(dayView(AUDIT_JOBS, todayAt9pm)).toEqual(expected);
    expect(dayView(AUDIT_JOBS, stripTap)).toEqual(expected);
    // Before/after proof — the pre-fix logic in the same TZ.
    const legacyToday = legacyDayView(AUDIT_JOBS, todayAt9pm);
    const legacyTap = legacyDayView(AUDIT_JOBS, stripTap);
    const legacyExpected: Record<string, [string[], string[]]> = {
      UTC: [["A-oct12"], ["A-oct12"]],
      "America/New_York": [["B-oct13"], ["A-oct12"]],
      "America/Phoenix": [["B-oct13"], ["A-oct12"]],
      "Australia/Sydney": [["A-oct12"], ["C-oct11"]],
      "Asia/Kolkata": [["A-oct12"], ["C-oct11"]],
    };
    expect([legacyToday, legacyTap]).toEqual(legacyExpected[deviceTz] || [legacyToday, legacyTap]);
  });
});

// Parent run only: re-run THIS file in 5 child Jest processes, each launched
// with a real ``TZ`` env, and require every child to pass.
(IS_CHILD ? describe.skip : describe)("3 · 5-TZ matrix (child Jest per device TZ)", () => {
  jest.setTimeout(240_000);
  it.each(DEVICE_TZS)("TZ=%s → child suite passes", async (tz) => {
    const jestBin = path.join(__dirname, "..", "node_modules", "jest", "bin", "jest.js");
    const out: string = await new Promise((resolve, reject) => {
      execFile(
        process.execPath,
        [jestBin, "--ci", "--forceExit", "--colors=false", path.join("__tests__", "schedule-day-view-timestamp-filter.test.ts")],
        { cwd: path.join(__dirname, ".."), env: { ...process.env, TZ: tz, P2_9_CHILD: "1" }, maxBuffer: 16 * 1024 * 1024 },
        (err, stdout, stderr) => (err ? reject(new Error(`TZ=${tz} child failed:\n${stdout}\n${stderr}`)) : resolve(`${stdout}\n${stderr}`)),
      );
    });
    expect(out).toMatch(/Tests:\s+(\d+ skipped, )?\d+ passed/);
    expect(out).not.toMatch(/failed/);
    expect(out).toContain(`device TZ=${tz}`);
  });
});

describe("tenant TZ default", () => {
  it("jobDayKey defaults to tenantTz() (America/Phoenix fallback) for scheduled_start-only rows", () => {
    // 2026-10-13T05:30Z = 22:30 Oct 12 in Phoenix (UTC-7), 01:30 Oct 13 in NY.
    const j = { id: "s", scheduled_date: null, scheduled_start: "2026-10-13T05:30:00Z" };
    expect(jobDayKey(j)).toBe("2026-10-12");
    expect(jobDayKey(j, "America/New_York")).toBe("2026-10-13");
  });
});

(IS_CHILD ? describe.skip : describe)("4 · screen contract — calendar.tsx routes all day keys through the helpers", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "..", "app", "(app)", "schedule", "calendar.tsx"), "utf8");
  const code = SRC.split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");

  it("imports the helpers", () => {
    expect(SRC).toContain('import { jobDayKey, localDateKey } from "@/src/utils/scheduleDayKey";');
    expect(SRC).toContain('import { tenantTz } from "@/src/utils/tenantTime";');
  });
  it("iso() is device-local (no UTC toISOString day keys in code)", () => {
    expect(code).toContain("const iso = (d: Date) => localDateKey(d);");
    expect(code).not.toMatch(/toISOString\(\)\.slice\(0,\s*10\)/);
  });
  it("dayJobs / weekCounts / jobsByDay all use jobDayKey (no exact or raw scheduled_date keys)", () => {
    expect(code).toContain("visibleJobs.filter((j) => jobDayKey(j, tz) === focusISO)");
    expect((code.match(/const d = jobDayKey\(j, tz\);/g) || []).length).toBe(2);
    expect(code).not.toContain("j.scheduled_date === focusISO");
    expect(code).not.toContain('const d = j.scheduled_date || "";');
  });
});
