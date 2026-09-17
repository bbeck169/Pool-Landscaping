/**
 * P37c · Mobile arrival endpoint test
 *
 * Verifies:
 *   1. OnMyWayButton sends POST /jobs/{id}/arrive with { source: "manual" } + coords.
 *   2. Arrival POST is fired alongside the on-my-way SMS.
 *   3. already_arrived / already_running responses are handled silently.
 *   4. Arrival failure does not surface an error alert.
 *   5. Arrival without coords sends only { source: "manual" }.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockPost = jest.fn();
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

const mockOfflineWrite = jest.fn();
jest.mock("@/src/services/offlineWrite", () => ({
  offlineWrite: (...args: any[]) => mockOfflineWrite(...args),
  queuedMessage: () => "Queued for sync",
}));

// Mock expo-location — geolocation
const mockGetForegroundPerms = jest.fn();
const mockGetCurrentPosition = jest.fn();
jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: () => mockGetForegroundPerms(),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: "granted" }),
  getCurrentPositionAsync: () => mockGetCurrentPosition(),
  Accuracy: { Balanced: 3 },
}));

jest.mock("@/src/theme", () => ({
  font: { bold: "System" },
  fontSize: { base: 16 },
  spacing: { sm: 8 },
  radius: { md: 8, sm: 4 },
}));

jest.spyOn(Alert, "alert").mockImplementation(() => {});

import OnMyWayButton from "@/src/components/schedule/OnMyWayButton";

beforeEach(() => {
  jest.clearAllMocks();
  // Default: geolocation returns coords
  mockGetForegroundPerms.mockResolvedValue({ status: "granted" });
  mockGetCurrentPosition.mockResolvedValue({
    coords: { latitude: 33.4484, longitude: -112.074 },
  });
  // Default: on-my-way SMS succeeds
  mockOfflineWrite.mockResolvedValue({
    data: { sent: true, eta_minutes: 12 },
    queued: false,
  });
  // Default: arrive succeeds
  mockPost.mockResolvedValue({ started: true });
});

describe("OnMyWayButton — P37c arrival POST", () => {
  it("sends POST /jobs/{id}/arrive with coords and source:manual", async () => {
    const { getByTestId } = render(
      <OnMyWayButton jobId="job-123" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/jobs/job-123/arrive", {
        lat: 33.4484,
        lng: -112.074,
        source: "manual",
      });
    });
  });

  it("sends arrival without coords when geolocation fails", async () => {
    // Geolocation returns null (denied)
    mockGetForegroundPerms.mockResolvedValue({ status: "denied" });

    const { getByTestId } = render(
      <OnMyWayButton jobId="job-456" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/jobs/job-456/arrive", {
        source: "manual",
      });
    });
  });

  it("handles already_arrived response silently (no error alert)", async () => {
    mockPost.mockResolvedValue({ already_arrived: true });

    const { getByTestId } = render(
      <OnMyWayButton jobId="job-789" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/jobs/job-789/arrive",
        expect.objectContaining({ source: "manual" })
      );
    });

    // The on-my-way SMS alert should still fire (not blocked by arrive)
    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "On my way",
        expect.stringContaining("on my way")
      );
    });
  });

  it("handles already_running response silently", async () => {
    mockPost.mockResolvedValue({ already_running: true });

    const { getByTestId } = render(
      <OnMyWayButton jobId="job-aaa" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/jobs/job-aaa/arrive",
        expect.objectContaining({ source: "manual" })
      );
    });
  });

  it("arrival POST failure does not surface error (silent catch)", async () => {
    mockPost.mockRejectedValue(new Error("Server error"));

    const { getByTestId } = render(
      <OnMyWayButton jobId="job-err" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    // The SMS alert should still work (on-my-way is separate)
    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "On my way",
        expect.stringContaining("on my way")
      );
    });

    // No "Send failed" alert for the arrival endpoint
    const failAlerts = (Alert.alert as jest.Mock).mock.calls.filter(
      ([title]: [string]) => title === "Send failed"
    );
    expect(failAlerts.length).toBe(0);
  });

  it("fires both on-my-way SMS and arrive POST in sequence", async () => {
    const callOrder: string[] = [];
    mockOfflineWrite.mockImplementation(async () => {
      callOrder.push("on-my-way");
      return { data: { sent: true }, queued: false };
    });
    mockPost.mockImplementation(async () => {
      callOrder.push("arrive");
      return { started: true };
    });

    const { getByTestId } = render(
      <OnMyWayButton jobId="job-seq" role="technician" testID="omw-btn" />
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-btn"));
    });

    await waitFor(() => {
      expect(callOrder).toContain("on-my-way");
      expect(callOrder).toContain("arrive");
    });
    // on-my-way fires first, then arrive
    expect(callOrder.indexOf("on-my-way")).toBeLessThan(
      callOrder.indexOf("arrive")
    );
  });

  it("does not render for non-allowed roles", () => {
    const { queryByTestId } = render(
      <OnMyWayButton jobId="job-x" role="customer" testID="omw-btn" />
    );
    expect(queryByTestId("omw-btn")).toBeNull();
  });
});
