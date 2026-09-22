/**
 * Phase P19 · tenantTime.test.ts — todayKeyInTenantTz across timezones.
 *
 * Freezes UTC time and asserts the returned YYYY-MM-DD matches what
 * that UTC instant looks like in the target timezone.
 */

import { todayKeyInTenantTz, setTenantTz, tenantTz } from "@/src/utils/tenantTime";

describe("todayKeyInTenantTz", () => {
  afterEach(() => {
    jest.useRealTimers();
    setTenantTz("America/Phoenix"); // reset
  });

  const matrix: [string, string, string][] = [
    // [freezeUtcISO, tenantTz, expectedYYYYMMDD]
    // 2026-04-16 12:00 UTC → same day everywhere in US
    ["2026-04-16T12:00:00.000Z", "America/New_York",    "2026-04-16"],
    ["2026-04-16T12:00:00.000Z", "America/Chicago",     "2026-04-16"],
    ["2026-04-16T12:00:00.000Z", "America/Denver",      "2026-04-16"],
    ["2026-04-16T12:00:00.000Z", "America/Los_Angeles",  "2026-04-16"],
    ["2026-04-16T12:00:00.000Z", "America/Phoenix",      "2026-04-16"],
    ["2026-04-16T12:00:00.000Z", "Pacific/Honolulu",     "2026-04-16"],

    // Phoenix rollover: 2026-04-17 01:30 UTC → Apr 16 at 18:30 PHX (UTC-7)
    ["2026-04-17T01:30:00.000Z", "America/Phoenix",      "2026-04-16"],

    // Eastern: 2026-04-17 03:30 UTC → Apr 16 at 23:30 ET (UTC-4 in April/DST)
    ["2026-04-17T03:30:00.000Z", "America/New_York",     "2026-04-16"],

    // Eastern: 2026-04-17 04:30 UTC → Apr 17 at 00:30 ET
    ["2026-04-17T04:30:00.000Z", "America/New_York",     "2026-04-17"],

    // Pacific: 2026-04-17 06:30 UTC → Apr 16 at 23:30 PT (UTC-7 in April/DST)
    ["2026-04-17T06:30:00.000Z", "America/Los_Angeles",  "2026-04-16"],

    // Hawaii: 2026-04-17 09:30 UTC → Apr 16 at 23:30 HST (UTC-10)
    ["2026-04-17T09:30:00.000Z", "Pacific/Honolulu",     "2026-04-16"],
  ];

  it.each(matrix)(
    "freeze %s in %s → %s",
    (freezeUtc, tz, expected) => {
      jest.useFakeTimers({ now: new Date(freezeUtc).getTime() });
      expect(todayKeyInTenantTz(tz)).toBe(expected);
    },
  );

  it("setTenantTz + tenantTz round-trips", () => {
    setTenantTz("America/Chicago");
    expect(tenantTz()).toBe("America/Chicago");
  });

  it("defaults to America/Phoenix when never set", () => {
    setTenantTz(""); // clear
    expect(tenantTz()).toBe("America/Phoenix");
  });
});
