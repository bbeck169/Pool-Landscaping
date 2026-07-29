/**
 * G0 · Feb-2026 — GPS settings admin page vitest.
 *
 * Covers:
 *   1. Non-admin → forbidden panel.
 *   2. HR-ack drives the Enable toggle disabled/enabled state.
 *   3. Save fires PUT with only the diffed subset of fields.
 *   4. 422 hr_agreement_required renders friendly inline error.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const putMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a), put: (...a) => putMock(...a) },
}));

const authState = { user: { role: "admin" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#eee", muted: "#666",
    onSurface: "#000", onSurfaceSecondary: "#666",
  },
}));

import GpsSettingsPage from "@/pages/admin/GpsSettingsPage";

const DEFAULT_ROW = {
  id: "row-1",
  tenant_id: "t1",
  enabled: false,
  hr_agreement_ack: false,
  ping_interval_foreground_s: 60,
  ping_interval_background_s: 300,
  retention_days: 90,
  geocoder: "mapbox",
};

const renderPage = () =>
  render(<MemoryRouter><GpsSettingsPage /></MemoryRouter>);

beforeEach(() => {
  getMock.mockReset(); putMock.mockReset();
  authState.user = { role: "admin" };
});
afterEach(() => cleanup());


describe("GpsSettingsPage", () => {
  it("non-admin sees the forbidden panel", () => {
    authState.user = { role: "technician" };
    renderPage();
    expect(screen.getByTestId("gps-settings-forbidden"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("gps-settings-page"))
      .not.toBeInTheDocument();
  });

  it("Enable toggle is disabled while HR ack is unchecked", async () => {
    getMock.mockResolvedValueOnce({ ...DEFAULT_ROW });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("gps-settings-page")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("gps-settings-enable")).toBeDisabled();
    // Ticking HR ack should enable it.
    fireEvent.click(screen.getByTestId("gps-settings-hr-ack"));
    await waitFor(() =>
      expect(screen.getByTestId("gps-settings-enable")).not.toBeDisabled(),
    );
  });

  it("Save PUTs only the diffed subset of fields", async () => {
    getMock.mockResolvedValueOnce({ ...DEFAULT_ROW });
    putMock.mockResolvedValueOnce({
      ...DEFAULT_ROW, hr_agreement_ack: true, enabled: true,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("gps-settings-page")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("gps-settings-hr-ack"));
    fireEvent.click(screen.getByTestId("gps-settings-enable"));
    fireEvent.click(screen.getByTestId("gps-settings-save"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const [path, payload] = putMock.mock.calls[0];
    expect(path).toBe("/admin/gps/settings");
    // Only the two diffed fields go up — untouched fields stay out.
    expect(payload).toEqual({ hr_agreement_ack: true, enabled: true });
    // Retention / interval / geocoder must NOT be sent.
    expect(payload).not.toHaveProperty("ping_interval_foreground_s");
    expect(payload).not.toHaveProperty("retention_days");
  });

  it("422 hr_agreement_required renders friendly inline error", async () => {
    getMock.mockResolvedValueOnce({ ...DEFAULT_ROW });
    const err = new Error("hr_agreement_required");
    err.status = 422;
    putMock.mockRejectedValueOnce(err);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("gps-settings-page")).toBeInTheDocument(),
    );
    // Untick guard — flip enable directly (can't because it's disabled),
    // but we can force diff by tweaking retention which is always allowed.
    fireEvent.change(screen.getByTestId("gps-settings-retention"),
                      { target: { value: "45" } });
    // Also directly tick then untick ack so we have a diff without
    // enable — but we want to trigger a 422 branch here; the friendlier
    // path is to click hr-ack ON, click enable ON, then untick hr-ack.
    fireEvent.click(screen.getByTestId("gps-settings-hr-ack"));
    fireEvent.click(screen.getByTestId("gps-settings-enable"));
    fireEvent.click(screen.getByTestId("gps-settings-hr-ack")); // ack back OFF
    fireEvent.click(screen.getByTestId("gps-settings-save"));
    await waitFor(() =>
      expect(screen.getByTestId("gps-settings-error").textContent)
        .toMatch(/tick the HR agreement box/i),
    );
  });
});
