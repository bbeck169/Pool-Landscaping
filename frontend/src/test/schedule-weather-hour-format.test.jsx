/**
 * Feb-2026 · UX regression — Schedule hourly weather strip must not
 * leak raw ISO timestamps into the label cells.
 *
 * Root cause fixed here: the older ``fmtHour`` in
 * ``components/Weather/WeatherWidget.jsx`` split on " " (WeatherAPI's
 * legacy shape). When the upstream shifted to ISO 8601
 * (``"YYYY-MM-DDTHH:MM:SS±HH:MM"``) the split returned a 1-element
 * array and the raw ISO leaked into the DOM.
 *
 * The formatter is unit-tested here directly (fastest signal;
 * mounting the full widget requires the /api/weather/* mocks + role
 * gate + geocode hook and is covered by ``phase39b-weather-widget``).
 * We also render a small proxy strip to prove the "Now" special-
 * case for i===0 and the sequential ``h AM/PM`` labels for i>=1.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { fmtHour } from "../components/Weather/WeatherWidget";


describe("WeatherWidget · fmtHour · ISO + legacy input handling", () => {
  it("formats ISO 8601 (with tz offset) as h AM/PM — no raw ISO leak", () => {
    // Input is the exact shape the tester reported leaking.
    const out = fmtHour("2026-08-26T09:00:00-07:00");
    // Must not leak the raw ISO fragments.
    expect(out).not.toContain("T");
    expect(out).not.toContain("00:00");
    expect(out).not.toContain("-07:00");
    // 12-hour US format ends in " AM" or " PM".
    expect(out).toMatch(/^\d{1,2}\s?(AM|PM)$/);
  });

  it("formats legacy WeatherAPI shape (space-separated) too", () => {
    const out = fmtHour("2026-08-26 09:00");
    expect(out).not.toContain("2026");
    expect(out).toMatch(/^\d{1,2}\s?(AM|PM)$/);
  });

  it("uses 12-hour boundary format at midnight and noon", () => {
    // Force local-tz alignment by using the browser's own tz for
    // both — the formatter never needs to shift zones because the
    // ISO carries an explicit offset that ``Intl.DateTimeFormat``
    // renders in the local zone.
    const midnight = new Date(2026, 5, 1, 0, 0).toISOString();
    const noon = new Date(2026, 5, 1, 12, 0).toISOString();
    expect(fmtHour(midnight)).toMatch(/^12\s?AM$/);
    expect(fmtHour(noon)).toMatch(/^12\s?PM$/);
    // Never renders 0 or 13.
    expect(fmtHour(midnight)).not.toMatch(/^0\s?AM$/);
    const oneMorning = new Date(2026, 5, 1, 1, 0).toISOString();
    const onePM = new Date(2026, 5, 1, 13, 0).toISOString();
    expect(fmtHour(oneMorning)).toMatch(/^1\s?AM$/);
    expect(fmtHour(onePM)).toMatch(/^1\s?PM$/);
    expect(fmtHour(onePM)).not.toMatch(/^13\s?PM$/);
  });

  it("returns empty string for empty / null input", () => {
    expect(fmtHour("")).toBe("");
    expect(fmtHour(null)).toBe("");
    expect(fmtHour(undefined)).toBe("");
  });

  it("degrades gracefully on unparseable input (returns as-is)", () => {
    expect(fmtHour("not-a-date")).toBe("not-a-date");
  });
});


// ── Behaviour test — small proxy strip mirrors the label wire-up
// from WeatherWidget.jsx (``{i === 0 ? "Now" : fmtHour(h.time)}``).
// Locks the "Now → h AM → h AM → ..." pattern without mounting the
// full widget.
function ProxyStrip({ hours }) {
  return (
    <div data-testid="weather-hourly-strip">
      {hours.map((h, i) => (
        <span key={i} data-testid={`weather-hour-${i}`}>
          {i === 0 ? "Now" : fmtHour(h.time)}
        </span>
      ))}
    </div>
  );
}


describe("WeatherWidget · hourly strip label wire-up", () => {
  const HOURS = [
    { time: "2026-08-26T08:00:00-07:00" },  // Now
    { time: "2026-08-26T09:00:00-07:00" },
    { time: "2026-08-26T10:00:00-07:00" },
    { time: "2026-08-26T12:00:00-07:00" },
    { time: "2026-08-26T13:00:00-07:00" },
  ];

  it("first cell reads 'Now' (special-case for current hour)", () => {
    render(<ProxyStrip hours={HOURS} />);
    expect(screen.getByTestId("weather-hour-0").textContent).toBe("Now");
  });

  it("subsequent cells render 12-hour AM/PM labels, no raw ISO", () => {
    render(<ProxyStrip hours={HOURS} />);
    for (let i = 1; i < HOURS.length; i += 1) {
      const txt = screen.getByTestId(`weather-hour-${i}`).textContent;
      // Never leaks any ISO fragment.
      expect(txt).not.toContain("T");
      expect(txt).not.toContain("00:00");
      expect(txt).not.toContain("-07:00");
      // Matches "h AM" or "h PM".
      expect(txt).toMatch(/^\d{1,2}\s?(AM|PM)$/);
    }
  });
});
