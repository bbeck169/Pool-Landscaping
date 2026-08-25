/**
 * Phase F1 · Feb 2026 — Jest specs for the shared file components.
 *
 * Mutable module-level stubs approach: one ``vi.mock`` factory
 * at the top that reads live values from ``__stubs``. Individual
 * tests flip ``__stubs.uploadFile`` / etc. between runs. This
 * avoids ``jest.resetModules()``, which nukes React and breaks
 * hooks in the render call.
 */
import React from "react";
import { describe, it, expect, jest, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const __stubs = {
  uploadFile: async () => ({}),
  deleteFile: async () => true,
  listFilesByEntity: async () => [],
  fetchAsBlob: async () => ({ url: "blob:stub", contentType: "image/png" }),
  revokeBlobUrl: () => {},
  buildAuthedDownloadUrl: (id) => `/api/files/${id}/download?auth=stub`,
};

vi.mock("@/api/files", () => ({
  uploadFile: (...a) => __stubs.uploadFile(...a),
  deleteFile: (...a) => __stubs.deleteFile(...a),
  listFilesByEntity: (...a) => __stubs.listFilesByEntity(...a),
  fetchAsBlob: (...a) => __stubs.fetchAsBlob(...a),
  revokeBlobUrl: (...a) => __stubs.revokeBlobUrl(...a),
  buildAuthedDownloadUrl: (...a) => __stubs.buildAuthedDownloadUrl(...a),
}));
// Feb 2026 · iOS field-upload compression is transparent to these
// regression tests — mock the helper as a pass-through so JSDOM (no
// real canvas / web-worker) doesn't hang the doUpload promise chain
// before it can hit the 25 MB / MIME gates.
vi.mock("@/lib/imageCompress", () => ({
  __esModule: true,
  compressImageIfNeeded: async (f) => f,
  default: async (f) => f,
}));
vi.mock("sonner", () => ({ toast: { success: () => {}, error: () => {} } }));

// Import components AFTER the mocks are declared.
import { FileUpload } from "@/components/files/FileUpload";
import { AuthedImage } from "@/components/files/AuthedImage";
import { FileList } from "@/components/files/FileList";


function mockFile(name, size, type) {
  const blob = new Blob([new Uint8Array(1)], { type });
  Object.defineProperty(blob, "size", { value: size });
  Object.defineProperty(blob, "name", { value: name });
  return blob;
}

beforeEach(() => {
  __stubs.uploadFile = async () => ({});
  __stubs.deleteFile = async () => true;
  __stubs.listFilesByEntity = async () => [];
  __stubs.fetchAsBlob = async () => ({ url: "blob:stub", contentType: "image/png" });
  __stubs.revokeBlobUrl = () => {};
});


// ═══════════════════════════════════════════════════════════════════
// FileUpload
// ═══════════════════════════════════════════════════════════════════
describe("FileUpload", () => {
  it("renders the drop-zone + browse button + hidden input", () => {
    render(<FileUpload accept="image/*" onUploaded={() => {}} onError={() => {}} />);
    expect(screen.getByTestId("file-upload-root")).toBeTruthy();
    expect(screen.getByTestId("file-upload-dropzone")).toBeTruthy();
    expect(screen.getByTestId("file-upload-input")).toBeTruthy();
  });

  it("uploads a valid image with the expected client-call shape (purpose + linked_entity_* passed through)", async () => {
    const spy = vi.fn(async ({ file }) => ({
      id: "f-1", url: "/api/files/f-1/download",
      original_filename: file.name, content_type: file.type, size: file.size,
    }));
    __stubs.uploadFile = spy;
    const onUploaded = vi.fn();
    render(<FileUpload purpose="job_photo" linkedEntityType="job"
                        linkedEntityId="job-1" accept="image/*"
                        onUploaded={onUploaded} onError={() => {}} />);
    const input = screen.getByTestId("file-upload-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [mockFile("pic.png", 1024, "image/png")] } });
    });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const arg = spy.mock.calls[0][0];
    expect(arg.file.name).toBe("pic.png");
    expect(arg.purpose).toBe("job_photo");
    expect(arg.linkedEntityType).toBe("job");
    expect(arg.linkedEntityId).toBe("job-1");
    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
  });

  it("rejects a > 25 MB file client-side (does NOT call uploadFile)", async () => {
    const spy = vi.fn();
    __stubs.uploadFile = spy;
    const onError = vi.fn();
    render(<FileUpload accept="image/*" onError={onError} onUploaded={() => {}} />);
    const input = screen.getByTestId("file-upload-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [mockFile("huge.png", 26 * 1024 * 1024, "image/png")] } });
    });
    expect(spy).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].code).toBe("FILE_TOO_LARGE");
  });

  it("rejects text/plain when accept='image/*' (does NOT call uploadFile)", async () => {
    const spy = vi.fn();
    __stubs.uploadFile = spy;
    const onError = vi.fn();
    render(<FileUpload accept="image/*" onError={onError} onUploaded={() => {}} />);
    const input = screen.getByTestId("file-upload-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [mockFile("note.txt", 128, "text/plain")] } });
    });
    expect(spy).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].code).toBe("UNSUPPORTED_MIME");
  });
});


