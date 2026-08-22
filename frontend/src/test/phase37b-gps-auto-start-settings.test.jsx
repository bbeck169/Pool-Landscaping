/**
 * Feb-2026 · P37b — GpsAutoStartPage settings surface.
 *
 * Pins:
 *   1. Renders form with defaults after mocked GET.
 *   2. PATCH shape uses ``gps_auto_start_enabled`` + ``arrival_radius_meters``
 *      (matches the openapi contract — NOT the shortened ``enabled`` field).
 *   3. 400 invalid_radius surfaces an inline error.
 *   4. Helper copy + "Enable GPS auto-start" toggle both present.
 *   5. Radius wrapper greys out when disabled (matches QuietHoursPage UX).
 *
 * RBAC is enforced at the App.js route wrapper, exercised via a
 * separate wrapper test.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
const mockPatch = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a), patch: (...a) => mockPatch(...a) },
}));

import GpsAutoStartPage from "@/pages/settings/GpsAutoStartPage";


const _seed = (over = {}) => ({
  gps_auto_start_enabled: false, arrival_radius_meters: 75, ...over,
});


beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
});


describe("GpsAutoStartPage · P37b", () => {
  it("renders form with defaults after mocked GET", async () => {
    mockGet.mockResolvedValue(_seed({ gps_auto_start_enabled: true,
                                          arrival_radius_meters: 120 }));
    render(<GpsAutoStartPage />);
    await waitFor(() => expect(screen.getByTestId("gps-auto-start-page"))
      .toBeTruthy());
    expect(screen.getByTestId("gps-auto-start-enabled-toggle").checked)
      .toBe(true);
    expect(Number(screen.getByTestId("gps-auto-start-radius-input").value))
      .toBe(120);
    expect(mockGet).toHaveBeenCalledWith("/settings/gps-auto-start");
    // Helper copy present.
    expect(screen.getByTestId("gps-auto-start-helper").textContent)
      .toMatch(/arrival radius/i);
    // Toggle label present.
    expect(screen.getByText(/Enable GPS auto-start/i)).toBeTruthy();
  });

  it("PATCH body uses gps_auto_start_enabled + arrival_radius_meters", async () => {
    mockGet.mockResolvedValue(_seed());
    mockPatch.mockResolvedValue(_seed({ gps_auto_start_enabled: true,
                                            arrival_radius_meters: 150 }));
    render(<GpsAutoStartPage />);
    await waitFor(() => expect(screen.getByTestId("gps-auto-start-page"))
      .toBeTruthy());

    fireEvent.click(screen.getByTestId("gps-auto-start-enabled-toggle"));
    fireEvent.change(screen.getByTestId("gps-auto-start-radius-input"),
      { target: { value: "150" } });
    fireEvent.click(screen.getByTestId("gps-auto-start-save"));

    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
    const [path, body] = mockPatch.mock.calls[0];
    expect(path).toBe("/settings/gps-auto-start");
    expect(body).toEqual({
      gps_auto_start_enabled: true,
      arrival_radius_meters: 150,
    });
    await waitFor(() => expect(screen.getByTestId("gps-auto-start-ok"))
      .toBeTruthy());
  });

  it("surfaces the 400 invalid_radius message inline", async () => {
    mockGet.mockResolvedValue(_seed());
    mockPatch.mockRejectedValue({
      body: { detail: { detail: "invalid_radius",
                            message: "arrival_radius_meters must be between 10 and 5000." } },
      message: "Bad request",
    });
    render(<GpsAutoStartPage />);
    await waitFor(() => expect(screen.getByTestId("gps-auto-start-page"))
      .toBeTruthy());
    fireEvent.change(screen.getByTestId("gps-auto-start-radius-input"),
      { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("gps-auto-start-save"));
    const errBox = await waitFor(() => screen.getByTestId("gps-auto-start-error"));
    expect(errBox.textContent).toMatch(/between 10 and 5000/);
  });

  it("radius wrapper greys out when disabled", async () => {
    mockGet.mockResolvedValue(_seed({ gps_auto_start_enabled: false }));
    render(<GpsAutoStartPage />);
    await waitFor(() => expect(screen.getByTestId("gps-auto-start-page"))
      .toBeTruthy());
    const wrap = screen.getByTestId("gps-auto-start-radius-wrap");
    expect(wrap.style.opacity).toBe("0.6");
  });
});
