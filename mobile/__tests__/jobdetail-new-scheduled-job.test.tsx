/**
 * Feb-2026 · Mobile "+ New Scheduled Job" quick-action on JobDetail.
 *
 * Source-inspection contract test — mirrors the sibling
 * ``schedule-job-notes`` shape. Asserts:
 *   1. The button exists on the mobile job detail screen with the
 *      correct testID and is gated by ``isAdmin``.
 *   2. The button pushes ``/job/new`` with pre-fill params derived
 *      from the current job's ``customer_id`` / ``technician_id``
 *      / ``service_type`` and today's date.
 *   3. The mobile ``/job/new`` route reads those params via
 *      ``useLocalSearchParams`` and hydrates the customer +
 *      technician pickers accordingly.
 */
import fs from "fs";
import path from "path";

const detailSrc = fs.readFileSync(
  path.resolve(__dirname, "../app/job/[id].tsx"),
  "utf8",
);
const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../app/job/new.tsx"),
  "utf8",
);

describe("Mobile JobDetail · '+ New Scheduled Job' quick-action", () => {
  it("renders an admin-gated <Pressable> with testID=jd-new-scheduled-job", () => {
    expect(detailSrc).toMatch(/testID=["']jd-new-scheduled-job["']/);
    // Admin gate must wrap the button so techs / customers don't see it.
    expect(detailSrc).toMatch(
      /isAdmin\s*\?[\s\S]{0,600}testID=["']jd-new-scheduled-job["']/,
    );
    expect(detailSrc).toMatch(/New Scheduled Job/);
  });

  it("pushes /job/new with pre-fill params from the current job", () => {
    expect(detailSrc).toMatch(/pathname:\s*["']\/job\/new["']/);
    expect(detailSrc).toMatch(/customer_id:\s*job\.customer_id/);
    expect(detailSrc).toMatch(/technician_id:\s*job\.technician_id/);
    expect(detailSrc).toMatch(/service_type:\s*job\.service_type/);
    expect(detailSrc).toMatch(
      /scheduled_date:\s*new Date\(\)\.toISOString\(\)\.slice\(0,\s*10\)/,
    );
  });
});

describe("Mobile /job/new · consumes pre-fill params", () => {
  it("reads customer_id / technician_id / service_type / scheduled_date via useLocalSearchParams", () => {
    expect(jobNewSrc).toMatch(/useLocalSearchParams<\{/);
    expect(jobNewSrc).toMatch(/customer_id\?:\s*string/);
    expect(jobNewSrc).toMatch(/technician_id\?:\s*string/);
    expect(jobNewSrc).toMatch(/service_type\?:\s*string/);
    expect(jobNewSrc).toMatch(/scheduled_date\?:\s*string/);
  });

  it("hydrates the customer + technician pickers when params match a row", () => {
    // Post-fetch, the code must look up the row by id and setCustomer/setTech.
    expect(jobNewSrc).toMatch(
      /prefill\?\.customer_id[\s\S]{0,300}setCustomer\(c\)/,
    );
    expect(jobNewSrc).toMatch(
      /prefill\?\.technician_id[\s\S]{0,300}setTech\(t\)/,
    );
  });
});
