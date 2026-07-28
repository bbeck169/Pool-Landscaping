/**
 * F2c.2 · Job Before/After Photos (read-only) — mobile tests
 *
 * Mirrors the web spec structure:
 *   1. Renders "Before & After Photos" card when files exist
 *   2. Hides entirely in readOnly mode when both lists are empty
 *   3. Shows two sections: "Before" and "After"
 *   4. canDelete=false in readOnly mode
 *   5. Shows FileUpload when NOT readOnly
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";
import { View, Text } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────────
const mockListFiles = jest.fn();

jest.mock("@/src/api", () => ({
  api_base: () => "http://test/api",
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/api/files", () => ({
  ...jest.requireActual("@/src/api/files"),
  uploadFile: jest.fn(),
  deleteFile: jest.fn(),
  listFilesByEntity: (...args: any[]) => mockListFiles(...args),
  buildAuthedDownloadUrl: (id: string, t: string) => `http://test/api/files/${id}/download?auth=${t}`,
}));

jest.mock("expo-image-picker", () => ({
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
}));

jest.mock("expo-document-picker", () => ({
  getDocumentAsync: jest.fn(),
}));

jest.mock("expo-file-system/legacy", () => ({
  cacheDirectory: "/tmp/",
  downloadAsync: jest.fn(),
}));

jest.mock("expo-image", () => ({
  Image: (props: any) => {
    const { View: V } = require("react-native");
    return <V testID={props.testID} />;
  },
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626",
    border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555",
    surfaceSecondary: "#F9FAFB", surfaceTertiary: "#E4E4E7",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 8, md: 12, lg: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24 },
}));

import { JobBeforeAfterPhotos } from "../src/components/files/JobBeforeAfterPhotos";

// ── Tests ─────────────────────────────────────────────────────────

describe("JobBeforeAfterPhotos (read-only / F2c.2)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("renders empty sentinel when readOnly and both lists empty", async () => {
    mockListFiles.mockResolvedValue([]);

    const { getByTestId, queryByTestId, queryByText } = render(
      <JobBeforeAfterPhotos jobId="job-1" readOnly />,
    );

    await waitFor(() => {
      expect(getByTestId("job-before-after-photos-empty")).toBeTruthy();
    });
    // The full card should NOT render
    expect(queryByTestId("job-before-after-photos")).toBeNull();
    expect(queryByText("Before & After Photos")).toBeNull();
  }, 15000);

  test("renders card when before files exist (readOnly)", async () => {
    mockListFiles.mockImplementation((_type: string, _id: string) => {
      return Promise.resolve([
        { id: "f1", original_filename: "before.jpg", content_type: "image/jpeg", size: 100 },
      ]);
    });

    const { getByTestId, getByText } = render(
      <JobBeforeAfterPhotos jobId="job-2" readOnly />,
    );

    await waitFor(() => {
      expect(getByTestId("job-before-after-photos")).toBeTruthy();
    });
    expect(getByText("Before")).toBeTruthy();
    expect(getByText("After")).toBeTruthy();
  });

  test("has two photo sections (Before + After)", async () => {
    mockListFiles.mockResolvedValue([
      { id: "f1", original_filename: "photo.jpg", content_type: "image/jpeg", size: 50 },
    ]);

    const { getByTestId } = render(
      <JobBeforeAfterPhotos jobId="job-3" readOnly />,
    );

    await waitFor(() => {
      expect(getByTestId("job-photos-job_before_photo")).toBeTruthy();
      expect(getByTestId("job-photos-job_after_photo")).toBeTruthy();
    });
  });

  test("hides FileUpload in readOnly mode", async () => {
    mockListFiles.mockResolvedValue([
      { id: "f1", original_filename: "x.jpg", content_type: "image/jpeg", size: 50 },
    ]);

    const { queryAllByTestId } = render(
      <JobBeforeAfterPhotos jobId="job-4" readOnly />,
    );

    await waitFor(() => {
      // No file-upload-root should exist
      expect(queryAllByTestId("file-upload-root")).toHaveLength(0);
    });
  });

  test("shows FileUpload when NOT readOnly (F2a preview)", async () => {
    mockListFiles.mockResolvedValue([]);

    const { getAllByTestId, getByTestId } = render(
      <JobBeforeAfterPhotos jobId="job-5" readOnly={false} />,
    );

    await waitFor(() => {
      expect(getByTestId("job-before-after-photos")).toBeTruthy();
    });
    // Should have 2 FileUpload roots (before + after)
    expect(getAllByTestId("file-upload-root")).toHaveLength(2);
  });
});
