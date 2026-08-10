/**
 * Phase 41.5c · Feb-2026 — Mobile Weather page render test.
 *
 * Boots ``app/weather.tsx`` with every native dep mocked. Covers:
 *   1. Admin loads tenant location, then risk-forecast + reschedule
 *      endpoints. All 5 forecast day cells render with rating.
 *   2. WeatherWidget is composed at the top (source-inspection —
 *      the widget itself has its own dedicated jest coverage; here
 *      we assert only that it is mounted).
 *   3. Pull-to-refresh triggers a fresh fetch of the risk endpoint
 *      and remounts the WeatherWidget.
 *   4. Zero poor days renders the "no reschedule needed" empty state.
 *   5. Risk endpoint failure surfaces a graceful fallback (no crash;
 *      empty grid message).
 *   6. Technician + customer are blocked by the role gate.
 */
import React from "react";
import { render, waitFor, act } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a) },
}));

let mockUser: any = { id: "u_admin", role: "admin", email: "a@ex.com" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

jest.mock("@/src/components/widgets", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    Header: ({ title }: { title: string }) =>
      ReactMock.createElement(RN.Text, { testID: "test-header" }, title),
  };
});

// Stub the existing weather widget — it has its own dedicated jest
// suite. We only need to assert it is mounted from the page.
jest.mock("@/src/components/weather/WeatherWidget", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    __esModule: true,
    default: () =>
      ReactMock.createElement(RN.View, { testID: "weather-widget-stub" }),
  };
});

// Return canned tenant coords so the risk fetch uses those.
const mockFetchLoc = jest.fn(async () => ({
  hq_lat: 33.5, hq_lng: -112.1, hq_address_formatted: "Test HQ",
}));
jest.mock("@/src/api/weather", () => ({
  fetchTenantLocation: (...a: any[]) => mockFetchLoc(...a),
}));

// eslint-disable-next-line import/first
import WeatherScreen from "@/app/weather";

const RISK_DAYS = [
  { date: "2026-02-14", high: 82, low: 55, precip: 10, wind_mph: 8,
    service_risk_rating: "good",  risk_reasons: [] },
  { date: "2026-02-15", high: 80, low: 54, precip: 30, wind_mph: 12,
    service_risk_rating: "fair",  risk_reasons: ["30% precip risk"] },
  { date: "2026-02-16", high: 68, low: 52, precip: 80, wind_mph: 26,
    service_risk_rating: "poor",  risk_reasons: ["80% precip risk", "26 mph winds"] },
  { date: "2026-02-17", high: 78, low: 56, precip: 15, wind_mph: 10,
    service_risk_rating: "good",  risk_reasons: [] },
  { date: "2026-02-18", high: 84, low: 60, precip: 5,  wind_mph: 7,
    service_risk_rating: "good",  risk_reasons: [] },
];

beforeEach(() => {
  mockApiGet.mockReset();
  mockFetchLoc.mockClear();
  mockUser = { id: "u_admin", role: "admin", email: "a@ex.com" };
});

