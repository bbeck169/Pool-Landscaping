/**
 * Feb 2026 — Integration tests for the iOS field-upload compression
 * wiring. Verifies that the two primary uploader components call the
 * helper BEFORE hitting the network, so large iPhone photos never go
 * on the wire full-size.
 *
 * We mock `@/lib/imageCompress` at the module edge so we can assert
 * (a) the helper was invoked with the raw picked file and
 * (b) the downstream upload sees the compressed result.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// ─── Mocks: helper + upstream deps ────────────────────────────────
const __stubs = {
  compressImageIfNeeded: vi.fn(),
  uploadFile: async () => ({}),
  apiPost: vi.fn(),
};

vi.mock("@/lib/imageCompress", () => ({
  __esModule: true,
  compressImageIfNeeded: (...a) => __stubs.compressImageIfNeeded(...a),
  default: (...a) => __stubs.compressImageIfNeeded(...a),
}));
vi.mock("@/api/files", () => ({
  uploadFile: (...a) => __stubs.uploadFile(...a),
  deleteFile: async () => true,
  listFilesByEntity: async () => [],
  fetchAsBlob: async () => ({ url: "blob:x", contentType: "image/png" }),
  revokeBlobUrl: () => {},
  buildAuthedDownloadUrl: (id) => `/api/files/${id}/download`,
}));
vi.mock("@/api", () => ({
  api: {
    post: (...a) => __stubs.apiPost(...a),
    del: async () => ({ photos: [] }),
    get: async () => ({}),
  },
  TOKEN_KEY: "auth_token",
}));
vi.mock("sonner", () => ({ toast: { success: () => {}, error: () => {} } }));

// Import AFTER mocks.
import { FileUpload } from "@/components/files/FileUpload";
import PhotoUploader from "@/components/checklist/PhotoUploader";

function mockFile(name, size, type) {
  const blob = new Blob([new Uint8Array(1)], { type });
  Object.defineProperty(blob, "size", { value: size });
  Object.defineProperty(blob, "name", { value: name });
  return blob;
}

beforeEach(() => {
  __stubs.compressImageIfNeeded.mockReset();
  __stubs.apiPost.mockReset();
  __stubs.uploadFile = async () => ({});
});

// ═══════════════════════════════════════════════════════════════════
// FileUpload — Path A (before/after) + Path C (customer photos, etc.)
// ═══════════════════════════════════════════════════════════════════
describe("FileUpload · image compression wiring", () => {
  it("calls compressImageIfNeeded with the raw picked file BEFORE upload", async () => {
    const raw = mockFile("iphone.jpg", 6 * 1024 * 1024, "image/jpeg");
    const compressed = mockFile("iphone.jpg", 900 * 1024, "image/jpeg");
    __stubs.compressImageIfNeeded.mockResolvedValueOnce(compressed);

    const uploadSpy = vi.fn(async ({ file }) => ({
      id: "f1", url: "/api/files/f1/download",
      original_filename: file.name, content_type: file.type, size: file.size,
    }));
    __stubs.uploadFile = uploadSpy;
    const onUploaded = vi.fn();

    render(<FileUpload accept="image/*" purpose="job_before_photo"
                        linkedEntityType="job" linkedEntityId="j-1"
                        onUploaded={onUploaded} onError={() => {}} />);
    const input = screen.getByTestId("file-upload-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [raw] } });
    });

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));

    // Helper was called with the raw file first.
    expect(__stubs.compressImageIfNeeded).toHaveBeenCalledTimes(1);
    expect(__stubs.compressImageIfNeeded.mock.calls[0][0]).toBe(raw);

    // Uploader received the COMPRESSED blob, not the raw one.
    const passedFile = uploadSpy.mock.calls[0][0].file;
    expect(passedFile).toBe(compressed);
    expect(passedFile.size).toBeLessThan(raw.size);

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
  });

  it("still respects the 25 MB gate after compression (safety net)", async () => {
    // Simulate the fallback path — compression fails and returns the
    // raw 40 MB file. The 25 MB gate must still fire.
    const monster = mockFile("huge.jpg", 40 * 1024 * 1024, "image/jpeg");
    __stubs.compressImageIfNeeded.mockResolvedValueOnce(monster);

    const uploadSpy = vi.fn();
    __stubs.uploadFile = uploadSpy;
    const onError = vi.fn();

    render(<FileUpload accept="image/*" onError={onError} onUploaded={() => {}} />);
    const input = screen.getByTestId("file-upload-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [monster] } });
    });

    expect(__stubs.compressImageIfNeeded).toHaveBeenCalledTimes(1);
    expect(uploadSpy).not.toHaveBeenCalled();
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0].code).toBe("FILE_TOO_LARGE");
  });
});

// ═══════════════════════════════════════════════════════════════════
// PhotoUploader (checklist) — Path B (base64 JSON to /jobs/{jid}/photos)
// ═══════════════════════════════════════════════════════════════════
describe("PhotoUploader (checklist) · image compression wiring", () => {
  it("calls compressImageIfNeeded per file BEFORE base64-encoding + POST", async () => {
    const raw = mockFile("iphone.jpg", 5 * 1024 * 1024, "image/jpeg");
    const compressed = mockFile("iphone.jpg", 800 * 1024, "image/jpeg");
    __stubs.compressImageIfNeeded.mockResolvedValueOnce(compressed);
    __stubs.apiPost.mockResolvedValueOnce({ photos: [{ id: "p1" }] });

    const onPhotosChange = vi.fn();
    render(<PhotoUploader jobId="j-1" photos={[]}
                            onPhotosChange={onPhotosChange} />);

    const input = screen.getByTestId("checklist-photo-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [raw] } });
    });

    await waitFor(() => expect(__stubs.apiPost).toHaveBeenCalledTimes(1));
    expect(__stubs.compressImageIfNeeded).toHaveBeenCalledTimes(1);
    expect(__stubs.compressImageIfNeeded.mock.calls[0][0]).toBe(raw);

    // The POST body's `data` field is a base64 data URL. We can't
    // easily assert exact bytes because FileReader read the compressed
    // File, but we CAN assert the endpoint + label were correct.
    const [url, body] = __stubs.apiPost.mock.calls[0];
    expect(url).toBe("/jobs/j-1/photos");
    expect(typeof body.data).toBe("string");
    expect(body.data.startsWith("data:")).toBe(true);
    expect(body.label).toMatch(/^checklist-/);
    await waitFor(() => expect(onPhotosChange).toHaveBeenCalledTimes(1));
  });

  it("compresses each of multiple files before uploading them one by one", async () => {
    const f1 = mockFile("a.jpg", 4 * 1024 * 1024, "image/jpeg");
    const f2 = mockFile("b.jpg", 3 * 1024 * 1024, "image/jpeg");
    const c1 = mockFile("a.jpg", 700 * 1024, "image/jpeg");
    const c2 = mockFile("b.jpg", 600 * 1024, "image/jpeg");
    __stubs.compressImageIfNeeded
      .mockResolvedValueOnce(c1)
      .mockResolvedValueOnce(c2);
    __stubs.apiPost.mockResolvedValue({ photos: [] });

    render(<PhotoUploader jobId="j-2" photos={[]}
                            onPhotosChange={() => {}} />);

    const input = screen.getByTestId("checklist-photo-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [f1, f2] } });
    });

    await waitFor(() => expect(__stubs.apiPost).toHaveBeenCalledTimes(2));
    expect(__stubs.compressImageIfNeeded).toHaveBeenCalledTimes(2);
    expect(__stubs.compressImageIfNeeded.mock.calls[0][0]).toBe(f1);
    expect(__stubs.compressImageIfNeeded.mock.calls[1][0]).toBe(f2);
  });
});
