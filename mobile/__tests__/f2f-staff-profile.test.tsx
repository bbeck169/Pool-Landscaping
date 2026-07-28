/**
 * Wave M3 · F2f Staff Profile Photo tests.
 *
 * Tests the profile screen: initial badge, FileUpload, PATCH /users/me,
 * remove photo, identity card display.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

const mockGet = jest.fn();
const mockPatch = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: (...a: any[]) => mockPatch(...a),
    post: jest.fn().mockResolvedValue({}),
  },
  api_base: () => "http://test-backend/api",
  getAuthToken: () => Promise.resolve("test-token"),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", name: "Test User", email: "test@example.com", role: "admin" },
  }),
}));

jest.mock("expo-image", () => ({
  Image: "Image",
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text>{title}</Text>;
  },
}));

jest.mock("@/src/components/files/FileUpload", () => ({
  FileUpload: ({ onUploaded, purpose, disabled, linkedEntityId }: any) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable
        testID="mock-file-upload-profile"
        onPress={() => onUploaded?.({ id: "file-xyz" })}
        disabled={disabled}
      >
        <Text>FileUpload ({purpose}) entity={linkedEntityId}</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/src/components/files/AuthedImage", () => ({
  AuthedImage: ({ fileId }: any) => {
    const { Text } = require("react-native");
    return <Text testID={`authed-image-${fileId}`}>AuthedImage</Text>;
  },
}));

jest.spyOn(require("react-native").Alert, "alert");
const Alert = require("react-native").Alert;

import ProfileScreen from "@/app/(app)/profile";

describe("F2f · Staff Profile Photo", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("shows loading state then renders profile with initial badge (no photo)", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Test User",
      email: "test@example.com",
      role: "admin",
      profile_photo_url: null,
    });

    const { getByTestId, getByText } = render(<ProfileScreen />);

    await waitFor(() => {
      expect(getByTestId("my-profile-page")).toBeTruthy();
      expect(getByTestId("profile-initial-badge")).toBeTruthy();
      expect(getByText("T")).toBeTruthy(); // first letter of "Test User"
    });
  }, 15000);

  it("shows AuthedImage when profile_photo_url is set", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Alice",
      email: "alice@example.com",
      role: "technician",
      profile_photo_url: "/api/files/photo123/download",
    });

    const { getByTestId } = render(<ProfileScreen />);

    await waitFor(() => {
      expect(getByTestId("authed-image-photo123")).toBeTruthy();
    });
  });

  it("displays identity card with name, email, and role", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Super Admin",
      email: "super@aquaterra.com",
      role: "super_admin",
      profile_photo_url: null,
    });

    const { getByTestId } = render(<ProfileScreen />);

    await waitFor(() => {
      expect(getByTestId("profile-name")).toBeTruthy();
      expect(getByTestId("profile-email")).toBeTruthy();
      expect(getByTestId("profile-role")).toBeTruthy();
      expect(getByTestId("profile-identity-card")).toBeTruthy();
    });
  });

  it("PATCHes profile_photo_url on FileUpload success", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Test User",
      email: "test@example.com",
      role: "admin",
      profile_photo_url: null,
    });
    mockPatch.mockResolvedValue({
      user: {
        id: "u1",
        name: "Test User",
        email: "test@example.com",
        role: "admin",
        profile_photo_url: "/api/files/file-xyz/download",
      },
    });

    const { getByTestId } = render(<ProfileScreen />);

    await waitFor(() => expect(getByTestId("mock-file-upload-profile")).toBeTruthy());

    // Trigger upload callback
    await act(async () => {
      fireEvent.press(getByTestId("mock-file-upload-profile"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/users/me",
        { profile_photo_url: "/api/files/file-xyz/download" },
      );
    });
  });

  it("shows remove photo button when photo exists and PATCHes null on press", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Test User",
      email: "test@example.com",
      role: "admin",
      profile_photo_url: "/api/files/photo456/download",
    });
    mockPatch.mockResolvedValue({
      user: {
        id: "u1",
        name: "Test User",
        email: "test@example.com",
        role: "admin",
        profile_photo_url: null,
      },
    });

    const { getByTestId } = render(<ProfileScreen />);

    await waitFor(() => expect(getByTestId("profile-remove-photo")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("profile-remove-photo"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/users/me",
        { profile_photo_url: null },
      );
    });
  });

  it("shows profile photo card with upload component", async () => {
    mockGet.mockResolvedValue({
      id: "u1",
      name: "Test User",
      email: "test@example.com",
      role: "admin",
      profile_photo_url: null,
    });

    const { getByTestId, getByText } = render(<ProfileScreen />);

    await waitFor(() => {
      expect(getByTestId("profile-photo-card")).toBeTruthy();
      expect(getByTestId("mock-file-upload-profile")).toBeTruthy();
      expect(getByText(/Recommended/)).toBeTruthy();
    });
  });

  it("falls back to context user if /auth/me fails", async () => {
    mockGet.mockRejectedValue(new Error("Network error"));

    const { getByTestId, getByText } = render(<ProfileScreen />);

    await waitFor(() => {
      expect(getByTestId("my-profile-page")).toBeTruthy();
      // Should fall back to auth context user
      expect(getByText("T")).toBeTruthy(); // "Test User" from mock auth
    });
  });
});
