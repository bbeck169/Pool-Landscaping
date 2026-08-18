/**
 * Feb-2026 · JobNew monthly Nth-weekday recurrence + Ends radio.
 *
 * Source-inspection contract test. Asserts:
 *   1. Shared ``MonthlyNthWeekdaySelector`` + ``RecurrenceEndsRadio``
 *      are imported and rendered when ``form.cadence === "monthly"``.
 *   2. The submit branch POSTs to ``/recurring-jobs`` (not ``/jobs``)
 *      with the exact wire shape when the user selects nth_weekday.
 *   3. The Ends radio state flows into the payload
 *      (``recurrence_never_ends`` + ``end_date``).
 *   4. The shared selector emits the correct enum + int types
 *      (monthly_nth_week=string, monthly_weekday=int 0..6).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);
const recurringSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/RecurringJobs.jsx"),
  "utf8",
);
const selectorSrc = fs.readFileSync(
  path.resolve(
    __dirname,
    "../components/recurring/MonthlyNthWeekdaySelector.jsx",
  ),
  "utf8",
);

describe("JobNew · monthly Nth-weekday selector wiring", () => {
  it("imports the shared MonthlyNthWeekdaySelector + RecurrenceEndsRadio", () => {
    expect(jobNewSrc).toMatch(
      /import\s+\{[\s\S]*?MonthlyNthWeekdaySelector,\s*RecurrenceEndsRadio,?[\s\S]*?\}\s+from\s+["']@\/components\/recurring\/MonthlyNthWeekdaySelector["']/,
    );
  });

  it("renders both selectors only when form.cadence === 'monthly'", () => {
    expect(jobNewSrc).toMatch(
      /form\.cadence\s*===\s*["']monthly["']\s*\?[\s\S]{0,600}<MonthlyNthWeekdaySelector[\s\S]{0,300}<RecurrenceEndsRadio/,
    );
    expect(jobNewSrc).toMatch(/testid="jf-monthly-recurrence"|testid=\{["']jf-monthly-recurrence["']\}/);
  });

  it("submit branch POSTs to /recurring-jobs when monthly + nth_weekday", () => {
    // The wantsNthWeekdayTemplate gate MUST require BOTH cadence=monthly
    // AND monthly_pattern=nth_weekday — day_of_month monthly keeps
    // the historical POST /jobs loop.
    expect(jobNewSrc).toMatch(
      /wantsNthWeekdayTemplate\s*=\s*[\s\S]{0,100}form\.cadence\s*===\s*["']monthly["'][\s\S]{0,100}form\.monthly_pattern\s*===\s*["']nth_weekday["']/,
    );
    expect(jobNewSrc).toMatch(/api\.post\(["']\/recurring-jobs["'],\s*tplPayload\)/);
  });

  it("payload emits the correct string / int types the backend requires", () => {
    // monthly_nth_week: STRING (backend rejects int with 422)
    expect(jobNewSrc).toMatch(/monthly_nth_week:\s*form\.monthly_nth_week/);
    // monthly_weekday: INT (0..6)
    expect(jobNewSrc).toMatch(/monthly_weekday:\s*form\.monthly_weekday/);
    // Ends contract — recurrence_never_ends + null-when-never
    expect(jobNewSrc).toMatch(/recurrence_never_ends:\s*!!form\.recurrence_never_ends/);
    expect(jobNewSrc).toMatch(
      /end_date:\s*form\.recurrence_never_ends\s*\?\s*null\s*:\s*\(form\.end_date\s*\|\|\s*null\)/,
    );
  });
});

describe("RecurringJobs.jsx · reuses the same shared selector", () => {
  it("imports MonthlyNthWeekdaySelector from the shared path", () => {
    expect(recurringSrc).toMatch(
      /import\s+\{[\s\S]{0,60}MonthlyNthWeekdaySelector[\s\S]{0,60}\}\s+from\s+["']@\/components\/recurring\/MonthlyNthWeekdaySelector["']/,
    );
  });

  it("mounts the selector when frequency === 'monthly'", () => {
    expect(recurringSrc).toMatch(
      /editing\.frequency\s*===\s*["']monthly["']\s*\?[\s\S]{0,900}<MonthlyNthWeekdaySelector/,
    );
  });
});

describe("MonthlyNthWeekdaySelector · type + label contract", () => {
  it("monthly_nth_week enum values are the strings the backend expects", () => {
    // Backend: {"first","second","third","fourth","last"}
    for (const v of ["first", "second", "third", "fourth", "last"]) {
      expect(selectorSrc).toMatch(new RegExp(`value:\\s*["']${v}["']`));
    }
  });

  it("weekday values are ints 0..6 with Mon=0 ordering", () => {
    // First DOW_OPTS entry MUST be Mon at value 0 (matches Python
    // ``date.weekday()``).
    expect(selectorSrc).toMatch(
      /DOW_OPTS\s*=\s*\[\s*\{\s*value:\s*0,\s*label:\s*["']Mon["']/,
    );
  });
});
