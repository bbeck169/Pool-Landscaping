/**
 * Phase 30 — Time Clock Team Aggregation Table (web).
 *
 * Locks the payroll-friendly table rendering of the expanded
 * per-technician history inside the admin "Team aggregation" card:
 *
 *   • 5-column table in order:
 *     Date | Clock In | Clock Out | Hours Worked | Location
 *   • Shifts grouped by local-tz date-of-clock-in.
 *   • Multiple shifts on the same day: date label shows on the
 *     first row only, subsequent same-day rows have an empty date
 *     cell.
 *   • Orphan still-clocked-in row: Clock Out = ``—``, Hours = ``—``,
 *     Location shows ONLY the In GPS line (no Out line).
 *   • Total Hours ``<tfoot>`` reuses backend ``t.total_seconds``
 *     (no client re-sum) in ``H:MM`` format.
 *   • GPS in Location column uses ``.toFixed(4)`` precision.
 *   • Outer wrapper preserves the Phase-46.3 testid
 *     ``landscape-time-clock-admin-tech-punches-${user_id}`` so the
 *     existing adminAggregation.test regression lock stays green.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, cleanup, waitFor, fireEvent, act,
  within,
} from "@testing-library/react";

import {
  buildShiftRows, fmtHoursMinutes, _fmtLatLng, _dayKey, _fmtDateLabel,
} from "@/lib/timeclock/pairPunches";

const getMock = vi.fn();
const postMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));

let _mockUser = null;
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _mockUser }),
}));

import LandscapingTimeClock from "@/pages/tech/LandscapingTimeClock";

function _mkPunch(id, ts, punch_type, lat, lng) {
  return { id, ts, lat, lng, punch_type, job_id: null };
}

function _summaryMock() {
  return {
    range: { start: "2026-02-02", end: "2026-02-08" },
    techs: [
      {
        user_id: "u-mig",
        name: "Miguel Munoz",
        status: "out",
        // 2 completed shifts Mon + 2 completed Tue
        //   Mon 0:00 + Mon 9:51 + Tue 0:03 + Tue 8:26 = 18:20 = 65 940s
        total_seconds: 65940,
        last_punch: {
          ts: "2026-02-04T16:17:00+00:00",
          lat: 33.6512, lng: -112.2938, punch_type: "out",
        },
        punches: [
          _mkPunch("p1", "2026-02-02T12:57:00+00:00", "in",
            33.6123, -112.3812),
          _mkPunch("p2", "2026-02-02T12:57:00+00:00", "out",
            33.6123, -112.3812),
          _mkPunch("p3", "2026-02-02T13:25:00+00:00", "in",
            33.6500, -112.2900),
          _mkPunch("p4", "2026-02-02T23:16:00+00:00", "out",
            33.6512, -112.2812),
          _mkPunch("p5", "2026-02-03T12:52:00+00:00", "in",
            33.6511, -112.2805),
          _mkPunch("p6", "2026-02-03T12:55:00+00:00", "out",
            33.6511, -112.2805),
          _mkPunch("p7", "2026-02-03T14:51:00+00:00", "in",
            33.6512, -112.2810),
          _mkPunch("p8", "2026-02-03T23:17:00+00:00", "out",
            33.6512, -112.2938),
        ],
      },
      {
        user_id: "u-open",
        name: "Still Clocked In Sam",
        status: "in",
        total_seconds: 0,
        last_punch: {
          ts: "2026-02-04T13:00:00+00:00",
          lat: 33.70, lng: -112.10, punch_type: "in",
        },
        punches: [
          _mkPunch("q1", "2026-02-04T13:00:00+00:00", "in",
            33.7000, -112.1000),
        ],
      },
    ],
  };
}

function _mineBaseMock() {
  return (url) => {
    if (String(url).startsWith("/timeclock/mine-today")) {
      return Promise.resolve({ punches: [], seconds: 0, clocked_in: false });
    }
    if (String(url).startsWith("/timeclock/mine-summary")) {
      return Promise.resolve({ days: [], total_seconds: 0, punches: [] });
    }
    if (String(url).startsWith("/timeclock/admin-summary")) {
      return Promise.resolve(_summaryMock());
    }
    return Promise.resolve({});
  };
}

function _render() {
  return render(
    <MemoryRouter initialEntries={["/landscape/time-clock"]}>
      <LandscapingTimeClock />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});
afterEach(() => cleanup());

describe("Phase 30 · buildShiftRows pure helper", () => {
  it("pairs in→out punches into shifts in timestamp order", () => {
    const rows = buildShiftRows([
      _mkPunch("a", "2026-02-02T08:00:00+00:00", "in", 33.5, -112.1),
      _mkPunch("b", "2026-02-02T10:00:00+00:00", "out", 33.5, -112.1),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].open).toBe(false);
    expect(rows[0].hoursLabel).toBe("2:00");
  });

  it("groups multiple pairs per day under the same date key", () => {
    const rows = buildShiftRows(_summaryMock().techs[0].punches);
    // 4 completed shifts across 2 calendar days (per clock-in local date)
    expect(rows).toHaveLength(4);
    expect(rows[0].dateKey).toBe(rows[1].dateKey);
    expect(rows[2].dateKey).toBe(rows[3].dateKey);
    expect(rows[0].dateKey).not.toBe(rows[2].dateKey);
    // showDate = true on first row of each day, false on subsequent
    expect(rows[0].showDate).toBe(true);
    expect(rows[1].showDate).toBe(false);
    expect(rows[2].showDate).toBe(true);
    expect(rows[3].showDate).toBe(false);
  });

  it("renders orphan still-clocked-in with out=null and hours=—", () => {
    const rows = buildShiftRows([
      _mkPunch("a", "2026-02-04T13:00:00+00:00", "in", 33.7, -112.1),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].open).toBe(true);
    expect(rows[0].clockOutLabel).toBe("—");
    expect(rows[0].hoursLabel).toBe("—");
    expect(rows[0].outLatLng).toBeNull();
  });

  it("warns and skips an orphan OUT punch (no preceding in)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const rows = buildShiftRows([
      _mkPunch("x", "2026-02-02T10:00:00+00:00", "out", 33.5, -112.1),
    ]);
    expect(rows).toHaveLength(0);
    expect(warn).toHaveBeenCalledWith(
      "[timeclock] orphan OUT punch", expect.any(Object));
    warn.mockRestore();
  });

  it("formats Location lat/lng at 4-decimal precision", () => {
    expect(_fmtLatLng(33.65123, -112.29876))
      .toBe("33.6512,-112.2988");
    expect(_fmtLatLng(null, -112)).toBe("—");
  });

  it("formats hours as H:MM (no leading zero on hours)", () => {
    expect(fmtHoursMinutes(0)).toBe("0:00");
    expect(fmtHoursMinutes(60 * 60 * 9 + 60 * 51)).toBe("9:51");
    expect(fmtHoursMinutes(65940)).toBe("18:19");
    expect(fmtHoursMinutes(null)).toBe("—");
  });

  it("_dayKey + _fmtDateLabel are stable + non-empty for a real ts",
    () => {
      const d = new Date("2026-02-02T12:00:00+00:00");
      expect(_dayKey(d)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(_fmtDateLabel(d)).toMatch(/^[A-Za-z]{3} \d{2}\/\d{2}$/);
    });
});

describe("Phase 30 · table rendering · admin aggregation", () => {
  it("renders 5 column headers in exact order: " +
      "Date | Clock In | Clock Out | Hours Worked | Location",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-mig"));
      await act(async () => { fireEvent.click(expandBtn); });
      const table = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-table-u-mig"));
      const headers = within(table).getAllByRole("columnheader")
        .map((th) => th.textContent.trim());
      expect(headers).toEqual([
        "Date", "Clock In", "Clock Out", "Hours Worked", "Location",
      ]);
    });

  it("preserves the Phase-46.3 ``…-tech-punches-${uid}`` wrapper testid",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-mig"));
      await act(async () => { fireEvent.click(expandBtn); });
      await waitFor(() => expect(screen.getByTestId(
        "landscape-time-clock-admin-tech-punches-u-mig",
      )).toBeInTheDocument());
    });

  it("renders Total Hours footer using backend t.total_seconds",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-mig"));
      await act(async () => { fireEvent.click(expandBtn); });
      const footer = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-total-footer-u-mig"));
      // 65 940 seconds → 18:19 per fmtHoursMinutes
      expect(footer).toHaveTextContent(/Total Hours/i);
      expect(footer).toHaveTextContent("18:19");
    });

  it("orphan still-clocked-in row shows Clock Out `—`, Hours `—`, " +
      "and Location rendered as In-only (no Out line)",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-open"));
      await act(async () => { fireEvent.click(expandBtn); });
      const table = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-table-u-open"));
      const openRows = within(table).getAllByTestId(
        /landscape-time-clock-admin-tech-shift-row-u-open-/);
      expect(openRows).toHaveLength(1);
      expect(openRows[0].getAttribute("data-still-open")).toBe("true");
      const cells = within(openRows[0]).getAllByRole("cell");
      // cells: [Date][In][Out][Hours][Location]
      expect(cells[2].textContent).toBe("—");
      expect(cells[3].textContent).toBe("—");
      expect(cells[4].textContent).toMatch(/^In\s+33\.7000,-112\.1000$/);
      expect(cells[4].textContent).not.toMatch(/Out/);
    });

  it("Location column renders stacked In + Out lines with 4-decimal GPS",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-mig"));
      await act(async () => { fireEvent.click(expandBtn); });
      const table = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-table-u-mig"));
      // 1st shift row for u-mig (p1→p2): In 33.6123,-112.3812
      //                                   Out 33.6123,-112.3812
      const row = within(table).getByTestId(
        "landscape-time-clock-admin-tech-shift-row-u-mig-p1");
      const loc = within(row).getAllByRole("cell")[4];
      expect(loc.textContent).toContain("In");
      expect(loc.textContent).toContain("33.6123,-112.3812");
      expect(loc.textContent).toContain("Out");
    });

  it("multiple shifts on the same day: date label shown on first row " +
      "only, empty on subsequent same-day rows",
    async () => {
      _mockUser = { id: "u-admin", role: "admin" };
      getMock.mockImplementation(_mineBaseMock());
      _render();
      const expandBtn = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-expand-u-mig"));
      await act(async () => { fireEvent.click(expandBtn); });
      const table = await waitFor(() => screen.getByTestId(
        "landscape-time-clock-admin-tech-table-u-mig"));
      const dataRows = within(table).getAllByTestId(
        /landscape-time-clock-admin-tech-shift-row-u-mig-/);
      expect(dataRows).toHaveLength(4);
      const dateCell = (r) => within(r).getAllByRole("cell")[0].textContent;
      // 1st row of a day: non-empty
      expect(dateCell(dataRows[0]).trim()).not.toBe("");
      // 2nd row same day: empty
      expect(dateCell(dataRows[1]).trim()).toBe("");
      // 3rd row new day: non-empty
      expect(dateCell(dataRows[2]).trim()).not.toBe("");
      // 4th row same day: empty
      expect(dateCell(dataRows[3]).trim()).toBe("");
    });
});
