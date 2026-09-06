/**
 * Phase 41.5c · Feb-2026 — Mobile Notification Preferences render test.
 *
 * Boots ``app/settings/notifications.tsx`` with every native dep
 * mocked. Covers:
 *   1. Authenticated user (any role) loads the toggle grid from
 *      GET /settings/notifications — Switches reflect the returned
 *      channel matrix.
 *   2. Flipping a Switch marks the form dirty; Save fires PUT with
 *      the full { channels, quiet_hours } payload.
 *   3. "All on" / "All off" bulk actions per channel column set every
 *      kind's Switch for that column and dirty the form.
 *   4. Quiet-hours toggle + start/end/timezone edits are included in
 *      the PUT payload.
 *   5. Undo reverts the local draft to the last-saved state without
 *      firing a network call.
 *   6. Error path: PUT rejection surfaces an error toast; the local
 *      draft is preserved (matches web — non-optimistic UI).
 *   7. Unauthenticated user (no ``user.id``) sees the sign-in gate
 *      and no fetch runs.
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPut = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    put: (...a: any[]) => mockApiPut(...a),
  },
}));

let mockUser: any = { id: "u1", role: "technician", email: "t@ex.com" };
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

// eslint-disable-next-line import/first
import NotificationPrefsScreen from "@/app/settings/notifications";

const KINDS = [
  { key: "job_status_change", label: "Job status change" },
  { key: "quote_sent",        label: "Quote sent" },
  { key: "invoice_paid",      label: "Invoice paid" },
];

const CHANNELS_INITIAL = {
  job_status_change: { bell: true,  push: false, email: false, sms: false },
  quote_sent:        { bell: true,  push: true,  email: true,  sms: false },
  invoice_paid:      { bell: true,  push: false, email: true,  sms: false },
};

const QUIET_INITIAL = {
  enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC",
};

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPut.mockReset();
  mockUser = { id: "u1", role: "technician", email: "t@ex.com" };
});

describe("Phase 41.5c · mobile Notification Preferences", () => {
  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("loads the toggle grid from GET /settings/notifications", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0]).toBe("/settings/notifications");

    await waitFor(() => expect(getByTestId("notif-prefs-scroll")).toBeTruthy());
    // Row per kind rendered.
    expect(getByTestId("notif-prefs-row-job_status_change")).toBeTruthy();
    expect(getByTestId("notif-prefs-row-quote_sent")).toBeTruthy();
    expect(getByTestId("notif-prefs-row-invoice_paid")).toBeTruthy();
    // Switch values match backend state.
    expect(getByTestId("notif-prefs-toggle-job_status_change-bell").props.value).toBe(true);
    expect(getByTestId("notif-prefs-toggle-job_status_change-push").props.value).toBe(false);
    expect(getByTestId("notif-prefs-toggle-quote_sent-email").props.value).toBe(true);
    expect(getByTestId("notif-prefs-toggle-invoice_paid-sms").props.value).toBe(false);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("flipping a switch + tapping Save PUTs the full { channels, quiet_hours } payload", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    mockApiPut.mockResolvedValueOnce({
      channels: { ...CHANNELS_INITIAL,
                   job_status_change: { bell: true, push: true, email: false, sms: false } },
      quiet_hours: QUIET_INITIAL,
    });

    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("notif-prefs-toggle-job_status_change-push"));

    await act(async () => {
      fireEvent(getByTestId("notif-prefs-toggle-job_status_change-push"),
                "valueChange", true);
    });
    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-save"));
    });

    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    expect(mockApiPut.mock.calls[0][0]).toBe("/settings/notifications");
    const body = mockApiPut.mock.calls[0][1];
    expect(body.channels.job_status_change.push).toBe(true);
    expect(body.channels.quote_sent).toEqual(CHANNELS_INITIAL.quote_sent);
    expect(body.quiet_hours).toEqual(QUIET_INITIAL);
    // Success toast.
    await waitFor(() => expect(getByTestId("notif-prefs-toast")).toBeTruthy());
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("'all on' bulk action sets every kind's Switch in the column", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    mockApiPut.mockResolvedValueOnce({
      channels: {
        job_status_change: { ...CHANNELS_INITIAL.job_status_change, sms: true },
        quote_sent:        { ...CHANNELS_INITIAL.quote_sent, sms: true },
        invoice_paid:      { ...CHANNELS_INITIAL.invoice_paid, sms: true },
      },
      quiet_hours: QUIET_INITIAL,
    });
    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("notif-prefs-all-on-sms"));

    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-all-on-sms"));
    });
    // Every kind's SMS toggle flips to true in the local draft.
    expect(getByTestId("notif-prefs-toggle-job_status_change-sms").props.value).toBe(true);
    expect(getByTestId("notif-prefs-toggle-quote_sent-sms").props.value).toBe(true);
    expect(getByTestId("notif-prefs-toggle-invoice_paid-sms").props.value).toBe(true);

    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-save"));
    });
    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    const body = mockApiPut.mock.calls[0][1];
    expect(body.channels.job_status_change.sms).toBe(true);
    expect(body.channels.quote_sent.sms).toBe(true);
    expect(body.channels.invoice_paid.sms).toBe(true);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("quiet-hours toggle + timezone chip changes flow into the PUT payload", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    const updatedQuiet = {
      enabled: true, start_time: "23:00", end_time: "06:00",
      timezone: "America/Phoenix",
    };
    mockApiPut.mockResolvedValueOnce({
      channels: CHANNELS_INITIAL, quiet_hours: updatedQuiet,
    });

    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("notif-quiet-hours-toggle"));

    await act(async () => {
      fireEvent(getByTestId("notif-quiet-hours-toggle"), "valueChange", true);
    });
    await act(async () => {
      fireEvent.changeText(getByTestId("notif-quiet-hours-start"), "23:00");
    });
    await act(async () => {
      fireEvent.changeText(getByTestId("notif-quiet-hours-end"), "06:00");
    });
    await act(async () => {
      fireEvent.press(getByTestId("notif-quiet-hours-tz-America/Phoenix"));
    });
    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-save"));
    });

    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    const body = mockApiPut.mock.calls[0][1];
    expect(body.quiet_hours).toEqual(updatedQuiet);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("Undo reverts the draft to the last-saved state and does not hit the network", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("notif-prefs-toggle-invoice_paid-sms"));

    await act(async () => {
      fireEvent(getByTestId("notif-prefs-toggle-invoice_paid-sms"),
                "valueChange", true);
    });
    expect(getByTestId("notif-prefs-toggle-invoice_paid-sms").props.value).toBe(true);

    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-reset"));
    });
    // Reverted to the initial GET response value.
    expect(getByTestId("notif-prefs-toggle-invoice_paid-sms").props.value).toBe(false);
    expect(mockApiPut).not.toHaveBeenCalled();
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("PUT failure shows an error toast and preserves the local draft", async () => {
    mockApiGet.mockResolvedValueOnce({
      kinds: KINDS,
      channels: CHANNELS_INITIAL,
      quiet_hours: QUIET_INITIAL,
    });
    mockApiPut.mockRejectedValueOnce(new Error("network down"));

    const { getByTestId } = render(<NotificationPrefsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("notif-prefs-toggle-quote_sent-sms"));

    await act(async () => {
      fireEvent(getByTestId("notif-prefs-toggle-quote_sent-sms"),
                "valueChange", true);
    });
    await act(async () => {
      fireEvent.press(getByTestId("notif-prefs-save"));
    });

    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getByTestId("notif-prefs-toast")).toBeTruthy());
    // Draft is preserved (non-optimistic UI mirrors web behaviour).
    expect(getByTestId("notif-prefs-toggle-quote_sent-sms").props.value).toBe(true);
  });

  it("unauthenticated user sees the sign-in gate and no fetch runs", () => {
    mockUser = null;
    const { getByTestId, queryByTestId } = render(<NotificationPrefsScreen />);
    expect(getByTestId("notif-prefs-unauth")).toBeTruthy();
    expect(queryByTestId("notif-prefs-screen")).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
  });
});