// ═══════════════════════════════════════════════════════════════════
// AuthedImage
// ═══════════════════════════════════════════════════════════════════
describe("AuthedImage", () => {
  it("renders loading skeleton, then <img> when fetch resolves", async () => {
    let resolve;
    __stubs.fetchAsBlob = () => new Promise((r) => { resolve = r; });
    render(<AuthedImage fileId="fid-1" alt="pic" size={40} />);
    expect(screen.getByTestId("authed-image-fid-1-loading")).toBeTruthy();
    await act(async () => { resolve({ url: "blob:xyz", contentType: "image/png" }); });
    const img = await screen.findByTestId("authed-image-fid-1");
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe("blob:xyz");
  });

  it("revokes the blob url on unmount", async () => {
    const revoke = vi.fn();
    __stubs.revokeBlobUrl = revoke;
    __stubs.fetchAsBlob = async () => ({ url: "blob:xyz", contentType: "image/png" });
    const { unmount } = render(<AuthedImage fileId="fid-u" alt="pic" size={40} />);
    await screen.findByTestId("authed-image-fid-u");
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:xyz");
  });

  it("renders fallback prop on fetch error", async () => {
    __stubs.fetchAsBlob = async () => { throw new Error("boom"); };
    render(<AuthedImage fileId="fid-e" alt="pic" size={40}
                          fallback={<span data-testid="my-fallback">nope</span>} />);
    await screen.findByTestId("my-fallback");
  });
});


// ═══════════════════════════════════════════════════════════════════
// FileList
// ═══════════════════════════════════════════════════════════════════
describe("FileList", () => {
  it("fetches on mount and renders items", async () => {
    __stubs.listFilesByEntity = async () => [
      { id: "a", original_filename: "a.pdf", content_type: "application/pdf", size: 1024 },
      { id: "b", original_filename: "b.png", content_type: "image/png", size: 2048 },
    ];
    render(<FileList linkedEntityType="job" linkedEntityId="j1" canDelete />);
    await screen.findByTestId("file-list-item-a");
    expect(screen.getByTestId("file-list-item-b")).toBeTruthy();
    expect(screen.getByTestId("file-list-delete-a")).toBeTruthy();
  });

  it("hides delete button when canDelete=false", async () => {
    __stubs.listFilesByEntity = async () => [
      { id: "a", original_filename: "a.pdf", content_type: "application/pdf", size: 128 },
    ];
    render(<FileList linkedEntityType="job" linkedEntityId="j1" canDelete={false} />);
    await screen.findByTestId("file-list-item-a");
    expect(screen.queryByTestId("file-list-delete-a")).toBeNull();
  });

  it("removes item after successful delete", async () => {
    let cur = [{ id: "gone", original_filename: "gone.pdf",
                    content_type: "application/pdf", size: 300 }];
    __stubs.listFilesByEntity = async () => [...cur];
    __stubs.deleteFile = async (id) => {
      cur = cur.filter((x) => x.id !== id);
      return true;
    };
    render(<FileList linkedEntityType="job" linkedEntityId="j1" canDelete />);
    await screen.findByTestId("file-list-item-gone");
    fireEvent.click(screen.getByTestId("file-list-delete-gone"));
    await waitFor(() => expect(screen.queryByTestId("file-list-item-gone")).toBeNull());
  });
});
