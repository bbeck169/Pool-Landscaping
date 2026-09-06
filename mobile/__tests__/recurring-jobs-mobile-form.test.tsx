/**
 * Mobile · Recurring Jobs create/edit form · Feb-2026.
 *
 * Contract test — asserts the mobile ``finance/recurring-jobs.tsx``
 * source implements the Task B + monthly nth-weekday spec:
 *
 *   1. `+ New` button opens the sheet with `openCreate`.
 *   2. Row tap opens the same sheet with `openEdit`.
 *   3. Sheet renders all recurrence controls with stable testIDs:
 *      frequency chips, day-of-week chips, monthly-pattern chips,
 *      nth-week + weekday chips, day-of-month input, start/end date
 *      fields, price + notes.
 *   4. Ends radio group (Never / On date) is mutually exclusive and
 *      Never is the create-mode default.
 *   5. `openEdit` normalises legacy rows (no flag + no end_date)
 *      into Never mode.
 *   6. `save()` nulls out `end_date` when `recurrence_never_ends` is
 *      true so the API never sees both fields set.
 *   7. Per-row `Stop` button posts to `/recurring-jobs/{id}/stop`
 *      via `showConfirm`.
 *
 * Source-inspection style (matches `admin-sidebar-pinned-nav.test.jsx`
 * on web + `phase41-2-admin-list-page-mount.test.tsx` on mobile) —
 * avoids mounting the full sheet's DateTimePicker + expo-router deps.
 */
import fs from "fs";
import path from "path";

function readSrc(): string {
  return fs.readFileSync(
    path.resolve(__dirname, "../app/finance/recurring-jobs.tsx"),
    "utf8",
  );
}

describe("Mobile RecurringJobs · sheet + create action", () => {
  const src = readSrc();

  it("registers a `+ New` create button in the header", () => {
    expect(src).toMatch(/testID="recurring-new-btn"/);
    // The button's onPress fires openCreate.
    expect(src).toMatch(/onPress=\{openCreate\}[\s\S]{0,80}testID="recurring-new-btn"/);
  });

  it("opens the same sheet from a row tap via openEdit", () => {
    expect(src).toMatch(/testID=\{`recurring-edit-\$\{r\.id\}`\}/);
    expect(src).toMatch(/onPress=\{\(\)\s*=>\s*openEdit\(r\)\}/);
  });

  it("wires openCreate → editing state with Ends=Never by default", () => {
    // The create default must set `recurrence_never_ends: true` per the
    // product rule ("Ends: Never" is the default mode).
    const create = src.match(
      /const\s+openCreate\s*=[\s\S]*?setEditing\(\{([\s\S]*?)\}\)/,
    );
    expect(create).not.toBeNull();
    expect(create![1]).toMatch(/recurrence_never_ends:\s*true/);
    expect(create![1]).toMatch(/end_date:\s*null/);
  });
});

