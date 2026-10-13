/**
 * P2 #10e · Feb-2026 — NotificationPrefs 4 automation-toggle rows
 * + "Customize templates →" link.
 *
 * Covers:
 *   1. All 4 toggle rows render with the right testids, initial
 *      state driven by GET /tenants/mine/settings.
 *   2. Flipping a toggle calls PATCH /tenants/mine/settings with
 *      exactly ``{ [flagKey]: !previous }`` — one atomic payload
 *      per flip.
 *   3. The "Customize templates →" link navigates to
 *      ``/settings/notifications/templates``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";


vi.mock("@/api", () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));


const navMock = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navMock,
}));


import { api } from "@/api";
import { TenantAutomationTogglesSection } from "@/pages/settings/NotificationPrefs";


const _FLAG_TESTIDS = [
  { key: "lead_conversion_welcome_enabled",   suffix: "lead-conversion-welcome-enabled" },
  { key: "completion_followup_sms_enabled",   suffix: "completion-followup-sms-enabled" },
  { key: "invoice_past_due_enabled",          suffix: "invoice-past-due-enabled" },
  { key: "estimate_reminder_enabled",         suffix: "estimate-reminder-enabled" },
];


beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  navMock.mockReset();
});


describe("P2 #10e · TenantAutomationTogglesSection", () => {
  it("Case 1 — all 4 rows render with correct testids and initial state from GET", async () => {
    api.get.mockResolvedValue({
      id: "t1",
      lead_conversion_welcome_enabled: true,
      completion_followup_sms_enabled: false,
      invoice_past_due_enabled: true,
      estimate_reminder_enabled: false,
    });
    render(<TenantAutomationTogglesSection />);
    for (const { suffix } of _FLAG_TESTIDS) {
      const sw = await waitFor(
        () => screen.getByTestId(`tenant-toggle-${suffix}`),
      );
      expect(sw).toBeTruthy();
      // row wrapper also present
      expect(screen.getByTestId(`tenant-toggle-${suffix}-row`)).toBeTruthy();
    }
    // Initial aria-checked matches GET payload.
    await waitFor(() => {
      expect(
        screen.getByTestId("tenant-toggle-lead-conversion-welcome-enabled")
              .getAttribute("aria-checked"),
      ).toBe("true");
      expect(
        screen.getByTestId("tenant-toggle-completion-followup-sms-enabled")
              .getAttribute("aria-checked"),
      ).toBe("false");
      expect(
        screen.getByTestId("tenant-toggle-invoice-past-due-enabled")
              .getAttribute("aria-checked"),
      ).toBe("true");
      expect(
        screen.getByTestId("tenant-toggle-estimate-reminder-enabled")
              .getAttribute("aria-checked"),
      ).toBe("false");
    });
    cleanup();
  });

  it("Case 2 — unset flags default to ON (opt-out posture)", async () => {
    api.get.mockResolvedValue({ id: "t1" });  // no flags set
    render(<TenantAutomationTogglesSection />);
    for (const { suffix } of _FLAG_TESTIDS) {
      const sw = await waitFor(
        () => screen.getByTestId(`tenant-toggle-${suffix}`),
      );
      await waitFor(
        () => expect(sw.getAttribute("aria-checked")).toBe("true"),
      );
    }
    cleanup();
  });

  it("Case 3 — flip calls PATCH /tenants/mine/settings with the right flag key", async () => {
    api.get.mockResolvedValue({
      id: "t1",
      invoice_past_due_enabled: true,
    });
    api.patch.mockResolvedValue({
      id: "t1",
      invoice_past_due_enabled: false,
    });
    render(<TenantAutomationTogglesSection />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-toggle-invoice-past-due-enabled"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(sw);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/tenants/mine/settings",
        { invoice_past_due_enabled: false },
      );
    });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    await waitFor(() =>
      expect(
        screen.getByTestId("tenant-toggle-invoice-past-due-enabled-toast")
              .textContent,
      ).toMatch(/Saved/i),
    );
    cleanup();
  });

  it("Case 4 — flipping one toggle does NOT PATCH the other 3 flags", async () => {
    api.get.mockResolvedValue({ id: "t1" });  // all unset, default on
    api.patch.mockResolvedValue({
      id: "t1",
      estimate_reminder_enabled: false,
    });
    render(<TenantAutomationTogglesSection />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-toggle-estimate-reminder-enabled"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(sw);

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    // Exactly ONE PATCH, exactly ONE key in the body.
    const [[, body]] = api.patch.mock.calls;
    expect(Object.keys(body)).toEqual(["estimate_reminder_enabled"]);
    expect(body.estimate_reminder_enabled).toBe(false);
    cleanup();
  });

  it("Case 5 — PATCH failure rolls the optimistic flip back", async () => {
    api.get.mockResolvedValue({
      id: "t1",
      completion_followup_sms_enabled: true,
    });
    api.patch.mockRejectedValue(new Error("boom"));
    render(<TenantAutomationTogglesSection />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-toggle-completion-followup-sms-enabled"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(sw);
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    // After failure, the switch reverts.
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));
    await waitFor(() =>
      expect(
        screen.getByTestId("tenant-toggle-completion-followup-sms-enabled-toast")
              .textContent,
      ).toMatch(/boom|failed/i),
    );
    cleanup();
  });

  it("Case 6 — Customize templates link navigates to /settings/notifications/templates", async () => {
    api.get.mockResolvedValue({ id: "t1" });
    render(<TenantAutomationTogglesSection />);
    const link = await waitFor(
      () => screen.getByTestId("tenant-automation-customize-templates-link"),
    );
    fireEvent.click(link);
    expect(navMock).toHaveBeenCalledWith("/settings/notifications/templates");
    cleanup();
  });
});
