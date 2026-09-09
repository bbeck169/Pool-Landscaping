/**
 * Feb-2026 · Phase B — tenant decline-notification toggle Vitest.
 *
 * Covers:
 *   * Renders as ON when the tenant settings GET returns
 *     ``notify_admin_on_decline: true`` (or omits the field).
 *   * Renders as OFF when the tenant settings GET returns
 *     ``notify_admin_on_decline: false``.
 *   * Click flips the switch, PATCHes ``/tenants/mine/settings``
 *     with the new boolean, and surfaces a "Saved" toast.
 *   * A PATCH failure rolls the optimistic flip back and shows
 *     the server error.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";


vi.mock("@/api", () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));

import { api } from "@/api";
import { TenantDeclineNotifyToggle } from "@/pages/settings/NotificationPrefs";


beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
});


describe("Phase B · TenantDeclineNotifyToggle", () => {
  it("renders as ON by default when field is undefined", async () => {
    api.get.mockResolvedValue({ id: "t1" });  // no ``notify_admin_on_decline``
    render(<TenantDeclineNotifyToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-decline-notify-toggle"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));
    cleanup();
  });

  it("renders as OFF when tenant has notify_admin_on_decline=false", async () => {
    api.get.mockResolvedValue({ id: "t1", notify_admin_on_decline: false });
    render(<TenantDeclineNotifyToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-decline-notify-toggle"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("false"));
    cleanup();
  });

  it("click PATCHes /tenants/mine/settings with the new boolean", async () => {
    api.get.mockResolvedValue({ id: "t1", notify_admin_on_decline: true });
    api.patch.mockResolvedValue({ id: "t1", notify_admin_on_decline: false });
    render(<TenantDeclineNotifyToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-decline-notify-toggle"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(sw);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/tenants/mine/settings",
        { notify_admin_on_decline: false },
      );
    });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    // "Saved" toast surfaces briefly.
    await waitFor(() =>
      expect(screen.getByTestId("tenant-decline-notify-toast").textContent)
        .toMatch(/Saved/i),
    );
    cleanup();
  });

  it("PATCH failure rolls the optimistic flip back", async () => {
    api.get.mockResolvedValue({ id: "t1", notify_admin_on_decline: true });
    api.patch.mockRejectedValue(new Error("boom"));
    render(<TenantDeclineNotifyToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-decline-notify-toggle"),
    );
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));

    fireEvent.click(sw);
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    // After failure, the switch reverts to its previous state.
    await waitFor(() => expect(sw.getAttribute("aria-checked")).toBe("true"));
    // Error toast is surfaced.
    await waitFor(() =>
      expect(screen.getByTestId("tenant-decline-notify-toast").textContent)
        .toMatch(/boom|failed/i),
    );
    cleanup();
  });
});
