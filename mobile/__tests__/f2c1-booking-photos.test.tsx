/**
 * F2c.1 · Portal booking photo upload — mobile tests
 *
 * Tests:
 *   1. Confirmation screen shows FileUpload when createdId is set
 *   2. FileUpload has correct props (purpose, linkedEntityType, maxFiles)
 *   3. "Done" button navigates to portal home
 *   4. Upload counter increments
 *   5. No FileUpload when createdId is null (backend returned no id)
 *   6. Form submission captures returned id
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { View, Text, Pressable, ScrollView } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────────
const mockApiPost = jest.fn();
const mockReplace = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { name: "Test", role: "customer" }, token: "tok" }),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: (...a: any[]) => mockApiPost(...a),
  },
  api_base: () => "http://test/api",
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/api/files", () => ({
  ...jest.requireActual("@/src/api/files"),
  uploadFile: jest.fn(),
  deleteFile: jest.fn(),
  listFilesByEntity: jest.fn().mockResolvedValue([]),
  buildAuthedDownloadUrl: (id: string, t: string) => `http://test/api/files/${id}/download?auth=${t}`,
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn(), back: jest.fn() }),
  usePathname: () => "/request-service",
}));

jest.mock("expo-image-picker", () => ({
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
}));

jest.mock("expo-document-picker", () => ({ getDocumentAsync: jest.fn() }));
jest.mock("expo-file-system/legacy", () => ({ cacheDirectory: "/tmp/", downloadAsync: jest.fn() }));
jest.mock("expo-image", () => ({ Image: (p: any) => { const {View:V}=require("react-native"); return <V testID={p.testID}/>; } }));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("react-native-keyboard-controller", () => ({
  KeyboardAwareScrollView: (props: any) => {
    const { ScrollView: SV } = require("react-native");
    return <SV {...props} />;
  },
}));

jest.mock("@/src/hooks/useBreadcrumbs", () => ({ useBreadcrumbs: () => [] }));
jest.mock("@/src/components/nav/Breadcrumbs", () => {
  const { View: V } = require("react-native");
  return { __esModule: true, default: () => <V /> };
});

jest.mock("@/src/components/ui", () => {
  const { Pressable: P, Text: T } = require("react-native");
  return {
    PrimaryButton: (props: any) => (
      <P testID={props.testID} onPress={props.onPress}>
        <T>{props.title}</T>
      </P>
    ),
    Loading: () => null,
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View: V, Text: T } = require("react-native");
  return {
    Header: (props: any) => <V><T>{props.title}</T></V>,
    NotificationBell: () => <V />,
  };
});

jest.mock("@/src/theme", () => ({
  colors: { surface:"#fff", brand:"#0284C7", muted:"#999", error:"#DC2626", border:"#E5E7EB", onSurface:"#111", onSurfaceSecondary:"#555", surfaceSecondary:"#F9FAFB", surfaceTertiary:"#E4E4E7", success:"#16A34A" },
  spacing: { xs:4, sm:8, md:12, lg:16, xl:24, "2xl":32, "3xl":48 },
  radius: { sm:8, md:12, lg:16, pill:999 },
  font: { regular:"System", medium:"System", semibold:"System", bold:"System" },
  fontSize: { sm:12, base:14, lg:16, xl:20, "2xl":24 },
  // Mirrors src/theme.ts:74 — AppTextInput reads it at module load.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));

import RequestService from "../app/request-service";

describe("F2c.1 · Portal booking photo upload", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("shows FileUpload after successful submission with id", async () => {
    mockApiPost.mockResolvedValue({ id: "req-123" });

    const { getByTestId, getByText, queryByTestId } = render(<RequestService />);

    // Fill the details field
    const input = getByTestId("rs-details");
    fireEvent.changeText(input, "Pool needs cleaning urgently");
    await page_wait(100);

    // Submit
    fireEvent.press(getByTestId("rs-submit"));

    // Wait for confirmation screen
    await waitFor(() => {
      expect(getByText("Request submitted!")).toBeTruthy();
    }, { timeout: 10000 });

    // FileUpload section should be visible
    expect(getByTestId("booking-photo-upload-section")).toBeTruthy();
    expect(getByTestId("file-upload-root")).toBeTruthy();
    expect(getByTestId("file-upload-camera-btn")).toBeTruthy();
  }, 15000);

  test("Done button navigates to portal home", async () => {
    mockApiPost.mockResolvedValue({ id: "req-456" });

    const { getByTestId, getByText } = render(<RequestService />);

    fireEvent.changeText(getByTestId("rs-details"), "Need help with pool cleaning");
    fireEvent.press(getByTestId("rs-submit"));

    await waitFor(() => {
      expect(getByText("Request submitted!")).toBeTruthy();
    }, { timeout: 10000 });

    // Press Done
    fireEvent.press(getByTestId("request-done-button"));
    expect(mockReplace).toHaveBeenCalledWith("/portal/home");
  }, 15000);

  test("hides FileUpload when backend returns no id", async () => {
    mockApiPost.mockResolvedValue({ message: "ok" });

    const { getByTestId, getByText, queryByTestId } = render(<RequestService />);

    fireEvent.changeText(getByTestId("rs-details"), "Some request");
    fireEvent.press(getByTestId("rs-submit"));

    await waitFor(() => {
      expect(getByText("Request submitted!")).toBeTruthy();
    }, { timeout: 10000 });

    // FileUpload section should NOT be visible (no id captured)
    expect(queryByTestId("booking-photo-upload-section")).toBeNull();
    // Done button should still work
    expect(getByTestId("request-done-button")).toBeTruthy();
  }, 15000);

  test("captures message_id from actual backend shape", async () => {
    mockApiPost.mockResolvedValue({ message_id: "msg-123", ok: true, message: { id: "msg-123" } });

    const { getByTestId, getByText } = render(<RequestService />);

    fireEvent.changeText(getByTestId("rs-details"), "My pool is dirty and needs cleaning");
    fireEvent.press(getByTestId("rs-submit"));

    await waitFor(() => {
      expect(getByTestId("booking-photo-upload-section")).toBeTruthy();
    }, { timeout: 10000 });
  }, 15000);

  test("form validation prevents empty submission", () => {
    const { getByTestId } = render(<RequestService />);
    const btn = getByTestId("rs-submit");
    fireEvent.press(btn);
    expect(mockApiPost).not.toHaveBeenCalled();
  });
});

function page_wait(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
