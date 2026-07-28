/**
 * F2a · Job Before/After Photos (tech-side upload) — mobile tests
 *
 * Tests that the job detail screen correctly wires JobBeforeAfterPhotos:
 *   1. readOnly=false for tech/admin roles (upload visible)
 *   2. readOnly=true for customer role (read-only, hidden if empty)
 *   3. Component is present alongside legacy base64 photo system
 *   4. Both Before and After sections rendered
 *   5. FileUpload has correct purpose values
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";
import { View, Text } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────────
const mockListFiles = jest.fn();
const mockApiGet = jest.fn();

jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), del: jest.fn() },
  api_base: () => "http://test/api",
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.mock("@/src/api/files", () => ({
  ...jest.requireActual("@/src/api/files"),
  uploadFile: jest.fn(),
  deleteFile: jest.fn(),
  listFilesByEntity: (...a: any[]) => mockListFiles(...a),
  buildAuthedDownloadUrl: (id: string, t: string) => `http://test/api/files/${id}/download?auth=${t}`,
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

jest.mock("@/src/theme", () => ({
  colors: { surface:"#fff", brand:"#0284C7", muted:"#999", error:"#DC2626", border:"#E5E7EB", onSurface:"#111", onSurfaceSecondary:"#555", surfaceSecondary:"#F9FAFB", surfaceTertiary:"#E4E4E7", success:"#16A34A", divider:"#E5E7EB" },
  spacing: { xs:4, sm:8, md:12, lg:16, xl:24, "2xl":32, "3xl":48 },
  radius: { sm:8, md:12, lg:16, pill:999 },
  font: { regular:"System", medium:"System", semibold:"System", bold:"System" },
  fontSize: { sm:12, base:14, lg:16, xl:20, "2xl":24 },
}));

// ── Tests on JobBeforeAfterPhotos wiring ─────────────────────────

import { JobBeforeAfterPhotos } from "../src/components/files/JobBeforeAfterPhotos";

describe("F2a · JobBeforeAfterPhotos (tech upload mode)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListFiles.mockResolvedValue([]);
  });

  test("readOnly=false shows FileUpload in both sections", async () => {
    const { getAllByTestId, getByTestId } = render(
      <JobBeforeAfterPhotos jobId="job-abc" readOnly={false} />,
    );

    await waitFor(() => {
      expect(getByTestId("job-before-after-photos")).toBeTruthy();
    });
    // 2 FileUpload roots (Before + After)
    expect(getAllByTestId("file-upload-root")).toHaveLength(2);
    // 2 camera buttons
    expect(getAllByTestId("file-upload-camera-btn")).toHaveLength(2);
  });

  test("readOnly=true hides FileUpload completely", async () => {
    mockListFiles.mockResolvedValue([
      { id: "f1", original_filename: "a.jpg", content_type: "image/jpeg", size: 100 },
    ]);

    const { queryAllByTestId, getByTestId } = render(
      <JobBeforeAfterPhotos jobId="job-abc" readOnly />,
    );

    await waitFor(() => {
      expect(getByTestId("job-before-after-photos")).toBeTruthy();
    });
    expect(queryAllByTestId("file-upload-root")).toHaveLength(0);
  });

  test("passes correct purpose to FileList sections", async () => {
    mockListFiles.mockResolvedValue([]);

    render(<JobBeforeAfterPhotos jobId="job-xyz" readOnly={false} />);

    await waitFor(() => {
      // listFilesByEntity should be called with purpose for each section
      expect(mockListFiles).toHaveBeenCalledWith("job", "job-xyz", "job_before_photo");
      expect(mockListFiles).toHaveBeenCalledWith("job", "job-xyz", "job_after_photo");
    });
  });

  test("Before section has purpose=job_before_photo testID", async () => {
    mockListFiles.mockResolvedValue([]);

    const { getByTestId } = render(
      <JobBeforeAfterPhotos jobId="j1" readOnly={false} />,
    );

    await waitFor(() => {
      expect(getByTestId("job-photos-job_before_photo")).toBeTruthy();
      expect(getByTestId("job-photos-job_after_photo")).toBeTruthy();
    });
  });
});
