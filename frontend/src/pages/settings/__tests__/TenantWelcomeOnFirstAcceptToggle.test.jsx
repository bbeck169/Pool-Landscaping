/**
 * WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — vitest for the
 * ``TenantWelcomeOnFirstAcceptToggle`` admin settings toggle.
 *
 * Single case:
 *   • Renders with the backend-read value and flip POSTs the new
 *     value to ``/tenants/mine/settings``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    patch: (...a) => patchSpy(...a),
    post: vi.fn(),
  },
}));

beforeEach(() => {
  getSpy.mockReset();
  patchSpy.mockReset();
});

import { TenantWelcomeOnFirstAcceptToggle } from "@/pages/settings/NotificationPrefs";


describe("TenantWelcomeOnFirstAcceptToggle · WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE", () => {
  it("reads initial value from backend and flips to patch endpoint", async () => {
    getSpy.mockResolvedValue({
      welcome_email_on_first_accepted_quote_enabled: true,
    });
    patchSpy.mockResolvedValue({
      welcome_email_on_first_accepted_quote_enabled: false,
    });

    render(<TenantWelcomeOnFirstAcceptToggle />);

    await waitFor(() => {
      const btn = screen.getByTestId(
        "tenant-welcome-first-accept-toggle",
      );
      expect(btn.getAttribute("aria-checked")).toBe("true");
    });
    expect(getSpy).toHaveBeenCalledWith("/tenants/mine/settings");

    fireEvent.click(
      screen.getByTestId("tenant-welcome-first-accept-toggle"),
    );
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(patchSpy.mock.calls[0][0]).toBe("/tenants/mine/settings");
    expect(patchSpy.mock.calls[0][1]).toEqual({
      welcome_email_on_first_accepted_quote_enabled: false,
    });
  });
});
