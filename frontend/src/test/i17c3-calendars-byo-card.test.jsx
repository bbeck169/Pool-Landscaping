/**
 * Phase I1.7.c.3 · Feb-2026 — Calendars BYO card vitest suite.
 *
 * Pins:
 *   1. Renders one Calendars card per provider (google, outlook).
 *   2. Cap-save PUT to /calendars_{provider} sends monthly_sync_op_cap.
 *   3. Connect button hits /oauth/start and follows the returned
 *      auth_url via window.location.assign.
 *   4. Per-tech Disconnect fires modal → POST /disconnect.
 *   5. Usage bar renders warn / blocked at the right statuses.
 *   6. Modal flow: opens on click, Confirm fires the disconnect,
 *      Cancel closes without any HTTP call.
 *   7. Post-callback bounce toast surfaces success + error paths
 *      (?calendar_connect=success|error).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: (...a) => mockPut(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...a) => mockToastSuccess(...a),
    { success: (...a) => mockToastSuccess(...a),
      error: (...a) => mockToastError(...a) },
  ),
}));

import TenantIntegrationsCard from "@/components/settings/TenantIntegrationsCard";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";


const renderCard = () => render(
  <ConfirmProvider>
    <TenantIntegrationsCard />
  </ConfirmProvider>,
);


const _CAL_SCHEMAS = [
  { provider_key: "calendars_google", kind: "calendars", models: [], fields: [
    { name: "monthly_sync_op_cap", required: false, secret: false,
      label: "Monthly sync-op cap (null=unlimited, 0=block-all)" },
    { name: "default_calendar_id", required: false, secret: false,
      label: "Default calendar ID (leave blank for 'primary')" },
  ]},
  { provider_key: "calendars_outlook", kind: "calendars", models: [], fields: [
    { name: "monthly_sync_op_cap", required: false, secret: false,
      label: "Monthly sync-op cap" },
    { name: "default_calendar_id", required: false, secret: false,
      label: "Default calendar ID" },
  ]},
];


const _TECHS = [
  { id: "tech-1", name: "Ada Lovelace",   email: "ada@example.com" },
  { id: "tech-2", name: "Grace Hopper",   email: "grace@example.com" },
];


const _mockRoutes = (calProviders = [], calLinks = [], techs = _TECHS,
                        initialSearch = "") => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17c3", integrations: [] };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: [], ai: [], maps: [], calendars: _CAL_SCHEMAS };
    if (path === "/tenants/me/integrations/ai/usage")
      return { providers: [] };
    if (path === "/tenants/me/integrations/maps/usage")
      return { providers: [] };
    if (path === "/tenants/me/integrations/calendars/usage")
      return { tenant_id: "tenant-i17c3", period_yyyymm: "202602",
                providers: calProviders, technicians: calLinks };
    if (path === "/users?role=tech")
      return techs;
    if (path === "/users") return techs;
    if (typeof path === "string" && path.startsWith(
        "/tenants/me/integrations/calendars_google/oauth/start")) {
      return {
        provider_key: "calendars_google",
        provider: "google",
        technician_user_id: "tech-1",
        auth_url: "https://accounts.google.com/o/oauth2/v2/auth?fake=1",
        state: "s.tok",
      };
    }
    if (typeof path === "string" && path.startsWith(
        "/tenants/me/integrations/calendars_outlook/oauth/start")) {
      return {
        provider_key: "calendars_outlook",
        provider: "outlook",
        technician_user_id: "tech-1",
        auth_url: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?fake=1",
        state: "s.tok2",
      };
    }
    return {};
  });
  // Replace window.location with a fresh assign spy AND the requested
  // ?calendar_connect=… search string so the root-level effect that
  // surfaces the OAuth-callback bounce can be exercised.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      ...window.location,
      assign: vi.fn(),
      pathname: "/settings/integrations",
      search: initialSearch,
      hash: "",
    },
  });
  // history.replaceState is called by the bounce-absorb effect.
  window.history.replaceState = vi.fn();
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPut.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.clear();
});


afterEach(() => { vi.restoreAllMocks(); });


describe("TenantIntegrationsCard · Calendars BYO cards (I1.7.c.3)", () => {
  const _asAdmin = () => window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "admin@example.com" }));

  it("renders one Calendars card per provider with the tech-picker + Connect button", async () => {
    _asAdmin();
    _mockRoutes();
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_google")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-calendars_outlook")).toBeTruthy();
    // Cap-input + Save + Connect exist per card.
    expect(screen.getByTestId("tenant-integration-calendars_google-cap-input")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-calendars_google-save")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-calendars_google-connect")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-calendars_google-tech-select")).toBeTruthy();
    // Default status pill: "No technicians connected".
    expect(
      screen.getByTestId("tenant-integration-calendars_google-status").textContent,
    ).toMatch(/no technicians connected/i);
  });

  it("Save cap sends PUT with monthly_sync_op_cap only (config is empty object)", async () => {
    _asAdmin();
    _mockRoutes();
    mockPut.mockResolvedValue({ saved: true });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_google-cap-input")).toBeTruthy(),
    );
    fireEvent.change(
      screen.getByTestId("tenant-integration-calendars_google-cap-input"),
      { target: { value: "750" } },
    );
    fireEvent.click(screen.getByTestId("tenant-integration-calendars_google-save"));
    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/tenants/me/integrations/calendars_google",
        { config: {}, monthly_sync_op_cap: 750 },
      ),
    );
  });

  it("empty cap value sends null (unlimited)", async () => {
    _asAdmin();
    _mockRoutes();
    mockPut.mockResolvedValue({ saved: true });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_outlook-save")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-calendars_outlook-save"));
    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/tenants/me/integrations/calendars_outlook",
        { config: {}, monthly_sync_op_cap: null },
      ),
    );
  });

  it("Connect button hits /oauth/start and calls window.location.assign", async () => {
    _asAdmin();
    _mockRoutes();
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_google-connect")).toBeTruthy(),
    );
    // Selected tech defaults to first — click Connect.
    fireEvent.click(screen.getByTestId("tenant-integration-calendars_google-connect"));
    await waitFor(() =>
      expect(window.location.assign).toHaveBeenCalledWith(
        "https://accounts.google.com/o/oauth2/v2/auth?fake=1",
      ),
    );
  });

  it("shows connected-technician list when links are present", async () => {
    _asAdmin();
    _mockRoutes(
      [{ provider: "google", period_yyyymm: "202602",
          push_event: 3, pull_delta: 4, total: 7,
          monthly_sync_op_cap: 100, connected_technicians: 1,
          pct_used: 0.07, status: "ok" }],
      [{ technician_user_id: "tech-1", technician_name: "Ada Lovelace",
          technician_email: "ada@example.com",
          provider_key: "calendars_google", provider: "google",
          connected: true, connected_email: "ada@google.com",
          calendar_id: "primary" }],
    );
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_google-technicians")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-calendars_google-tech-tech-1")).toBeTruthy();
    expect(
      screen.getByTestId("tenant-integration-calendars_google-tech-tech-1-disconnect"),
    ).toBeTruthy();
    // Status pill flips to "1 technician connected".
    expect(
      screen.getByTestId("tenant-integration-calendars_google-status").textContent,
    ).toMatch(/1 technician connected/i);
  });

  it("usage bar renders warn at status=warn", async () => {
    _asAdmin();
    _mockRoutes([{
      provider: "google", period_yyyymm: "202602",
      push_event: 80, pull_delta: 0, total: 80,
      monthly_sync_op_cap: 100, connected_technicians: 1,
      pct_used: 0.8, status: "warn",
    }]);
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_google-usage-warn")).toBeTruthy(),
    );
  });

  it("usage bar renders blocked at status=blocked", async () => {
    _asAdmin();
    _mockRoutes([{
      provider: "outlook", period_yyyymm: "202602",
      push_event: 100, pull_delta: 0, total: 100,
      monthly_sync_op_cap: 100, connected_technicians: 1,
      pct_used: 1.0, status: "blocked",
    }]);
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-calendars_outlook-usage-blocked")).toBeTruthy(),
    );
  });

  it("callback bounce `?calendar_connect=success` surfaces a toast + cleans the URL", async () => {
    _asAdmin();
    _mockRoutes([], [], _TECHS,
                    "?calendar_connect=success&provider=google&technician_user_id=tech-1");
    renderCard();
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/Calendar \(google\) connected/i),
      ),
    );
    expect(window.history.replaceState).toHaveBeenCalled();
  });

  it("callback bounce `?calendar_connect=error` surfaces an error toast with the reason", async () => {
    _asAdmin();
    _mockRoutes([], [], _TECHS,
                    "?calendar_connect=error&provider=outlook&error=state_expired");
    renderCard();
    await waitFor(() =>
      expect(mockToastError).toHaveBeenCalledWith(
        expect.stringMatching(/Calendar \(outlook\) connect failed: state_expired/i),
      ),
    );
  });

  // ── Modal · Task A parity ──────────────────────────────────
  describe("per-technician disconnect modal · Task A parity", () => {
    const _linksForOne = [{
      technician_user_id: "tech-1", technician_name: "Ada Lovelace",
      technician_email: "ada@example.com",
      provider_key: "calendars_google", provider: "google",
      connected: true, connected_email: "ada@google.com",
      calendar_id: "primary",
    }];

    it("opens the in-app modal on Disconnect click (no window.confirm)", async () => {
      _asAdmin();
      _mockRoutes([], _linksForOne);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId(
          "tenant-integration-calendars_google-tech-tech-1-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId(
        "tenant-integration-calendars_google-tech-tech-1-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy();
      expect(mockPost).not.toHaveBeenCalled();
    });

    it("Confirm fires POST /disconnect for that technician", async () => {
      _asAdmin();
      _mockRoutes([], _linksForOne);
      mockPost.mockResolvedValue({ removed: true, provider_key: "calendars_google" });
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId(
          "tenant-integration-calendars_google-tech-tech-1-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId(
        "tenant-integration-calendars_google-tech-tech-1-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-confirm"));
      await waitFor(() =>
        expect(mockPost).toHaveBeenCalledWith(
          "/tenants/me/integrations/calendars_google/disconnect",
          { technician_user_id: "tech-1" },
        ),
      );
    });

    it("Cancel closes the modal without firing POST", async () => {
      _asAdmin();
      _mockRoutes([], _linksForOne);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId(
          "tenant-integration-calendars_google-tech-tech-1-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId(
        "tenant-integration-calendars_google-tech-tech-1-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-cancel"));
      await waitFor(() =>
        expect(screen.queryByTestId("integrations-disconnect-confirm")).toBeNull(),
      );
      expect(mockPost).not.toHaveBeenCalled();
    });
  });
});