describe("Phase 41.5c · mobile Weather page", () => {
  it("admin loads risk + reschedule using tenant HQ coordinates", async () => {
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })  // /weather/risk
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });  // /reschedule

    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() => expect(mockFetchLoc).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    // Risk endpoint carries the tenant coords + days=5.
    expect(mockApiGet.mock.calls[0][0])
      .toBe("/weather/risk?lat=33.5&lng=-112.1&days=5");
    expect(mockApiGet.mock.calls[1][0])
      .toBe("/weather/reschedule-recommendations");

    // WeatherWidget is mounted.
    expect(getByTestId("weather-widget-stub")).toBeTruthy();
    // Risk grid + all 5 day cells.
    await waitFor(() =>
      expect(getByTestId("weather-page-risk-grid")).toBeTruthy());
    for (const d of RISK_DAYS) {
      expect(getByTestId(`weather-page-risk-${d.date}`)).toBeTruthy();
      expect(getByTestId(`weather-page-risk-rating-${d.date}`)).toBeTruthy();
    }
  });

  it("falls back to the hardcoded coords when tenant location fetch fails", async () => {
    mockFetchLoc.mockRejectedValueOnce(new Error("no location"));
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });

    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(mockApiGet.mock.calls[0][0])
      .toBe("/weather/risk?lat=33.7897&lng=-112.3226&days=5");
    await waitFor(() =>
      expect(getByTestId("weather-page-risk-grid")).toBeTruthy());
  });

  it("pull-to-refresh triggers a fresh risk + reschedule fetch", async () => {
    mockApiGet.mockResolvedValue({ days: RISK_DAYS });
    mockApiGet.mockResolvedValueOnce({ days: RISK_DAYS })
              .mockResolvedValueOnce({ suggested: [], poor_days: [] })
              .mockResolvedValueOnce({ days: RISK_DAYS })
              .mockResolvedValueOnce({ suggested: [], poor_days: [] });

    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));

    const scroll = getByTestId("weather-page-scroll");
    const refreshControl = scroll.props.refreshControl;
    expect(refreshControl).toBeDefined();
    await act(async () => { refreshControl.props.onRefresh(); });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(4));
  });

  it("empty poor-days response renders the recs-empty state", async () => {
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });
    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() =>
      expect(getByTestId("weather-page-recs-empty")).toBeTruthy());
  });

  it("populated recommendations render a rec-row per suggested job", async () => {
    const suggested = [
      { id: "j1", title: "Weekly cleaning", customer_name: "Alice",
        scheduled_date: "2026-02-16", technician_name: "Bob" },
      { id: "j2", title: "Chemical check",  customer_name: "Carol",
        scheduled_date: "2026-02-16", technician_name: null },
    ];
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })
      .mockResolvedValueOnce({ suggested, poor_days: ["2026-02-16"] });
    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() =>
      expect(getByTestId("weather-page-recs-card")).toBeTruthy());
    expect(getByTestId("weather-page-rec-j1")).toBeTruthy();
    expect(getByTestId("weather-page-rec-j2")).toBeTruthy();
  });

  it("risk endpoint failure degrades gracefully to the empty grid state", async () => {
    mockApiGet
      .mockResolvedValueOnce({ days: [] })  // graceful catch inside load
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });
    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() =>
      expect(getByTestId("weather-page-risk-empty")).toBeTruthy());
  });

  it("technician is blocked by the role gate and no fetch runs", () => {
    mockUser = { id: "u_t", role: "technician", email: "t@ex.com" };
    const { getByTestId, queryByTestId } = render(<WeatherScreen />);
    expect(getByTestId("weather-page-role-gate")).toBeTruthy();
    expect(queryByTestId("weather-page")).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
    expect(mockFetchLoc).not.toHaveBeenCalled();
  });

  it("customer is blocked by the role gate too", () => {
    mockUser = { id: "u_c", role: "customer", email: "c@ex.com" };
    const { getByTestId } = render(<WeatherScreen />);
    expect(getByTestId("weather-page-role-gate")).toBeTruthy();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  // Phase 41.5c-fixup · Feb 2026 — role gate widened to include
  // ``manager`` so the drawer entry and the page gate agree.
  it("manager loads the page (widened per Phase 41.5c-fixup)", async () => {
    mockUser = { id: "u_m", role: "manager", email: "m@ex.com" };
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });
    const { getByTestId, queryByTestId } = render(<WeatherScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(getByTestId("weather-page")).toBeTruthy();
    expect(queryByTestId("weather-page-role-gate")).toBeNull();
  });

  it("super_admin loads the page", async () => {
    mockUser = { id: "u_sa", role: "super_admin", email: "s@ex.com" };
    mockApiGet
      .mockResolvedValueOnce({ days: RISK_DAYS })
      .mockResolvedValueOnce({ suggested: [], poor_days: [] });
    const { getByTestId } = render(<WeatherScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(getByTestId("weather-page")).toBeTruthy();
  });
});
