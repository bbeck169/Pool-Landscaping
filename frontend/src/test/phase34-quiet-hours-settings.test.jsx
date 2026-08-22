/**
 * Feb-2026 · P34 — QuietHoursPage settings surface.
 *
 * Pins:
 *   1. Renders the enabled toggle + time inputs + save button after
 *      loading the current config from GET /api/settings/quiet-hours.
 *   2. Save PATCHes /api/settings/quiet-hours with the current form
 *      body.
 *   3. 400 (bad start) surfaces a visible error message.
 *   4. Toggling the enabled checkbox flips the payload sent on save.
 *   5. Disabled state greys out the time inputs (still interactable
 *      per UX decision, but visually greyed).
 *
 * RBAC is enforced at the ``App.js`` route wrapper, so this suite
 * assumes the user already passed the gate.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
const mockPatch = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a), patch: (...a) => mockPatch(...a) },
}));

import QuietHoursPage from "@/pages/settings/QuietHoursPage";


const _seed = (over = {}) => ({
  enabled: false, start: "08:00", end: "20:00",
  timezone: "America/Phoenix", tenant_timezone: "America/Phoenix",
  ...over,
});


beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
});


describe("QuietHoursPage · P34", () => {
  it("renders the current config from GET /settings/quiet-hours", async () => {
    mockGet.mockResolvedValue(_seed({ enabled: true, start: "09:00", end: "21:00" }));
    render(<QuietHoursPage />);
    await waitFor(() => expect(screen.getByTestId("quiet-hours-page")).toBeTruthy());
    expect(screen.getByTestId("quiet-hours-enabled-toggle").checked).toBe(true);
    expect(screen.getByTestId("quiet-hours-start-input").value).toBe("09:00");
    expect(screen.getByTestId("quiet-hours-end-input").value).toBe("21:00");
    expect(mockGet).toHaveBeenCalledWith("/settings/quiet-hours");
  });

  it("PATCHes with the current body on Save", async () => {
    mockGet.mockResolvedValue(_seed());
    mockPatch.mockResolvedValue(_seed({ enabled: true }));
    render(<QuietHoursPage />);
    await waitFor(() => expect(screen.getByTestId("quiet-hours-page")).toBeTruthy());

    fireEvent.click(screen.getByTestId("quiet-hours-enabled-toggle"));
    fireEvent.change(screen.getByTestId("quiet-hours-start-input"),
      { target: { value: "09:00" } });
    fireEvent.change(screen.getByTestId("quiet-hours-end-input"),
      { target: { value: "21:00" } });
    fireEvent.click(screen.getByTestId("quiet-hours-save"));

    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
    const [path, body] = mockPatch.mock.calls[0];
    expect(path).toBe("/settings/quiet-hours");
    expect(body).toMatchObject({ enabled: true, start: "09:00", end: "21:00" });

    // Green-status pill appears.
    await waitFor(() => expect(screen.getByTestId("quiet-hours-ok")).toBeTruthy());
  });

  it("surfaces a 400 error message when save fails", async () => {
    mockGet.mockResolvedValue(_seed());
    mockPatch.mockRejectedValue({
      body: { detail: { message: "start must be HH:MM 24-hour format" } },
      message: "Bad request",
    });
    render(<QuietHoursPage />);
    await waitFor(() => expect(screen.getByTestId("quiet-hours-page")).toBeTruthy());
    fireEvent.click(screen.getByTestId("quiet-hours-save"));
    const errBox = await waitFor(() => screen.getByTestId("quiet-hours-error"));
    expect(errBox.textContent).toMatch(/HH:MM/);
  });

  it("time inputs are visually greyed when quiet hours are disabled", async () => {
    mockGet.mockResolvedValue(_seed({ enabled: false }));
    render(<QuietHoursPage />);
    await waitFor(() => expect(screen.getByTestId("quiet-hours-page")).toBeTruthy());
    const wrap = screen.getByTestId("quiet-hours-time-inputs");
    // Inline style tag captures the opacity because we set it via ``style``.
    expect(wrap.style.opacity).toBe("0.6");
  });

  it("toggling enabled then saving sends enabled=true to the server", async () => {
    mockGet.mockResolvedValue(_seed({ enabled: false }));
    mockPatch.mockResolvedValue(_seed({ enabled: true }));
    render(<QuietHoursPage />);
    await waitFor(() => expect(screen.getByTestId("quiet-hours-page")).toBeTruthy());
    fireEvent.click(screen.getByTestId("quiet-hours-enabled-toggle"));
    fireEvent.click(screen.getByTestId("quiet-hours-save"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
    const body = mockPatch.mock.calls[0][1];
    expect(body.enabled).toBe(true);
  });
});
