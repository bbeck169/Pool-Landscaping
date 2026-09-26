/**
 * ARPermissionGate unit tests — AR-1.
 *
 * Mocks expo-image-picker (camera permissions) and expo-sensors
 * (DeviceMotion) to test the three gate states:
 *   1. Granted → renders placeholder, calls onGranted
 *   2. Denied → renders onboarding
 *   3. Denied with canAskAgain=false → triggers Open Settings alert
 */
import React from "react";
import { render, act, waitFor, fireEvent } from "@testing-library/react-native";
import { Alert, Linking } from "react-native";

/* ── mocks ─────────────────────────────────────────────────────── */
const mockGetCameraPerms = jest.fn();
const mockRequestCameraPerms = jest.fn();
const mockGetMotionPerms = jest.fn();
const mockRequestMotionPerms = jest.fn();

jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: (...args: any[]) => mockGetCameraPerms(...args),
  requestCameraPermissionsAsync: (...args: any[]) => mockRequestCameraPerms(...args),
}));

jest.mock("expo-sensors", () => ({
  DeviceMotion: {
    getPermissionsAsync: (...args: any[]) => mockGetMotionPerms(...args),
    requestPermissionsAsync: (...args: any[]) => mockRequestMotionPerms(...args),
  },
}));

jest.mock("react-native/Libraries/Linking/Linking", () => ({
  openSettings: jest.fn(),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

jest.spyOn(Alert, "alert");

/* ── import AFTER mocks ────────────────────────────────────────── */
// eslint-disable-next-line @typescript-eslint/no-var-requires
const ARPermissionGate = require("@/src/components/measure/ARPermissionGate.native").default;

/* ── helpers ───────────────────────────────────────────────────── */
function setPerms(cam: { status: string; canAskAgain: boolean }, mot: { status: string; canAskAgain: boolean }) {
  mockGetCameraPerms.mockResolvedValue(cam);
  mockGetMotionPerms.mockResolvedValue(mot);
}

const GRANTED = { status: "granted", canAskAgain: true };
const DENIED = { status: "denied", canAskAgain: true };
const DENIED_FINAL = { status: "denied", canAskAgain: false };

import { Text } from "react-native";

/* ── tests ─────────────────────────────────────────────────────── */
describe("ARPermissionGate", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders placeholder and calls onGranted when both permissions granted", async () => {
    setPerms(GRANTED, GRANTED);
    const onGranted = jest.fn();

    const { getByTestId } = render(
      <ARPermissionGate
        onGranted={onGranted}
        placeholder={<Text testID="ar-placeholder">AR ready</Text>}
      />,
    );

    await waitFor(() => {
      expect(onGranted).toHaveBeenCalledTimes(1);
    });

    expect(getByTestId("ar-placeholder")).toBeTruthy();
  });

  it("renders onboarding when camera permission denied", async () => {
    setPerms(DENIED, GRANTED);
    const onGranted = jest.fn();

    const { getByTestId } = render(
      <ARPermissionGate onGranted={onGranted} />,
    );

    await waitFor(() => {
      expect(getByTestId("ar-gate-onboarding")).toBeTruthy();
    });

    expect(onGranted).not.toHaveBeenCalled();

    // Verify permission cards
    expect(getByTestId("ar-gate-cam")).toBeTruthy();
    expect(getByTestId("ar-gate-motion")).toBeTruthy();

    // Verify CTA button exists
    expect(getByTestId("ar-gate-grant-btn")).toBeTruthy();
  });

  it("calls onGranted after granting permissions via CTA", async () => {
    // Start denied
    setPerms(DENIED, GRANTED);
    const onGranted = jest.fn();

    const { getByTestId } = render(
      <ARPermissionGate
        onGranted={onGranted}
        placeholder={<Text testID="ar-placeholder">AR ready</Text>}
      />,
    );

    await waitFor(() => {
      expect(getByTestId("ar-gate-onboarding")).toBeTruthy();
    });

    // Now simulate granting via the CTA
    mockRequestCameraPerms.mockResolvedValue(GRANTED);
    mockGetCameraPerms.mockResolvedValue(GRANTED);
    mockGetMotionPerms.mockResolvedValue(GRANTED);

    await act(async () => {
      fireEvent.press(getByTestId("ar-gate-grant-btn"));
    });

    await waitFor(() => {
      expect(onGranted).toHaveBeenCalled();
    });
  });

  it("shows Open Settings alert when canAskAgain is false", async () => {
    // Camera denied permanently
    setPerms(DENIED_FINAL, GRANTED);
    const onGranted = jest.fn();

    const { getByTestId } = render(
      <ARPermissionGate onGranted={onGranted} />,
    );

    await waitFor(() => {
      expect(getByTestId("ar-gate-onboarding")).toBeTruthy();
    });

    // Simulate request returning denied+canAskAgain=false
    mockRequestCameraPerms.mockResolvedValue(DENIED_FINAL);

    await act(async () => {
      fireEvent.press(getByTestId("ar-gate-grant-btn"));
    });

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Camera access required",
        expect.stringContaining("Settings"),
        expect.arrayContaining([
          expect.objectContaining({ text: "Open Settings" }),
        ]),
      );
    });

    // onGranted should NOT have been called
    expect(onGranted).not.toHaveBeenCalled();
  });
});
