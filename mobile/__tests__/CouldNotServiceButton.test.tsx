/**
 * Could Not Service — Mobile Jest tests (Phase 1 mobile parity).
 *
 * Covers:
 *   1. Button hidden for terminal statuses; visible otherwise.
 *   2. Role gate — hidden for customer.
 *   3. Modal opens on button tap; reasons list fetched on open.
 *   4. Submit disabled until reason + (notes if key=other) + ≥1 photo,
 *      then enabled and POSTs the correct body shape.
 *   5. Success + guard-hit toast rendering (Alert.alert).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

/* ── Mocks ─────────────────────────────────────────────────────────── */

const mockApiGet = jest.fn();
const mockApiPost = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    put: jest.fn(),
    del: jest.fn(),
    delete: jest.fn(),
  },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

// Stub FileUpload so we don't touch expo-image-picker in jest.
// Simulate an "uploaded" photo by exposing a testID button that
// invokes onUploaded with a fake FileRecord.
jest.mock("@/src/components/files/FileUpload", () => {
  const React = require("react");
  const { Pressable, Text } = require("react-native");
  return {
    FileUpload: ({ onUploaded }: any) => (
      React.createElement(
        Pressable,
        {
          testID: "cns-fake-upload-btn",
          onPress: () => onUploaded?.({ id: "file-1", content_type: "image/jpeg" }),
        },
        React.createElement(Text, {}, "fake upload"),
      )
    ),
    default: null,
  };
});

jest.spyOn(Alert, "alert");

import CouldNotServiceButton from "@/src/components/schedule/CouldNotServiceButton";

/* ── Helpers ───────────────────────────────────────────────────────── */

const REASONS_FIXTURE = {
  reasons: [
    { id: "r-locked", key: "locked_out",   label: "Locked out",         sort_order: 0, is_default: true, active: true },
    { id: "r-weath",  key: "weather",      label: "Weather",            sort_order: 3, is_default: true, active: true },
    { id: "r-other",  key: "other",        label: "Other",              sort_order: 6, is_default: true, active: true },
  ],
};

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockResolvedValue(REASONS_FIXTURE);
});

/* ── Tests ─────────────────────────────────────────────────────────── */

describe("CouldNotServiceButton — visibility gates", () => {

  test("hidden for customer role", () => {
    const { queryByTestId } = render(
      <CouldNotServiceButton jobId="j1" jobStatus="scheduled" role="customer" testID="cns-vis" />,
    );
    expect(queryByTestId("cns-vis")).toBeNull();
  });

  test("hidden for terminal status: completed", () => {
    const { queryByTestId } = render(
      <CouldNotServiceButton jobId="j1" jobStatus="completed" role="technician" testID="cns-vis" />,
    );
    expect(queryByTestId("cns-vis")).toBeNull();
  });

  test("hidden for terminal status: could_not_service", () => {
    const { queryByTestId } = render(
      <CouldNotServiceButton jobId="j1" jobStatus="could_not_service" role="technician" testID="cns-vis" />,
    );
    expect(queryByTestId("cns-vis")).toBeNull();
  });

  test("hidden for terminal status: canceled + cancelled + skipped", () => {
    for (const status of ["canceled", "cancelled", "skipped"]) {
      const { queryByTestId } = render(
        <CouldNotServiceButton jobId="j1" jobStatus={status} role="technician" testID={`cns-${status}`} />,
      );
      expect(queryByTestId(`cns-${status}`)).toBeNull();
    }
  });

  test("visible for technician on scheduled job", () => {
    const { getByTestId } = render(
      <CouldNotServiceButton jobId="j1" jobStatus="scheduled" role="technician" testID="cns-vis" />,
    );
    expect(getByTestId("cns-vis")).toBeTruthy();
  });

  test("visible for admin, manager, super_admin", () => {
    for (const role of ["admin", "manager", "super_admin"]) {
      const { getByTestId } = render(
        <CouldNotServiceButton jobId="j1" jobStatus="pending" role={role} testID={`cns-${role}`} />,
      );
      expect(getByTestId(`cns-${role}`)).toBeTruthy();
    }
  });
});


describe("CouldNotServiceButton — modal + submit", () => {

  test("opens modal on tap and fetches reasons", async () => {
    const { getByTestId } = render(
      <CouldNotServiceButton jobId="j1" jobStatus="scheduled" role="technician" testID="cns-open" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("cns-open"));
    });

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith("/settings/job-outcome-reasons");
      expect(getByTestId("could-not-service-modal")).toBeTruthy();
      expect(getByTestId("cns-reason-locked_out")).toBeTruthy();
      expect(getByTestId("cns-reason-other")).toBeTruthy();
    });
  });

  test("submit disabled until reason + photo (and notes if key=other) — then POST body", async () => {
    mockApiPost.mockResolvedValueOnce({
      status: "could_not_service",
      sms_result: { sent: true, reason: null },
    });

    const { getByTestId } = render(
      <CouldNotServiceButton jobId="job-42" jobStatus="scheduled" role="technician" testID="cns-flow" />,
    );

    await act(async () => { fireEvent.press(getByTestId("cns-flow")); });
    await waitFor(() => expect(getByTestId("could-not-service-modal")).toBeTruthy());

    const submitBtn = getByTestId("cns-submit");

    // Initially disabled — no reason, no photo.
    expect(submitBtn.props.accessibilityState?.disabled ?? submitBtn.props.disabled).toBeTruthy();

    // Pick "Other" — notes now required.
    await act(async () => { fireEvent.press(getByTestId("cns-reason-other")); });

    // Fake-upload a photo (satisfies ≥1 photo).
    await act(async () => { fireEvent.press(getByTestId("cns-fake-upload-btn")); });

    // Still disabled — notes required because key=other.
    expect(submitBtn.props.accessibilityState?.disabled ?? submitBtn.props.disabled).toBeTruthy();

    // Enter notes → enabled.
    await act(async () => {
      fireEvent.changeText(getByTestId("cns-notes"), "Broken pump — reschedule.");
    });

    await waitFor(() => {
      expect(submitBtn.props.accessibilityState?.disabled ?? submitBtn.props.disabled).toBeFalsy();
    });

    // Submit.
    await act(async () => { fireEvent.press(submitBtn); });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        "/jobs/job-42/could-not-service",
        {
          reason_id: "r-other",
          reason_notes: "Broken pump — reschedule.",
          photo_file_ids: ["file-1"],
        },
      );
    });

    // Success alert (combined message when SMS sent).
    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Marked",
        expect.stringContaining("Customer notified"),
      );
    });
  });

  test("guard-hit (sms not sent, sms_opt_in_false) shows secondary line in success toast", async () => {
    mockApiPost.mockResolvedValueOnce({
      status: "could_not_service",
      sms_result: { sent: false, reason: "sms_opt_in_false" },
    });

    const { getByTestId } = render(
      <CouldNotServiceButton jobId="j5" jobStatus="scheduled" role="admin" testID="cns-guard" />,
    );

    await act(async () => { fireEvent.press(getByTestId("cns-guard")); });
    await waitFor(() => expect(getByTestId("cns-reason-locked_out")).toBeTruthy());

    await act(async () => { fireEvent.press(getByTestId("cns-reason-locked_out")); });
    await act(async () => { fireEvent.press(getByTestId("cns-fake-upload-btn")); });
    await act(async () => { fireEvent.press(getByTestId("cns-submit")); });

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Marked",
        expect.stringContaining("Customer opted out of SMS"),
      );
    });
  });
});
