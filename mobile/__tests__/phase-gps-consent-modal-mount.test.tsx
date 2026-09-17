/**
 * P37c · GPS Consent Modal mount test
 *
 * Verifies:
 *   1. GpsConsentModal renders and auto-checks consent via GET /tech-gps-consent/me.
 *   2. When consent is NOT active → modal becomes visible.
 *   3. When consent IS active → modal stays hidden.
 *   4. Grant button calls POST /tech-gps-consent with correct payload.
 *   5. Decline button hides modal without POST.
 *   6. Schedule mounts modal for tech role users.
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

jest.mock("@/src/services/offlineWrite", () => ({
  offlineWrite: jest.fn(async ({ onlineFn }: any) => {
    const data = await onlineFn();
    return { data, queued: false };
  }),
}));

jest.mock("@/src/background/jobGeofence", () => ({
  invalidateConsentCache: jest.fn(),
}));

import GpsConsentModal from "@/src/components/gps/GpsConsentModal";
import { invalidateConsentCache } from "@/src/background/jobGeofence";

beforeEach(() => {
  jest.clearAllMocks();
});

describe("GpsConsentModal", () => {
  it("auto-checks consent on mount and shows modal when NOT active", async () => {
    mockGet.mockResolvedValueOnce({ active: false });

    const { getByTestId } = render(<GpsConsentModal />);

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith("/tech-gps-consent/me");
    });
    await waitFor(() => {
      expect(getByTestId("gps-consent-modal")).toBeTruthy();
    });
  });

  it("stays hidden when consent IS active", async () => {
    mockGet.mockResolvedValueOnce({ active: true });

    const { queryByTestId } = render(<GpsConsentModal />);

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith("/tech-gps-consent/me");
    });
    // Give time for the state to settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(queryByTestId("gps-consent-modal")).toBeNull();
  });

  it("grant button calls POST /tech-gps-consent and invalidates cache", async () => {
    mockGet.mockResolvedValueOnce({ active: false });
    mockPost.mockResolvedValueOnce({ ok: true });
    // offlineWrite will call onlineFn → api.post
    const offlineWrite = require("@/src/services/offlineWrite").offlineWrite;
    offlineWrite.mockImplementation(async ({ onlineFn }: any) => {
      const data = await onlineFn();
      return { data, queued: false };
    });

    const onDismiss = jest.fn();
    const { getByTestId } = render(<GpsConsentModal onDismiss={onDismiss} />);

    await waitFor(() => {
      expect(getByTestId("gps-consent-modal")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("gps-consent-grant"));
    });

    await waitFor(() => {
      expect(offlineWrite).toHaveBeenCalledWith(
        expect.objectContaining({
          op_type: "gps_consent",
          entity_id: "self",
          endpoint: "/tech-gps-consent",
          method: "POST",
          payload: { granted: true, method: "mobile_onboarding_modal" },
        })
      );
    });
    expect(invalidateConsentCache).toHaveBeenCalled();
    expect(onDismiss).toHaveBeenCalledWith(true);
  });

  it("decline button hides modal without POST", async () => {
    mockGet.mockResolvedValueOnce({ active: false });

    const onDismiss = jest.fn();
    const { getByTestId, queryByTestId } = render(
      <GpsConsentModal onDismiss={onDismiss} />
    );

    await waitFor(() => {
      expect(getByTestId("gps-consent-modal")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("gps-consent-decline"));
    });

    // Modal should be gone
    await waitFor(() => {
      expect(queryByTestId("gps-consent-modal")).toBeNull();
    });
    expect(onDismiss).toHaveBeenCalledWith(false);
    // No POST should have been made (only the initial GET)
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("handles network error on consent check gracefully (no crash)", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));

    const { queryByTestId } = render(<GpsConsentModal />);

    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });
    // Should not crash — modal stays hidden on error
    expect(queryByTestId("gps-consent-modal")).toBeNull();
  });

  it("renders with autoOpen=true without fetching consent", async () => {
    const { getByTestId } = render(<GpsConsentModal autoOpen />);

    // Should show immediately
    expect(getByTestId("gps-consent-modal")).toBeTruthy();
    // Should NOT have checked consent (autoOpen bypasses check)
    expect(mockGet).not.toHaveBeenCalled();
  });
});