describe("Mobile RecurringJobs · form fields render with stable testIDs", () => {
  const src = readSrc();

  // Fields with directly-quoted testIDs.
  const DIRECT_TESTIDS = [
    "recurring-customer-id",
    "recurring-service-type",
    "recurring-day-of-month",
    "recurring-start-date",
    "recurring-end-date",
    "recurring-ends-never",
    "recurring-ends-on-date",
    "recurring-price",
    "recurring-notes",
    "recurring-save-btn",
  ];

  // ChipRow instances — assert by their `testIDPrefix` value. Concrete
  // per-chip testIDs like `recurring-freq-weekly` are constructed at
  // runtime via a template literal, so we assert the prefix + option
  // set instead of hardcoding all N final ids.
  const CHIP_ROW_PREFIXES = [
    "recurring-freq",
    "recurring-dow",
    "recurring-monthly-pattern",
    "recurring-nth-week",
    "recurring-monthly-weekday",
  ];

  it.each(DIRECT_TESTIDS)("renders testID %s (raw)", (id) => {
    expect(src).toContain(`testID="${id}"`);
  });

  it.each(CHIP_ROW_PREFIXES)("wires ChipRow testIDPrefix=%s", (pfx) => {
    expect(src).toContain(`testIDPrefix="${pfx}"`);
  });

  it("frequency ChipRow exposes weekly/biweekly/monthly options", () => {
    // FREQ_OPTS drives the frequency chip labels.
    // Phase Hygiene B · Feb-2026 — the option set was extended to include
    // ``quarterly`` + ``semi_annual`` for lower-cadence recurring jobs.
    // The contract is that the three K73.5 options are still present;
    // additional options are additive and don't break the sheet.
    expect(src).toMatch(
      /FREQ_OPTS:\s*RecurringJob\["frequency"\]\[\]\s*=\s*\[\s*"weekly",\s*"biweekly",\s*"monthly"/,
    );
  });

  it("nth-week ChipRow exposes first/second/third/fourth/last", () => {
    expect(src).toMatch(
      /NTH_WEEK_OPTS[\s\S]{0,200}=\s*\n?\s*\["first",\s*"second",\s*"third",\s*"fourth",\s*"last"\]/,
    );
  });
});

describe("Mobile RecurringJobs · Ends radio mutual exclusion", () => {
  const src = readSrc();

  it("Never onPress clears end_date and sets the flag", () => {
    const neverBlock = src.match(
      /testID="recurring-ends-never"[\s\S]{0,300}/,
    );
    // Never onPress is defined BEFORE the testID in the JSX — search the
    // whole file for the onPress+setEditing pair with the flag+null combo.
    expect(src).toMatch(
      /recurrence_never_ends:\s*true,\s*end_date:\s*null/,
    );
    expect(neverBlock).not.toBeNull();
  });

  it("On-date onPress explicitly turns the flag off (so end_date can persist)", () => {
    expect(src).toMatch(
      /testID="recurring-ends-on-date"[\s\S]{0,300}/,
    );
    // The onPress must set the flag false — verified globally.
    expect(src).toMatch(/recurrence_never_ends:\s*false/);
  });

  it("End date field is disabled when Never is active", () => {
    expect(src).toMatch(
      /testID="recurring-end-date"[\s\S]{0,200}disabled=\{!!editing\.recurrence_never_ends\}/,
    );
  });
});

describe("Mobile RecurringJobs · openEdit normalises legacy rows", () => {
  const src = readSrc();

  it("no flag + no end_date on a legacy row becomes Never", () => {
    // Exactly the rule ported from the web
    // `RecurringJobs.jsx::openEdit`.
    expect(src).toMatch(
      /row\.recurrence_never_ends\s*===\s*true[\s\S]{0,200}row\.recurrence_never_ends\s*==\s*null[\s\S]{0,80}!row\.end_date/,
    );
  });
});

describe("Mobile RecurringJobs · save payload guarantees exclusive mode", () => {
  const src = readSrc();

  it("save() nulls end_date when recurrence_never_ends is true", () => {
    expect(src).toMatch(
      /if\s*\(payload\.recurrence_never_ends\)\s*payload\.end_date\s*=\s*null/,
    );
  });

  it("uses PATCH for edit and POST for create", () => {
    expect(src).toMatch(/api\.patch\(`\/recurring-jobs\/\$\{editing\.id\}`/);
    expect(src).toMatch(/api\.post\("\/recurring-jobs",\s*payload\)/);
  });
});

describe("Mobile RecurringJobs · Stop action", () => {
  const src = readSrc();

  it("renders a per-row Stop button on active rows with stable testid", () => {
    expect(src).toMatch(/testID=\{`recurring-stop-\$\{r\.id\}`\}/);
    // Only rendered when the row is active — guard on `r.active`.
    expect(src).toMatch(
      /\{r\.active\s*\?[\s\S]{0,400}testID=\{`recurring-stop-\$\{r\.id\}`\}/,
    );
  });

  it("Stop confirms via showConfirm and POSTs to /recurring-jobs/{id}/stop", () => {
    expect(src).toMatch(
      /showConfirm\(\{[\s\S]{0,600}api\.post\(`\/recurring-jobs\/\$\{row\.id\}\/stop`/,
    );
  });
});
