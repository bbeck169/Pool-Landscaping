/**
 * Feb-2026 · P37c — GpsConsentModal Jest tests.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a),
           post: (...a: any[]) => mockPost(...a) },
}));

jest.mock("@/src/background/jobGeofence", () => ({
  invalidateConsentCache: jest.fn(),
}));

import GpsConsentModal from "../src/components/gps/GpsConsentModal";


afterEach(() => { jest.clearAllMocks(); });


describe("GpsConsentModal · P37c", () => {
  it("shows when GET /tech-gps-consent/me returns active=false", async () => {
    mockGet.mockResolvedValue({ active: false, history: [] });
    const { getByTestId } = render(<GpsConsentModal />);
    await waitFor(() => expect(getByTestId("gps-consent-modal")).toBeTruthy());
    expect(getByTestId("gps-consent-grant")).toBeTruthy();
    expect(getByTestId("gps-consent-decline")).toBeTruthy();
  });

  it("does NOT show when GET returns active=true", async () => {
    mockGet.mockResolvedValue({ active: true, history: [] });
    const { queryByTestId } = render(<GpsConsentModal />);
    // Give the effect a beat to resolve.
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(queryByTestId("gps-consent-modal")).toBeNull();
  });

  it("Grant posts the correct body then dismisses", async () => {
    mockGet.mockResolvedValue({ active: false });
    mockPost.mockResolvedValue({ ok: true, active: true, granted: true });
    const onDismiss = jest.fn();
    const { getByTestId, queryByTestId } = render(
      <GpsConsentModal onDismiss={onDismiss} />,
    );
    await waitFor(() => expect(getByTestId("gps-consent-grant")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("gps-consent-grant")); });
    expect(mockPost).toHaveBeenCalledWith("/tech-gps-consent", {
      granted: true, method: "mobile_onboarding_modal",
    });
    await waitFor(() => expect(queryByTestId("gps-consent-modal")).toBeNull());
    expect(onDismiss).toHaveBeenCalledWith(true);
  });

  it("Decline does NOT post, but still dismisses", async () => {
    mockGet.mockResolvedValue({ active: false });
    const onDismiss = jest.fn();
    const { getByTestId, queryByTestId } = render(
      <GpsConsentModal onDismiss={onDismiss} />,
    );
    await waitFor(() => expect(getByTestId("gps-consent-decline")).toBeTruthy());
    fireEvent.press(getByTestId("gps-consent-decline"));
    expect(mockPost).not.toHaveBeenCalled();
    await waitFor(() => expect(queryByTestId("gps-consent-modal")).toBeNull());
    expect(onDismiss).toHaveBeenCalledWith(false);
  });
});
