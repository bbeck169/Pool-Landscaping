/**
 * On My Way button · Jest tests.
 *
 * Covers:
 *   1. Role gate — hidden for customer, visible for technician.
 *   2. Geolocation resolves → POST body includes lat/lng.
 *   3. Geolocation errors → POST still fires without coords.
 *   4. Guard-hit toasts for 'already_sent_today' and 'no_phone'.
 *   5. 10s local disable after success.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

/* ── Mocks ─────────────────────────────────────────────────────────── */

const mockGetForeground = jest.fn();
const mockRequestForeground = jest.fn();
const mockGetCurrentPosition = jest.fn();

jest.mock("expo-location", () => ({
  getForegroundPermissionsAsync: (...a: any[]) => mockGetForeground(...a),
  requestForegroundPermissionsAsync: (...a: any[]) => mockRequestForeground(...a),
  getCurrentPositionAsync: (...a: any[]) => mockGetCurrentPosition(...a),
  Accuracy: { Balanced: 3 },
}));

const mockApiPost = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: (...a: any[]) => mockApiPost(...a),
    put: jest.fn(),
    delete: jest.fn(),
  },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "technician", name: "Tech" } }),
}));

jest.spyOn(Alert, "alert");

import OnMyWayButton from "@/src/components/schedule/OnMyWayButton";

/* ── Helpers ───────────────────────────────────────────────────────── */

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  mockGetForeground.mockResolvedValue({ status: "granted" });
  mockRequestForeground.mockResolvedValue({ status: "granted" });
  mockGetCurrentPosition.mockResolvedValue({
    coords: { latitude: 33.45, longitude: -112.07, accuracy: 10 },
  });
});

afterEach(() => {
  jest.useRealTimers();
});

/* ── Tests ─────────────────────────────────────────────────────────── */

describe("OnMyWayButton", () => {

  test("hidden for customer role", () => {
    const { queryByTestId } = render(
      <OnMyWayButton jobId="j1" role="customer" testID="omw-test" />,
    );
    expect(queryByTestId("omw-test")).toBeNull();
  });

  test("visible for technician role", () => {
    const { getByTestId } = render(
      <OnMyWayButton jobId="j1" role="technician" testID="omw-test" />,
    );
    expect(getByTestId("omw-test")).toBeTruthy();
  });

  test("geolocation resolves → POST includes lat/lng", async () => {
    mockApiPost.mockResolvedValueOnce({ sent: true, eta_minutes: 12 });

    const { getByTestId } = render(
      <OnMyWayButton jobId="j1" role="technician" customerName="Jane Doe" testID="omw-geo" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-geo"));
      // Flush microtasks
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        "/jobs/j1/on-my-way",
        expect.objectContaining({ origin_lat: 33.45, origin_lng: -112.07 }),
      );
    });
  });

  test("geolocation errors → POST fires without coords", async () => {
    mockGetCurrentPosition.mockRejectedValueOnce(new Error("GPS error"));
    mockApiPost.mockResolvedValueOnce({ sent: true, eta_minutes: null });

    const { getByTestId } = render(
      <OnMyWayButton jobId="j1" role="technician" testID="omw-nocoords" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-nocoords"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/jobs/j1/on-my-way", {});
    });
  });

  test("guard 'already_sent_today' shows humanized alert", async () => {
    mockApiPost.mockResolvedValueOnce({ sent: false, reason: "already_sent_today" });

    const { getByTestId } = render(
      <OnMyWayButton jobId="j2" role="admin" testID="omw-guard1" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-guard1"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Not sent",
        "Already notified this customer today",
      );
    });
  });

  test("guard 'no_phone' shows humanized alert", async () => {
    mockApiPost.mockResolvedValueOnce({ sent: false, reason: "no_phone" });

    const { getByTestId } = render(
      <OnMyWayButton jobId="j3" role="technician" testID="omw-guard2" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-guard2"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Not sent",
        "Customer has no phone on file",
      );
    });
  });

  test("10s cooldown disables button after success", async () => {
    mockApiPost.mockResolvedValueOnce({ sent: true, eta_minutes: 5 });

    const { getByTestId, queryByText } = render(
      <OnMyWayButton jobId="j4" role="technician" testID="omw-cooldown" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("omw-cooldown"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
    });

    // Button should be in cooldown state — text says "Sent"
    await waitFor(() => {
      expect(queryByText("Sent")).toBeTruthy();
    });

    // Advance 10s to clear cooldown
    act(() => { jest.advanceTimersByTime(10_000); });

    await waitFor(() => {
      expect(queryByText("On my way")).toBeTruthy();
    });
  });
});
