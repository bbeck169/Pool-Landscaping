/**
 * Phase F1 · Tests for FileUpload, AuthedImage, FileList.
 *
 * Mirrors the 10 web specs where they translate to mobile:
 *   1. FileUpload renders action buttons
 *   2. FileUpload shows camera, library, and document picker buttons
 *   3. FileUpload client-side validates oversized files
 *   4. FileUpload client-side validates disallowed MIME types
 *   5. FileUpload shows uploaded items with metadata
 *   6. FileUpload removes items on delete
 *   7. AuthedImage renders loading state
 *   8. AuthedImage renders image when URL resolves
 *   9. FileList renders loading then items
 *  10. FileList shows empty state when no files
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { View, Text, Pressable, ActivityIndicator, FlatList, Alert } from "react-native";

// ── Global Mocks ─────────────────────────────────────────────────

// Mock getAuthToken
jest.mock("@/src/api", () => ({
  api_base: () => "http://test-backend/api",
  getAuthToken: jest.fn().mockResolvedValue("mock-token-123"),
}));

// Mock expo-file-system/legacy
jest.mock("expo-file-system/legacy", () => ({
  cacheDirectory: "/tmp/cache/",
  downloadAsync: jest.fn().mockResolvedValue({ uri: "/tmp/cache/file_123", status: 200 }),
}));

// Mock expo-image
jest.mock("expo-image", () => {
  const { View: V } = require("react-native");
  return {
    Image: (props: any) => {
      // Simulate onLoad after a tick
      if (props.onLoad) setTimeout(() => props.onLoad(), 10);
      return <V testID={props.testID} />;
    },
  };
});

// Mock expo-image-picker
const mockLaunchCamera = jest.fn();
const mockLaunchLibrary = jest.fn();
const mockCameraPermission = jest.fn();
const mockMediaPermission = jest.fn();

jest.mock("expo-image-picker", () => ({
  launchCameraAsync: (...args: any[]) => mockLaunchCamera(...args),
  launchImageLibraryAsync: (...args: any[]) => mockLaunchLibrary(...args),
  requestCameraPermissionsAsync: () => mockCameraPermission(),
  requestMediaLibraryPermissionsAsync: () => mockMediaPermission(),
}));

// Mock expo-document-picker
const mockGetDocument = jest.fn();
jest.mock("expo-document-picker", () => ({
  getDocumentAsync: (...args: any[]) => mockGetDocument(...args),
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

// ── API mocks ────────────────────────────────────────────────────
const mockUploadFile = jest.fn();
const mockDeleteFile = jest.fn();
const mockListFiles = jest.fn();

jest.mock("@/src/api/files", () => {
  const actual = jest.requireActual("@/src/api/files");
  return {
    ...actual,
    uploadFile: (...args: any[]) => mockUploadFile(...args),
    deleteFile: (...args: any[]) => mockDeleteFile(...args),
    listFilesByEntity: (...args: any[]) => mockListFiles(...args),
    buildAuthedDownloadUrl: (id: string, token: string) =>
      `http://test-backend/api/files/${id}/download?auth=${token}`,
  };
});

// ── Imports AFTER mocks ──────────────────────────────────────────
import { FileUpload } from "../src/components/files/FileUpload";
import { AuthedImage } from "../src/components/files/AuthedImage";
import { FileList } from "../src/components/files/FileList";
import { mimeAllowed, humanBytes, MAX_UPLOAD_SIZE_BYTES } from "../src/api/files";

// ═══════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════

describe("files API helpers", () => {
  test("mimeAllowed accepts image/* for image/jpeg", () => {
    expect(mimeAllowed("image/jpeg", "image/*")).toBe(true);
  });
  test("mimeAllowed rejects text/plain for image/*", () => {
    expect(mimeAllowed("text/plain", "image/*")).toBe(false);
  });
  test("mimeAllowed accepts application/pdf when listed", () => {
    expect(mimeAllowed("application/pdf", "image/*,application/pdf")).toBe(true);
  });
  test("humanBytes formats correctly", () => {
    expect(humanBytes(500)).toBe("500 B");
    expect(humanBytes(1024 * 512)).toBe("512.0 KB");
    expect(humanBytes(1024 * 1024 * 3)).toBe("3.0 MB");
  });
  test("MAX_UPLOAD_SIZE_BYTES is 25 MB", () => {
    expect(MAX_UPLOAD_SIZE_BYTES).toBe(25 * 1024 * 1024);
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileUpload
// ═══════════════════════════════════════════════════════════════════

describe("FileUpload component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCameraPermission.mockResolvedValue({ granted: true });
    mockMediaPermission.mockResolvedValue({ granted: true });
  });

  test("renders camera and library buttons", () => {
    const { getByTestId } = render(<FileUpload />);
    expect(getByTestId("file-upload-root")).toBeTruthy();
    expect(getByTestId("file-upload-camera-btn")).toBeTruthy();
    expect(getByTestId("file-upload-library-btn")).toBeTruthy();
  });

  test("shows document picker button when accept includes PDF", () => {
    const { getByTestId } = render(
      <FileUpload accept="image/*,application/pdf" />
    );
    expect(getByTestId("file-upload-document-btn")).toBeTruthy();
  });

  test("hides document picker button when accept is only images", () => {
    const { queryByTestId } = render(<FileUpload accept="image/*" />);
    expect(queryByTestId("file-upload-document-btn")).toBeNull();
  });

  test("calls onError for oversized file (client-side gate)", async () => {
    const onError = jest.fn();
    jest.spyOn(Alert, "alert");

    mockLaunchCamera.mockResolvedValue({
      canceled: false,
      assets: [{
        uri: "file:///big.jpg",
        fileName: "big.jpg",
        mimeType: "image/jpeg",
        fileSize: 30 * 1024 * 1024, // 30 MB > 25 MB
      }],
    });

    const { getByTestId } = render(<FileUpload onError={onError} />);
    await act(async () => {
      fireEvent.press(getByTestId("file-upload-camera-btn"));
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({ code: "FILE_TOO_LARGE" })
      );
    });
    expect(mockUploadFile).not.toHaveBeenCalled();
  });

  test("calls onError for disallowed MIME type", async () => {
    const onError = jest.fn();
    jest.spyOn(Alert, "alert");

    mockLaunchLibrary.mockResolvedValue({
      canceled: false,
      assets: [{
        uri: "file:///doc.txt",
        fileName: "doc.txt",
        mimeType: "text/plain",
        fileSize: 100,
      }],
    });

    const { getByTestId } = render(
      <FileUpload accept="image/*" onError={onError} />
    );
    await act(async () => {
      fireEvent.press(getByTestId("file-upload-library-btn"));
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({ code: "UNSUPPORTED_MIME" })
      );
    });
    expect(mockUploadFile).not.toHaveBeenCalled();
  });

  test("uploads file and shows item on success", async () => {
    const onUploaded = jest.fn();
    const payload = {
      id: "file-1",
      url: "/api/files/file-1/download",
      size: 5000,
      content_type: "image/jpeg",
      original_filename: "photo.jpg",
      storage_path: "uploads/photo.jpg",
    };

    mockUploadFile.mockResolvedValue(payload);
    mockLaunchCamera.mockResolvedValue({
      canceled: false,
      assets: [{
        uri: "file:///photo.jpg",
        fileName: "photo.jpg",
        mimeType: "image/jpeg",
        fileSize: 5000,
      }],
    });

    const { getByTestId, getByText } = render(
      <FileUpload onUploaded={onUploaded} />
    );
    await act(async () => {
      fireEvent.press(getByTestId("file-upload-camera-btn"));
    });

    await waitFor(() => {
      expect(onUploaded).toHaveBeenCalledWith(payload);
    });
    expect(getByText("photo.jpg")).toBeTruthy();
  });

  test("buttons disabled when disabled prop is true", () => {
    const { getByTestId } = render(<FileUpload disabled />);
    // Buttons render but are disabled — press should not open picker
    fireEvent.press(getByTestId("file-upload-camera-btn"));
    expect(mockCameraPermission).not.toHaveBeenCalled();
  });
});

// ═══════════════════════════════════════════════════════════════════
// AuthedImage
// ═══════════════════════════════════════════════════════════════════

describe("AuthedImage component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("renders loading state initially", async () => {
    const { getByTestId } = render(<AuthedImage fileId="img-1" />);
    expect(getByTestId("authed-image-img-1-loading")).toBeTruthy();
  });

  test("renders image after token resolves", async () => {
    const { getByTestId, queryByTestId } = render(<AuthedImage fileId="img-2" />);

    // Initially loading
    expect(getByTestId("authed-image-img-2-loading")).toBeTruthy();

    // After token resolves and image loads
    await waitFor(() => {
      expect(queryByTestId("authed-image-img-2")).toBeTruthy();
    }, { timeout: 3000 });
  });

  test("renders fallback on error", async () => {
    // Override getAuthToken to reject
    const { getAuthToken } = require("@/src/api");
    getAuthToken.mockRejectedValueOnce(new Error("no token"));

    const fallbackEl = <View testID="custom-fallback" />;
    const { getByTestId } = render(
      <AuthedImage fileId="img-err" fallback={fallbackEl} />
    );

    await waitFor(() => {
      expect(getByTestId("custom-fallback")).toBeTruthy();
    });
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileList
// ═══════════════════════════════════════════════════════════════════

describe("FileList component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("shows loading state initially", () => {
    mockListFiles.mockReturnValue(new Promise(() => {})); // never resolves
    const { getByTestId } = render(
      <FileList linkedEntityType="dev" linkedEntityId="test" />
    );
    expect(getByTestId("file-list-loading")).toBeTruthy();
  });

  test("shows empty state when no files", async () => {
    mockListFiles.mockResolvedValue([]);
    const { getByTestId, getByText } = render(
      <FileList linkedEntityType="dev" linkedEntityId="test" />
    );

    await waitFor(() => {
      expect(getByTestId("file-list-empty")).toBeTruthy();
    });
    expect(getByText("No files yet.")).toBeTruthy();
  });

  test("renders file items after fetching", async () => {
    mockListFiles.mockResolvedValue([
      {
        id: "f-1",
        original_filename: "report.pdf",
        content_type: "application/pdf",
        size: 1024 * 100,
        created_at: "2026-07-01T00:00:00Z",
      },
      {
        id: "f-2",
        original_filename: "poolshot.jpg",
        content_type: "image/jpeg",
        size: 2048 * 50,
        created_at: "2026-07-02T00:00:00Z",
      },
    ]);

    const { getByTestId, getByText } = render(
      <FileList linkedEntityType="dev" linkedEntityId="test" canDelete />
    );

    await waitFor(() => {
      expect(getByTestId("file-list")).toBeTruthy();
    });

    expect(getByTestId("file-list-item-f-1")).toBeTruthy();
    expect(getByTestId("file-list-item-f-2")).toBeTruthy();
    expect(getByText("report.pdf")).toBeTruthy();
    expect(getByText("poolshot.jpg")).toBeTruthy();
    // Delete buttons present
    expect(getByTestId("file-list-delete-f-1")).toBeTruthy();
    expect(getByTestId("file-list-delete-f-2")).toBeTruthy();
  });

  test("hides delete buttons when canDelete is false", async () => {
    mockListFiles.mockResolvedValue([
      { id: "f-3", original_filename: "img.jpg", content_type: "image/jpeg", size: 100 },
    ]);

    const { getByTestId, queryByTestId } = render(
      <FileList linkedEntityType="dev" linkedEntityId="test" canDelete={false} />
    );

    await waitFor(() => {
      expect(getByTestId("file-list-item-f-3")).toBeTruthy();
    });
    expect(queryByTestId("file-list-delete-f-3")).toBeNull();
  });

  test("shows error state on fetch failure", async () => {
    mockListFiles.mockRejectedValue(new Error("Network issue"));

    const { getByTestId, getByText } = render(
      <FileList linkedEntityType="dev" linkedEntityId="test" />
    );

    await waitFor(() => {
      expect(getByTestId("file-list-error")).toBeTruthy();
    });
    expect(getByText("Network issue")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// Demo screen env gate
// ═══════════════════════════════════════════════════════════════════

describe("Dev file-upload screen", () => {
  test("renders in preview mode", () => {
    process.env.EXPO_PUBLIC_ENV = "preview";
    const DevScreen = require("../app/dev/file-upload").default;
    const { getByTestId } = render(<DevScreen />);
    expect(getByTestId("dev-file-upload-screen")).toBeTruthy();
  });

  test("shows gated message in non-preview mode", () => {
    process.env.EXPO_PUBLIC_ENV = "production";
    const DevScreen = require("../app/dev/file-upload").default;
    const { getByText, queryByTestId } = render(<DevScreen />);
    expect(queryByTestId("dev-file-upload-screen")).toBeNull();
    expect(getByText(/only available in preview builds/)).toBeTruthy();
  });
});
