/**
 * Phase K9 · Feb-2026 — NotificationPrefs "Portal chat SMS notifications" card.
 *
 * Contract:
 *   1. Card renders with an E.164 input bound to
 *      ``tenant.admin_sms_notify_to`` returned from
 *      ``GET /tenants/current``.
 *   2. Save button PATCHes ``/tenants/{tid}`` with the new value.
 *   3. Client-side E.164 validation surfaces an inline error and
 *      disables the Save button on invalid entries.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy, putSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
  putSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    patch: (...a) => patchSpy(...a),
    put: (...a) => putSpy(...a),
    post: (...a) => postSpy(...a),
  },
  TOKEN_KEY: "access_token",
}));

vi.mock("@/components/comms/CommsWhitelistBanner", () => ({
  default: () => null,
}));

// react-router-dom's useNavigate is used by the outer component.
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

beforeEach(() => {
  getSpy.mockReset();
  patchSpy.mockReset();
  putSpy.mockReset();
  postSpy.mockReset();
  // /settings/notifications payload is required by the outer component
  // but the K9 card doesn't consume any of it.
  getSpy.mockImplementation((path) => {
    if (path === "/settings/notifications") {
      return Promise.resolve({
        kinds: [], channels: {}, quiet_hours: {
          enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC",
        },
      });
    }
    if (path === "/tenants/current") {
      return Promise.resolve({ id: "tenant-k9",
                                admin_sms_notify_to: "+16028874400" });
    }
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());

import NotificationPrefs from "@/pages/settings/NotificationPrefs";

describe("NotificationPrefs · K9 portal chat SMS card", () => {
  it("prefills from GET /tenants/current and PATCHes on save", async () => {
    render(<NotificationPrefs />);
    // Card renders.
    await waitFor(() =>
      expect(screen.getByTestId("k9-portal-sms-card")).toBeInTheDocument(),
    );
    const input = screen.getByTestId("k9-portal-sms-input");
    // Prefilled from /tenants/current.
    await waitFor(() => expect(input.value).toBe("+16028874400"));
    // Change the value.
    fireEvent.change(input, { target: { value: "+14805551234" } });
    // Save button becomes enabled.
    const saveBtn = screen.getByTestId("k9-portal-sms-save");
    patchSpy.mockResolvedValueOnce({ admin_sms_notify_to: "+14805551234" });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [path, body] = patchSpy.mock.calls[0];
    expect(path).toBe("/tenants/tenant-k9");
    expect(body).toEqual({ admin_sms_notify_to: "+14805551234" });
    // Toast confirms save.
    await waitFor(() =>
      expect(screen.getByTestId("k9-portal-sms-toast")).toBeInTheDocument(),
    );
  });

  it("surfaces an inline error and disables Save on invalid E.164", async () => {
    render(<NotificationPrefs />);
    await waitFor(() =>
      expect(screen.getByTestId("k9-portal-sms-card")).toBeInTheDocument(),
    );
    const input = screen.getByTestId("k9-portal-sms-input");
    await waitFor(() => expect(input.value).toBe("+16028874400"));
    fireEvent.change(input, { target: { value: "6028874400" } });    // no +
    await waitFor(() =>
      expect(screen.getByTestId("k9-portal-sms-invalid")).toBeInTheDocument(),
    );
    const saveBtn = screen.getByTestId("k9-portal-sms-save");
    expect(saveBtn).toBeDisabled();
    // PATCH should not fire.
    expect(patchSpy).not.toHaveBeenCalled();
  });

  it("PATCHes null when cleared to allow un-setting the phone", async () => {
    render(<NotificationPrefs />);
    await waitFor(() =>
      expect(screen.getByTestId("k9-portal-sms-card")).toBeInTheDocument(),
    );
    const input = screen.getByTestId("k9-portal-sms-input");
    await waitFor(() => expect(input.value).toBe("+16028874400"));
    fireEvent.change(input, { target: { value: "" } });
    const saveBtn = screen.getByTestId("k9-portal-sms-save");
    patchSpy.mockResolvedValueOnce({ admin_sms_notify_to: null });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [, body] = patchSpy.mock.calls[0];
    expect(body).toEqual({ admin_sms_notify_to: null });
  });
});
